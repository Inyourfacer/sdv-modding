"""Portrait sheet: one neutral base, every expression re-sampled from it at partial denoise (one workflow)."""
from __future__ import annotations

from ..graph import ApiGraph, Base, presets
from . import Ctx, write_result


def frame_labels(spec: dict) -> list[str]:
    pre = presets()
    labels = list(spec["frame_labels"])
    ext = pre["_extended_labels"]
    return [ext[i - 6] if l.startswith("frame_") and 0 <= i - 6 < len(ext) else l for i, l in enumerate(labels)]


def build(ctx: Ctx) -> dict:
    s, spec, pre = ctx.s, ctx.spec, presets()
    emotions, framing = pre["_emotions"], pre["_framing"]["portrait"]
    labels = frame_labels(spec)
    W, H = spec["gen_w"], spec["gen_h"]
    g = ApiGraph()
    b = Base(g, s)

    def text(label: str, outfit: bool = True) -> str:
        return s.positive(framing, s.subject, ctx.outfit_tags if outfit else "", emotions.get(label, label.replace("_", " ")))

    # base frame: from the approved reference when there is one, else drawn from scratch
    if ctx.reference:
        base = b.sample(b.encode(text("neutral", False)), b.encode_image(ctx.load_reference(g, W, H)), denoise=ctx.neutral_denoise)
    else:
        base = b.sample(b.encode(text("neutral", False)), b.empty_latent(W, H), denoise=1.0)
    if ctx.outfit_tags:  # the outfit is re-drawn from the default look so face, hair and pose carry over
        base = b.sample(b.encode(text("neutral")), base, denoise=ctx.outfit_denoise)

    stem = f"{ctx.name}_portrait"
    jobs = []
    wanted = set(ctx.frames) if ctx.frames else None
    for i, label in enumerate(labels):
        if wanted and label not in wanted:
            continue
        latent = base if i == 0 else b.sample(b.encode(text(label)), base, denoise=ctx.denoise)
        prefix = f"sdv/{stem}_{label}"
        b.save(b.decode(latent), prefix)
        jobs.append({"id": label, "frames": [i], "label": label, "output_prefix": prefix, "workflow": f"{stem}.api.json"})
    return write_result(ctx, {stem: g}, jobs, {"recipe": "portrait_sheet", "outfit_tags": ctx.outfit_tags})

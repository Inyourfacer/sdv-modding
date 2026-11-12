"""Sprite sheet by in-context inpainting.

The approved reference sits in the left half of a wide canvas; only the right half is generated, so the model copies
face, hair, outfit and colours from what it can see. One generation per facing (down/right/up); left is mirrored from right
at post-process. Walk-cycle frames are NOT generated here (see references/art-recipes.md for the honest limits).
"""
from __future__ import annotations

from ..graph import ApiGraph, Base, presets
from . import Ctx, write_result

PANEL_W, PANEL_H = 832, 1216  # SDXL-friendly panel; the canvas is two panels wide


def plan_rows(spec: dict, mirror_left: bool, frames: list[str] | None) -> list[dict]:
    labels, cols = spec["frame_labels"], spec["cols"]
    jobs = []
    for r in range(spec["rows"]):
        idx = list(range(r * cols, (r + 1) * cols))
        lab = labels[idx[0]].split("_")[0]
        jobs.append({"id": lab, "frames": idx, "label": lab})
    if mirror_left:
        right = next((j for j in jobs if j["label"] == "right"), None)
        for j in jobs:
            if j["label"] == "left" and right:
                j["mirror_of"] = "right"
    if frames:
        for j in jobs:
            if j["id"] not in frames:
                j["skip"] = True
    return jobs


def build(ctx: Ctx) -> dict:
    s, spec, pre = ctx.s, ctx.spec, presets()
    framing, style, dirs = pre["_framing"]["sprite"], pre["_framing"]["sprite_style"], pre["_directions"]
    g = ApiGraph()
    b = Base(g, s)
    W, H = PANEL_W, PANEL_H

    ref = ctx.load_reference(g, W, H)
    blank = g.add("EmptyImage", width=W, height=H, batch_size=1, color=0xFFFFFF)
    canvas = g.add("ImageStitch", image1=ref, image2=[blank, 0], direction="right", match_image_size=True,
                   spacing_width=0, spacing_color="white")
    keep = g.add("SolidMask", value=0.0, width=2 * W, height=H)
    new = g.add("SolidMask", value=1.0, width=W, height=H)
    mask = g.add("MaskComposite", destination=[keep, 0], source=[new, 0], x=W, y=0, operation="add")
    masked = [g.add("SetLatentNoiseMask", samples=b.encode_image([canvas, 0]), mask=[mask, 0]), 0]

    stem = f"{ctx.name}_sprite"
    jobs = plan_rows(spec, ctx.mirror_left, ctx.frames)
    for j in jobs:
        if j.get("skip") or j.get("mirror_of"):
            continue
        text = s.positive(framing, s.subject, ctx.outfit_tags, dirs.get(j["label"], j["label"]), style)
        panel = g.add("ImageCrop", image=b.decode(b.sample(b.encode(text), masked, denoise=1.0)), width=W, height=H, x=W, y=0)
        prefix = f"sdv/{stem}_{j['id']}"
        b.save([panel, 0], prefix)
        j["output_prefix"], j["workflow"] = prefix, f"{stem}.api.json"
    return write_result(ctx, {stem: g}, jobs, {"recipe": "sprite_sheet", "outfit_tags": ctx.outfit_tags})

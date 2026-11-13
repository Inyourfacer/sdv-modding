"""Reference sheet: a front/side/back turnaround of one character, to be approved before any other asset is made."""
from __future__ import annotations

from ..graph import ApiGraph, Base, presets
from . import Ctx, write_result

W, H = 1536, 1024


def build(ctx: Ctx) -> dict:
    s = ctx.s
    framing = presets()["_framing"]["reference_sheet"]
    g = ApiGraph()
    b = Base(g, s)
    text = s.positive(framing, s.subject, ctx.outfit_tags)
    latent = b.sample(b.encode(text), b.empty_latent(W, H), denoise=1.0)
    stem = f"{ctx.name}_reference"
    prefix = f"sdv/{stem}"
    b.save(b.decode(latent), prefix)
    jobs = [{"id": "reference", "frames": [], "label": "reference", "output_prefix": prefix, "workflow": f"{stem}.api.json"}]
    return write_result(ctx, {stem: g}, jobs, {"recipe": "reference_sheet", "outfit_tags": ctx.outfit_tags})

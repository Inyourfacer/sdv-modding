"""Recipes turn a character/asset description into ComfyUI API workflows plus a jobs.json that postprocess.py understands.

  portrait_sheet   one neutral base, every expression re-sampled from it (same character, outfit, framing); optional outfit stage
  sprite_sheet     in-context inpainting: approved reference on the left of a wide canvas, only the right half is generated
  reference_sheet  front/side/back turnaround to approve before anything else is made for a character

All use core ComfyUI nodes only. The 'simple' recipe (one independent txt2img per frame) stays in make_comfy_workflow.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from ..graph import ApiGraph, Base, Settings


@dataclass
class Ctx:
    s: Settings
    name: str
    out_dir: Path
    spec: dict | None = None
    spec_key: str | None = None
    reference: Path | None = None
    outfit_tags: str = ""
    denoise: float = 0.55          # expression re-sample strength
    outfit_denoise: float = 0.65   # base -> outfit strength
    neutral_denoise: float = 0.30  # reference -> neutral frame strength
    mirror_left: bool = True
    frames: list[str] | None = None
    inputs: list[str] = field(default_factory=list)

    def load_reference(self, g: ApiGraph, w: int, h: int) -> list:
        """Copy the approved reference next to the workflows (comfy.py uploads it) and scale it to w x h."""
        if not self.reference or not Path(self.reference).exists():
            raise SystemExit("This recipe needs an approved reference image: pass --reference <png> "
                             "(make one with --recipe reference_sheet and approve it first).")
        fname = f"sdv_{self.name}_ref.png"
        dst = self.out_dir / "input" / fname
        dst.parent.mkdir(parents=True, exist_ok=True)
        Image.open(self.reference).convert("RGB").save(dst)
        self.inputs.append(fname)
        li = g.add("LoadImage", image=fname)
        sc = g.add("ImageScale", image=[li, 0], upscale_method="lanczos", width=w, height=h, crop="center")
        return [sc, 0]


def write_result(ctx: Ctx, graphs: dict[str, ApiGraph], jobs: list[dict], extra: dict | None = None) -> dict:
    """Write <stem>.api.json files and jobs.json. Returns the manifest."""
    out = ctx.out_dir
    out.mkdir(parents=True, exist_ok=True)
    for stem, g in graphs.items():
        problems = g.check()
        if problems:
            raise SystemExit("internal error, bad graph: " + "; ".join(problems))
        (out / f"{stem}.api.json").write_text(json.dumps(g.nodes, indent=2), encoding="utf-8")
    spec = ctx.spec or {}
    manifest = {
        "recipe": (extra or {}).get("recipe"), "spec": ctx.spec_key, "name": ctx.name,
        "frame_w": spec.get("frame_w"), "frame_h": spec.get("frame_h"), "cols": spec.get("cols"), "rows": spec.get("rows"),
        "anchor": spec.get("anchor", "center"), "remove_bg": spec.get("remove_bg", False), "colors_key": spec.get("colors"),
        "seed": ctx.s.seed, "checkpoint": ctx.s.ckpt, "loras": ctx.s.loras, "negative": ctx.s.negative,
        "game_asset": spec.get("game_asset"), "workflows": [f"{k}.api.json" for k in graphs], "inputs": ctx.inputs,
        "jobs": jobs, **{k: v for k, v in (extra or {}).items() if k != "recipe"},
    }
    (out / "jobs.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def get(name: str):
    from . import portrait_sheet, reference_sheet, sprite_sheet
    return {"portrait_sheet": portrait_sheet, "sprite_sheet": sprite_sheet, "reference_sheet": reference_sheet}[name]


DEFAULT_SPEC = {"portrait_sheet": "portrait", "sprite_sheet": "character_sprite", "reference_sheet": None}
RECIPES = tuple(DEFAULT_SPEC)

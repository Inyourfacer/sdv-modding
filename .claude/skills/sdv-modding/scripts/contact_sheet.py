#!/usr/bin/env python3
"""One PNG to review every take of an asset: this is what Claude opens and what the owner is shown before approving.

  python contact_sheet.py art/mira_sprite/take_a.png art/mira_sprite/take_b.png --spec character_sprite \
        --reference art/Mira/reference.png --out art/mira_sprite/contact.png [--palette art/Mira/palette.png]

Per take: label, QA verdict and the first findings, then the sheet at 4x on a light background, on a dark background, and at
actual game size on a ground colour (how the player sees it). For sprites a mock-up row shows each facing at game scale.
The character reference sits at the left so drift is visible. Frame names are printed under the first take.
Nothing here writes into a mod folder.
"""
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from postprocess import palette_from_png
from qa_art import analyze, merge_frames, verdict
from sdvlib import get_spec

LIGHT, DARK, GROUND = (240, 236, 226), (38, 34, 46), (96, 150, 78)
VERDICT_COLOUR = {"PASS": (40, 140, 60), "WARN": (200, 130, 0), "FAIL": (200, 40, 40)}


def font(size=13):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def on_bg(im: Image.Image, bg, scale: int) -> Image.Image:
    big = im.convert("RGBA").resize((im.width * scale, im.height * scale), Image.NEAREST)
    canvas = Image.new("RGBA", big.size, bg + (255,))
    canvas.alpha_composite(big)
    return canvas.convert("RGB")


def reference_panel(path: str | None, h: int) -> Image.Image | None:
    if not path or not Path(path).exists():
        return None
    im = Image.open(path).convert("RGB")
    return im.resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS)


def build(sheets: list[Path], spec: dict, out: Path, reference: str | None = None, palette: str | None = None,
          kind: str = "vanilla", n: int = 1, colors: int | None = None) -> dict:
    """Write the contact sheet and return {take_name: verdict}."""
    pal = palette_from_png(palette) if palette and Path(palette).exists() else None
    f, fb = font(13), font(15)
    pad, textw = 12, 380
    blocks, verdicts = [], {}
    ref_h = 0
    for sp in sheets:
        im = Image.open(sp)
        results = merge_frames(analyze(im, spec, kind, n, pal, colors))
        v = verdict(results)
        verdicts[sp.stem] = v
        S = 4 if max(im.size) <= 200 else 2 if max(im.size) <= 600 else 1
        light, dark = on_bg(im, LIGHT, S), on_bg(im, DARK, S)
        game = on_bg(im, GROUND, 1)
        blocks.append((sp.stem, v, results, light, dark, game))
        ref_h = max(ref_h, light.height)
    ref = reference_panel(reference, ref_h)
    cw = sum(b.width for b in blocks[0][3:5]) + blocks[0][5].width + pad * 5 + textw
    W = cw + (ref.width + pad if ref else 0)
    H = sum(max(b[3].height, 120) + pad for b in blocks) + pad + 24
    sheet = Image.new("RGB", (W, H), (250, 248, 244))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 4), "frames: " + ", ".join(f"{i}={l}" for i, l in enumerate(spec["frame_labels"][:12])) + (" ..." if len(spec["frame_labels"]) > 12 else ""), fill=(60, 60, 60), font=f)
    y = 24 + pad // 2
    for stem, v, results, light, dark, game in blocks:
        x = pad
        if ref:
            sheet.paste(ref, (x, y)); x += ref.width + pad
        d.text((x, y), stem, fill=(20, 20, 20), font=fb)
        d.text((x, y + 20), f"QA {v['level']}  ({v['fails']} fail, {v['warns']} warn)", fill=VERDICT_COLOUR[v["level"]], font=fb)
        ty = y + 44
        shown = 0
        for line in v["reasons"][:5]:
            for k, part in enumerate(textwrap.wrap(line, 52)[:2]):
                d.text((x, ty), ("- " if k == 0 else "  ") + part, fill=(70, 70, 70), font=f); ty += 15
            shown += 1
        if len(v["reasons"]) > shown:
            d.text((x, ty), f"... +{len(v['reasons']) - shown} more", fill=(70, 70, 70), font=f)
        x += textw
        sheet.paste(light, (x, y)); x += light.width + pad
        sheet.paste(dark, (x, y)); x += dark.width + pad
        sheet.paste(game, (x, y))
        y += max(light.height, 120) + pad
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return verdicts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sheets", nargs="+"); ap.add_argument("--spec", required=True)
    ap.add_argument("--frame"); ap.add_argument("--cols", type=int); ap.add_argument("--rows", type=int)
    ap.add_argument("--target", default="vanilla"); ap.add_argument("--reference"); ap.add_argument("--palette")
    ap.add_argument("--colors", type=int); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    from postprocess import parse_target
    spec = get_spec(a.spec, a.frame, a.cols, a.rows)
    kind, n = parse_target(a.target)
    v = build([Path(s) for s in a.sheets], spec, Path(a.out), a.reference, a.palette, kind, n, a.colors)
    for k, x in v.items():
        print(f"{k}: {x['level']} ({x['fails']} fail, {x['warns']} warn)")
    print(f"contact sheet: {a.out}   <- open this image and look at it before telling the owner anything is good")


if __name__ == "__main__":
    main()

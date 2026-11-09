#!/usr/bin/env python3
"""Write a spec-exact placeholder sheet so a mod loads and can be tested before real art exists.

  python make_placeholder.py --spec portrait --out "[CP] Mira/assets/portraits/Mira.png" --label Mira
  python make_placeholder.py --spec character_sprite --out assets/sprites/Mira.png --color 7a5cff --init-dir comfy/init
  python make_placeholder.py --spec furniture --frame 32x32 --cols 2 --out assets/furniture.png

--init-dir also writes one image per frame at generation size (white bg) for use as
img2img/composition guides in ComfyUI (pass the same folder to make_comfy_workflow.py --init).
"""
from __future__ import annotations

import argparse
import colorsys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from sdvlib import get_spec, safe_name


def hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def shade(rgb, f):
    return tuple(max(0, min(255, int(c * f))) for c in rgb)


def row_color(base, row):
    r, g, b = [c / 255 for c in base]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb((h + row * 0.09) % 1, l, s)
    return (int(r * 255), int(g * 255), int(b * 255))


def draw_portrait(d: ImageDraw.ImageDraw, x, y, w, h, col, idx):
    d.rectangle([x, y, x + w - 1, y + h - 1], fill=shade(col, 1.6) + (255,))
    cx = x + w // 2
    hr = w * 0.22
    d.ellipse([cx - hr, y + h * 0.18, cx + hr, y + h * 0.18 + hr * 2.2], fill=shade(col, 1.0) + (255,))
    d.rounded_rectangle([x + w * 0.15, y + h * 0.68, x + w * 0.85, y + h], radius=max(1, w // 10), fill=shade(col, 0.7) + (255,))
    # expression hint: mouth shape per index
    my = y + h * 0.18 + hr * 1.6
    mw = hr * 0.6
    ink = (30, 20, 30, 255)
    if idx == 1:
        d.arc([cx - mw, my - mw * 0.6, cx + mw, my + mw * 0.6], 20, 160, fill=ink, width=max(1, w // 48))
    elif idx == 2:
        d.arc([cx - mw, my, cx + mw, my + mw], 200, 340, fill=ink, width=max(1, w // 48))
    elif idx == 5:
        d.line([cx - mw, my + 2, cx + mw, my - 2], fill=ink, width=max(1, w // 48))
    else:
        d.line([cx - mw * 0.6, my, cx + mw * 0.6, my], fill=ink, width=max(1, w // 48))
    if idx == 4:
        r = max(1, w // 24)
        d.ellipse([cx - hr * 0.8 - r, my - r * 3, cx - hr * 0.8 + r, my - r], fill=(240, 120, 150, 255))
        d.ellipse([cx + hr * 0.8 - r, my - r * 3, cx + hr * 0.8 + r, my - r], fill=(240, 120, 150, 255))


def draw_character(d, x, y, w, h, col, label):
    direction, _, step = label.partition("_")
    step = int(step) if step.isdigit() else 0
    body = shade(col, 1.0) + (255,)
    dark = shade(col, 0.6) + (255,)
    skin = (240, 200, 170, 255)
    # head
    d.rectangle([x + w * 0.25, y + h * 0.12, x + w * 0.75 - 1, y + h * 0.40], fill=skin)
    d.rectangle([x + w * 0.25, y + h * 0.10, x + w * 0.75 - 1, y + h * 0.18], fill=dark)  # hair
    # torso
    d.rectangle([x + w * 0.22, y + h * 0.42, x + w * 0.78 - 1, y + h * 0.72], fill=body)
    # legs with walk offset
    lo = [0, 1, 0, -1][step % 4]
    d.rectangle([x + w * 0.28, y + h * 0.72, x + w * 0.46, y + h - 1 - max(0, lo)], fill=dark)
    d.rectangle([x + w * 0.54, y + h * 0.72, x + w * 0.72, y + h - 1 - max(0, -lo)], fill=dark)
    # facing marker (eyes)
    ey = y + h * 0.27
    ink = (20, 20, 30, 255)
    if direction == "down":
        d.point([(x + w * 0.38, ey), (x + w * 0.62, ey)], fill=ink)
    elif direction == "right":
        d.point([(x + w * 0.66, ey)], fill=ink)
    elif direction == "left":
        d.point([(x + w * 0.34, ey)], fill=ink)
    else:  # up: hair covers head
        d.rectangle([x + w * 0.25, y + h * 0.12, x + w * 0.75 - 1, y + h * 0.36], fill=dark)


def draw_generic(d, x, y, w, h, col, idx):
    pad = max(1, min(w, h) // 8)
    d.rounded_rectangle([x + pad, y + pad, x + w - 1 - pad, y + h - 1 - pad], radius=max(1, min(w, h) // 5),
                        fill=shade(col, 1.0) + (255,), outline=shade(col, 0.5) + (255,))
    d.line([x + pad, y + pad, x + w - 1 - pad, y + h - 1 - pad], fill=shade(col, 0.75) + (255,))


def label_frame(d, x, y, w, h, text):
    if min(w, h) < 32:
        return
    font = ImageFont.load_default()
    d.text((x + 2, y + 1), text[:14], fill=(0, 0, 0, 255), font=font)


def render_frame(spec, idx, w, h, color, label, labels_on=True) -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = row_color(color, idx // spec["cols"])
    key = spec["key"]
    if key.startswith("portrait"):
        draw_portrait(d, 0, 0, w, h, col, idx)
    elif key in ("character_sprite",) or (key == "fs_hair"):
        lab = spec["frame_labels"][idx]
        if key == "fs_hair":
            lab = {"front": "down_0", "back": "up_0"}.get(lab, lab + "_0")
        draw_character(d, 0, 0, w, h, col, lab)
    else:
        draw_generic(d, 0, 0, w, h, col, idx)
    if labels_on:
        label_frame(d, 0, 0, w, h, f"{idx}:{spec['frame_labels'][idx]}")
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frame", help="override frame size WxH")
    ap.add_argument("--cols", type=int)
    ap.add_argument("--rows", type=int)
    ap.add_argument("--color", default="c07a4a", help="base hex color")
    ap.add_argument("--label", default="", help="name drawn in the first frame if large enough")
    ap.add_argument("--init-dir", help="also write per-frame init images at generation size here")
    ap.add_argument("--force", action="store_true", help="overwrite an existing non-placeholder file")
    a = ap.parse_args()

    spec = get_spec(a.spec, a.frame, a.cols, a.rows)
    color = hex_rgb(a.color)
    fw, fh = spec["frame_w"], spec["frame_h"]
    sheet = Image.new("RGBA", (spec["sheet_w"], spec["sheet_h"]), (0, 0, 0, 0))
    for i in range(spec["cols"] * spec["rows"]):
        fr = render_frame(spec, i, fw, fh, color, a.label)
        sheet.alpha_composite(fr, ((i % spec["cols"]) * fw, (i // spec["cols"]) * fh))
    if a.label and fw >= 48:
        ImageDraw.Draw(sheet).text((2, fh - 12), a.label[:12], fill=(0, 0, 0, 255), font=ImageFont.load_default())

    out = Path(a.out)
    if out.exists() and not a.force:
        try:
            if Image.open(out).info.get("sdv_placeholder") != "1":
                raise SystemExit(f"{out} exists and is not a placeholder; pass --force to overwrite")
        except SystemExit:
            raise
        except Exception:
            pass
    out.parent.mkdir(parents=True, exist_ok=True)
    from PIL.PngImagePlugin import PngInfo
    meta = PngInfo(); meta.add_text("sdv_placeholder", "1"); meta.add_text("sdv_spec", a.spec)
    sheet.save(out, pnginfo=meta)
    print(f"placeholder {out} ({spec['sheet_w']}x{spec['sheet_h']}, {spec['cols']}x{spec['rows']} frames of {fw}x{fh})")

    if a.init_dir:
        idir = Path(a.init_dir); idir.mkdir(parents=True, exist_ok=True)
        gw, gh = spec["gen_w"], spec["gen_h"]
        for i, lab in enumerate(spec["frame_labels"]):
            fr = render_frame(spec, i, fw, fh, color, a.label, labels_on=False)
            scale = min(gw / fw, gh / fh) * 0.8
            big = fr.resize((max(1, int(fw * scale)), max(1, int(fh * scale))), Image.NEAREST)
            bg = Image.new("RGBA", (gw, gh), (255, 255, 255, 255))
            ox = (gw - big.width) // 2
            oy = gh - big.height - int(gh * 0.05) if spec.get("anchor") == "bottom" else (gh - big.height) // 2
            bg.alpha_composite(big, (ox, oy))
            p = idir / f"{safe_name(lab)}.png"
            bg.convert("RGB").save(p)
        print(f"init images -> {idir} ({len(spec['frame_labels'])} files at {gw}x{gh})")


if __name__ == "__main__":
    main()

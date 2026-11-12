#!/usr/bin/env python3
"""Build and lock a character's colour palette so every sheet of that character uses the same colours.

  python palette.py build --images art/Mira/reference.png art/Mira/portrait_reference.png --colors 24 --out art/Mira/palette.png
  python palette.py build --images ... --colors 24 --out art/Mira/palette.png --lock Mira     # also records it in sdv-project.json
  python palette.py show art/Mira/palette.png                                                 # list colours as hex

The palette PNG is a strip, one pixel per colour. postprocess.py uses it with --palette <png> or --character <id>
(nearest colour in Lab space), so portraits, sprites and outfits of one character stay on one palette.
Build it from the approved reference (several crops are fine); background pixels (near the image border colour) are ignored.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from postprocess import build_palette, remove_background
from sdvlib import PROJECT_NAME, find_project, load_project, save_project


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--images", nargs="+", required=True); b.add_argument("--colors", type=int, default=24)
    b.add_argument("--out", required=True); b.add_argument("--lock", help="character id to record palette_png for")
    b.add_argument("--keep-background", action="store_true"); b.add_argument("--bg-tol", type=int, default=40)
    s = sub.add_parser("show"); s.add_argument("palette")
    a = ap.parse_args()

    if a.cmd == "show":
        px = np.array(Image.open(a.palette).convert("RGB")).reshape(-1, 3)
        print(f"{len(px)} colours: " + " ".join("#%02x%02x%02x" % tuple(c) for c in px))
        return
    frames = []
    for p in a.images:
        im = Image.open(p).convert("RGBA")
        frames.append(im if a.keep_background else remove_background(im, a.bg_tol))
    pal = build_palette(frames, a.colors)
    if not len(pal):
        raise SystemExit("No opaque pixels found; check the images (or --keep-background).")
    lum = pal @ np.array([0.299, 0.587, 0.114])
    pal = pal[np.argsort(lum)]
    img = Image.new("RGB", (len(pal), 1)); img.putdata([tuple(int(v) for v in c) for c in pal])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(a.out)
    print(f"palette: {len(pal)} colours -> {a.out}")
    if a.lock:
        pp = find_project()
        if not pp:
            raise SystemExit(f"No {PROJECT_NAME} to record the palette in; run project.py sync first.")
        proj = load_project(pp)
        ch = (proj["characters"] or {}).get(a.lock)
        if ch is None:
            raise SystemExit(f"Unknown character '{a.lock}' in {PROJECT_NAME}.")
        try:
            ch["palette_png"] = Path(a.out).resolve().relative_to(pp.parent.resolve()).as_posix()
        except ValueError:
            ch["palette_png"] = str(Path(a.out).resolve())
        save_project(proj, pp)
        print(f"recorded as characters.{a.lock}.palette_png")


if __name__ == "__main__":
    main()

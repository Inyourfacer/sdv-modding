#!/usr/bin/env python3
"""Small sheet edits so Claude fixes one frame instead of regenerating a whole asset.

  python sheet.py slice   sheet.png --spec character_sprite --out-dir frames/          # one PNG per frame, named by label
  python sheet.py assemble --spec character_sprite --out sheet.png frames/down_0.png ...  # frames in order
  python sheet.py mirror-row sheet.png --spec character_sprite --src right --dst left --out fixed.png
  python sheet.py shift-frame sheet.png --spec character_sprite --frame-index 5 --dx 0 --dy -1 --out fixed.png
  python sheet.py copy-frame sheet.png --spec character_sprite --src 4 --dst 5 6 7 --out fixed.png
  python sheet.py preview-anim sheet.png --spec character_sprite --row 0 --out walk_down.gif [--fps 6 --scale 8]
  python sheet.py diff a.png b.png --out diff.png

--spec gives the layout (assets/asset_specs.json); override with --frame WxH --cols N --rows N. Edits never overwrite the input:
--out is required (pass the same path to edit in place on purpose).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from sdvlib import get_spec, safe_name


def layout(a, sheet: Image.Image | None = None):
    spec = get_spec(a.spec, a.frame, a.cols, a.rows)
    if sheet is not None:
        fw, fh = spec["frame_w"], spec["frame_h"]
        if sheet.width % fw or sheet.height % fh:
            raise SystemExit(f"{sheet.size} is not a whole number of {fw}x{fh} frames; pass --frame/--cols/--rows")
        spec["cols"], spec["rows"] = sheet.width // fw, sheet.height // fh
        spec = get_spec(a.spec, f"{fw}x{fh}", spec["cols"], spec["rows"])
    return spec


def box(spec, i):
    c = spec["cols"]
    return ((i % c) * spec["frame_w"], (i // c) * spec["frame_h"], (i % c + 1) * spec["frame_w"], (i // c + 1) * spec["frame_h"])


def save(im: Image.Image, out: str):
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    print(f"wrote {out}")


def row_frames(spec, name: str):
    """Frame indices of a row named by the first label's prefix (e.g. 'right') or by number."""
    cols = spec["cols"]
    if str(name).isdigit():
        r = int(name)
        return list(range(r * cols, (r + 1) * cols))
    for r in range(spec["rows"]):
        if spec["frame_labels"][r * cols].split("_")[0] == name:
            return list(range(r * cols, (r + 1) * cols))
    raise SystemExit(f"No row '{name}'. Rows: " + ", ".join(spec["frame_labels"][r * cols].split("_")[0] for r in range(spec["rows"])))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, sheet=True):
        if sheet:
            p.add_argument("sheet")
        p.add_argument("--spec", required=True); p.add_argument("--frame"); p.add_argument("--cols", type=int); p.add_argument("--rows", type=int)

    s = sub.add_parser("slice"); common(s); s.add_argument("--out-dir", required=True)
    s = sub.add_parser("assemble"); common(s, False); s.add_argument("frames", nargs="+"); s.add_argument("--out", required=True)
    s = sub.add_parser("mirror-row"); common(s); s.add_argument("--src", required=True); s.add_argument("--dst", required=True); s.add_argument("--out", required=True)
    s = sub.add_parser("shift-frame"); common(s); s.add_argument("--frame-index", "--frame-no", dest="idx", type=int)
    s.add_argument("--dx", type=int, default=0); s.add_argument("--dy", type=int, default=0); s.add_argument("--out", required=True)
    s = sub.add_parser("copy-frame"); common(s); s.add_argument("--src", type=int, required=True); s.add_argument("--dst", type=int, nargs="+", required=True); s.add_argument("--out", required=True)
    s = sub.add_parser("preview-anim"); common(s); s.add_argument("--row", default="0"); s.add_argument("--fps", type=float, default=6)
    s.add_argument("--scale", type=int, default=8); s.add_argument("--out", required=True)
    s = sub.add_parser("diff"); s.add_argument("a"); s.add_argument("b"); s.add_argument("--out")
    a = ap.parse_args()

    if a.cmd == "diff":
        x, y = Image.open(a.a).convert("RGBA"), Image.open(a.b).convert("RGBA")
        if x.size != y.size:
            raise SystemExit(f"different sizes: {x.size} vs {y.size}")
        d = (np.array(x) != np.array(y)).any(-1)
        print(f"{int(d.sum())} of {d.size} pixels differ" + (f"; first at x={np.argwhere(d)[0][1]} y={np.argwhere(d)[0][0]}" if d.any() else ""))
        if a.out:
            vis = np.array(y).copy(); vis[..., 3] = np.maximum(vis[..., 3] // 3, 40)
            vis[d] = (255, 0, 80, 255)
            save(Image.fromarray(vis, "RGBA"), a.out)
        raise SystemExit(1 if d.any() else 0)

    if a.cmd == "assemble":
        spec = get_spec(a.spec, a.frame, a.cols, a.rows)
        if len(a.frames) > spec["cols"] * spec["rows"]:
            raise SystemExit("more frames than the layout holds")
        out = Image.new("RGBA", (spec["sheet_w"], spec["sheet_h"]), (0, 0, 0, 0))
        for i, f in enumerate(a.frames):
            fr = Image.open(f).convert("RGBA")
            if fr.size != (spec["frame_w"], spec["frame_h"]):
                raise SystemExit(f"{f} is {fr.size}, expected {(spec['frame_w'], spec['frame_h'])}")
            out.paste(fr, box(spec, i)[:2])
        return save(out, a.out)

    sheet = Image.open(a.sheet).convert("RGBA")
    spec = layout(a, sheet)
    if a.cmd == "slice":
        d = Path(a.out_dir); d.mkdir(parents=True, exist_ok=True)
        for i in range(spec["cols"] * spec["rows"]):
            sheet.crop(box(spec, i)).save(d / f"{i:02d}_{safe_name(spec['frame_labels'][i])}.png")
        print(f"sliced {spec['cols'] * spec['rows']} frames -> {d}")
    elif a.cmd == "mirror-row":
        src, dst = row_frames(spec, a.src), row_frames(spec, a.dst)
        out = sheet.copy()
        for s_i, d_i in zip(src, dst):
            out.paste(Image.new("RGBA", (spec["frame_w"], spec["frame_h"]), (0, 0, 0, 0)), box(spec, d_i)[:2])
            out.paste(sheet.crop(box(spec, s_i)).transpose(Image.FLIP_LEFT_RIGHT), box(spec, d_i)[:2])
        save(out, a.out)
    elif a.cmd == "shift-frame":
        idx = a.idx if a.idx is not None else None
        if idx is None:
            raise SystemExit("--frame-index N is required (shift-frame uses --frame for the frame size)")
        fr = sheet.crop(box(spec, idx))
        moved = Image.new("RGBA", fr.size, (0, 0, 0, 0)); moved.paste(fr, (a.dx, a.dy))
        out = sheet.copy()
        out.paste(Image.new("RGBA", fr.size, (0, 0, 0, 0)), box(spec, idx)[:2]); out.paste(moved, box(spec, idx)[:2])
        save(out, a.out)
    elif a.cmd == "copy-frame":
        fr = sheet.crop(box(spec, a.src))
        out = sheet.copy()
        for d_i in a.dst:
            out.paste(Image.new("RGBA", fr.size, (0, 0, 0, 0)), box(spec, d_i)[:2]); out.paste(fr, box(spec, d_i)[:2])
        save(out, a.out)
    elif a.cmd == "preview-anim":
        idxs = row_frames(spec, a.row)
        bg = (236, 232, 222, 255)
        frames = []
        for i in idxs:
            fr = sheet.crop(box(spec, i)).resize((spec["frame_w"] * a.scale, spec["frame_h"] * a.scale), Image.NEAREST)
            canvas = Image.new("RGBA", fr.size, bg); canvas.alpha_composite(fr); frames.append(canvas.convert("P", palette=Image.ADAPTIVE))
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=int(1000 / a.fps), loop=0, disposal=2)
        print(f"wrote {a.out} ({len(frames)} frames at {a.fps:g} fps)")


if __name__ == "__main__":
    main()

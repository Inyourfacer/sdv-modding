#!/usr/bin/env python3
"""Turn ComfyUI outputs into a game-ready SDV sheet.

Pipeline per job: background removal -> crop to subject -> fit into frame (anchor) ->
area downscale -> hard alpha -> palette reduction -> optional outline/grayscale -> place in sheet.

  # with jobs.json from make_comfy_workflow.py (finds newest output per job in --images)
  python postprocess.py --jobs comfy/Mira_portrait/jobs.json \
      --images "C:/StabilityMatrix/Data/Packages/ComfyUI/output/sdv" --out "[CP] Mira/assets/portraits/Mira.png"

  # pick specific files for jobs
  python postprocess.py --jobs jobs.json --pick neutral=out/a.png --pick happy=out/b.png --out sheet.png

  # no jobs.json: explicit spec + inputs in frame order
  python postprocess.py --spec object_icon --inputs gem.png --out assets/objects.png

Frames not covered keep whatever the existing --out sheet has (e.g. the placeholder).
Writes a 4x preview next to jobs.json (or ./sdv_previews/), never inside the mod.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from sdvlib import get_spec, load_config, load_json


# ---------------------------------------------------------------- steps
def remove_background(im: Image.Image, tol: int = 40) -> Image.Image:
    """Flood-remove the background color connected to the image border."""
    rgba = np.array(im.convert("RGBA"))
    rgb = rgba[..., :3].astype(np.int32)
    h, w = rgb.shape[:2]
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    close = np.sqrt(((rgb - bg) ** 2).sum(-1)) < tol
    region = np.zeros_like(close)
    region[0, :] = close[0, :]; region[-1, :] = close[-1, :]
    region[:, 0] = close[:, 0]; region[:, -1] = close[:, -1]
    while True:
        grown = region.copy()
        grown[1:, :] |= region[:-1, :]; grown[:-1, :] |= region[1:, :]
        grown[:, 1:] |= region[:, :-1]; grown[:, :-1] |= region[:, 1:]
        grown &= close
        if (grown == region).all():
            break
        region = grown
    rgba[..., 3] = np.where(region, 0, rgba[..., 3])
    return Image.fromarray(rgba, "RGBA")


def crop_to_content(im: Image.Image) -> Image.Image:
    bbox = im.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    return im.crop(bbox) if bbox else im


def fit_frame(im: Image.Image, fw: int, fh: int, anchor: str, pad: int, fill: bool) -> Image.Image:
    """Scale (area-average) the subject into a fw x fh frame."""
    if fill:
        # portraits / tiles: center-crop to frame aspect, then resize to fill
        target_ratio = fw / fh
        w, h = im.size
        if w / h > target_ratio:
            nw = int(h * target_ratio); im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = int(w / target_ratio)
            top = 0 if anchor == "top" else (h - nh if anchor == "bottom" else (h - nh) // 2)
            im = im.crop((0, top, w, top + nh))
        return im.resize((fw, fh), Image.BOX)
    aw, ah = fw - 2 * pad, fh - pad if anchor == "bottom" else fh - 2 * pad
    s = min(aw / im.width, ah / im.height)
    nw, nh = max(1, round(im.width * s)), max(1, round(im.height * s))
    # premultiply to avoid dark/white fringes when averaging transparent pixels
    arr = np.array(im.convert("RGBA")).astype(np.float32)
    arr[..., :3] *= arr[..., 3:4] / 255.0
    pm = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA").resize((nw, nh), Image.BOX)
    out = np.array(pm).astype(np.float32)
    a = out[..., 3:4]
    out[..., :3] = np.where(a > 0, out[..., :3] * 255.0 / np.maximum(a, 1), 0)
    small = Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGBA")
    frame = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    x = (fw - nw) // 2
    y = fh - nh if anchor == "bottom" else (fh - nh) // 2
    frame.alpha_composite(small, (x, y))
    return frame


def hard_alpha(im: Image.Image, thresh: int = 128) -> Image.Image:
    arr = np.array(im)
    arr[..., 3] = np.where(arr[..., 3] >= thresh, 255, 0)
    return Image.fromarray(arr, "RGBA")


def quantize(im: Image.Image, colors: int, palette: Image.Image | None) -> Image.Image:
    alpha = im.getchannel("A")
    rgb = im.convert("RGB")
    if palette is not None:
        q = rgb.quantize(palette=palette, dither=Image.Dither.NONE)
    else:
        opaque = np.array(alpha) > 0
        if opaque.sum() == 0:
            return im
        # quantize using only opaque pixels so the transparent area doesn't steal palette slots
        px = np.array(rgb)[opaque].reshape(-1, 1, 3)
        sample = Image.fromarray(px.astype(np.uint8), "RGB")
        pal = sample.quantize(colors=max(2, colors), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        q = rgb.quantize(palette=pal, dither=Image.Dither.NONE)
    out = q.convert("RGBA")
    out.putalpha(alpha)
    return out


def outline(im: Image.Image, darken: float = 0.45) -> Image.Image:
    arr = np.array(im).astype(np.int32)
    a = arr[..., 3] > 0
    nb = np.zeros_like(a)
    nb[1:, :] |= a[:-1, :]; nb[:-1, :] |= a[1:, :]; nb[:, 1:] |= a[:, :-1]; nb[:, :-1] |= a[:, 1:]
    edge = nb & ~a
    if not edge.any():
        return im
    mean = arr[a][:, :3].mean(0) if a.any() else np.array([40, 30, 40])
    col = (mean * darken).astype(np.int32)
    arr[edge, :3] = col
    arr[edge, 3] = 255
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def process(src: Path, spec: dict, opts) -> Image.Image:
    im = Image.open(src).convert("RGBA")
    bg_mode = opts.background
    remove = (spec.get("remove_bg") and bg_mode == "auto") or bg_mode == "remove"
    if remove:
        im = remove_background(im, opts.bg_tol)
        im = crop_to_content(im)
    fill = not remove
    fr = fit_frame(im, spec["frame_w"], spec["frame_h"], spec.get("anchor", "center"), opts.pad, fill)
    fr = hard_alpha(fr)
    if opts.grayscale:
        g = ImageOps.grayscale(fr.convert("RGB")).convert("RGBA"); g.putalpha(fr.getchannel("A")); fr = g
    fr = quantize(fr, opts.colors, opts.palette_img)
    if opts.outline:
        fr = outline(fr)
    return fr


# ---------------------------------------------------------------- job resolution
def newest_output(images_dir: Path, prefix: str) -> Path | None:
    stem = Path(prefix).name
    cands = [p for p in images_dir.rglob(f"{stem}_*.png")]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", help="jobs.json from make_comfy_workflow.py")
    ap.add_argument("--images", help="folder with ComfyUI outputs (searched recursively)")
    ap.add_argument("--pick", action="append", default=[], help="job_id=path override (repeatable)")
    ap.add_argument("--spec"); ap.add_argument("--frame"); ap.add_argument("--cols", type=int); ap.add_argument("--rows", type=int)
    ap.add_argument("--inputs", nargs="*", default=[], help="(no jobs.json) images in frame order")
    ap.add_argument("--out", required=True)
    ap.add_argument("--colors", type=int, help="palette size (default from config by asset type)")
    ap.add_argument("--palette", help="PNG whose colors define the palette")
    ap.add_argument("--background", choices=["auto", "remove", "keep"])
    ap.add_argument("--bg-tol", type=int, default=40)
    ap.add_argument("--pad", type=int, default=0)
    ap.add_argument("--outline", action="store_true")
    ap.add_argument("--grayscale", action="store_true", help="for recolorable Fashion Sense hair etc.")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--config")
    a = ap.parse_args()

    cfg = load_config(a.config)
    pp = cfg.get("postprocess", {})

    if a.jobs:
        jm = load_json(a.jobs)
        spec = get_spec(jm["spec"], f"{jm['frame_w']}x{jm['frame_h']}", jm["cols"], jm["rows"])
        jobs = jm["jobs"]
    else:
        if not a.spec:
            raise SystemExit("--spec is required without --jobs")
        spec = get_spec(a.spec, a.frame, a.cols, a.rows)
        jobs = [{"id": spec["frame_labels"][i], "frames": [i]} for i in range(len(a.inputs))]
        a.pick += [f"{spec['frame_labels'][i]}={p}" for i, p in enumerate(a.inputs)]

    a.colors = a.colors or int(pp.get(spec.get("colors") or "sprite_colors", 16))
    a.background = a.background or pp.get("background", "auto")
    a.outline = a.outline or bool(pp.get("outline"))
    pal = a.palette or pp.get("palette_png")
    a.palette_img = None
    if pal:
        p = Image.open(pal).convert("RGB").quantize(colors=256, dither=Image.Dither.NONE)
        a.palette_img = p

    picks = dict(s.split("=", 1) for s in a.pick)
    out = Path(a.out)
    sheet = Image.new("RGBA", (spec["sheet_w"], spec["sheet_h"]), (0, 0, 0, 0))
    if out.exists():
        old = Image.open(out).convert("RGBA")
        if old.size == sheet.size:
            sheet = old
        else:
            print(f"note: existing {out} is {old.size}, expected {sheet.size}; starting blank")

    fw, fh, cols = spec["frame_w"], spec["frame_h"], spec["cols"]
    done, missing = {}, []
    for j in jobs:
        if j.get("skip") or j.get("mirror_of"):
            continue
        src = picks.get(j["id"])
        if not src and a.images and j.get("output_prefix"):
            src = newest_output(Path(a.images), j["output_prefix"])
        if not src or not Path(src).exists():
            missing.append(j["id"]); continue
        fr = process(Path(src), spec, a)
        done[j["id"]] = fr
        for idx in j["frames"]:
            box = ((idx % cols) * fw, (idx // cols) * fh)
            sheet.paste(Image.new("RGBA", (fw, fh), (0, 0, 0, 0)), box)
            sheet.paste(fr, box)
        print(f"  {j['id']:<12} <- {src}")
    for j in jobs:
        m = j.get("mirror_of")
        if m and m in done:
            fr = ImageOps.mirror(done[m])
            for idx in j["frames"]:
                box = ((idx % cols) * fw, (idx // cols) * fh)
                sheet.paste(Image.new("RGBA", (fw, fh), (0, 0, 0, 0)), box)
                sheet.paste(fr, box)
            print(f"  {j['id']:<12} <- mirror of {m}")

    out.parent.mkdir(parents=True, exist_ok=True)
    from PIL.PngImagePlugin import PngInfo
    meta = PngInfo()
    if missing:  # still partly placeholder -> validate_mod.py keeps flagging it
        meta.add_text("sdv_placeholder", "1")
    sheet.save(out, pnginfo=meta)
    print(f"wrote {out} ({sheet.width}x{sheet.height}, {a.colors} colors/frame)")
    if missing:
        print(f"missing outputs (kept existing pixels): {', '.join(missing)}")
    if not a.no_preview:
        # keep previews out of the mod folder so they don't ship
        prev_dir = Path(a.jobs).parent if a.jobs else Path.cwd() / "sdv_previews"
        prev_dir.mkdir(parents=True, exist_ok=True)
        prev = prev_dir / (out.stem + "_preview.png")
        sheet.resize((sheet.width * 4, sheet.height * 4), Image.NEAREST).save(prev)
        print(f"preview {prev}")


if __name__ == "__main__":
    main()

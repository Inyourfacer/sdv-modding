#!/usr/bin/env python3
"""Turn ComfyUI outputs into game-ready SDV sheets, for one or several targets from the same master images.

  # with jobs.json from make_comfy_workflow.py / batch.py (finds the newest output per job in --images)
  python postprocess.py --jobs comfy/Mira_portrait/jobs.json --images runs/Mira/<ts>/outputs --out "[CP] Mira/assets/portraits/Mira.png"

  # several targets in one pass (vanilla 1x, Sprites in Detail 8x, Portraiture 256 px frames)
  python postprocess.py --jobs jobs.json --images outputs --target vanilla=art/Mira.png --target hd:8=art/Mira_hd.png \\
         --target portraiture:256=art/Mira_256.png

  # pick specific files for jobs / no jobs.json
  python postprocess.py --jobs jobs.json --pick happy=out/b.png --out sheet.png
  python postprocess.py --spec object_icon --inputs gem.png --out assets/objects.png

Targets: `vanilla` (game size, palette-reduced, hard alpha), `hd:N` (vanilla frame x N, full colour, for Sprites in Detail),
`portraiture:F` (square F px frames, full colour). Frames not covered keep the existing sheet's pixels (the placeholder).
Vanilla pipeline per sheet: background removal -> crop to subject -> one common scale for the whole sheet (sprites) -> downscale
(`--resample dominant` picks the most common colour per output pixel: crisper than averaging) -> hard alpha -> ONE palette for the
whole sheet (or a locked palette: --palette / --character) -> orphan-pixel cleanup -> optional outline/grayscale.
Writes a 4x preview next to jobs.json (or ./sdv_previews/), never inside the mod.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from sdvlib import get_spec, load_config, load_json, load_project


# ---------------------------------------------------------------- background / framing
def remove_background(im: Image.Image, tol: int = 40) -> Image.Image:
    """Flood-remove the background color connected to the image border."""
    rgba = np.array(im.convert("RGBA"))
    rgb = rgba[..., :3].astype(np.int32)
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


def premult_resize(im: Image.Image, nw: int, nh: int, resample) -> Image.Image:
    """Resize without dark/white fringes from transparent pixels."""
    arr = np.array(im.convert("RGBA")).astype(np.float32)
    arr[..., :3] *= arr[..., 3:4] / 255.0
    pm = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA").resize((nw, nh), resample)
    out = np.array(pm).astype(np.float32)
    a = out[..., 3:4]
    out[..., :3] = np.where(a > 0, out[..., :3] * 255.0 / np.maximum(a, 1), 0)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGBA")


def fit_scale(im: Image.Image, fw: int, fh: int, anchor: str, pad: int) -> float:
    aw, ah = fw - 2 * pad, (fh - pad if anchor == "bottom" else fh - 2 * pad)
    return min(aw / im.width, ah / im.height)


def place(small: Image.Image, fw: int, fh: int, anchor: str) -> Image.Image:
    frame = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    x = (fw - small.width) // 2
    y = fh - small.height if anchor == "bottom" else (fh - small.height) // 2
    frame.alpha_composite(small, (x, y))
    return frame


def downscale_dominant(im: Image.Image, nw: int, nh: int, k: int = 6) -> Image.Image:
    """Crisp pixel-art downscale: per output pixel take the most common colour of its k x k source block."""
    big = premult_resize(im, nw * k, nh * k, Image.LANCZOS)
    arr = np.array(big)
    blocks = arr.reshape(nh, k, nw, k, 4).transpose(0, 2, 1, 3, 4).reshape(nh, nw, k * k, 4)
    out = np.zeros((nh, nw, 4), np.uint8)
    for y in range(nh):
        for x in range(nw):
            b = blocks[y, x]
            op = b[:, 3] >= 128
            if op.sum() * 2 < k * k:       # mostly transparent -> transparent
                continue
            rgb = b[op, :3]
            key = (rgb[:, 0] >> 3).astype(np.int32) << 10 | (rgb[:, 1] >> 3).astype(np.int32) << 5 | (rgb[:, 2] >> 3).astype(np.int32)
            vals, counts = np.unique(key, return_counts=True)
            sel = key == vals[counts.argmax()]
            out[y, x, :3] = rgb[sel].mean(0).astype(np.uint8)
            out[y, x, 3] = 255
    return Image.fromarray(out, "RGBA")


def hard_alpha(im: Image.Image, thresh: int = 128) -> Image.Image:
    arr = np.array(im)
    arr[..., 3] = np.where(arr[..., 3] >= thresh, 255, 0)
    return Image.fromarray(arr, "RGBA")


# ---------------------------------------------------------------- colour: Lab palettes
def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def build_palette(frames: list[Image.Image], colors: int) -> np.ndarray:
    """Median-cut palette from the opaque pixels of every frame together (one palette per sheet)."""
    px = [np.array(f)[np.array(f)[..., 3] > 0][:, :3] for f in frames]
    px = np.concatenate([p for p in px if len(p)]) if any(len(p) for p in px) else np.zeros((0, 3), np.uint8)
    if len(px) == 0:
        return np.zeros((0, 3), np.uint8)
    sample = Image.fromarray(px.reshape(-1, 1, 3).astype(np.uint8), "RGB")
    q = sample.quantize(colors=max(2, colors), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = np.array(q.getpalette()[: 3 * (max(q.getdata()) + 1)], np.uint8).reshape(-1, 3)
    return np.unique(pal, axis=0)


def apply_palette(im: Image.Image, palette: np.ndarray) -> Image.Image:
    """Map every opaque pixel to the nearest palette colour (distance measured in Lab)."""
    if len(palette) == 0:
        return im
    arr = np.array(im)
    op = arr[..., 3] > 0
    if not op.any():
        return im
    plab = srgb_to_lab(palette)
    px = arr[op][:, :3]
    uniq, inv = np.unique(px, axis=0, return_inverse=True)
    d = ((srgb_to_lab(uniq)[:, None, :] - plab[None, :, :]) ** 2).sum(-1)
    arr[op, :3] = palette[d.argmin(1)][inv.reshape(-1)]
    return Image.fromarray(arr, "RGBA")


def palette_from_png(path: str) -> np.ndarray:
    im = Image.open(path).convert("RGBA")
    a = np.array(im)
    px = a[a[..., 3] > 0][:, :3]
    return np.unique(px, axis=0)


def cleanup_orphans(im: Image.Image) -> Image.Image:
    """Drop isolated opaque pixels and fill single-pixel holes (typical downscale noise)."""
    arr = np.array(im)
    a = arr[..., 3] > 0
    p = np.pad(a, 1)
    n = p[:-2, 1:-1].astype(int) + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]
    orphan = a & (n == 0)
    hole = ~a & (n == 4)
    if hole.any():
        pr = np.pad(arr[..., :3].astype(np.int32), ((1, 1), (1, 1), (0, 0)))
        avg = (pr[:-2, 1:-1] + pr[2:, 1:-1] + pr[1:-1, :-2] + pr[1:-1, 2:]) // 4
        arr[hole, :3] = avg[hole]
        arr[hole, 3] = 255
    arr[orphan] = 0
    return Image.fromarray(arr, "RGBA")


def outline(im: Image.Image, darken: float = 0.45) -> Image.Image:
    arr = np.array(im).astype(np.int32)
    a = arr[..., 3] > 0
    nb = np.zeros_like(a)
    nb[1:, :] |= a[:-1, :]; nb[:-1, :] |= a[1:, :]; nb[:, 1:] |= a[:, :-1]; nb[:, :-1] |= a[:, 1:]
    edge = nb & ~a
    if not edge.any():
        return im
    mean = arr[a][:, :3].mean(0) if a.any() else np.array([40, 30, 40])
    arr[edge, :3] = (mean * darken).astype(np.int32)
    arr[edge, 3] = 255
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


# ---------------------------------------------------------------- pipeline
def prepare(src: Path, spec: dict, opts) -> Image.Image:
    """Load a master image; remove the background and crop to the subject for cut-out specs."""
    im = Image.open(src).convert("RGBA")
    remove = (spec.get("remove_bg") and opts.background == "auto") or opts.background == "remove"
    if remove:
        im = crop_to_content(remove_background(im, opts.bg_tol))
    im.info["cutout"] = bool(remove)
    return im


def parse_target(text: str):
    kind, _, n = text.partition(":")
    kind = kind.strip().lower()
    if kind not in ("vanilla", "hd", "portraiture"):
        raise SystemExit(f"Unknown target '{text}': use vanilla, hd:N or portraiture:F")
    if kind != "vanilla" and not n.isdigit():
        raise SystemExit(f"Target '{text}' needs a number (hd:8 = 8x vanilla, portraiture:256 = 256 px frames)")
    return kind, int(n) if n else 1


def target_spec(spec: dict, kind: str, n: int) -> dict:
    t = dict(spec)
    if kind == "hd":
        t["frame_w"], t["frame_h"] = spec["frame_w"] * n, spec["frame_h"] * n
    elif kind == "portraiture":
        t["frame_w"] = t["frame_h"] = n
    t["sheet_w"], t["sheet_h"] = t["frame_w"] * t["cols"], t["frame_h"] * t["rows"]
    return t


def finish_frames(prepared: dict[str, Image.Image], spec_t: dict, kind: str, opts) -> dict[str, Image.Image]:
    """Master images -> frames for one target. Sprites share one scale so figures keep their relative size."""
    fw, fh, anchor = spec_t["frame_w"], spec_t["frame_h"], spec_t.get("anchor", "center")
    cut = {k: im for k, im in prepared.items() if im.info.get("cutout")}
    common = None
    if cut and anchor == "bottom" and opts.consistent_scale:
        common = min(fit_scale(im, fw, fh, anchor, opts.pad) for im in cut.values())
    dominant = (opts.resample == "dominant") or (opts.resample == "auto" and kind == "vanilla" and bool(cut))
    out = {}
    for k, im in prepared.items():
        if im.info.get("cutout"):
            s = common if common is not None else fit_scale(im, fw, fh, anchor, opts.pad)
            nw, nh = max(1, round(im.width * s)), max(1, round(im.height * s))
            small = downscale_dominant(im, nw, nh) if dominant and kind == "vanilla" else premult_resize(im, nw, nh, Image.LANCZOS if kind != "vanilla" else Image.BOX)
            fr = place(small, fw, fh, anchor)
        else:  # portraits / tiles: center-crop to the frame aspect, fill
            w, h = im.size
            ratio = fw / fh
            if w / h > ratio:
                nw = int(h * ratio); im2 = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
            else:
                nh = int(w / ratio)
                top = 0 if anchor == "top" else (h - nh if anchor == "bottom" else (h - nh) // 2)
                im2 = im.crop((0, top, w, top + nh))
            if dominant and kind == "vanilla":
                fr = downscale_dominant(im2, fw, fh)
            else:
                fr = im2.resize((fw, fh), Image.BOX if kind == "vanilla" else Image.LANCZOS)
        if kind == "vanilla":
            fr = hard_alpha(fr)
        else:  # soft edges stay, but stray faint alpha is dropped
            arr = np.array(fr); arr[..., 3] = np.where(arr[..., 3] < 24, 0, arr[..., 3]); fr = Image.fromarray(arr, "RGBA")
        if opts.grayscale:
            g = ImageOps.grayscale(fr.convert("RGB")).convert("RGBA"); g.putalpha(fr.getchannel("A")); fr = g
        out[k] = fr
    if kind == "vanilla":
        pal = opts.palette_arr if opts.palette_arr is not None else build_palette(list(out.values()), opts.colors)
        opts.used_palette = pal
        for k in out:
            out[k] = apply_palette(out[k], pal)
            if not opts.no_cleanup:
                out[k] = cleanup_orphans(out[k])
            if opts.outline:
                out[k] = outline(out[k])
    return out


def newest_output(images_dir: Path, prefix: str) -> Path | None:
    stem = Path(prefix).name
    cands = [p for p in images_dir.rglob(f"{stem}_*.png")]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def write_sheet(path: Path, spec_t: dict, jobs: list[dict], frames: dict[str, Image.Image], missing: list[str], kind: str, n: int):
    sheet = Image.new("RGBA", (spec_t["sheet_w"], spec_t["sheet_h"]), (0, 0, 0, 0))
    base_is_real_art = False
    if path.exists():
        old_img = Image.open(path)
        if old_img.size == sheet.size:
            sheet = old_img.convert("RGBA")
            base_is_real_art = old_img.info.get("sdv_placeholder") != "1"
        else:
            print(f"note: existing {path} is {old_img.size}, expected {sheet.size}; starting blank")
    fw, fh, cols = spec_t["frame_w"], spec_t["frame_h"], spec_t["cols"]
    covered = set()

    def put(idx, fr):
        box = ((idx % cols) * fw, (idx // cols) * fh)
        sheet.paste(Image.new("RGBA", (fw, fh), (0, 0, 0, 0)), box)
        sheet.paste(fr, box)
        covered.add(idx)

    for j in jobs:
        if j["id"] in frames:
            for idx in j["frames"]:
                put(idx, frames[j["id"]])
    for j in jobs:
        m = j.get("mirror_of")
        if m and m in frames:
            for idx in j["frames"]:
                put(idx, ImageOps.mirror(frames[m]))
    from PIL.PngImagePlugin import PngInfo
    meta = PngInfo()
    uncovered = [i for i in range(cols * spec_t["rows"]) if i not in covered]
    if uncovered and not base_is_real_art:
        meta.add_text("sdv_placeholder", "1")
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, pnginfo=meta)
    return sheet, uncovered


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", help="jobs.json from make_comfy_workflow.py")
    ap.add_argument("--images", help="folder with ComfyUI outputs (searched recursively)")
    ap.add_argument("--pick", action="append", default=[], help="job_id=path override (repeatable)")
    ap.add_argument("--spec"); ap.add_argument("--frame"); ap.add_argument("--cols", type=int); ap.add_argument("--rows", type=int)
    ap.add_argument("--inputs", nargs="*", default=[], help="(no jobs.json) images in frame order")
    ap.add_argument("--out", help="vanilla output sheet (same as --target vanilla=PATH)")
    ap.add_argument("--target", action="append", default=[], help="kind[:N]=path; kinds: vanilla, hd:N, portraiture:F (repeatable)")
    ap.add_argument("--colors", type=int, help="palette size for vanilla (default from config by asset type)")
    ap.add_argument("--palette", help="PNG whose colours define the palette (locks the character look)")
    ap.add_argument("--character", help="character id in sdv-project.json: use its palette_png")
    ap.add_argument("--save-palette", help="write the palette used for the vanilla sheet to this PNG")
    ap.add_argument("--background", choices=["auto", "remove", "keep"])
    ap.add_argument("--bg-tol", type=int, default=40)
    ap.add_argument("--pad", type=int, default=0)
    ap.add_argument("--resample", choices=["auto", "dominant", "box"], default="auto",
                    help="vanilla downscale: dominant colour per pixel (auto for cut-out sprites/items) or area average")
    ap.add_argument("--no-consistent-scale", dest="consistent_scale", action="store_false", help="scale every frame to fit on its own")
    ap.add_argument("--no-cleanup", action="store_true", help="keep orphan pixels / single-pixel holes")
    ap.add_argument("--outline", action="store_true")
    ap.add_argument("--grayscale", action="store_true", help="for recolorable Fashion Sense hair etc.")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--config")
    a = ap.parse_args()

    cfg = load_config(a.config)
    pp = cfg.get("postprocess", {})
    targets = [t.split("=", 1) for t in a.target]
    if a.out:
        targets.insert(0, ["vanilla", a.out])
    if not targets:
        raise SystemExit("Give --out (vanilla) or one or more --target kind[:N]=path.")

    if a.jobs:
        jm = load_json(a.jobs)
        if not jm.get("frame_w"):
            raise SystemExit("This jobs.json has no sheet layout (a reference sheet?); nothing to post-process.")
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
    if a.character and not a.palette:
        ch = ((load_project() or {}).get("characters") or {}).get(a.character) or {}
        pal = ch.get("palette_png") or pal
    a.palette_arr = palette_from_png(pal) if pal and Path(pal).exists() else None
    a.used_palette = None

    picks = dict(s.split("=", 1) for s in a.pick)
    prepared, missing = {}, []
    for j in jobs:
        if j.get("skip") or j.get("mirror_of"):
            continue
        src = picks.get(j["id"])
        if not src and a.images and j.get("output_prefix"):
            src = newest_output(Path(a.images), j["output_prefix"])
        if not src or not Path(src).exists():
            missing.append(j["id"]); continue
        prepared[j["id"]] = prepare(Path(src), spec, a)
        print(f"  {j['id']:<12} <- {src}")
    for j in jobs:
        if j.get("mirror_of") and j["mirror_of"] in prepared:
            print(f"  {j['id']:<12} <- mirror of {j['mirror_of']}")

    for tgt, path in targets:
        kind, n = parse_target(tgt)
        spec_t = target_spec(spec, kind, n)
        frames = finish_frames(prepared, spec_t, kind, a)
        sheet, uncovered = write_sheet(Path(path), spec_t, jobs, frames, missing, kind, n)
        extra = f", {a.colors} colors" if kind == "vanilla" and a.palette_arr is None else (", locked palette" if kind == "vanilla" else "")
        print(f"wrote {path} [{tgt}] ({sheet.width}x{sheet.height}{extra})")
        if kind == "vanilla" and a.save_palette and a.used_palette is not None and len(a.used_palette):
            pimg = Image.new("RGB", (len(a.used_palette), 1))
            pimg.putdata([tuple(int(v) for v in c) for c in a.used_palette]); pimg.save(a.save_palette)
            print(f"palette ({len(a.used_palette)} colours) -> {a.save_palette}")
        if uncovered:
            print(f"  frames kept as existing/placeholder: {', '.join(map(str, uncovered))}")
        if not a.no_preview and kind == "vanilla":
            prev_dir = Path(a.jobs).parent if a.jobs else Path.cwd() / "sdv_previews"
            prev_dir.mkdir(parents=True, exist_ok=True)
            prev = prev_dir / (Path(path).stem + "_preview.png")
            sheet.resize((sheet.width * 4, sheet.height * 4), Image.NEAREST).save(prev)
            print(f"preview {prev}")
    if missing:
        print(f"missing outputs (kept existing pixels): {', '.join(missing)}")


if __name__ == "__main__":
    main()

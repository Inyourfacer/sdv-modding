#!/usr/bin/env python3
"""Automatic checks on a generated sheet. These catch mechanical problems; they do NOT replace looking at the image.

  python qa_art.py check art/mira_sprite/take_a.png --spec character_sprite [--target vanilla|hd:8|portraiture:256]
                         [--character Mira | --palette art/Mira/palette.png] [--colors 16] [--json]

Exit code 1 when any check FAILs. Every result carries a number so a failure says how bad it is:
  dimensions, transparent corners (background really removed), figure clipped at an edge, feet on the baseline,
  figure size, empty frame, semi-transparent pixels (vanilla), palette size / palette violations / distance to the locked palette,
  figure height consistent across facings, colour drift between facings (outfit/hair changing), identical facings,
  portrait expressions: same character (not drifting) yet visibly different from neutral.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from postprocess import palette_from_png, parse_target, srgb_to_lab, target_spec
from sdvlib import get_spec, load_project

# thresholds in one place so they can be tuned from live experience
HEIGHT_RATIO_WARN, HEIGHT_RATIO_FAIL = 1.15, 1.35
ROW_COLOUR_DRIFT_WARN, ROW_COLOUR_DRIFT_FAIL = 18.0, 35.0      # mean Lab distance between facings
PALETTE_DISTANCE_WARN = 12.0
PORTRAIT_DIFF_FAIL, PORTRAIT_DIFF_NONE = 0.55, 0.004           # share of pixels differing from neutral
DUPLICATE_ROW_DIFF = 0.02
SMALL_FIGURE = 0.45                                            # figure height / frame height


def res(frame, check, level, value, msg):
    return {"frame": frame, "check": check, "level": level, "value": value, "msg": msg}


def frame_view(sheet: np.ndarray, spec: dict, i: int) -> np.ndarray:
    c, fw, fh = spec["cols"], spec["frame_w"], spec["frame_h"]
    y, x = (i // c) * fh, (i % c) * fw
    return sheet[y:y + fh, x:x + fw]


def bbox(alpha: np.ndarray):
    ys, xs = np.where(alpha > 0)
    return (xs.min(), ys.min(), xs.max(), ys.max()) if len(ys) else None


def lower_body(f: np.ndarray) -> np.ndarray:
    """The frame with everything above the figure's lower 55% made transparent (clothes, not hair/face)."""
    bb = bbox(f[..., 3])
    if bb is None:
        return f
    cut_y = bb[1] + int((bb[3] - bb[1] + 1) * 0.45)
    g = f.copy(); g[:cut_y, 3] = 0
    return g


def mean_lab(frames: list[np.ndarray]):
    """Lab of the most common colour among the opaque pixels (the main garment colour; a mean would be diluted by skin/boots)."""
    px = [f[f[..., 3] > 0][:, :3] for f in frames]
    px = np.concatenate([p for p in px if len(p)]) if any(len(p) for p in px) else None
    if px is None:
        return None
    key = (px[:, 0] >> 3).astype(np.int32) << 10 | (px[:, 1] >> 3).astype(np.int32) << 5 | (px[:, 2] >> 3).astype(np.int32)
    vals, counts = np.unique(key, return_counts=True)
    return srgb_to_lab(px[key == vals[counts.argmax()]].mean(0, keepdims=True))[0]


def analyze(sheet_img: Image.Image, spec: dict, kind: str = "vanilla", n: int = 1, palette: np.ndarray | None = None,
            colors: int | None = None) -> list[dict]:
    out = []
    st = target_spec(spec, kind, n)
    if sheet_img.size != (st["sheet_w"], st["sheet_h"]):
        out.append(res(None, "dimensions", "FAIL", list(sheet_img.size), f"expected {st['sheet_w']}x{st['sheet_h']} for {kind}"))
        return out                                           # nothing else is meaningful
    out.append(res(None, "dimensions", "PASS", list(sheet_img.size), "exact"))
    if sheet_img.info.get("sdv_placeholder") == "1":
        out.append(res(None, "placeholder", "WARN", None, "some frames are still placeholder"))
    arr = np.array(sheet_img.convert("RGBA"))
    cols, rows, fw, fh = st["cols"], st["rows"], st["frame_w"], st["frame_h"]
    cut = bool(spec.get("remove_bg"))
    anchor = spec.get("anchor", "center")
    labels = st["frame_labels"]
    scale = n if kind == "hd" else 1
    frames = [frame_view(arr, st, i) for i in range(cols * rows)]

    if kind == "vanilla":
        a = arr[..., 3]
        semi = int(((a > 0) & (a < 255)).sum())
        out.append(res(None, "semi_transparent", "FAIL" if semi else "PASS", semi, "vanilla sheets need hard alpha" if semi else "none"))
        op = arr[a > 0][:, :3]
        if len(op):
            distinct = len(np.unique(op, axis=0))
            if palette is not None and len(palette):
                inpal = {tuple(c) for c in palette}
                bad = sum(1 for c in np.unique(op, axis=0) if tuple(c) not in inpal)
                out.append(res(None, "palette_violation", "FAIL" if bad else "PASS", bad, f"{bad} colour(s) outside the locked palette" if bad else "all on palette"))
                d = np.sqrt(((srgb_to_lab(op[::7]) [:, None, :] - srgb_to_lab(palette)[None, :, :]) ** 2).sum(-1)).min(1).mean()
                out.append(res(None, "palette_distance", "WARN" if d > PALETTE_DISTANCE_WARN else "PASS", round(float(d), 1), "mean distance to nearest palette colour"))
            elif colors:
                out.append(res(None, "palette_size", "WARN" if distinct > colors else "PASS", distinct, f"{distinct} colours (limit {colors})"))

    # per-frame
    heights = {}
    for i, f in enumerate(frames):
        alpha = f[..., 3]
        lab = f"{i}:{labels[i]}"
        if not cut:
            continue
        frac = float((alpha > 0).mean())
        if frac < 0.01:
            out.append(res(lab, "empty_frame", "FAIL", round(frac, 4), "nothing in this frame (background removal ate it, or it was never filled)"))
            continue
        corners = [alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]]
        solid = sum(1 for c in corners if c > 0)
        if solid >= 2:
            out.append(res(lab, "background_left", "FAIL", solid, f"{solid} of 4 corners are opaque: background was not removed"))
        bb = bbox(alpha)
        x0, y0, x1, y1 = bb
        clipped = [s for s, hit in (("left", x0 == 0), ("right", x1 == fw - 1), ("top", y0 == 0)) if hit]
        if clipped:
            out.append(res(lab, "clipped", "WARN", clipped, "figure touches the " + "/".join(clipped) + " edge (cut off?)"))
        if anchor == "bottom":
            gap = fh - 1 - y1
            if gap > 2 * scale:
                out.append(res(lab, "feet_baseline", "WARN", gap, f"feet are {gap}px above the frame bottom"))
        h = (y1 - y0 + 1) / fh
        heights[i] = y1 - y0 + 1
        if h < SMALL_FIGURE and anchor == "bottom":
            out.append(res(lab, "small_figure", "WARN", round(h, 2), f"figure fills only {int(h * 100)}% of the frame height"))

    # sheet-level for sprite-like sheets (several rows of facings)
    if cut and rows > 1 and heights:
        row_h = {}
        for r in range(rows):
            hs = [heights[r * cols + c] for c in range(cols) if (r * cols + c) in heights]
            if hs:
                row_h[r] = float(np.median(hs))
        if len(row_h) > 1:
            ratio = max(row_h.values()) / max(1.0, min(row_h.values()))
            lvl = "FAIL" if ratio > HEIGHT_RATIO_FAIL else "WARN" if ratio > HEIGHT_RATIO_WARN else "PASS"
            out.append(res(None, "height_consistency", lvl, round(ratio, 2), "tallest row / shortest row"))
        ref_lab, drift = None, {}
        for r in range(rows):
            lab_r = mean_lab([lower_body(frames[r * cols + c]) for c in range(cols)])
            if lab_r is None:
                continue
            if ref_lab is None:
                ref_lab = lab_r
            else:
                drift[r] = float(np.sqrt(((lab_r - ref_lab) ** 2).sum()))
        if drift:
            worst_r, worst = max(drift.items(), key=lambda kv: kv[1])
            lvl = "FAIL" if worst > ROW_COLOUR_DRIFT_FAIL else "WARN" if worst > ROW_COLOUR_DRIFT_WARN else "PASS"
            out.append(res(None, "facing_colour_drift", lvl, round(worst, 1),
                           f"clothes colour in row {worst_r} ({labels[worst_r * cols].split('_')[0]}) differs most from the first row (outfit changing between facings?)"))
        firsts = [frames[r * cols] for r in range(rows) if (frames[r * cols][..., 3] > 0).any()]
        for a_i in range(len(firsts)):
            for b_i in range(a_i + 1, len(firsts)):
                d = float((firsts[a_i] != firsts[b_i]).any(-1).mean())
                if d < DUPLICATE_ROW_DIFF:
                    out.append(res(None, "identical_facings", "WARN", round(d, 3), f"rows {a_i} and {b_i} are almost identical"))

    # portraits: expressions
    if not cut and spec.get("key", "").startswith("portrait") and len(frames) > 1:
        base = frames[0][..., :3].astype(int)
        for i in range(1, len(frames)):
            fr = frames[i]
            if not fr[..., 3].any():
                continue
            d = float((np.abs(fr[..., :3].astype(int) - base).max(-1) > 40).mean())
            lab = f"{i}:{labels[i]}"
            if d > PORTRAIT_DIFF_FAIL:
                out.append(res(lab, "expression_drift", "FAIL", round(d, 3), "differs from neutral almost everywhere (a different person/pose?)"))
            elif d < PORTRAIT_DIFF_NONE:
                out.append(res(lab, "no_expression_change", "WARN", round(d, 4), "looks identical to neutral"))
    return out


def merge_frames(results: list[dict]) -> list[dict]:
    """Identical findings on consecutive frames (the 4 copies of a facing) become one line, 'frames 4-7'."""
    out = []
    for r in results:
        prev = out[-1] if out else None
        if prev and r["frame"] and prev["frame"] and (prev["check"], prev["value"], prev["msg"], prev["level"]) == (r["check"], r["value"], r["msg"], r["level"]):
            first = prev["frame"].split("-")[0].split(":")[0]
            prev["frame"] = f"{first}-{r['frame'].split(':')[0]}"
            continue
        out.append(dict(r))
    return out


def verdict(results: list[dict]) -> dict:
    fails = [r for r in results if r["level"] == "FAIL"]
    warns = [r for r in results if r["level"] == "WARN"]
    return {"level": "FAIL" if fails else "WARN" if warns else "PASS", "fails": len(fails), "warns": len(warns),
            "score": len(fails) * 100 + len(warns), "reasons": [f"{r['check']}" + (f"[{r['frame']}]" if r["frame"] else "") + f": {r['msg']}" for r in fails + warns]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("sheet"); c.add_argument("--spec", required=True); c.add_argument("--frame"); c.add_argument("--cols", type=int); c.add_argument("--rows", type=int)
    c.add_argument("--target", default="vanilla"); c.add_argument("--palette"); c.add_argument("--character"); c.add_argument("--colors", type=int)
    c.add_argument("--json", action="store_true")
    a = ap.parse_args()
    spec = get_spec(a.spec, a.frame, a.cols, a.rows)
    kind, n = parse_target(a.target)
    pal_path = a.palette
    if a.character and not pal_path:
        ch = ((load_project() or {}).get("characters") or {}).get(a.character) or {}
        pal_path = ch.get("palette_png")
    pal = palette_from_png(pal_path) if pal_path and Path(pal_path).exists() else None
    results = merge_frames(analyze(Image.open(a.sheet), spec, kind, n, pal, a.colors))
    v = verdict(results)
    if a.json:
        print(json.dumps({"verdict": v, "results": results}, indent=2))
    else:
        for r in results:
            if r["level"] != "PASS" or a.target == "vanilla" and r["frame"] is None:
                print(f"[{r['level']:<4}] {r['check']:<20} {str(r['frame'] or 'sheet'):<14} {r['value']!s:<10} {r['msg']}")
        print(f"\nverdict: {v['level']}  ({v['fails']} fail, {v['warns']} warn)  Remember: these checks do not replace looking at the image.")
    sys.exit(1 if v["fails"] else 0)


if __name__ == "__main__":
    main()

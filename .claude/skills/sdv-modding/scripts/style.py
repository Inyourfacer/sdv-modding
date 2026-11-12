#!/usr/bin/env python3
"""Pick the project's house art style: compare checkpoint/LoRA candidates on the same small test set, then lock the winner.

  python style.py test --candidate "wai=waiIllustriousSDXL_v170.safetensors" \
                       --candidate "wai+pixel=waiIllustriousSDXL_v170.safetensors+PixelArt_Icon_IL_M_V2.1_00002.safetensors:0.8:pixel art" \
                       [--preset illustrious] [--no-run]
  python style.py lock --checkpoint X.safetensors --lora "file.safetensors:0.8:trigger words" --preset illustrious

A candidate is  label=checkpoint[+lora[:strength[:trigger words]]]...  The fixed test set per candidate: one portrait
(neutral + happy), three item icons, one ground tile. Everything is post-processed to game size and laid out side by side
(4x, nearest-neighbour) in style-test/comparison.png, with the owner's unpacked vanilla art alongside when it is available.
Nothing here touches a mod folder. `lock` writes art_style into sdv-project.json; until it is locked, art commands warn.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from sdvlib import PROJECT_NAME, find_project, load_config, load_project, new_project, save_project

HERE = Path(__file__).resolve().parent
PORTRAIT_SUBJECT = "1girl, short brown hair, green eyes, friendly, farmer, overalls, plaid shirt"
ITEMS = [("apple", "a red apple"), ("sword", "an iron sword"), ("potion", "a blue potion bottle")]
TILE = ("tile", "seamless grass ground tile")


def parse_candidate(text: str):
    label, _, rest = text.partition("=")
    if not rest:
        raise SystemExit(f"Bad candidate '{text}': expected label=checkpoint[+lora[:strength[:trigger]]]...")
    parts = rest.split("+")
    loras = []
    for p in parts[1:]:
        f = p.split(":")
        lo = {"name": f[0], "strength_model": float(f[1]) if len(f) > 1 and f[1] else 0.8}
        lo["strength_clip"] = lo["strength_model"]
        if len(f) > 2:
            lo["trigger"] = ":".join(f[2:])
        loras.append(lo)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", label), parts[0], loras


def lora_arg(lo: dict) -> str:
    return f"{lo['name']}:{lo['strength_model']}:{lo['strength_clip']}" + (f":{lo['trigger']}" if lo.get("trigger") else "")


def sh(cmd, cwd):
    return subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True)


def make_jobs(label, ckpt, loras, out: Path, preset):
    """Return [(kind, workflow_dir, spec_args)] after building every workflow for one candidate."""
    mk = [sys.executable, HERE / "make_comfy_workflow.py", "--checkpoint", ckpt, "--no-config-loras", "--seed", "4242", "--api"]
    for lo in loras:
        mk += ["--lora", lora_arg(lo)]
    if preset:
        mk += ["--preset", preset]
    jobs = []
    d = out / label / "portrait"
    r = sh(mk + ["--recipe", "portrait_sheet", "--name", "Test", "--subject", PORTRAIT_SUBJECT, "--frames", "neutral,happy", "--out-dir", d], out)
    jobs.append(("portrait", d, r))
    for name, subj in ITEMS:
        d = out / label / name
        jobs.append((name, d, sh(mk + ["--spec", "object_icon", "--name", name, "--subject", subj, "--out-dir", d], out)))
    d = out / label / TILE[0]
    jobs.append((TILE[0], d, sh(mk + ["--spec", "tilesheet", "--cols", "1", "--rows", "1", "--name", TILE[0], "--subject", TILE[1], "--out-dir", d], out)))
    for kind, d, r in jobs:
        if r.returncode != 0:
            raise SystemExit(f"building {label}/{kind} failed: {(r.stderr or r.stdout).strip()[-400:]}")
    return jobs


def font(size=14):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def vanilla_samples(cfg: dict):
    """Frames from the owner's own unpacked game content, if present (not shipped with the skill)."""
    root = cfg.get("unpacked_content")
    out = []
    if root and (Path(root) / "Portraits" / "Abigail.png").exists():
        im = Image.open(Path(root) / "Portraits" / "Abigail.png").convert("RGBA")
        out.append(("vanilla portrait", im.crop((0, 0, 64, 64))))
    obj = Path(root) / "Maps" / "springobjects.png" if root else None
    if obj and obj.exists():
        im = Image.open(obj).convert("RGBA")
        out.append(("vanilla items", im.crop((16 * 4, 0, 16 * 7, 16))))  # three neighbouring 16x16 icons
    return out


def build_sheet(cands: list[tuple[str, dict[str, Path]]], vanilla, out_png: Path):
    S = 4
    cell = 64 * S
    cols = 2 + len(ITEMS) + 1
    labw, pad = 190, 10
    rows = ([("reference", None)] if vanilla else []) + [(l, p) for l, p in cands]
    W = labw + cols * (cell + pad)
    sheet = Image.new("RGB", (W, len(rows) * (cell + pad) + pad), (236, 232, 222))
    d = ImageDraw.Draw(sheet)
    f = font()
    for r, (label, paths) in enumerate(rows):
        y = pad + r * (cell + pad)
        d.text((8, y + 8), label, fill=(30, 30, 30), font=f)
        if paths is None:
            x = labw
            for text, im in vanilla:
                big = im.resize((im.width * S, im.height * S), Image.NEAREST)
                sheet.paste(big, (x, y), big); d.text((x, y + cell - 14), text, fill=(30, 30, 30), font=f); x += big.width + pad
            continue
        x = labw
        pim = Image.open(paths["portrait"]).convert("RGBA") if paths.get("portrait") and paths["portrait"].exists() else None
        for i in (0, 1):
            if pim:
                fr = pim.crop(((i % 2) * 64, (i // 2) * 64, (i % 2) * 64 + 64, (i // 2) * 64 + 64)).resize((cell, cell), Image.NEAREST)
                sheet.paste(fr, (x, y), fr)
            x += cell + pad
        for k, _ in ITEMS + [TILE]:
            p = paths.get(k)
            if p and p.exists():
                im = Image.open(p).convert("RGBA").crop((0, 0, 16, 16)).resize((16 * S * 2, 16 * S * 2), Image.NEAREST)
                sheet.paste(im, (x, y + 20), im)
            x += cell + pad
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)


def cmd_test(a):
    cfg = load_config(a.config)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cands = []
    for text in a.candidate:
        label, ckpt, loras = parse_candidate(text)
        print(f"building {label}: {ckpt}" + "".join(f" + {l['name']}" for l in loras))
        jobs = make_jobs(label, ckpt, loras, out, a.preset)
        paths = {}
        if not a.no_run:
            for kind, d, _ in jobs:
                wfs = sorted(d.glob("*.api.json"))
                r = sh([sys.executable, HERE / "comfy.py", "run", *wfs, "--asset-id", f"styletest_{label}_{kind}", "--runs-dir", out / "runs"], out)
                if r.returncode == 2:
                    raise SystemExit("ComfyUI is not reachable. Ask the owner, then start it (comfy.py --start) and re-run.")
                if r.returncode != 0:
                    print(f"  {label}/{kind}: run failed: {(r.stderr or r.stdout).strip()[-300:]}"); continue
                m = re.search(r"run folder: (.+)", r.stdout)
                sheet = out / label / f"{kind}.png"
                pr = sh([sys.executable, HERE / "postprocess.py", "--jobs", d / "jobs.json", "--images", Path(m.group(1).strip()) / "outputs",
                         "--out", sheet, "--no-preview"], out)
                if pr.returncode == 0:
                    paths[kind] = sheet
        cands.append((label, paths))
    if a.no_run:
        print(f"workflows built under {out} (--no-run: nothing was queued)")
        return
    build_sheet(cands, vanilla_samples(cfg), out / "comparison.png")
    print(f"comparison sheet: {out / 'comparison.png'}\nPick one, then: python style.py lock --checkpoint <file> [--lora ...] [--preset ...]")


def cmd_lock(a):
    pp = find_project()
    proj = load_project(pp) if pp else new_project()
    path = pp or Path.cwd() / PROJECT_NAME
    st = proj.setdefault("art_style", {})
    st["checkpoint"] = a.checkpoint
    loras = []
    for text in a.lora:
        _, _, ls = parse_candidate("x=c+" + text)
        loras += ls
    st["loras"] = loras
    if a.preset:
        st["preset"] = a.preset
    for k in ("quality_prefix", "negative", "style_suffix"):
        v = getattr(a, k)
        if v is not None:
            st[k] = v
    st.setdefault("takes", 3)
    st.setdefault("max_rounds", 3)
    save_project(proj, path)
    print(f"art_style locked in {path}: {a.checkpoint}" + "".join(f" + {l['name']}" for l in loras))


def main():
    ap = argparse.ArgumentParser(description="Compare and lock the project's art style.")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("test")
    t.add_argument("--candidate", action="append", required=True)
    t.add_argument("--preset"); t.add_argument("--out", default="style-test"); t.add_argument("--no-run", action="store_true")
    lk = sub.add_parser("lock")
    lk.add_argument("--checkpoint", required=True); lk.add_argument("--lora", action="append", default=[])
    lk.add_argument("--preset"); lk.add_argument("--quality-prefix", dest="quality_prefix")
    lk.add_argument("--negative"); lk.add_argument("--style-suffix", dest="style_suffix")
    a = ap.parse_args()
    {"test": cmd_test, "lock": cmd_lock}[a.cmd](a)


if __name__ == "__main__":
    main()

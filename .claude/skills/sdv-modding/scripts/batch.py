#!/usr/bin/env python3
"""Build and run art for assets listed in sdv-project.json: recipe -> ComfyUI -> candidate sheets (never the mod).

  python batch.py plan   [--ids a,b] [--character Mira] [--status placeholder] [--takes 3]
  python batch.py run    [same filters] [--takes 3]            # build, queue on ComfyUI, post-process each take
  python batch.py approve-reference Mira art/Mira/reference_pick.png

Order is enforced per character: no reference approved -> the asset gets a reference_sheet job instead, and nothing else
is made for that character until you approve one (approve-reference). Candidates land in art/<asset-id>/take_<a|b|c>.png
beside the project file; installing a candidate into the mod is a separate, explicit step (it never happens here).
ComfyUI is never started by this script; comfy.py exits with code 2 when it is down.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from sdvlib import PROJECT_NAME, find_project, load_project, save_project

HERE = Path(__file__).resolve().parent
TAKES = "abcdefghij"


def select(proj: dict, a) -> list[dict]:
    rows = proj["assets"]
    if a.ids:
        want = set(a.ids.split(","))
        rows = [r for r in rows if r["id"] in want]
    if a.character:
        rows = [r for r in rows if r.get("character") == a.character]
    if a.status:
        rows = [r for r in rows if r["status"] == a.status]
    if a.spec:
        rows = [r for r in rows if r.get("spec") == a.spec]
    return rows


def decide(proj: dict, row: dict) -> dict:
    """Pick the recipe for one asset, honouring the reference gate."""
    ch = (proj.get("characters") or {}).get(row.get("character") or "")
    spec = row.get("spec")
    if ch and spec in ("portrait", "character_sprite", "portrait_hd"):
        ref = ch.get("reference_image")
        if not ref or not Path(ref).exists():
            return {"recipe": "reference_sheet", "spec": None, "note": f"no approved reference for {row['character']}: making a reference sheet first"}
        return {"recipe": "portrait_sheet" if spec.startswith("portrait") else "sprite_sheet", "spec": "portrait" if spec.startswith("portrait") else "character_sprite"}
    if not spec:
        return {"recipe": None, "note": "no spec set for this asset (set 'spec' in the project file)"}
    return {"recipe": "simple", "spec": spec}


def base_seed(proj: dict, row: dict) -> int:
    ch = (proj.get("characters") or {}).get(row.get("character") or "") or {}
    if ch.get("seed") is not None:
        return int(ch["seed"])
    return sum(ord(c) for c in row["id"]) * 7919 % 2_000_000_000


def build_cmd(proj: dict, row: dict, plan: dict, take: int, out_dir: Path) -> list[str]:
    ch_id = row.get("character")
    cmd = [sys.executable, str(HERE / "make_comfy_workflow.py"), "--name", re.sub(r"[^A-Za-z0-9_.-]+", "_", row["id"]),
           "--out-dir", str(out_dir), "--seed", str(base_seed(proj, row) + take * 1000), "--api"]
    if plan["recipe"] == "simple":
        subj = (row.get("prompt") or {}).get("positive") or row.get("notes") or row["id"].replace("_", " ")
        cmd += ["--spec", plan["spec"], "--subject", subj]
    else:
        cmd += ["--recipe", plan["recipe"], "--character", ch_id]
        if plan.get("spec"):
            cmd += ["--spec", plan["spec"]]
        if row.get("outfit"):
            cmd += ["--outfit", row["outfit"]]
    if (row.get("prompt") or {}).get("negative"):
        cmd += ["--negative-extra", row["prompt"]["negative"]]
    return cmd


def sh(cmd: list[str], cwd: Path):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser(description="Build/run art for project assets.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        s = sub.add_parser(name)
        s.add_argument("--ids"); s.add_argument("--character"); s.add_argument("--status"); s.add_argument("--spec")
        s.add_argument("--takes", type=int); s.add_argument("--timeout", type=float, default=1800)
    ar = sub.add_parser("approve-reference"); ar.add_argument("character"); ar.add_argument("image")
    ar.add_argument("--kind", choices=["body", "portrait"], default="body",
                    help="body = full figure (sprites, gate); portrait = head-and-shoulders (portrait sheets)")
    ar.add_argument("--crop", help="left,top,right,bottom as fractions 0-1 or pixels, to cut one figure out of a sheet")
    a = ap.parse_args()

    pp = find_project()
    if not pp:
        raise SystemExit(f"No {PROJECT_NAME}; run project.py sync first.")
    root = pp.parent
    proj = load_project(pp)

    if a.cmd == "approve-reference":
        ch = (proj["characters"] or {}).get(a.character)
        if ch is None:
            raise SystemExit(f"Unknown character '{a.character}'. Add it under characters in {PROJECT_NAME} first.")
        fname = "reference.png" if a.kind == "body" else "portrait_reference.png"
        dst = root / "art" / re.sub(r"[^A-Za-z0-9_.-]+", "_", a.character) / fname
        dst.parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(a.image).convert("RGB")
        if a.crop:
            l, t, r, b_ = [float(x) for x in a.crop.split(",")]
            box = [int(v * im.width) if v <= 1 and i % 2 == 0 else int(v * im.height) if v <= 1 else int(v) for i, v in enumerate((l, t, r, b_))]
            im = im.crop(tuple(box))
        im.save(dst)
        ch["reference_image" if a.kind == "body" else "portrait_reference_image"] = dst.relative_to(root).as_posix()
        save_project(proj, pp)
        print(f"{a.kind} reference approved for {a.character}: {dst.relative_to(root).as_posix()} ({im.width}x{im.height})")
        return

    takes = a.takes or int((proj.get("art_style") or {}).get("takes") or 3)
    rows = select(proj, a)
    if not rows:
        raise SystemExit("No assets match.")
    gate_done = set()
    failures = 0
    for row in rows:
        plan = decide(proj, row)
        if not plan["recipe"]:
            print(f"skip {row['id']}: {plan['note']}"); continue
        if plan["recipe"] == "reference_sheet":
            if row.get("character") in gate_done:
                print(f"skip {row['id']}: waiting on reference for {row['character']}"); continue
            gate_done.add(row.get("character"))
        n = takes
        print(f"\n== {row['id']}: {plan['recipe']} x{n} take(s)" + (f"  [{plan['note']}]" if plan.get("note") else ""))
        for t in range(n):
            letter = TAKES[t]
            wf = root / "comfy" / row["id"] / f"take_{letter}"
            for stale in list(wf.glob("*.api.json")) + list(wf.glob("jobs.json")):   # our own generated files only
                stale.unlink()
            r = sh(build_cmd(proj, row, plan, t, wf), root)
            if r.returncode != 0:
                print(f"  take {letter}: build failed: {(r.stderr or r.stdout).strip().splitlines()[-1]}"); failures += 1; continue
            if a.cmd == "plan":
                print(f"  take {letter}: {wf}"); continue
            aid = f"{row['id']}_take_{letter}"
            r = sh([sys.executable, str(HERE / "comfy.py"), "run", *map(str, sorted(wf.glob("*.api.json"))), "--asset-id", aid,
                    "--runs-dir", str(root / "runs"), "--timeout", str(a.timeout)], root)
            sys.stdout.write(r.stdout)
            if r.returncode != 0:
                sys.stderr.write(r.stderr)
                if r.returncode == 2:
                    raise SystemExit("ComfyUI is not reachable. Ask the owner, then start it (comfy.py --start) and re-run.")
                failures += 1; continue
            m = re.search(r"run folder: (.+)", r.stdout)
            outs = Path(m.group(1).strip()) / "outputs"
            if plan["recipe"] == "reference_sheet":
                print(f"  take {letter}: reference image(s) in {outs}")
                continue
            cand = root / "art" / row["id"] / f"take_{letter}.png"
            targets = [f"vanilla={cand}"]
            for tg in row.get("targets") or []:
                kind = tg.get("kind")
                if kind == "hd":
                    n = int(tg.get("scale", 8))
                    targets.append(f"hd:{n}=" + str(cand.with_name(f"{cand.stem}.hd{n}.png")))
                elif kind == "portraiture":
                    n = int(tg.get("frame", 256))
                    targets.append(f"portraiture:{n}=" + str(cand.with_name(f"{cand.stem}.portraiture{n}.png")))
            pcmd = [sys.executable, str(HERE / "postprocess.py"), "--jobs", str(wf / "jobs.json"), "--images", str(outs), "--no-preview"]
            for tg in targets:
                pcmd += ["--target", tg]
            if row.get("character"):
                pcmd += ["--character", row["character"]]
            pr = sh(pcmd, root)
            print(f"  take {letter}: " + ("candidate " + cand.relative_to(root).as_posix() if pr.returncode == 0 else "postprocess failed: " + pr.stderr.strip()[-200:]))
            failures += pr.returncode != 0
        if a.cmd == "run" and plan["recipe"] != "reference_sheet":
            art = root / "art" / row["id"]
            cands = sorted(art.glob("take_?.png"))          # one vanilla file per take; HD/Portraiture files sit beside it
            if cands:
                row["status"] = "generated"
                row["candidates"] = [c.relative_to(root).as_posix() for c in cands]
                row["candidate_targets"] = {c.stem: [f.relative_to(root).as_posix() for f in sorted(art.glob(c.stem + ".*.png"))] for c in cands}
                save_project(proj, pp)
    if a.cmd == "run" and gate_done:
        print("\nReference sheets were made. Look at them, pick one, then: python batch.py approve-reference <character> <image>")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()

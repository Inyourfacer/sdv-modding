#!/usr/bin/env python3
"""Build, run, check and install art for assets listed in sdv-project.json. The mod is only touched by `install`.

  python batch.py plan   [--ids a,b] [--character Mira] [--status placeholder] [--takes 3]
  python batch.py run    [same filters] [--takes 3] [--rounds 3]   # generate -> post-process -> QA -> re-roll failures -> contact sheet
  python batch.py approve-reference Mira art/Mira/sheet.png --kind body --crop 0,0.02,0.235,0.99
  python batch.py approve <asset-id> --take b --owner-approved      # records the owner's choice (status approved)
  python batch.py install <asset-id> [--overwrite]                  # copies the approved take into the mod (with a backup)

The loop per asset: N takes (default 3) -> qa_art.py on each -> takes that FAIL are re-rolled with a new seed (and a nudged
--denoise where the failure says so), at most `rounds` times (default 3) -> art/<id>/contact.png with every take, the QA result and the
reference -> STOP. Claude must open contact.png, review it against the character, and show the owner before `approve`.
`approve` needs --owner-approved, which Claude passes only after the owner chose a take in the conversation. `install` refuses
without an approved take, and refuses to overwrite real (non-placeholder) art without --overwrite; whatever it replaces is copied to
backups/<timestamp>/ first. ComfyUI is never started here: comfy.py exits 2 when it is down.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

from sdvlib import PROJECT_NAME, find_project, get_spec, load_config, load_project, save_project

HERE = Path(__file__).resolve().parent
TAKES = "abcdefghij"


# ---------------------------------------------------------------- selection and planning
def select(proj: dict, a) -> list[dict]:
    rows = proj["assets"]
    if getattr(a, "ids", None):
        want = set(a.ids.split(","))
        rows = [r for r in rows if r["id"] in want]
    if getattr(a, "character", None):
        rows = [r for r in rows if r.get("character") == a.character]
    if getattr(a, "status", None):
        rows = [r for r in rows if r["status"] == a.status]
    if getattr(a, "spec", None):
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


def build_cmd(proj: dict, row: dict, plan: dict, seed: int, out_dir: Path, denoise: float | None) -> list[str]:
    cmd = [sys.executable, str(HERE / "make_comfy_workflow.py"), "--name", re.sub(r"[^A-Za-z0-9_.-]+", "_", row["id"]),
           "--out-dir", str(out_dir), "--seed", str(seed), "--api"]
    if plan["recipe"] == "simple":
        subj = (row.get("prompt") or {}).get("positive") or row.get("notes") or row["id"].replace("_", " ")
        cmd += ["--spec", plan["spec"], "--subject", subj]
    else:
        cmd += ["--recipe", plan["recipe"], "--character", row["character"]]
        if plan.get("spec"):
            cmd += ["--spec", plan["spec"]]
        if row.get("outfit"):
            cmd += ["--outfit", row["outfit"]]
        if denoise is not None and plan["recipe"] == "portrait_sheet":
            cmd += ["--denoise", f"{denoise:.2f}"]
    if (row.get("prompt") or {}).get("negative"):
        cmd += ["--negative-extra", row["prompt"]["negative"]]
    return cmd


def sh(cmd: list, cwd: Path):
    return subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True)


def target_args(row: dict, cand: Path) -> list[str]:
    targets = [f"vanilla={cand}"]
    for tg in row.get("targets") or []:
        kind = tg.get("kind")
        if kind == "hd":
            n = int(tg.get("scale", 8))
            targets.append(f"hd:{n}=" + str(cand.with_name(f"{cand.stem}.hd{n}.png")))
        elif kind == "portraiture":
            n = int(tg.get("frame", 256))
            targets.append(f"portraiture:{n}=" + str(cand.with_name(f"{cand.stem}.portraiture{n}.png")))
    out = []
    for tg in targets:
        out += ["--target", tg]
    return out


# ---------------------------------------------------------------- one take
class ComfyDown(Exception):
    pass


def clear_stale(wf: Path):
    for stale in list(wf.glob("*.api.json")) + list(wf.glob("jobs.json")):       # our own generated files only
        stale.unlink()


def generate_take(root, proj, row, plan, t: int, rnd: int, denoise, timeout) -> Path | None:
    letter = TAKES[t]
    wf = root / "comfy" / row["id"] / f"take_{letter}"
    clear_stale(wf)
    seed = base_seed(proj, row) + t * 1000 + rnd * 100000
    r = sh(build_cmd(proj, row, plan, seed, wf, denoise), root)
    if r.returncode != 0:
        print(f"  take {letter}: build failed: {(r.stderr or r.stdout).strip().splitlines()[-1]}")
        return None
    r = sh([sys.executable, HERE / "comfy.py", "run", *sorted(wf.glob("*.api.json")), "--asset-id", f"{row['id']}_take_{letter}",
            "--runs-dir", root / "runs", "--timeout", timeout], root)
    sys.stdout.write(r.stdout)
    if r.returncode == 2:
        sys.stderr.write(r.stderr)
        raise ComfyDown()
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return None
    m = re.search(r"run folder: (.+)", r.stdout)
    outs = Path(m.group(1).strip()) / "outputs"
    if plan["recipe"] == "reference_sheet":
        print(f"  take {letter}: reference image(s) in {outs}")
        return None
    cand = root / "art" / row["id"] / f"take_{letter}.png"
    pcmd = [sys.executable, HERE / "postprocess.py", "--jobs", wf / "jobs.json", "--images", outs, "--no-preview", *target_args(row, cand)]
    if row.get("character"):
        pcmd += ["--character", row["character"]]
    pr = sh(pcmd, root)
    if pr.returncode != 0:
        print(f"  take {letter}: postprocess failed: {pr.stderr.strip()[-200:]}")
        return None
    return cand


def qa_for(root, proj, row, plan, cand: Path):
    from postprocess import palette_from_png
    from qa_art import analyze, merge_frames, verdict
    spec = get_spec(plan["spec"])
    ch = (proj.get("characters") or {}).get(row.get("character") or "") or {}
    palp = ch.get("palette_png")
    pal = palette_from_png(str(root / palp)) if palp and (root / palp).exists() else None
    cfg = load_config()
    colors = int((cfg.get("postprocess") or {}).get(spec.get("colors") or "sprite_colors", 16))
    results = merge_frames(analyze(Image.open(cand), spec, "vanilla", 1, pal, colors))
    return verdict(results), results


def adjust(plan: dict, v: dict, denoise: float | None) -> tuple[float | None, str]:
    """Nudge a failed take's settings from what failed; otherwise the re-roll is just a new seed."""
    cur = denoise if denoise is not None else 0.55
    if plan["recipe"] == "portrait_sheet" and any(r.startswith("expression_drift") for r in v["reasons"]):
        new = max(0.30, round(cur - 0.10, 2))
        return new, f"denoise {cur:.2f} -> {new:.2f} (expressions drifted from neutral)"
    return denoise, "new seed"


# ---------------------------------------------------------------- approve / install
def is_placeholder(p: Path) -> bool:
    try:
        return Image.open(p).info.get("sdv_placeholder") == "1"
    except Exception:
        return False


def find_row(proj, asset):
    row = next((r for r in proj["assets"] if r["id"] == asset), None)
    if not row:
        raise SystemExit(f"No asset '{asset}'.")
    return row


def cmd_approve(a, root, proj, pp):
    row = find_row(proj, a.asset)
    if not a.owner_approved:
        raise SystemExit("Refusing: pass --owner-approved only after the owner looked at the contact sheet and chose this take in the conversation.")
    cand = root / "art" / row["id"] / f"take_{a.take}.png"
    if not cand.exists():
        raise SystemExit(f"No candidate {cand.relative_to(root).as_posix()}.")
    q = (row.get("qa") or {}).get(f"take_{a.take}") or {}
    if q.get("level") == "FAIL" and not a.force:
        raise SystemExit(f"take_{a.take} failed QA ({'; '.join(q.get('reasons', [])[:3])}). Approve anyway only if the owner insists: --force.")
    row["status"], row["take"] = "approved", f"take_{a.take}"
    row["approved"] = {"take": a.take, "qa": q.get("level"), "at": datetime.now().isoformat(timespec="seconds")}
    save_project(proj, pp)
    print(f"{row['id']}: approved take_{a.take}. Next: python batch.py install {row['id']}")


def cmd_install(a, root, proj, pp):
    row = find_row(proj, a.asset)
    if row["status"] != "approved" or not row.get("take"):
        raise SystemExit(f"{a.asset} is '{row['status']}', not approved. Show the contact sheet to the owner, then batch.py approve.")
    take = row["take"]
    base = root / "art" / row["id"]
    files = row.get("files") or []
    if not files:
        raise SystemExit(f"{a.asset} has no 'files' (destination in the mod). Set it in {PROJECT_NAME}.")
    jobs = [(base / f"{take}.png", root / files[0])]
    for tg in row.get("targets") or []:
        kind = tg.get("kind")
        if kind in ("hd", "portraiture"):
            n = int(tg.get("scale", 8)) if kind == "hd" else int(tg.get("frame", 256))
            tag = f"hd{n}" if kind == "hd" else f"portraiture{n}"
            if tg.get("file"):
                jobs.append((base / f"{take}.{tag}.png", root / tg["file"]))
            else:
                print(f"note: target {kind}:{n} has no 'file' in the project, so it is not installed (set targets[].file).")
    for src, dst in jobs:
        if not src.exists():
            raise SystemExit(f"Missing {src.relative_to(root).as_posix()}.")
    blocked = [d for s, d in jobs if d.exists() and not is_placeholder(d) and not a.overwrite]
    if blocked:
        raise SystemExit("Refusing to overwrite real art without --overwrite (it will be backed up first): " + ", ".join(str(b.relative_to(root)) for b in blocked))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for src, dst in jobs:
        if dst.exists():
            bk = root / "backups" / stamp / dst.relative_to(root)
            bk.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, bk)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        print(f"installed {dst.relative_to(root).as_posix()}")
    row["status"] = "installed"
    row["installed"] = {"take": take, "at": datetime.now().isoformat(timespec="seconds")}
    save_project(proj, pp)
    print("next: python validate_mod.py <the mod folder>, then test in game.")


def approve_reference(a, root, proj, pp):
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


# ---------------------------------------------------------------- the loop for one asset
def run_asset(root, proj, pp, row, plan, takes, max_rounds, timeout):
    """Generate takes, QA them, re-roll FAILs (bounded), write the contact sheet. Returns (best_take_letter, level) or None."""
    state = {t: {"denoise": None, "verdict": None, "path": None, "redo": False} for t in range(takes)}
    history = []
    for t in range(takes):
        state[t]["path"] = generate_take(root, proj, row, plan, t, 0, None, timeout)
    if plan["recipe"] == "reference_sheet":
        return None
    for rnd in range(0, max_rounds + 1):
        for t, st in state.items():
            if st["path"] and (st["verdict"] is None or st["redo"]):
                st["verdict"], _ = qa_for(root, proj, row, plan, st["path"])
                st["redo"] = False
                print(f"  take {TAKES[t]}: QA {st['verdict']['level']} ({st['verdict']['fails']} fail, {st['verdict']['warns']} warn)")
        failed = [t for t, st in state.items() if not st["path"] or st["verdict"]["level"] == "FAIL"]
        if not failed or rnd == max_rounds:
            break
        for t in failed:
            st = state[t]
            v = st["verdict"] or {"reasons": ["no output"], "level": "NO OUTPUT"}
            new_d, note = adjust(plan, v, st["denoise"])
            history.append({"round": rnd + 1, "take": TAKES[t], "level": v["level"], "reasons": v["reasons"], "adjustment": note})
            print(f"  re-roll take {TAKES[t]} (round {rnd + 1}): {note}")
            st["denoise"] = new_d
            st["path"] = generate_take(root, proj, row, plan, t, rnd + 1, new_d, timeout)
            st["verdict"], st["redo"] = None, True
    ok = {t: st for t, st in state.items() if st["path"] and st["verdict"]}
    if not ok:
        return False
    art = root / "art" / row["id"]
    best = min(ok, key=lambda t: (ok[t]["verdict"]["score"], t))
    from contact_sheet import build as contact
    ch = (proj.get("characters") or {}).get(row.get("character") or "") or {}
    ref = ch.get("portrait_reference_image") if plan["recipe"] == "portrait_sheet" else ch.get("reference_image")
    contact([ok[t]["path"] for t in sorted(ok)], get_spec(plan["spec"]), art / "contact.png",
            str(root / ref) if ref else None, str(root / ch["palette_png"]) if ch.get("palette_png") else None, "vanilla", 1)
    row["status"] = "generated"
    row["candidates"] = [ok[t]["path"].relative_to(root).as_posix() for t in sorted(ok)]
    row["candidate_targets"] = {ok[t]["path"].stem: [f.relative_to(root).as_posix() for f in sorted(art.glob(ok[t]["path"].stem + ".*.png"))] for t in sorted(ok)}
    row["qa"] = {f"take_{TAKES[t]}": {"level": ok[t]["verdict"]["level"], "score": ok[t]["verdict"]["score"], "reasons": ok[t]["verdict"]["reasons"]} for t in sorted(ok)}
    row["recommended"] = f"take_{TAKES[best]}"
    row["history"] = (row.get("history") or []) + history
    (art / "qa.json").write_text(json.dumps({"qa": row["qa"], "recommended": row["recommended"], "history": history}, indent=2), encoding="utf-8")
    save_project(proj, pp)
    return TAKES[best], ok[best]["verdict"]["level"]


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        s = sub.add_parser(name)
        s.add_argument("--ids"); s.add_argument("--character"); s.add_argument("--status"); s.add_argument("--spec")
        s.add_argument("--takes", type=int); s.add_argument("--rounds", type=int); s.add_argument("--timeout", type=float, default=1800)
    ar = sub.add_parser("approve-reference"); ar.add_argument("character"); ar.add_argument("image")
    ar.add_argument("--kind", choices=["body", "portrait"], default="body",
                    help="body = full figure (sprites, gate); portrait = head-and-shoulders (portrait sheets)")
    ar.add_argument("--crop", help="left,top,right,bottom as fractions 0-1 or pixels, to cut one figure out of a sheet")
    ap2 = sub.add_parser("approve"); ap2.add_argument("asset"); ap2.add_argument("--take", required=True)
    ap2.add_argument("--owner-approved", action="store_true"); ap2.add_argument("--force", action="store_true")
    ins = sub.add_parser("install"); ins.add_argument("asset"); ins.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()

    pp = find_project()
    if not pp:
        raise SystemExit(f"No {PROJECT_NAME}; run project.py sync first.")
    root = pp.parent
    proj = load_project(pp)

    if a.cmd == "approve-reference":
        return approve_reference(a, root, proj, pp)
    if a.cmd == "approve":
        return cmd_approve(a, root, proj, pp)
    if a.cmd == "install":
        return cmd_install(a, root, proj, pp)

    style = proj.get("art_style") or {}
    takes = a.takes or int(style.get("takes") or 3)
    max_rounds = a.rounds if a.rounds is not None else int(style.get("max_rounds") or 3)
    rows = select(proj, a)
    if not rows:
        raise SystemExit("No assets match.")
    gate_done, failures, reviews = set(), 0, []
    for row in rows:
        plan = decide(proj, row)
        if not plan["recipe"]:
            print(f"skip {row['id']}: {plan['note']}"); continue
        if plan["recipe"] == "reference_sheet":
            if row.get("character") in gate_done:
                print(f"skip {row['id']}: waiting on reference for {row['character']}"); continue
            gate_done.add(row.get("character"))
        print(f"\n== {row['id']}: {plan['recipe']} x{takes} take(s), up to {max_rounds} re-roll round(s)" + (f"  [{plan['note']}]" if plan.get("note") else ""))
        if a.cmd == "plan":
            for t in range(takes):
                wf = root / "comfy" / row["id"] / f"take_{TAKES[t]}"
                clear_stale(wf)
                r = sh(build_cmd(proj, row, plan, base_seed(proj, row) + t * 1000, wf, None), root)
                print(f"  take {TAKES[t]}: " + (str(wf) if r.returncode == 0 else "build failed: " + (r.stderr or r.stdout).strip().splitlines()[-1]))
                failures += r.returncode != 0
            continue
        try:
            res = run_asset(root, proj, pp, row, plan, takes, max_rounds, a.timeout)
        except ComfyDown:
            raise SystemExit("ComfyUI is not reachable. Ask the owner, then start it (comfy.py --start) and re-run.")
        if res is False:
            failures += 1
            print(f"  no usable takes for {row['id']}")
        elif res:
            reviews.append((row["id"], root / "art" / row["id"] / "contact.png", f"take_{res[0]}", res[1]))
    if reviews:
        print("\nREVIEW NEEDED (do not install anything yet):")
        for rid, png, rec, lvl in reviews:
            print(f"  {rid}: open {png}  (QA recommends {rec}, {lvl})")
        print("Open each contact sheet, check it against the character, show it to the owner. After they choose: batch.py approve <id> --take <letter> --owner-approved")
    if a.cmd == "run" and gate_done:
        print("\nReference sheets were made. Look at them, pick one, then: python batch.py approve-reference <character> <image> --kind body --crop ...")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Prepare a release of one or more mods: validate, bump versions, changelog, zips, draft description. Never uploads anything.

  python release.py "[CP] My Mod" "[SID] My Mod" --version 1.2.0 --note "Added the Cottage" [--out releases] [--dry-run]
  options: --allow-placeholders  --update-key Nexus:1234  --force-version  --project-name "My Mod"

Order (nothing is written unless every check passes): validate_mod.py on each mod (ERRORs and leftover placeholder art stop it) ->
Version in each manifest (text edit) and MinimumVersion for dependencies between the mods of this release -> CHANGELOG.md section
(your notes + new custom IDs + art installed since the last release) and a record in sdv-project.json -> one zip per mod and one
all-in-one zip in the output folder (outside the mods; config.json, backups, runs, previews, *.bak left out; C# mods are built in
Release first) -> a draft description for the mod page. See references/release.md.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import cptext
from sdvlib import find_project, load_manifest, load_project, save_project

HERE = Path(__file__).resolve().parent
SKIP_NAMES = {"config.json", "Thumbs.db", ".DS_Store", ".sdv-game.json"}
SKIP_DIRS = {"backups", "runs", "art-source", ".git", "releases", "tests", "__pycache__"}
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")


def die(msg: str):
    raise SystemExit("release.py: " + msg)


def vtuple(v: str):
    return tuple(int(x) for x in re.match(r"(\d+)\.(\d+)\.(\d+)", v).groups())


def included(path: Path, root: Path, is_csharp: bool) -> bool:
    rel = path.relative_to(root)
    parts = set(rel.parts[:-1])
    if parts & SKIP_DIRS or (is_csharp and parts & {"bin", "obj"}) or (not is_csharp and parts & {"obj"}):
        return False
    n = path.name
    return not (n in SKIP_NAMES or n.endswith(("_preview.png", ".bak", ".pdb")) or " - Copy" in n or n.endswith(".before-8x.bak"))


def mod_files(mod: Path) -> list[tuple[Path, str]]:
    """(source, path inside the zip below the mod folder) for a mod."""
    is_cs = bool(list(mod.glob("*.csproj")))
    out = []
    if is_cs:
        build = mod / "bin" / "Release" / "net6.0"
        for f in sorted(build.glob("*.dll")):
            out.append((f, f.name))
        for name in ("manifest.json",):
            out.append((mod / name, name))
        for sub in ("i18n", "assets"):
            for f in sorted((mod / sub).rglob("*")) if (mod / sub).exists() else []:
                if f.is_file() and included(f, mod, True):
                    out.append((f, f.relative_to(mod).as_posix()))
        return out
    for f in sorted(mod.rglob("*")):
        if f.is_file() and included(f, mod, False):
            out.append((f, f.relative_to(mod).as_posix()))
    return out


def set_version(text: str, version: str) -> str:
    new, n = re.subn(r'(?i)("version"\s*:\s*")([^"]*)(")', lambda m: m.group(1) + version + m.group(3), text, count=1)
    if not n:
        die("a manifest has no Version")
    return new


def set_update_keys(text: str, keys: list[str]) -> str:
    arr = "[ " + ", ".join(json.dumps(k) for k in keys) + " ]"
    new, n = re.subn(r'(?i)("updatekeys"\s*:\s*)\[[^\]]*\]', lambda m: m.group(1) + arr, text, count=1)
    return new if n else cptext.insert_in_object(text, {"UpdateKeys": keys})


def bump_dependencies(text: str, release_ids: set[str], version: str) -> str:
    data = json.loads(cptext_strip(text))
    changed = False
    for d in data.get("Dependencies") or data.get("dependencies") or []:
        uid = str(d.get("UniqueID") or d.get("UniqueId") or "")
        if uid.lower() in release_ids and d.get("MinimumVersion") != version:
            d["MinimumVersion"] = version
            changed = True
    if not changed:
        return text
    key = "Dependencies" if "Dependencies" in data else "dependencies"
    data[key] = data.get(key)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"       # manifests are small; only formatting differs


def cptext_strip(text: str) -> str:
    from sdvlib import _strip_json_comments
    return re.sub(r",(\s*[}\]])", r"\1", _strip_json_comments(text.lstrip("﻿")))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mods", nargs="+")
    ap.add_argument("--version", required=True)
    ap.add_argument("--note", action="append", default=[])
    ap.add_argument("--out", default="releases")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-placeholders", action="store_true")
    ap.add_argument("--force-version", action="store_true", help="allow a version that is not higher than the current one")
    ap.add_argument("--update-key", action="append", default=[], help="e.g. Nexus:1234 (only real IDs the owner gave)")
    ap.add_argument("--project-name")
    a = ap.parse_args()
    if not SEMVER.match(a.version):
        die(f"--version '{a.version}' is not semantic (1.2.0)")
    pp = find_project()
    root = pp.parent if pp else Path.cwd()
    mods = [Path(m).resolve() if Path(m).is_absolute() else (root / m if (root / m).exists() else Path(m)).resolve() for m in a.mods]
    for m in mods:
        if not (m / "manifest.json").exists():
            die(f"{m} has no manifest.json")
    name = a.project_name or root.name
    out_dir = (Path(a.out) if Path(a.out).is_absolute() else root / a.out)

    # 1. validate (writes nothing)
    ids = {load_manifest(m / "manifest.json")["UniqueID"].lower() for m in mods}
    problems = []
    for m in mods:
        r = subprocess.run([sys.executable, str(HERE / "validate_mod.py"), str(m), "--json"], capture_output=True, text=True, cwd=root)
        try:
            res = json.loads(r.stdout)
        except ValueError:
            die(f"could not validate {m.name}: {r.stderr.strip()[:300]}")
        for x in res["results"]:
            if x["level"] == "ERROR":
                problems.append(f"{m.name}: {x['where']}: {x['message']}")
            elif "still a placeholder" in x["message"] and not a.allow_placeholders:
                problems.append(f"{m.name}: {x['where']}: {x['message']} (placeholder art; --allow-placeholders for a preview build)")
        cur = load_manifest(m / "manifest.json").get("Version", "0.0.0")
        if re.match(r"\d+\.\d+\.\d+", str(cur)) and vtuple(a.version) <= vtuple(str(cur)) and not a.force_version:
            problems.append(f"{m.name}: version {a.version} is not higher than the current {cur} (--force-version)")
    if problems:
        print("Release blocked:\n" + "\n".join(" - " + p for p in problems[:40]))
        raise SystemExit(1)

    # plan
    plan = []
    for m in mods:
        files = mod_files(m)
        plan.append((m, files))
    print(f"release {a.version} of {len(mods)} mod(s): " + ", ".join(m.name for m in mods))
    for m, files in plan:
        print(f"  {m.name}: {len(files)} file(s) -> {out_dir / (m.name + ' ' + a.version + '.zip')}")
    if a.dry_run:
        print("[dry-run] nothing written")
        return

    # 2. manifests
    for m in mods:
        mf = m / "manifest.json"
        text = mf.read_text(encoding="utf-8-sig")
        text = set_version(text, a.version)
        if a.update_key:
            text = set_update_keys(text, a.update_key)
        text = bump_dependencies(text, ids, a.version)
        mf.write_text(text, encoding="utf-8")

    # 3. changelog + project record
    proj = None
    new_ids, installed = [], []
    if pp:
        subprocess.run([sys.executable, str(HERE / "project.py"), "sync", "--root", str(root)], capture_output=True, text=True, cwd=root)
        proj = load_project(pp)
        last = proj.get("release") or {}
        seen = set(last.get("ids", []))
        new_ids = sorted(f"{v['kind']} {i}" for i, v in proj["ids"].items() if i not in seen)
        since = last.get("at", "")
        installed = sorted(r["id"] for r in proj["assets"] if r.get("status") == "installed" and (r.get("installed") or {}).get("at", "") > since)
    lines = [f"## {a.version} - {datetime.now().strftime('%Y-%m-%d')}", ""]
    lines += [f"- {n}" for n in a.note] or ["- (no notes given)"]
    if new_ids:
        lines += ["- New content: " + ", ".join(new_ids[:30]) + (" ..." if len(new_ids) > 30 else "")]
    if installed:
        lines += ["- Art updated: " + ", ".join(installed[:30]) + (" ..." if len(installed) > 30 else "")]
    section = "\n".join(lines) + "\n\n"
    cl = root / "CHANGELOG.md"
    old = cl.read_text(encoding="utf-8") if cl.exists() else "# Changelog\n\n"
    head, _, rest = old.partition("\n\n") if old.startswith("# ") else ("# Changelog", "", old)
    cl.write_text(head + "\n\n" + section + rest.lstrip("\n"), encoding="utf-8")
    if proj is not None:
        proj["release"] = {"version": a.version, "at": datetime.now().isoformat(timespec="seconds"), "ids": sorted(proj["ids"])}
        save_project(proj, pp)

    # 4. zips (C# mods are built first)
    out_dir.mkdir(parents=True, exist_ok=True)
    for m, _ in plan:
        if list(m.glob("*.csproj")):
            r = subprocess.run(["dotnet", "build", "-c", "Release", "-nologo", "-v", "q", "-p:EnableModDeploy=false", "-p:EnableModZip=false"], cwd=m, capture_output=True, text=True)
            if r.returncode != 0:
                die(f"dotnet build failed for {m.name}:\n" + (r.stdout + r.stderr)[-1200:])
    plan = [(m, mod_files(m)) for m in mods]
    allzip = out_dir / f"{name} {a.version} (all).zip"
    with zipfile.ZipFile(allzip, "w", zipfile.ZIP_DEFLATED) as za:
        for m, files in plan:
            z = out_dir / f"{m.name} {a.version}.zip"
            with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
                for src, arc in files:
                    zf.write(src, f"{m.name}/{arc}")
                    za.write(src, f"{m.name}/{arc}")
            print(f"wrote {z}")
    print(f"wrote {allzip}")

    # 5. draft description
    mans = [load_manifest(m / "manifest.json") for m in mods]
    deps = sorted({str(d.get("UniqueID")) for mn in mans for d in (mn.get("Dependencies") or []) if str(d.get("UniqueID", "")).lower() not in ids}
                  | {str((mn.get("ContentPackFor") or {}).get("UniqueID")) for mn in mans if mn.get("ContentPackFor")})
    desc = [f"# {name} {a.version}", ""] + [f"**{mn.get('Name')}**: {mn.get('Description', '')}" for mn in mans] + ["", "## Requirements", ""]
    desc += [f"- {d}" for d in deps if d and d != "None"] or ["- SMAPI 4.x"]
    desc += ["", "## What's new", "", section.strip(), "", "_Draft generated by release.py: edit before publishing. Nothing was uploaded._", ""]
    dpath = out_dir / f"{name} {a.version} - description.md"
    dpath.write_text("\n".join(desc), encoding="utf-8")
    print(f"wrote {dpath}\nNothing was uploaded or published. Changelog: {cl}")


if __name__ == "__main__":
    main()

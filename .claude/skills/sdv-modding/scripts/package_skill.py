#!/usr/bin/env python3
"""Package the skill for the claude.ai account (Settings > Skills) from this repo, and compare a zip with the repo.

  python package_skill.py                       # checks the skill, writes dist/sdv-modding-<version>.zip
  python package_skill.py --check dist/x.zip    # same version and same file contents as the repo?
  python package_skill.py --lint                # only the checks

The zip has the skill folder (sdv-modding/) at its root with SKILL.md directly inside. Left out: tests, caches, build output, run
folders, evals. PACKAGE_MANIFEST.json (version + a hash per file) is added so two copies can be compared later. The repo is the single
source of truth: change it here, bump VERSION, package, upload. Uploading is a manual step by the owner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {"tests", "__pycache__", ".pytest_cache", "bin", "obj", "out", "runs", "evals", "dist", ".git"}
EXCLUDE_FILES = {".sdv-game.json", "sdv-modding.config.json", "sdv-project.json"}
EXCLUDE_SUFFIX = (".pyc", ".pyo")


def version() -> str:
    return (SKILL / "VERSION").read_text(encoding="utf-8").strip()


def files() -> list[Path]:
    out = []
    for p in sorted(SKILL.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(SKILL)
        if set(rel.parts[:-1]) & EXCLUDE_DIRS or p.name in EXCLUDE_FILES or p.name.endswith(EXCLUDE_SUFFIX):
            continue
        out.append(p)
    return out


def lint() -> list[str]:
    bad = []
    sk = SKILL / "SKILL.md"
    text = sk.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return ["SKILL.md has no frontmatter"]
    fm = dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M))
    if fm.get("name") != "sdv-modding":
        bad.append("frontmatter name must be sdv-modding")
    if not fm.get("description") or len(fm["description"]) > 1024:
        bad.append(f"description missing or longer than 1024 characters ({len(fm.get('description', ''))})")
    if len(text.splitlines()) > 150:
        bad.append(f"SKILL.md is {len(text.splitlines())} lines (keep it under 150; detail belongs in references/)")
    refs = set(re.findall(r"`(references/[A-Za-z0-9_\-]+\.md)`", text)) | set(re.findall(r"`(assets/[A-Za-z0-9_.\-]+)`", text))
    refs |= {f"scripts/{n}" for n in re.findall(r"scripts/([A-Za-z0-9_]+\.py)", text)}
    for r in sorted(refs):
        if not (SKILL / r).exists():
            bad.append(f"SKILL.md mentions {r}, which does not exist")
    for ref in (SKILL / "references").glob("*.md"):
        mentioned = ref.name in text
        if not mentioned:
            bad.append(f"references/{ref.name} is not routed from SKILL.md")
    if not re.match(r"^\d+\.\d+\.\d+$", version()):
        bad.append("VERSION is not semantic")
    return bad


def manifest() -> dict:
    return {"name": "sdv-modding", "version": version(),
            "files": {p.relative_to(SKILL).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files()}}


def build(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    z = out_dir / f"sdv-modding-{version()}.zip"
    man = manifest()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files():
            zf.write(p, f"sdv-modding/{p.relative_to(SKILL).as_posix()}")
        zf.writestr("sdv-modding/PACKAGE_MANIFEST.json", json.dumps(man, indent=1))
    return z


def check(zpath: Path) -> int:
    with zipfile.ZipFile(zpath) as zf:
        theirs = json.loads(zf.read("sdv-modding/PACKAGE_MANIFEST.json"))
    mine = manifest()
    print(f"zip version {theirs['version']}, repo version {mine['version']}")
    diff = [f for f in sorted(set(theirs["files"]) | set(mine["files"])) if theirs["files"].get(f) != mine["files"].get(f)]
    for f in diff[:40]:
        state = "only in repo" if f not in theirs["files"] else "only in zip" if f not in mine["files"] else "differs"
        print(f"  {state}: {f}")
    print("identical" if not diff and theirs["version"] == mine["version"] else f"{len(diff)} file(s) differ")
    return 0 if not diff and theirs["version"] == mine["version"] else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check"); ap.add_argument("--lint", action="store_true"); ap.add_argument("--out", default=str(SKILL.parent.parent.parent / "dist"))
    a = ap.parse_args()
    if a.check:
        sys.exit(check(Path(a.check)))
    problems = lint()
    for p in problems:
        print("LINT:", p)
    if problems:
        raise SystemExit(1)
    if a.lint:
        print("lint ok")
        return
    z = build(Path(a.out))
    print(f"wrote {z} ({z.stat().st_size // 1024} KB, {len(files()) + 1} files). Upload it yourself in claude.ai Settings > Skills (replace the old copy); `package_skill.py --check` compares.")


if __name__ == "__main__":
    main()

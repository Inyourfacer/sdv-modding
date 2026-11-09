#!/usr/bin/env python3
"""Copy a content pack (CP / Portraiture / FS / AT) into the game's Mods folder and/or zip it for release.
C# mods deploy themselves on `dotnet build` (ModBuildConfig); use this only for their paired packs.

  python deploy.py "[CP] Mira"              # copy to <game>/Mods (replaces previous copy, keeps the user's config.json)
  python deploy.py "[CP] Mira" --zip        # also write "[CP] Mira 1.0.0.zip" next to the folder
  python deploy.py "[CP] Mira" --zip-only
"""
from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

from sdvlib import load_config, load_json, mods_path

SKIP = {"Thumbs.db", ".DS_Store"}
SKIP_SUFFIX = ("_preview.png",)


def files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.name not in SKIP and not p.name.endswith(SKIP_SUFFIX) and ".git" not in p.parts:
            yield p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mod")
    ap.add_argument("--zip", action="store_true")
    ap.add_argument("--zip-only", action="store_true")
    ap.add_argument("--mods", help="override Mods folder")
    ap.add_argument("--config")
    a = ap.parse_args()

    src = Path(a.mod).resolve()
    man = load_json(src / "manifest.json")
    if not a.zip_only:
        dest_root = Path(a.mods) if a.mods else mods_path(load_config(a.config))
        if not dest_root.exists():
            raise SystemExit(f"Mods folder not found: {dest_root} (set game_path/mods_path in sdv-modding.config.json)")
        dest = dest_root / src.name
        saved_cfg = (dest / "config.json").read_bytes() if (dest / "config.json").exists() else None
        if dest.exists():
            shutil.rmtree(dest)
        for f in files(src):
            t = dest / f.relative_to(src)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, t)
        if saved_cfg is not None:
            (dest / "config.json").write_bytes(saved_cfg)
        print(f"deployed -> {dest}")
    if a.zip or a.zip_only:
        z = src.parent / f"{src.name} {man.get('Version', '1.0.0')}.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files(src):
                if f.name == "config.json":
                    continue  # generated per-player
                zf.write(f, Path(src.name) / f.relative_to(src))
        print(f"zip -> {z}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Regenerate assets/gamedata_fields.json: the real field names of every game-data model, read from the installed game DLL.

  python gamedata_fields.py            # needs the .NET SDK and the game folder (config game_path); no game code is run

The JSON data files that mods patch (Data/Objects, Data/Crops, Data/Characters, ...) deserialize into these models, so a key that is
not listed here for its model is a typo or a field from another game version. generators (add.py) and the validator check against it.
The tool source is tools/apidump; it uses System.Reflection.MetadataLoadContext (a NuGet package; restore needs it cached or online).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from doctor import find_game
from sdvlib import load_config

SKILL = Path(__file__).resolve().parent.parent
OUT = SKILL / "assets" / "gamedata_fields.json"


def main():
    cfg = load_config()
    game = find_game(cfg)
    if not game or not (Path(game) / "StardewValley.GameData.dll").exists():
        raise SystemExit("Game folder not found; run doctor.py --write-config.")
    tool = SKILL / "tools" / "apidump"
    b = subprocess.run(["dotnet", "build", "-c", "Release", "-o", str(tool / "out"), "-nologo", "-v", "q"], cwd=tool, capture_output=True, text=True)
    if b.returncode != 0:
        raise SystemExit("building tools/apidump failed:\n" + (b.stdout + b.stderr)[-1500:])
    r = subprocess.run(["dotnet", str(tool / "out" / "apidump.dll"), game, "--gamedata"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr[-1500:])
    data = json.loads(r.stdout)
    ver = ""
    try:
        ver = json.loads((Path(game) / "Stardew Valley.deps.json").read_text(encoding="utf-8")).get("runtimeTarget", {}).get("name", "")
    except Exception:
        pass
    keep = {k: v for k, v in data.items() if not k.endswith("+<>c")}
    OUT.write_text(json.dumps({"_doc": "Public fields/properties of StardewValley.GameData.* models, from the installed game DLL (gamedata_fields.py).",
                               "_runtime": ver, "types": keep}, indent=1), encoding="utf-8")
    print(f"{len(keep)} types -> {OUT}")


if __name__ == "__main__":
    main()

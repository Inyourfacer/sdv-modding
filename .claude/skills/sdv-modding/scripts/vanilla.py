#!/usr/bin/env python3
"""Look things up in the game's own unpacked content instead of guessing ("verify against vanilla").

  python vanilla.py size Portraits/Abigail            # pixel size of a vanilla image asset
  python vanilla.py exists Maps/springobjects          # is there such an asset?
  python vanilla.py find portrait [--data]             # asset names containing text (and, with --data, data keys/values)
  python vanilla.py keys Data/Objects [--like jam]     # entry keys of a data asset
  python vanilla.py entry Data/Objects 245             # one entry as JSON
  python vanilla.py item 245                           # which Data/* asset defines item id 245 (objects, craftables, weapons, ...)

Reads `Content (unpacked)` made by StardewXnbHack (config `unpacked_content`, or <game>/Content (unpacked), or the --root option).
If it is missing the tool says how to get it; nothing is guessed. Images are read with Pillow, data with the JSON files XnbHack writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image

from doctor import find_game
from sdvlib import load_config, loads_tolerant

ITEM_DATA = {"(O)": "Data/Objects", "(BC)": "Data/BigCraftables", "(W)": "Data/Weapons", "(H)": "Data/hats", "(S)": "Data/Shirts",
             "(P)": "Data/Pants", "(B)": "Data/Boots", "(T)": "Data/Tools", "(F)": "Data/Furniture", "(TR)": "Data/Trinkets"}
HOW = ("Game content is not unpacked. With the owner's OK run StardewXnbHack (github.com/Pathoschild/StardewXnbHack/releases, put its exe in the "
       "game folder and run it in a terminal window), then set unpacked_content in sdv-modding.config.json (doctor.py --write-config finds "
       "<game>/Content (unpacked)).")


class Vanilla:
    def __init__(self, root: Path | str | None = None, cfg: dict | None = None):
        cfg = cfg or load_config()
        if root:                                  # an explicit root is used as given, never replaced by a fallback
            cands = [root]
        else:
            cands = [cfg.get("unpacked_content"), Path.home() / ".sdv-skill" / "Content (unpacked)"]
            game = find_game(cfg)
            if game:
                cands += [Path(game) / "Content (unpacked)", Path(game).parent / "Content (unpacked)"]
        self.root = next((Path(c) for c in cands if c and Path(c).is_dir()), None)

    @property
    def available(self) -> bool:
        return self.root is not None

    def _file(self, asset: str, exts=(".png", ".json")) -> Path | None:
        if not self.root:
            return None
        a = asset.replace("\\", "/").strip("/")
        for e in exts:
            p = self.root / (a + e)
            if p.exists():
                return p
        return None

    def exists(self, asset: str) -> bool | None:
        """True/False, or None when the content is not unpacked (unknown)."""
        if not self.root:
            return None
        return self._file(asset, (".png", ".json", ".tmx", ".tbin")) is not None

    @lru_cache(maxsize=512)
    def size(self, asset: str) -> tuple[int, int] | None:
        p = self._file(asset, (".png",))
        if not p:
            return None
        with Image.open(p) as im:
            return im.size

    @lru_cache(maxsize=64)
    def data(self, asset: str):
        p = self._file(asset, (".json",))
        return loads_tolerant(p.read_text(encoding="utf-8-sig")) if p else None

    def assets(self):
        if not self.root:
            return []
        return sorted(p.relative_to(self.root).with_suffix("").as_posix() for p in self.root.rglob("*") if p.suffix in (".png", ".json", ".tmx", ".tbin"))

    def has_item(self, qualified_or_bare: str) -> bool | None:
        """Does vanilla define this item ID? Bare/numeric ids are looked up in Objects."""
        if not self.root:
            return None
        t = qualified_or_bare.strip()
        q = next((k for k in ITEM_DATA if t.startswith(k)), None)
        key = t[len(q):] if q else t
        for prefix in ([q] if q else ["(O)"]):
            d = self.data(ITEM_DATA[prefix])
            if isinstance(d, dict) and key in d:
                return True
        return False if self.data("Data/Objects") is not None else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root"); ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("size", "exists"):
        sub.add_parser(n).add_argument("asset")
    f = sub.add_parser("find"); f.add_argument("text"); f.add_argument("--data", action="store_true")
    k = sub.add_parser("keys"); k.add_argument("asset"); k.add_argument("--like")
    e = sub.add_parser("entry"); e.add_argument("asset"); e.add_argument("key")
    sub.add_parser("item").add_argument("id")
    sub.add_parser("specs")
    a = ap.parse_args()
    v = Vanilla(a.root, load_config(a.config))
    if not v.available:
        raise SystemExit(HOW)

    if a.cmd == "size":
        s = v.size(a.asset)
        if not s:
            raise SystemExit(f"No image asset '{a.asset}' in {v.root}")
        print(f"{a.asset}: {s[0]}x{s[1]}")
    elif a.cmd == "exists":
        ok = v.exists(a.asset)
        print("yes" if ok else "no")
        sys.exit(0 if ok else 1)
    elif a.cmd == "find":
        t = a.text.lower()
        names = [n for n in v.assets() if t in n.lower()]
        print("\n".join(names[:200]) or "(no asset names match)")
        if a.data:
            for n in v.assets():
                if not n.startswith("Data/"):
                    continue
                d = v.data(n)
                if isinstance(d, dict):
                    hits = [k for k, val in d.items() if t in str(k).lower() or t in json.dumps(val).lower()[:400]]
                    for h in hits[:10]:
                        print(f"{n} :: {h}")
    elif a.cmd == "keys":
        d = v.data(a.asset)
        if not isinstance(d, dict):
            raise SystemExit(f"No data asset '{a.asset}' (is it a dictionary asset under Data/?)")
        ks = [k for k in d if not a.like or a.like.lower() in str(k).lower() or a.like.lower() in json.dumps(d[k]).lower()[:300]]
        print(f"{len(ks)} of {len(d)} keys")
        print("\n".join(map(str, ks[:300])))
    elif a.cmd == "entry":
        d = v.data(a.asset)
        if not isinstance(d, dict) or a.key not in d:
            raise SystemExit(f"No entry '{a.key}' in {a.asset}")
        print(json.dumps(d[a.key], indent=2, ensure_ascii=False))
    elif a.cmd == "specs":
        specs = json.loads((Path(__file__).resolve().parent.parent / "assets" / "asset_specs.json").read_text(encoding="utf-8"))
        bad = 0
        for key, sp in specs.items():
            ref = sp.get("vanilla_ref") if isinstance(sp, dict) else None
            if not ref:
                continue
            size = v.size(ref["asset"])
            ok = bool(size) and bool(eval(ref["rule"], {"__builtins__": {}}, {"w": size[0], "h": size[1]}))   # rules are our own, in asset_specs.json
            bad += not ok
            print(f"[{'ok' if ok else 'FAIL'}] {key:<16} {ref['asset']:<28} {size[0] if size else '?'}x{size[1] if size else '?'}  rule: {ref['rule']}")
        sys.exit(1 if bad else 0)
    elif a.cmd == "item":
        hits = [asset for asset in ITEM_DATA.values() if isinstance(v.data(asset), dict) and a.id.split(")")[-1] in v.data(asset)]
        print(", ".join(hits) if hits else "not found in any item data asset")
        sys.exit(0 if hits else 1)


if __name__ == "__main__":
    main()

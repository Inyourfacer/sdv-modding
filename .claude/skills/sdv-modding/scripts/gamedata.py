"""Check Content Patcher data entries against the real game data models (assets/gamedata_fields.json, from the installed game DLL).

  import gamedata
  gamedata.check_entry({"Name": "x", "Prize": 3}, "ObjectData")   # -> ['Prize']  (not a field of ObjectData)

Only keys are checked (typos, fields from another game version, wrong nesting), not values. Nested models are followed through
the field types (List<ShopItemData>, Dictionary<String, X>, ...). Data/* targets map to their model in TARGET_MODEL.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

FIELDS = Path(__file__).resolve().parent.parent / "assets" / "gamedata_fields.json"
NS = "StardewValley.GameData."

# Data/<asset> -> model of ONE entry (the dictionary's value type)
TARGET_MODEL = {
    "Data/Objects": "ObjectData", "Data/BigCraftables": "BigCraftableData", "Data/Crops": "CropData", "Data/FruitTrees": "FruitTreeData",
    "Data/Characters": "CharacterData", "Data/Shops": "ShopData", "Data/Machines": "MachineData", "Data/Locations": "LocationData",
    "Data/Buildings": "BuildingData", "Data/Weapons": "WeaponData", "Data/Shirts": "ShirtData", "Data/Pants": "PantsData", "Data/TriggerActions": "TriggerActionData",
}


@lru_cache(maxsize=1)
def types() -> dict:
    if not FIELDS.exists():
        return {}
    return json.loads(FIELDS.read_text(encoding="utf-8"))["types"]


@lru_cache(maxsize=1)
def _short() -> dict:
    out: dict[str, list[str]] = {}
    for full in types():
        out.setdefault(full.rsplit(".", 1)[-1].split("+")[-1], []).append(full)
    return out


def resolve(name: str) -> str | None:
    if name in types():
        return name
    hits = _short().get(name, [])
    return hits[0] if len(hits) == 1 else (hits[0] if hits else None)


def _inner(type_text: str) -> str | None:
    """'List<ShopItemData>' / 'Dictionary<String, X>' / 'X[]' / 'X' -> 'X' when X is a game-data model, else None."""
    t = type_text.strip()
    m = re.match(r"^(?:List|Dictionary|IList|IDictionary)<(?:[^,<>]+,\s*)?(.+)>$", t)
    if m:
        t = m.group(1).strip()
    t = t.removesuffix("[]")
    return t if resolve(t) else None


def check_entry(entry, model: str, path: str = "") -> list[str]:
    """Unknown keys (as dotted paths) in entry for the given model; [] when everything is a real field."""
    full = resolve(model)
    if not full or not isinstance(entry, dict):
        return []
    fields = types()[full]
    bad = []
    for k, v in entry.items():
        if k not in fields:
            bad.append(f"{path}{k}")
            continue
        inner = _inner(fields[k])
        if inner is None:
            continue
        if isinstance(v, dict):
            if fields[k].startswith(("Dictionary", "IDictionary")):
                for kk, vv in v.items():
                    bad += check_entry(vv, inner, f"{path}{k}.{kk}.")
            else:
                bad += check_entry(v, inner, f"{path}{k}.")
        elif isinstance(v, list):
            for i, vv in enumerate(v):
                bad += check_entry(vv, inner, f"{path}{k}[{i}].")
    return bad

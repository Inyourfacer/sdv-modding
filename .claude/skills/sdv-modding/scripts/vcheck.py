"""Deeper Content Patcher checks used by validate_mod.py (cross-references, not just syntax).

Everything here is something that would otherwise fail silently or only show up in game:
  - fields the game's data model does not have (typo, wrong nesting)       - duplicate keys inside one JSON object
  - Texture names nothing loads                                             - SpriteIndex outside the sheet
  - a new NPC missing its sprite / portrait / dialogue / gift tastes        - own IDs that are referenced but never defined
  - vanilla item IDs that do not exist                                      - dependencies missing / undeclared
  - FromFile paths that only break for some token values (season, config)  - portrait $N commands beyond the sheet; malformed schedules
Each check says what it could not verify (e.g. no unpacked game content) instead of guessing.
"""
from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

from PIL import Image

import gamedata
from project import TARGET_KIND, cp_changes
from sdvlib import load_json

SEASONS = ["spring", "summer", "fall", "winter"]
BUILTIN_TOKENS = {"season": SEASONS, "weather": ["Sun", "Rain", "Wind", "Storm", "Snow", "GreenRain"],
                  "dayofweek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}
# model of the texture sheet and its cell size (w, h); SpriteIndex counts cells left->right, top->bottom
DEFAULT_TEXTURE = {"Data/Objects": ("Maps/springobjects", (16, 16)), "Data/BigCraftables": ("TileSheets/Craftables", (16, 32)),
                   "Data/Crops": ("TileSheets/crops", (128, 32)), "Data/FruitTrees": ("TileSheets/fruitTrees", (432, 80))}
ROW_FIELD = {"Data/FruitTrees": "TextureSpriteRow"}          # these index rows of cells, not cells
QID = re.compile(r"\((?:O|BC|F|W|H|S|P|B|T|TR|WP|FL)\)[A-Za-z0-9_.\-]+")
SCHEDULE_PART = re.compile(r'^(?:a?\d{3,4}|\d{3,4}) \S+ \d+ \d+ [0-3](?: \S+)?(?: "[^"]*")?$|^(?:\d{3,4}|a\d{3,4}) bed$|^(?:GOTO|NOT|MAIL|BED)\b')


def sub_modid(s, uid: str) -> str:
    return re.sub(r"\{\{\s*ModId\s*\}\}", uid, s, flags=re.I) if isinstance(s, str) else s


def walk_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from walk_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk_strings(v)


def dup_keys(text_path: Path):
    """Names of duplicate keys inside any one JSON object (SMAPI's parser silently keeps the last)."""
    from sdvlib import _strip_json_comments
    import re as _re
    found = []

    def hook(pairs):
        seen = set()
        for k, _ in pairs:
            if k in seen:
                found.append(k)
            seen.add(k)
        return dict(pairs)

    try:
        t = _strip_json_comments(text_path.read_text(encoding="utf-8-sig"))
        json.loads(_re.sub(r",(\s*[}\]])", r"\1", t), object_pairs_hook=hook)
    except Exception:
        return []
    return found


class Deep:
    def __init__(self, root: Path, man: dict, rep, vanilla=None, mods_dirs=(), project=None):
        self.root, self.man, self.rep, self.v = root, man, rep, vanilla
        self.uid = man.get("UniqueID", "")
        self.mods_dirs = [Path(m) for m in mods_dirs]
        self.project = project
        self.changes = []                       # (file_rel, index, change)
        counters: dict = {}
        for f, ch in cp_changes(root):
            rel = f.relative_to(root).as_posix()
            counters[rel] = counters.get(rel, -1) + 1
            self.changes.append((rel, counters[rel], ch))
        self.loads: dict[str, list[str]] = {}   # asset name -> FromFile(s)
        for rel, i, ch in self.changes:
            if ch.get("Action") == "Load" and ch.get("Target"):
                for t in str(ch["Target"]).split(","):
                    self.loads.setdefault(sub_modid(t.strip(), self.uid).lower(), []).append(str(ch.get("FromFile", "")))
        self.defined = self._defined_ids()
        self.deps = {str(d.get("UniqueID", "")).lower() for d in (man.get("Dependencies") or [])}
        self.vanilla_noted = False

    def where(self, rel, i, ch):
        return f"{rel} #{i}" + (f" ({ch['LogName']})" if ch.get("LogName") else "")

    def _defined_ids(self) -> set[str]:
        out = set()
        for rel, i, ch in self.changes:
            if ch.get("Action") == "EditData" and isinstance(ch.get("Entries"), dict) and ch.get("TargetField") is None:
                tgt = str(ch.get("Target", ""))
                if tgt in TARGET_KIND or tgt.startswith("Data/Events/") or tgt in ("Data/CookingRecipes", "Data/CraftingRecipes", "Data/mail"):
                    for k in ch["Entries"]:
                        out.add(re.sub(r"^\([A-Z]+\)", "", sub_modid(k.split("/")[0], self.uid)))
            if ch.get("Action") == "EditData" and ch.get("TargetField"):
                for k, v in (ch.get("Entries") or {}).items():
                    out.add(sub_modid(k, self.uid))
                    if isinstance(v, dict) and v.get("Id"):
                        out.add(sub_modid(v["Id"], self.uid))
        return out

    def note_vanilla(self):
        if self.v is None or not self.v.available:
            if not self.vanilla_noted:
                self.rep.info("vanilla", "game content is not unpacked, so vanilla textures/items/locations were not checked (see doctor.py)")
                self.vanilla_noted = True
            return False
        return True

    # ---------------------------------------------------------------- checks
    def run(self):
        self.duplicate_keys()
        self.model_fields()
        self.textures_and_indexes()
        self.npcs()
        self.id_references()
        self.dependencies()
        self.token_paths()
        self.text_formats()
        self.maps()

    def duplicate_keys(self):
        seen = set()
        for rel, _, _ in self.changes:
            if rel not in seen:
                seen.add(rel)
                d = dup_keys(self.root / rel)
                if d:
                    self.rep.warn(rel, f"duplicate JSON key(s): {', '.join(sorted(set(d))[:8])} (the parser keeps only the last one)")
        for extra in [self.root / "content.json", self.root / "i18n" / "default.json"]:
            if extra.exists() and extra.relative_to(self.root).as_posix() not in seen:
                d = dup_keys(extra)
                if d:
                    self.rep.warn(extra.relative_to(self.root).as_posix(), f"duplicate JSON key(s): {', '.join(sorted(set(d))[:8])}")

    def model_fields(self):
        if not gamedata.types():
            return
        for rel, i, ch in self.changes:
            if ch.get("Action") != "EditData":
                continue
            tgt = str(ch.get("Target", ""))
            model = gamedata.TARGET_MODEL.get(tgt)
            if not model:
                continue
            w = self.where(rel, i, ch)
            tf = ch.get("TargetField")
            if tf is None and isinstance(ch.get("Entries"), dict):
                for k, v in ch["Entries"].items():
                    if isinstance(v, dict):
                        bad = gamedata.check_entry(v, model)
                        if bad:
                            self.rep.warn(w, f"{tgt} entry '{k}': not fields of {model}: {', '.join(bad[:6])} (the game ignores them)")
            elif tgt == "Data/Shops" and tf and tf[-1] == "Items" and isinstance(ch.get("Entries"), dict):
                for k, v in ch["Entries"].items():
                    bad = gamedata.check_entry(v, "ShopItemData") if isinstance(v, dict) else []
                    if bad:
                        self.rep.warn(w, f"shop item '{k}': not fields of ShopItemData: {', '.join(bad)}")
            if isinstance(ch.get("Fields"), dict):
                for k, fields in ch["Fields"].items():
                    bad = gamedata.check_entry(fields, model) if isinstance(fields, dict) else []
                    if bad:
                        self.rep.warn(w, f"{tgt} Fields for '{k}': not fields of {model}: {', '.join(bad)}")

    def sheet_size(self, texture: str):
        """(w, h) of a texture the pack loads (literal PNG) or vanilla, else None."""
        key = sub_modid(texture, self.uid).lower()
        for ff in self.loads.get(key, []):
            if ff and "{{" not in ff and (self.root / ff).exists() and ff.lower().endswith(".png"):
                try:
                    with Image.open(self.root / ff) as im:
                        return im.size
                except Exception:
                    return None
        if self.v is not None and self.v.available:
            return self.v.size(texture)
        return None

    def textures_and_indexes(self):
        for rel, i, ch in self.changes:
            tgt = str(ch.get("Target", ""))
            if ch.get("Action") != "EditData" or tgt not in DEFAULT_TEXTURE or not isinstance(ch.get("Entries"), dict) or ch.get("TargetField") is not None:
                continue
            default, cell = DEFAULT_TEXTURE[tgt]
            w = self.where(rel, i, ch)
            for k, e in ch["Entries"].items():
                if not isinstance(e, dict):
                    continue
                k = sub_modid(k, self.uid)
                tex = e.get("Texture") or default
                if "{{" in sub_modid(str(tex), self.uid):
                    continue
                full = sub_modid(str(tex), self.uid)
                own = full.lower() in self.loads
                dep = re.match(r"^Mods/([^/]+)/", full) and re.match(r"^Mods/([^/]+)/", full).group(1).lower() in self.deps
                if not own and not dep:
                    ok = self.v.exists(full) if self.note_vanilla() else None
                    if ok is False:
                        self.rep.warn(w, f"'{k}' uses Texture '{full}': this pack does not load it and it is not a vanilla asset")
                        continue
                size = self.sheet_size(full)
                idx_field = ROW_FIELD.get(tgt, "SpriteIndex")
                idx = e.get(idx_field, 0)
                if size and isinstance(idx, int):
                    cols, rows = max(1, size[0] // cell[0]), max(1, size[1] // cell[1])
                    count = rows if idx_field == "TextureSpriteRow" else cols * rows
                    if idx < 0 or idx >= count:
                        self.rep.err(w, f"'{k}' {idx_field} {idx} is outside the sheet '{full}' ({size[0]}x{size[1]} = {count} cell(s) of {cell[0]}x{cell[1]})")

    def npcs(self):
        for rel, i, ch in self.changes:
            if ch.get("Action") != "EditData" or ch.get("Target") != "Data/Characters" or ch.get("TargetField") is not None:
                continue
            for key in (ch.get("Entries") or {}):
                full = sub_modid(key, self.uid)
                w = self.where(rel, i, ch)
                missing = []
                for what, asset in (("sprite sheet", f"Characters/{full}"), ("portrait sheet", f"Portraits/{full}")):
                    if asset.lower() not in self.loads and not self._edits(asset):
                        missing.append(f"{what} ('{asset}' is never loaded)")
                if f"characters/dialogue/{full}".lower() not in self.loads and not self._edits(f"Characters/Dialogue/{full}"):
                    missing.append(f"dialogue ('Characters/Dialogue/{full}' is never loaded or edited)")
                if missing:
                    self.rep.err(w, f"NPC '{full}' is missing: " + "; ".join(missing))
                if not any(c.get("Target") == "Data/NPCGiftTastes" and any(sub_modid(k, self.uid) == full for k in (c.get("Entries") or {})) for _, _, c in self.changes):
                    self.rep.warn(w, f"NPC '{full}' has no Data/NPCGiftTastes entry (gifting falls back to universal tastes)")
                if f"characters/schedules/{full}".lower() not in self.loads and not self._edits(f"Characters/schedules/{full}"):
                    self.rep.info(w, f"NPC '{full}' has no schedule asset (they will stand at their home tile)")
                if self.note_vanilla() and isinstance(ch["Entries"][key], dict):
                    locs = self.v.data("Data/Locations") or {}
                    own_locs = {sub_modid(k, self.uid) for _, _, c in self.changes if c.get("Target") == "Data/Locations" for k in (c.get("Entries") or {})}
                    for h in ch["Entries"][key].get("Home") or []:
                        loc = h.get("Location") if isinstance(h, dict) else None
                        if loc and "{{" not in loc and loc not in locs and sub_modid(loc, self.uid) not in own_locs and not self.v.exists(f"Maps/{loc}"):
                            self.rep.warn(w, f"NPC '{full}' Home location '{loc}' is not a vanilla location or one this pack adds")

    def _edits(self, asset: str) -> bool:
        a = asset.lower()
        return any(sub_modid(str(c.get("Target", "")), self.uid).lower() == a for _, _, c in self.changes if c.get("Action") in ("EditData", "EditImage", "Load"))

    ITEM_KINDS = {"object", "big_craftable", "furniture", "weapon", "shirt", "pants", "hat"}
    ITEM_FIELDS = {"ItemId", "RequiredItemId", "HarvestItemId", "TradeItemId", "PreserveId", "RandomItemId", "ObjectInternalName"}

    def defined_items(self) -> set[str]:
        """Item ids this pack adds (objects, big craftables, furniture, weapons, hats, shirts, pants)."""
        out = set()
        for rel, i, ch in self.changes:
            tgt = str(ch.get("Target", ""))
            if ch.get("Action") == "EditData" and TARGET_KIND.get(tgt) in self.ITEM_KINDS and ch.get("TargetField") is None:
                for k in (ch.get("Entries") or {}):
                    out.add(re.sub(r"^\([A-Z]+\)", "", sub_modid(k, self.uid)))
        return out

    def item_refs(self, obj):
        """Strings that refer to an item: values of item fields, and any qualified id like (O)Me.Mod_Thing."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in self.ITEM_FIELDS and isinstance(v, str):
                    yield v
                else:
                    yield from self.item_refs(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from self.item_refs(v)
        elif isinstance(obj, str):
            for q in QID.findall(obj):
                yield q

    def id_references(self):
        pref = re.escape(self.uid)
        items = self.defined_items()
        own = re.compile(r"(?<![A-Za-z0-9_.])" + pref + r"_[A-Za-z0-9_]+")
        for rel, i, ch in self.changes:
            if ch.get("Action") != "EditData":
                continue
            tgt = str(ch.get("Target", ""))
            w = self.where(rel, i, ch)
            body = {k: v for k, v in ch.items() if k in ("Entries", "Fields", "TextOperations")}
            refs = [sub_modid(r, self.uid) for r in self.item_refs(body)]
            if tgt == "Data/Machines" and isinstance(ch.get("Entries"), dict):
                refs += [sub_modid(k, self.uid) for k in ch["Entries"]]
            if tgt in ("Data/CookingRecipes", "Data/CraftingRecipes", "Data/NPCGiftTastes") and isinstance(ch.get("Entries"), dict):
                for val in ch["Entries"].values():
                    if isinstance(val, str):
                        refs += [t for part in sub_modid(val, self.uid).split("/") for t in part.split()]
            for ref in refs:
                for m in own.finditer(ref):
                    if m.group(0) not in items:
                        self.rep.err(w, f"refers to item '{m.group(0)}', which this pack never defines")
            if self.note_vanilla() and tgt in ("Data/CookingRecipes", "Data/CraftingRecipes") and isinstance(ch.get("Entries"), dict):
                for k, val in ch["Entries"].items():
                    if isinstance(val, str):
                        for tok in val.split("/")[0].split()[::2]:
                            if re.fullmatch(r"\d+", tok) and self.v.has_item(tok) is False:
                                self.rep.warn(w, f"recipe '{k}' needs item id {tok}, which vanilla does not define")
            if self.note_vanilla():
                for r in {x for x in refs if QID.fullmatch(x)}:
                    body_id = re.sub(r"^\(\w+\)", "", r)
                    if re.fullmatch(r"\d+", body_id) and self.v.has_item(r) is False:
                        self.rep.warn(w, f"item '{r}' does not exist in vanilla")

    def _asset_name(self, name: str) -> bool:
        return any(name.lower() in t for t in self.loads)

    def dependencies(self):
        declared = self.deps | {str((self.man.get("ContentPackFor") or {}).get("UniqueID", "")).lower()}
        installed = None
        if self.mods_dirs:
            installed = set()
            for d in self.mods_dirs:
                if d.exists():
                    for mf in list(d.glob("*/manifest.json")) + list(d.glob("*/*/manifest.json")):
                        try:
                            from sdvlib import load_manifest
                            installed.add(str(load_manifest(mf).get("UniqueID", "")).lower())
                        except Exception:
                            pass
        for d in self.man.get("Dependencies") or []:
            uid = str(d.get("UniqueID", ""))
            if installed is not None and uid.lower() not in installed and d.get("IsRequired") is not False and uid.lower() != self.uid.lower():
                self.rep.warn("manifest.json", f"required dependency '{uid}' is not installed in the searched Mods folders")
        used = set()
        for rel, i, ch in self.changes:
            when = ch.get("When")
            for wk in (when.keys() if isinstance(when, dict) else []):
                m = re.match(r"^\s*([A-Za-z0-9_\-]+\.[A-Za-z0-9_.\-]+)/", str(wk))
                if m:
                    used.add(m.group(1))
            for s in walk_strings({k: v for k, v in ch.items() if k in ("Target", "Entries", "When", "FromFile", "Fields")}):
                for m in re.finditer(r"\{\{\s*([A-Za-z0-9_.\-]+\.[A-Za-z0-9_.\-]+)/", s):
                    used.add(m.group(1))
                for m in re.finditer(r"Mods/([A-Za-z0-9_.\-]+)/", s):
                    used.add(m.group(1))
        used = {u for u in used if u.lower() != self.uid.lower() and u.lower() not in ("{{modid}}",)}
        for u in sorted(used):
            if u.lower() not in declared:
                self.rep.warn("manifest.json", f"the patches use '{u}' (a token or asset of another mod) but it is not in Dependencies; load order is then not guaranteed")

    def token_paths(self):
        cfg = {}
        try:
            c = load_json(self.root / "content.json")
        except Exception:
            return
        for name, spec in (c.get("ConfigSchema") or {}).items():
            vals = [v.strip() for v in str(spec.get("AllowValues", "")).split(",") if v.strip()] if isinstance(spec, dict) else []
            if vals:
                cfg[name.lower()] = vals
        for dt in c.get("DynamicTokens") or []:
            if isinstance(dt, dict) and dt.get("Name") and "{{" not in str(dt.get("Value", "")):
                cfg.setdefault(dt["Name"].lower(), [])
                cfg[dt["Name"].lower()] += [v.strip() for v in str(dt["Value"]).split(",") if v.strip() and v.strip() not in cfg[dt["Name"].lower()]]
        known = {**BUILTIN_TOKENS, **cfg}
        for rel, i, ch in self.changes:
            ff = ch.get("FromFile")
            if not ff or "{{" not in str(ff):
                continue
            ff = sub_modid(str(ff), self.uid)
            names = [n.strip().lower() for n in re.findall(r"\{\{\s*([^{}|:]+?)\s*\}\}", ff)]
            if not names or any(n not in known for n in names):
                continue
            uniq = sorted(set(names))
            combos = list(itertools.product(*[known[n] for n in uniq]))
            if len(combos) > 200:
                continue
            bad = []
            for combo in combos:
                path = ff
                for n, val in zip(uniq, combo):
                    path = re.sub(r"\{\{\s*" + re.escape(n) + r"\s*\}\}", val, path, flags=re.I)
                if not (self.root / path).exists() and not (self.root / path.lower()).exists():
                    bad.append(path)
            if bad:
                self.rep.err(self.where(rel, i, ch), f"FromFile '{ch['FromFile']}' is missing for {len(bad)} of {len(combos)} token value(s): {', '.join(bad[:4])}{' ...' if len(bad) > 4 else ''}")

    def text_formats(self):
        for rel, i, ch in self.changes:
            if ch.get("Action") != "EditData" or not isinstance(ch.get("Entries"), dict):
                continue
            tgt = sub_modid(str(ch.get("Target", "")), self.uid)
            w = self.where(rel, i, ch)
            m = re.match(r"^Characters/Dialogue/(.+)$", tgt)
            if m and not tgt.lower().startswith("characters/dialogue/marriagedialogue"):
                rows = self._portrait_rows(m.group(1))
                for k, val in ch["Entries"].items():
                    for n in re.findall(r"\$(\d+)", str(val)):
                        if rows is not None and int(n) >= rows * 2:
                            self.rep.warn(w, f"dialogue '{k}' uses portrait ${n} but the portrait sheet only has {rows * 2} frames (0-{rows * 2 - 1})")
            m = re.match(r"^Characters/schedules/(.+)$", tgt)
            if m:
                for k, val in ch["Entries"].items():
                    if isinstance(val, str) and "{{" not in val:
                        for part in val.split("/"):
                            if part.strip() and not SCHEDULE_PART.match(part.strip()):
                                self.rep.warn(w, f"schedule '{k}' has an entry that does not look like 'time location x y facing [animation] [\"dialogue\"]': {part.strip()[:60]}")
            if tgt.startswith("Data/Events/"):
                for k, script in ch["Entries"].items():
                    if isinstance(script, str) and "{{" not in script:
                        cmds = [c.strip() for c in script.split("/") if c.strip()]
                        if not cmds or cmds[-1].split()[0] != "end":
                            self.rep.warn(w, f"event '{k.split('/')[0]}' does not finish with an 'end' command (the player would be stuck)")

    def known_locations(self) -> set[str]:
        known = set()
        if self.v is not None and self.v.available:
            known |= set((self.v.data("Data/Locations") or {}).keys())
            known |= {Path(x).name for x in self.v.assets() if x.startswith("Maps/") and "/" not in x[5:]}
        for rel, i, ch in self.changes:
            if ch.get("Target") == "Data/Locations":
                known |= {sub_modid(k, self.uid) for k in (ch.get("Entries") or {})}
        return known

    def maps(self):
        """Every .tmx the pack ships (tilesheets exist, ids in range, layers, warps) and every AddWarps string."""
        try:
            import tmx
        except Exception:
            return
        known = self.known_locations() if self.note_vanilla() else set()
        for rel, i, ch in self.changes:
            w = self.where(rel, i, ch)
            ff = ch.get("FromFile")
            if ff and str(ff).lower().endswith(".tmx") and "{{" not in str(ff):
                path = self.root / str(ff)
                if not path.exists():
                    continue                                        # reported by the FromFile check
                try:
                    tm = tmx.TMap.load(path)
                except SystemExit as ex:
                    self.rep.err(w, f"{ff}: {ex}")
                    continue
                patch = ch.get("Action") == "EditMap"               # a patch map is a fragment: it need not be a whole location
                for lvl, msg in tmx.check_map(tm, path, self.v, known):
                    if patch and ("missing layer" in msg or "Back layer is empty" in msg or "no Warp property" in msg):
                        continue
                    getattr(self.rep, {"ERROR": "err", "WARN": "warn"}.get(lvl, "info"))(w, f"{ff}: {msg}")
            if ch.get("Action") == "EditMap" and isinstance(ch.get("AddWarps"), list):
                for warp in ch["AddWarps"]:
                    toks = sub_modid(str(warp), self.uid).split()
                    if len(toks) % 5 or not toks:
                        self.rep.err(w, f"AddWarps entry '{warp}' is not made of 'x y Location tx ty' groups")
                        continue
                    for g in range(0, len(toks), 5):
                        loc = toks[g + 2]
                        if known and loc not in known and "{{" not in loc:
                            self.rep.warn(w, f"AddWarps goes to '{loc}', which is not a vanilla location or one this pack adds")

    def _portrait_rows(self, npc: str):
        for ff in self.loads.get(f"portraits/{npc}".lower(), []):
            if ff and "{{" not in ff and (self.root / ff).exists():
                try:
                    with Image.open(self.root / ff) as im:
                        return max(1, im.height // 64)
                except Exception:
                    return None
        return None

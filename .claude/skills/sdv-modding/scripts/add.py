#!/usr/bin/env python3
"""Add content to a Content Patcher mod in one command: patch file + i18n keys + placeholder art + Include + project registration.

  python add.py npc          --mod "[CP] My Mod" --name Mira --display "Mira" --home "Town 52 70 2" --birthday "fall 12" [--gender Female]
  python add.py item         --mod ... --name "Moonberry Jam" --price 220 [--category -26] [--edibility 30]
  python add.py big-craftable --mod ... --name "Jam Press"
  python add.py machine      --mod ... --craftable "Jam Press" --input "(O)613" --output "Moonberry Jam" --minutes 600
  python add.py crop         --mod ... --name Moonberry --seasons spring,summer --days 1,2,2,3 [--regrow 3] [--shop SeedShop --seed-price 40]
  python add.py fruit-tree   --mod ... --name Plum --season spring
  python add.py recipe       --mod ... --kind cooking --name "Moonberry Jam" --ingredients "613 3 245 1" --yield "Moonberry Jam"
  python add.py shop-item    --mod ... --shop SeedShop --item "Moonberry Seeds" --price 40 [--condition "SEASON spring"]
  python add.py shop         --mod ... --name "Island Store" --items "Moonberry Jam:300,(O)388:20"
  python add.py mail         --mod ... --name Welcome --text "Hello!" [--item "(O)72 1"] [--condition "PLAYER_HEARTS Current X 2"]
  python add.py event        --mod ... --name Intro --location Town --npc Mira
  python add.py location     --mod ... --name Cottage --door "60 70" [--target-map Town] [--like Trailer --size 12x9]
  python add.py portrait-set --out <dir> --name "My Portraits" --npcs Abigail,Leo --frame 256
  python add.py sid-sprite   --mod "[SID] My Sprites" --npc "Characters/Me.MyMod_Mira" --scale 8

Everything is additive and non-destructive: it writes data/<Kind>/<Name>.json, appends one Include to content.json and i18n keys
WITHOUT reformatting those files (comments, indentation and trailing-comma style are kept), makes placeholder PNGs of the exact
size (never overwriting real art), and refuses to reuse an ID that already exists (--force to override). Files it modifies are
copied to backups/<timestamp>/ first. --dry-run prints what would happen. Afterwards it re-syncs sdv-project.json and runs
validate_mod.py. Field names come from the game's own data models (assets/gamedata_fields.json), checked by the tests.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cptext
import gamedata
from project import collect_ids
from sdvlib import PROJECT_NAME, dump_json, find_project, load_manifest, load_project, save_project, slug

HERE = Path(__file__).resolve().parent
DIRECTIONS = ["up", "right", "down", "left"]


def die(msg: str):
    raise SystemExit("add.py: " + msg)


# ---------------------------------------------------------------- the target mod
class Mod:
    def __init__(self, folder: str | None, dry: bool, force: bool):
        pp = find_project()
        self.root = pp.parent if pp else None
        if folder is None:
            proj = load_project() or {}
            cps = [m["folder"] for m in proj.get("mods", []) if m.get("type") == "cp"]
            if len(cps) != 1:
                die("pass --mod <folder> (the project has " + (str(len(cps)) if cps else "no") + " Content Patcher mods)")
            folder = cps[0]
        p = Path(folder)
        if not p.is_absolute() and self.root and (self.root / p).exists():
            p = self.root / p
        self.dir = p.resolve()
        if not (self.dir / "manifest.json").exists():
            die(f"{self.dir} has no manifest.json")
        self.man = load_manifest(self.dir / "manifest.json")
        self.uid = self.man["UniqueID"]
        self.root = self.root or self.dir.parent
        self.dry, self.force = dry, force
        self.stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.actions: list[str] = []
        self.new_ids: dict[str, str] = {}
        self.existing = set(collect_ids(self.dir, self.uid, self.uid.split(".")[0])[0]) if (self.dir / "content.json").exists() else set()

    # -- naming
    def rid(self, name: str) -> str:
        """CP form of an ID for a human name: {{ModId}}_MoonberryJam."""
        return "{{ModId}}_" + slug(name)

    def full(self, rid: str) -> str:
        return rid.replace("{{ModId}}", self.uid)

    def claim(self, rid: str, kind: str):
        full = self.full(rid)
        if full in self.existing and not self.force:
            die(f"'{full}' already exists in this mod (use --force to add anyway, or pick another --name)")
        self.new_ids[full] = kind

    def item_ref(self, text: str, qualifier: str = "(O)") -> str:
        """'(O)613' / '613' / 'Moonberry Jam' -> a qualified item ID (our own items get the {{ModId}} prefix)."""
        t = text.strip()
        if t.startswith("("):
            return t
        if re.fullmatch(r"-?\d+", t):
            return qualifier + t
        if "{{ModId}}" in t:
            return qualifier + t
        return qualifier + self.rid(t)

    # -- file operations (all honour --dry-run)
    def rel(self, p: Path) -> str:
        return p.relative_to(self.dir).as_posix()

    def log(self, msg: str):
        self.actions.append(msg)
        print(("[dry-run] " if self.dry else "") + msg)

    def backup(self, p: Path):
        if self.dry or not p.exists():
            return
        inside = self.root in p.parents
        dst = self.root / "backups" / self.stamp / (p.relative_to(self.root) if inside else Path(p.name))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)

    def write_new(self, rel: str, text: str):
        p = self.dir / rel
        if p.exists() and not self.force:
            die(f"{rel} already exists (use --force to overwrite)")
        self.log(f"write {rel}")
        if not self.dry:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    def data_file(self, rel: str, changes: list[dict]):
        self.write_new(rel, json.dumps({"Changes": changes}, indent=2, ensure_ascii=False) + "\n")
        self.include(rel)

    def include(self, rel: str):
        c = self.dir / "content.json"
        text = c.read_text(encoding="utf-8")
        new = cptext.add_include(text, rel)
        if new != text:
            self.log(f"content.json: + Include {rel}")
            if not self.dry:
                self.backup(c)
                c.write_text(new, encoding="utf-8")

    def i18n(self, entries: dict[str, str]):
        p = self.dir / "i18n" / "default.json"
        text = p.read_text(encoding="utf-8") if p.exists() else "{}\n"
        have = cptext.mask(text)[0]
        add = {}
        for k, v in entries.items():
            if re.search(r'"%s"\s*:' % re.escape(k), have):
                continue
            add[k] = v
        if not add:
            return
        self.log(f"i18n/default.json: + {', '.join(add)}")
        if not self.dry:
            self.backup(p)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(cptext.insert_in_object(text, add), encoding="utf-8")

    def placeholder(self, spec: str, rel: str, label: str = "", frame: str | None = None, cols: int | None = None, rows: int | None = None):
        p = self.dir / rel
        if p.exists():
            return
        self.log(f"placeholder {rel} ({spec}{' ' + frame if frame else ''})")
        if self.dry:
            return
        cmd = [sys.executable, str(HERE / "make_placeholder.py"), "--spec", spec, "--out", str(p), "--label", label]
        if frame:
            cmd += ["--frame", frame]
        if cols:
            cmd += ["--cols", str(cols)]
        if rows:
            cmd += ["--rows", str(rows)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            die("placeholder failed: " + (r.stderr or r.stdout).strip())

    def check(self, target: str, entries: dict):
        model = gamedata.TARGET_MODEL.get(target)
        if not model or not gamedata.types():
            return
        for k, v in entries.items():
            bad = gamedata.check_entry(v, model)
            if bad:
                die(f"internal error: generated {target} entry '{k}' has fields the game does not know: {', '.join(bad)}")

    def finish(self, validate: bool = True):
        if self.dry:
            return
        r = subprocess.run([sys.executable, str(HERE / "project.py"), "sync", "--root", str(self.root)], capture_output=True, text=True, cwd=self.root)
        print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
        if validate:
            v = subprocess.run([sys.executable, str(HERE / "validate_mod.py"), str(self.dir)] + (["--root", self.content_root] if getattr(self, "content_root", None) else []),
                               capture_output=True, text=True)
            print(v.stdout.strip().splitlines()[-1] if v.stdout.strip() else "")
            if v.returncode != 0:
                print(v.stdout)
                raise SystemExit("validate_mod.py reports errors in what was just generated; look above.")


def key(name: str) -> str:
    """Lower-case i18n key stem."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def add_ids(mod: Mod, pairs: list[tuple[str, str]]):
    for rid, kind in pairs:
        mod.claim(rid, kind)


# ---------------------------------------------------------------- generators
def gen_item(mod: Mod, a, *, name=None, display=None, desc=None, category=None, otype="Basic", price=None, edibility=None, extra=None):
    name = name or a.name
    rid = mod.rid(name)
    mod.claim(rid, "object")
    k = key(name)
    entry = {"Name": rid, "DisplayName": f"{{{{i18n:{k}.name}}}}", "Description": f"{{{{i18n:{k}.description}}}}",
             "Type": otype, "Category": int(category if category is not None else a.category), "Price": int(price if price is not None else a.price),
             "Texture": f"Mods/{{{{ModId}}}}/Objects/{slug(name)}", "SpriteIndex": 0}
    ed = edibility if edibility is not None else getattr(a, "edibility", None)
    if ed is not None:
        entry["Edibility"] = int(ed)
    entry.update(extra or {})
    changes = [{"Action": "Load", "Target": f"Mods/{{{{ModId}}}}/Objects/{slug(name)}", "FromFile": f"assets/Objects/{slug(name)}.png"},
               {"Action": "EditData", "Target": "Data/Objects", "Entries": {rid: entry}}]
    mod.check("Data/Objects", {rid: entry})
    mod.i18n({f"{k}.name": display or getattr(a, "display", None) or name, f"{k}.description": desc or getattr(a, "description", None) or f"{name}."})
    mod.placeholder("object_icon", f"assets/Objects/{slug(name)}.png", name)
    return changes


def cmd_item(mod: Mod, a):
    mod.data_file(f"data/Items/{slug(a.name)}.json", gen_item(mod, a))


def cmd_big_craftable(mod: Mod, a):
    rid, k = mod.rid(a.name), key(a.name)
    mod.claim(rid, "big_craftable")
    entry = {"Name": rid, "DisplayName": f"{{{{i18n:{k}.name}}}}", "Description": f"{{{{i18n:{k}.description}}}}", "Price": int(a.price),
             "Fragility": 0, "CanBePlacedOutdoors": True, "CanBePlacedIndoors": True, "IsLamp": False,
             "Texture": f"Mods/{{{{ModId}}}}/BigCraftables/{slug(a.name)}", "SpriteIndex": 0}
    mod.check("Data/BigCraftables", {rid: entry})
    mod.i18n({f"{k}.name": a.display or a.name, f"{k}.description": a.description or f"{a.name}."})
    mod.placeholder("big_craftable", f"assets/BigCraftables/{slug(a.name)}.png", a.name)
    mod.data_file(f"data/Items/{slug(a.name)}.json", [
        {"Action": "Load", "Target": f"Mods/{{{{ModId}}}}/BigCraftables/{slug(a.name)}", "FromFile": f"assets/BigCraftables/{slug(a.name)}.png"},
        {"Action": "EditData", "Target": "Data/BigCraftables", "Entries": {rid: entry}}])


def cmd_machine(mod: Mod, a):
    cr = mod.item_ref(a.craftable, "(BC)")
    out = mod.item_ref(a.output)
    entry = {"OutputRules": [{"Id": "Default",
                              "Triggers": [{"Id": "ItemPlacedInMachine", "Trigger": "ItemPlacedInMachine",
                                            "RequiredItemId": mod.item_ref(a.input), "RequiredCount": int(a.count)}],
                              "OutputItem": [{"Id": "Out", "ItemId": out}],
                              "MinutesUntilReady": int(a.minutes)}]}
    mod.check("Data/Machines", {cr: entry})
    mod.data_file(f"data/Machines/{slug(a.craftable)}.json", [{"Action": "EditData", "Target": "Data/Machines", "Entries": {cr: entry}}])


def cmd_crop(mod: Mod, a):
    n, k = slug(a.name), key(a.name)
    seed_rid, prod_rid = mod.rid(a.name + " Seeds"), mod.rid(a.name)
    mod.claim(seed_rid, "object"); mod.claim(prod_rid, "object")
    seasons = [s.strip().capitalize() for s in a.seasons.split(",")]
    days = [int(d) for d in a.days.split(",")]
    crop = {"Seasons": seasons, "DaysInPhase": days, "RegrowDays": int(a.regrow), "HarvestItemId": f"(O){prod_rid}",
            "HarvestMinStack": 1, "HarvestMaxStack": 1, "Texture": f"Mods/{{{{ModId}}}}/Crops/{n}", "SpriteIndex": 0}
    mod.check("Data/Crops", {seed_rid: crop})
    seed = {"Name": seed_rid, "DisplayName": f"{{{{i18n:{k}-seeds.name}}}}", "Description": f"{{{{i18n:{k}-seeds.description}}}}", "Type": "Seeds", "Category": -74,
            "Price": int(a.seed_price), "Texture": f"Mods/{{{{ModId}}}}/Objects/{n}Seeds", "SpriteIndex": 0}
    prod = {"Name": prod_rid, "DisplayName": f"{{{{i18n:{k}.name}}}}", "Description": f"{{{{i18n:{k}.description}}}}", "Type": "Basic", "Category": int(a.produce_category),
            "Price": int(a.price), "Edibility": int(a.edibility), "Texture": f"Mods/{{{{ModId}}}}/Objects/{n}", "SpriteIndex": 0}
    mod.check("Data/Objects", {seed_rid: seed, prod_rid: prod})
    changes = [
        {"Action": "Load", "Target": f"Mods/{{{{ModId}}}}/Crops/{n}", "FromFile": f"assets/Crops/{n}.png"},
        {"Action": "Load", "Target": f"Mods/{{{{ModId}}}}/Objects/{n}Seeds", "FromFile": f"assets/Objects/{n}Seeds.png"},
        {"Action": "Load", "Target": f"Mods/{{{{ModId}}}}/Objects/{n}", "FromFile": f"assets/Objects/{n}.png"},
        {"Action": "EditData", "Target": "Data/Objects", "Entries": {seed_rid: seed, prod_rid: prod}},
        {"Action": "EditData", "Target": "Data/Crops", "Entries": {seed_rid: crop}}]
    if a.shop:
        changes.append(shop_item_change(a.shop, mod.rid(a.name + " Seeds"), f"(O){seed_rid}", int(a.seed_price), None, a.shop_condition))
    mod.i18n({f"{k}-seeds.name": f"{a.name} Seeds", f"{k}-seeds.description": f"Plant these to grow {a.name}.", f"{k}.name": a.name, f"{k}.description": f"{a.name}."})
    mod.placeholder("crop", f"assets/Crops/{n}.png", a.name)
    mod.placeholder("object_icon", f"assets/Objects/{n}Seeds.png", "Seeds")
    mod.placeholder("object_icon", f"assets/Objects/{n}.png", a.name)
    mod.data_file(f"data/Crops/{n}.json", changes)


def cmd_fruit_tree(mod: Mod, a):
    n, k = slug(a.name), key(a.name)
    sap_rid, fruit_rid = mod.rid(a.name + " Sapling"), mod.rid(a.name)
    mod.claim(sap_rid, "object"); mod.claim(fruit_rid, "object")
    tree = {"DisplayName": f"{{{{i18n:{k}-tree.name}}}}", "Seasons": [a.season.capitalize()],
            "Fruit": [{"Id": "Fruit", "ItemId": f"(O){fruit_rid}"}], "Texture": f"Mods/{{{{ModId}}}}/FruitTrees/{n}", "TextureSpriteRow": 0}
    mod.check("Data/FruitTrees", {sap_rid: tree})
    sap = {"Name": sap_rid, "DisplayName": f"{{{{i18n:{k}-sapling.name}}}}", "Description": f"{{{{i18n:{k}-sapling.description}}}}", "Type": "Basic", "Category": -74,
           "Price": int(a.sapling_price), "Texture": f"Mods/{{{{ModId}}}}/Objects/{n}Sapling", "SpriteIndex": 0}
    fruit = {"Name": fruit_rid, "DisplayName": f"{{{{i18n:{k}.name}}}}", "Description": f"{{{{i18n:{k}.description}}}}", "Type": "Basic", "Category": -79,
             "Price": int(a.price), "Edibility": int(a.edibility), "Texture": f"Mods/{{{{ModId}}}}/Objects/{n}", "SpriteIndex": 0}
    mod.check("Data/Objects", {sap_rid: sap, fruit_rid: fruit})
    mod.i18n({f"{k}-tree.name": f"{a.name} Tree", f"{k}-sapling.name": f"{a.name} Sapling", f"{k}-sapling.description": f"Grows into a {a.name} tree.",
              f"{k}.name": a.name, f"{k}.description": f"{a.name}."})
    mod.placeholder("fruit_tree", f"assets/FruitTrees/{n}.png", a.name)
    mod.placeholder("object_icon", f"assets/Objects/{n}Sapling.png", "Sapling")
    mod.placeholder("object_icon", f"assets/Objects/{n}.png", a.name)
    mod.data_file(f"data/Crops/{n}Tree.json", [
        {"Action": "Load", "Target": f"Mods/{{{{ModId}}}}/FruitTrees/{n}", "FromFile": f"assets/FruitTrees/{n}.png"},
        {"Action": "Load", "Target": f"Mods/{{{{ModId}}}}/Objects/{n}Sapling", "FromFile": f"assets/Objects/{n}Sapling.png"},
        {"Action": "Load", "Target": f"Mods/{{{{ModId}}}}/Objects/{n}", "FromFile": f"assets/Objects/{n}.png"},
        {"Action": "EditData", "Target": "Data/Objects", "Entries": {sap_rid: sap, fruit_rid: fruit}},
        {"Action": "EditData", "Target": "Data/FruitTrees", "Entries": {sap_rid: tree}}])


def cmd_recipe(mod: Mod, a):
    rid, k = mod.rid(a.name), key(a.name)
    mod.claim(rid, "recipe")
    out = re.sub(r"^\(\w+\)", "", mod.item_ref(a.yield_item))
    if a.kind == "cooking":
        s = f"{a.ingredients}/10 10/{out}{' ' + str(a.yield_count) if int(a.yield_count) > 1 else ''}/{a.unlock}/{{{{i18n:{k}.name}}}}"
        target = "Data/CookingRecipes"
    else:
        s = f"{a.ingredients}/Home/{out}{' ' + str(a.yield_count) if int(a.yield_count) > 1 else ''}/{'true' if a.big_craftable else 'false'}/{a.unlock}/{{{{i18n:{k}.name}}}}"
        target = "Data/CraftingRecipes"
    mod.i18n({f"{k}.name": a.display or a.name})
    mod.data_file(f"data/Recipes/{slug(a.name)}.json", [{"Action": "EditData", "Target": target, "Entries": {rid: s}}])


def shop_item_change(shop: str, rid: str, item_id: str, price: int | None, condition: str | None, shop_condition=None) -> dict:
    e = {"Id": rid, "ItemId": item_id}
    if price is not None:
        e["Price"] = price
    if condition or shop_condition:
        e["Condition"] = condition or shop_condition
    return {"Action": "EditData", "Target": "Data/Shops", "TargetField": [shop, "Items"], "Entries": {rid: e}}


def cmd_shop_item(mod: Mod, a):
    item = mod.item_ref(a.item)
    rid = mod.rid(f"{a.shop} {re.sub(r'[^A-Za-z0-9]', '', item)}")
    mod.claim(rid, "shop_item")
    ch = shop_item_change(a.shop, rid, item, int(a.price) if a.price is not None else None, a.condition)
    mod.check("Data/Shops", {"x": {"Items": list(ch["Entries"].values())}})
    mod.data_file(f"data/Shops/{slug(a.shop)}_{slug(re.sub(r'[^A-Za-z0-9]', '', item))}.json", [ch])


def cmd_shop(mod: Mod, a):
    rid = mod.rid(a.name)
    mod.claim(rid, "shop")
    items = []
    for part in a.items.split(","):
        ref, _, price = part.partition(":")
        item = mod.item_ref(ref)
        e = {"Id": re.sub(r"[^A-Za-z0-9]", "", item), "ItemId": item}
        if price.strip():
            e["Price"] = int(price)
        items.append(e)
    shop = {"Owners": [{"Name": "AnyOrNone", "Id": "Default"}], "Items": items}
    mod.check("Data/Shops", {rid: shop})
    mod.data_file(f"data/Shops/{slug(a.name)}.json", [{"Action": "EditData", "Target": "Data/Shops", "Entries": {rid: shop}}])
    print(f"open it from a map tile property: Action OpenShop {mod.full(rid)}")


def cmd_mail(mod: Mod, a):
    rid, k = mod.rid(a.name), key(a.name)
    mod.claim(rid, "mail")
    text = f"{{{{i18n:{k}.text}}}}" + (f"%item object {a.item} %%" if a.item else "") + f"[#]{{{{i18n:{k}.title}}}}"
    trig = {"Id": rid, "Trigger": "DayStarted", "Actions": [f"AddMail Current {mod.full(rid)} now"]}
    if a.condition:
        trig["Condition"] = a.condition
    mod.check("Data/TriggerActions", {rid: trig})
    mod.i18n({f"{k}.text": a.text, f"{k}.title": a.title or a.name})
    mod.data_file(f"data/Mail/{slug(a.name)}.json", [
        {"Action": "EditData", "Target": "Data/mail", "Entries": {rid: text}},
        {"Action": "EditData", "Target": "Data/TriggerActions", "Entries": {rid: trig}}])


def cmd_event(mod: Mod, a):
    rid, k = mod.rid(a.name), key(a.name)
    mod.claim(rid, "event")
    npc = mod.rid(a.npc) if a.npc and "{{" not in a.npc and not a.npc[0].isdigit() and "_" not in a.npc else (a.npc or "")
    pre = a.pre or (f"f {npc} 250" if npc else "t 600 2600")
    script = (f"continue/64 15/farmer 64 16 2" + (f" {npc} 64 18 0" if npc else "") + "/skippable/pause 500/"
              + (f"speak {npc} \"{{{{i18n:{k}.line1}}}}\"/" if npc else "") + "pause 500/end")
    mod.i18n({f"{k}.line1": a.line or "Hello there."})
    mod.data_file(f"data/Events/{slug(a.name)}.json", [{"Action": "EditData", "Target": f"Data/Events/{a.location}", "Entries": {f"{rid}/{pre}": script}}])
    print("event script is a skeleton: edit it, then test with `debug ebi " + mod.full(rid) + "` in the SMAPI console or a harness 'debug' step.")


def cmd_npc(mod: Mod, a):
    n, k = slug(a.name), key(a.name)
    rid = mod.rid(a.name)
    mod.claim(rid, "npc")
    loc, x, y, *rest = a.home.split()
    facing = DIRECTIONS[int(rest[0])] if rest else "down"
    season, day = a.birthday.split()
    ch = {"DisplayName": f"{{{{i18n:{k}.name}}}}", "BirthSeason": season.capitalize(), "BirthDay": int(day), "HomeRegion": a.region,
          "Gender": a.gender, "Age": a.age, "Manner": a.manner, "SocialAnxiety": a.anxiety, "Optimism": a.optimism,
          "CanBeRomanced": False, "Home": [{"Id": "Default", "Location": loc, "Tile": {"X": int(x), "Y": int(y)}, "Direction": facing}]}
    mod.check("Data/Characters", {rid: ch})
    weekdays = {d: f"{{{{i18n:{k}.dialogue.default}}}}" for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")}
    dialogue = {"Introduction": f"{{{{i18n:{k}.introduction}}}}", **weekdays}
    taste = "/".join([f"{{{{i18n:{k}.gift.love}}}}", a.loves, f"{{{{i18n:{k}.gift.like}}}}", a.likes, f"{{{{i18n:{k}.gift.dislike}}}}", a.dislikes,
                      f"{{{{i18n:{k}.gift.hate}}}}", a.hates, f"{{{{i18n:{k}.gift.neutral}}}}", a.neutral]) + "/"
    mod.i18n({f"{k}.name": a.display or a.name, f"{k}.introduction": f"Hi, I'm {a.display or a.name}.", f"{k}.dialogue.default": "...",
              f"{k}.gift.love": "I love this!", f"{k}.gift.like": "Thanks, I like it.", f"{k}.gift.dislike": "Not really my thing.",
              f"{k}.gift.hate": "Ugh, no thanks.", f"{k}.gift.neutral": "Thanks."})
    if not (mod.dir / "assets" / "Empty.json").exists():
        mod.write_new("assets/Empty.json", "{}\n")
    mod.placeholder("character_sprite", f"assets/Characters/{n}.png", a.name)
    mod.placeholder("portrait", f"assets/Portraits/{n}.png", a.name)
    mod.data_file(f"data/Characters/{n}.json", [
        {"Action": "Load", "Target": f"Characters/{rid}", "FromFile": f"assets/Characters/{n}.png"},
        {"Action": "Load", "Target": f"Portraits/{rid}", "FromFile": f"assets/Portraits/{n}.png"},
        {"Action": "Load", "Target": f"Characters/Dialogue/{rid}", "FromFile": "assets/Empty.json"},
        {"Action": "EditData", "Target": f"Characters/Dialogue/{rid}", "Entries": dialogue},
        {"Action": "Load", "Target": f"Characters/schedules/{rid}", "FromFile": "assets/Empty.json"},
        {"Action": "EditData", "Target": f"Characters/schedules/{rid}", "Entries": {"default": f"900 {loc} {x} {y} {DIRECTIONS.index(facing)}"}},
        {"Action": "EditData", "Target": "Data/Characters", "Entries": {rid: ch}},
        {"Action": "EditData", "Target": "Data/NPCGiftTastes", "Entries": {rid: taste}}])
    # art-pipeline bookkeeping: a character entry and its two assets
    pp = find_project()
    if pp and not mod.dry:
        proj = load_project(pp)
        proj["characters"].setdefault(mod.full(rid), {"display_name": a.display or a.name, "subject": a.subject or "", "seed": random.randint(1, 2_000_000_000),
                                                      "outfits": {}, "loras": [], "reference_image": None})
        save_project(proj, pp)


def cmd_location(mod: Mod, a):
    """A new indoor location: starter .tmx (from another map's tilesheets), Data/Locations, a warp from the target map and one back."""
    import tmx
    from vanilla import Vanilla
    v = Vanilla(a.root)
    mod.content_root = a.root                   # validate against the same game content the map was built from
    if not v.available:
        die("the game content is not unpacked, so there are no vanilla tilesheets to build the map from (see references/validation.md)")
    n, rid, k = slug(a.name), mod.rid(a.name), key(a.name)
    mod.claim(rid, "location")
    w, h = [int(x) for x in re.split(r"[xX,]", a.size)]
    dx, dy = [int(x) for x in re.split(r"[ ,]", a.door.strip())]
    ax, ay = [int(x) for x in re.split(r"[ ,]", a.arrive.strip())] if a.arrive else (w // 2, h - 2)
    back_loc, bx, by = (a.back.split() + [None, None])[:3] if a.back else (a.target_map, str(dx), str(dy + 1))
    tm = tmx.new_like((w, h), a.like, v)
    tm.props["Warp"] = f"{ax} {h} {back_loc} {bx} {by}"                   # the exit sits one tile below the last row
    rel = f"assets/Maps/{n}.tmx"
    mod.log(f"write {rel} ({w}x{h}, tilesheets of {a.like})")
    if not mod.dry:
        p = mod.dir / rel
        if p.exists() and not mod.force:
            die(f"{rel} already exists (use --force)")
        tm.save(p)
    entry = {"DisplayName": f"{{{{i18n:{k}.name}}}}", "DefaultArrivalTile": {"X": ax, "Y": ay},
             "CreateOnLoad": {"MapPath": f"Maps/{rid}", "AlwaysActive": False}}
    mod.check("Data/Locations", {rid: entry})
    mod.i18n({f"{k}.name": a.display or a.name})
    mod.data_file(f"data/Locations/{n}.json", [
        {"Action": "Load", "Target": f"Maps/{rid}", "FromFile": rel},
        {"Action": "EditData", "Target": "Data/Locations", "Entries": {rid: entry}},
        {"Action": "EditMap", "Target": f"Maps/{a.target_map}", "AddWarps": [f"{dx} {dy} {rid} {ax} {ay}"]}])
    if not mod.dry:
        r = subprocess.run([sys.executable, str(HERE / "tmx.py"), "check", str(mod.dir / rel), "--mod", str(mod.dir)] + (["--root", a.root] if a.root else []),
                           capture_output=True, text=True)
        print("tmx check: " + (r.stdout.strip().splitlines() or ["?"])[-1])
        if r.returncode != 0:
            print(r.stdout)
    print(f"open it from {a.target_map} at tile {dx},{dy}; the map has no walls, furniture or Action tiles yet: edit it in Tiled, or patch with EditMap MapTiles. Preview: python tmx.py render \"{mod.dir / rel}\" --out preview.png")


def cmd_portrait_set(a):
    out = Path(a.out) / f"[Portraiture] {a.name}"
    if out.exists() and not a.force:
        die(f"{out} exists")
    cfg_author = a.author or "Author"
    uid = f"{slug(cfg_author)}.{slug(a.name)}"
    if a.dry_run:
        print(f"[dry-run] would create {out} with {a.npcs}")
        return
    r = subprocess.run([sys.executable, str(HERE / "new_mod.py"), "--type", "portraiture", "--name", a.name, "--author", cfg_author, "--out", str(a.out), "--uid", uid],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die(r.stderr.strip() or r.stdout.strip())
    for npc in [x.strip() for x in a.npcs.split(",") if x.strip()]:
        subprocess.run([sys.executable, str(HERE / "make_placeholder.py"), "--spec", "portrait_hd", "--frame", str(a.frame), "--out", str(out / f"{npc}.png"), "--label", npc],
                       check=True, capture_output=True)
        print(f"placeholder {npc}.png ({a.frame * 2}x{a.frame * 3})")
    print(f"created {out}")


def cmd_sid_sprite(mod: Mod, a):
    if (mod.man.get("ContentPackFor") or {}).get("UniqueID", "").lower() != "bleakcodex.spritesindetail":
        die("--mod must be a Sprites in Detail pack (new_mod.py --type sid)")
    name = re.split(r"[_.]", a.npc.split("/")[-1])[-1] or "Sprite"          # Characters/Me.MyMod_Mira -> Mira
    sheet = f"assets/{slug(name)}_hd.png"
    mod.placeholder("character_sprite", sheet, name, frame=f"{16 * a.scale}x{32 * a.scale}")
    entry = {"Target": a.npc, "FromFile": sheet, "SpriteWidth": 16, "SpriteHeight": 32, "WidthScale": a.scale, "HeightScale": a.scale,
             "SpriteOriginX": 8 * a.scale, "SpriteOriginY": 24 * a.scale + 1, "BreathType": "None"}
    c = mod.dir / "content.json"
    text = c.read_text(encoding="utf-8")
    if json.dumps(a.npc) in text and not mod.force:
        die(f"{a.npc} already has a Sprites entry")
    mod.log(f"content.json: + Sprites entry for {a.npc}")
    if not mod.dry:
        mod.backup(c)
        c.write_text(cptext.insert_in_array(text, "Sprites", entry), encoding="utf-8")


# ---------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, mod=True):
        if mod:
            p.add_argument("--mod", help="Content Patcher mod folder (default: the project's only CP mod)")
        p.add_argument("--dry-run", action="store_true"); p.add_argument("--force", action="store_true")
        p.add_argument("--no-validate", action="store_true")

    p = sub.add_parser("npc"); common(p); p.add_argument("--name", required=True); p.add_argument("--display")
    p.add_argument("--home", default="Town 52 70 2", help="Location x y [facing 0-3]"); p.add_argument("--birthday", default="Spring 1")
    p.add_argument("--gender", default="Female", choices=["Female", "Male", "Undefined"]); p.add_argument("--age", default="Adult", choices=["Adult", "Teen", "Child"])
    p.add_argument("--manner", default="Neutral"); p.add_argument("--anxiety", default="Neutral"); p.add_argument("--optimism", default="Neutral")
    p.add_argument("--region", default="Town"); p.add_argument("--subject", help="art tags stored on the character for the art pipeline")
    p.add_argument("--loves", default="(O)72"); p.add_argument("--likes", default="(O)395"); p.add_argument("--dislikes", default="(O)330")
    p.add_argument("--hates", default="(O)168"); p.add_argument("--neutral", default="")
    p = sub.add_parser("item"); common(p); p.add_argument("--name", required=True); p.add_argument("--display"); p.add_argument("--description")
    p.add_argument("--price", type=int, default=100); p.add_argument("--category", type=int, default=0); p.add_argument("--edibility", type=int, default=-300)
    p = sub.add_parser("big-craftable"); common(p); p.add_argument("--name", required=True); p.add_argument("--display"); p.add_argument("--description"); p.add_argument("--price", type=int, default=0)
    p = sub.add_parser("machine"); common(p); p.add_argument("--craftable", required=True); p.add_argument("--input", required=True); p.add_argument("--output", required=True)
    p.add_argument("--minutes", type=int, default=600); p.add_argument("--count", type=int, default=1)
    p = sub.add_parser("crop"); common(p); p.add_argument("--name", required=True); p.add_argument("--seasons", default="spring"); p.add_argument("--days", default="1,2,2,3")
    p.add_argument("--regrow", type=int, default=-1); p.add_argument("--price", type=int, default=100); p.add_argument("--seed-price", type=int, default=40)
    p.add_argument("--produce-category", type=int, default=-75); p.add_argument("--edibility", type=int, default=20)
    p.add_argument("--shop"); p.add_argument("--shop-condition")
    p = sub.add_parser("fruit-tree"); common(p); p.add_argument("--name", required=True); p.add_argument("--season", default="spring")
    p.add_argument("--price", type=int, default=80); p.add_argument("--sapling-price", type=int, default=1000); p.add_argument("--edibility", type=int, default=20)
    p = sub.add_parser("recipe"); common(p); p.add_argument("--name", required=True); p.add_argument("--display"); p.add_argument("--kind", choices=["cooking", "crafting"], default="cooking")
    p.add_argument("--ingredients", required=True, help='"613 3 245 1" = item id, count pairs'); p.add_argument("--yield", dest="yield_item", required=True)
    p.add_argument("--yield-count", type=int, default=1); p.add_argument("--unlock", default="default"); p.add_argument("--big-craftable", action="store_true")
    p = sub.add_parser("shop-item"); common(p); p.add_argument("--shop", required=True); p.add_argument("--item", required=True); p.add_argument("--price", type=int); p.add_argument("--condition")
    p = sub.add_parser("shop"); common(p); p.add_argument("--name", required=True); p.add_argument("--items", required=True, help='"Name or (O)id:price,..."')
    p = sub.add_parser("mail"); common(p); p.add_argument("--name", required=True); p.add_argument("--text", required=True); p.add_argument("--title"); p.add_argument("--item"); p.add_argument("--condition")
    p = sub.add_parser("event"); common(p); p.add_argument("--name", required=True); p.add_argument("--location", required=True); p.add_argument("--npc"); p.add_argument("--pre"); p.add_argument("--line")
    p = sub.add_parser("location"); common(p); p.add_argument("--name", required=True); p.add_argument("--display"); p.add_argument("--door", required=True, help='tile on the target map, "x y"')
    p.add_argument("--target-map", default="Town"); p.add_argument("--like", default="Trailer", help="vanilla map whose tilesheets and floor the new map starts from")
    p.add_argument("--size", default="12x9"); p.add_argument("--arrive", help='arrival tile inside the new map, "x y" (default: bottom centre)')
    p.add_argument("--back", help='where the exit leads, "Location x y" (default: just below the door)'); p.add_argument("--root", help="unpacked game content")
    p = sub.add_parser("portrait-set"); common(p, mod=False); p.add_argument("--out", required=True); p.add_argument("--name", required=True); p.add_argument("--npcs", required=True)
    p.add_argument("--frame", type=int, default=256); p.add_argument("--author")
    p = sub.add_parser("sid-sprite"); common(p); p.add_argument("--npc", required=True); p.add_argument("--scale", type=int, default=8)
    a = ap.parse_args()

    if a.cmd == "portrait-set":
        return cmd_portrait_set(a)
    mod = Mod(a.mod, a.dry_run, a.force)
    fn = {"npc": cmd_npc, "item": cmd_item, "big-craftable": cmd_big_craftable, "machine": cmd_machine, "crop": cmd_crop, "fruit-tree": cmd_fruit_tree,
          "recipe": cmd_recipe, "shop-item": cmd_shop_item, "shop": cmd_shop, "mail": cmd_mail, "event": cmd_event, "sid-sprite": cmd_sid_sprite, "location": cmd_location}[a.cmd]
    fn(mod, a)
    mod.finish(validate=not a.no_validate and a.cmd != "sid-sprite")
    if mod.new_ids:
        print("new ids: " + ", ".join(mod.new_ids))


if __name__ == "__main__":
    main()

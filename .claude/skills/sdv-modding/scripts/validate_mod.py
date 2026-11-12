#!/usr/bin/env python3
"""Static checks for an SDV mod folder (or a folder of mods).

  python validate_mod.py "[CP] Mira"
  python validate_mod.py ./mods --recursive

Checks: manifest fields & ID format, content pack target, JSON syntax (SMAPI-tolerant),
Content Patcher Format/Action/Target/FromFile, Include files, image sizes for known targets,
i18n keys used vs defined, custom IDs missing a mod prefix, leftover placeholders,
Fashion Sense / Alternative Textures / Portraiture layouts, C# csproj/EntryDll.
Exit code 1 if any ERROR.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PIL import Image

from sdvlib import load_json

KNOWN_PACKS = {
    "pathoschild.contentpatcher": "cp", "platonymous.portraiture": "portraiture",
    "peacefulend.fashionsense": "fs", "peacefulend.alternativetextures": "at",
    "bleakcodex.spritesindetail": "sid",
}
ACTIONS = {"Load", "EditData", "EditImage", "EditMap", "Include"}
ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
I18N_RE = re.compile(r"\{\{\s*i18n\s*:\s*([^}|\s]+)")
TOKEN_RE = re.compile(r"\{\{[^}]*\}\}")
IMG_TARGETS = [  # (target regex, width rule, height multiple, description)
    (re.compile(r"^Portraits/", re.I), lambda w: w == 128, 64, "portrait sheet must be 128 wide, height multiple of 64"),
    (re.compile(r"^Characters/(?!Dialogue|schedules|Farmer)", re.I), lambda w: w % 16 == 0, 16, "sprite sheet width multiple of 16 (vanilla NPCs: 64)"),
]


class Report:
    def __init__(self):
        self.items = []

    def err(self, where, msg): self.items.append(("ERROR", where, msg))
    def warn(self, where, msg): self.items.append(("WARN", where, msg))
    def info(self, where, msg): self.items.append(("INFO", where, msg))

    def print(self):
        for lvl, where, msg in self.items:
            print(f"[{lvl}] {where}: {msg}")
        e = sum(1 for i in self.items if i[0] == "ERROR"); w = sum(1 for i in self.items if i[0] == "WARN")
        print(f"\n{e} error(s), {w} warning(s)")
        return e


def read_json(path: Path, rep: Report):
    try:
        return load_json(path)
    except Exception as ex:
        rep.err(str(path), f"invalid JSON: {ex}")
        return None


def walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(k); yield from walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)


def check_image(path: Path, target: str, rep: Report, where: str):
    try:
        im = Image.open(path)
    except Exception as ex:
        rep.err(where, f"cannot open image {path.name}: {ex}"); return
    if im.info.get("sdv_placeholder") == "1":
        rep.warn(where, f"{path.name} is still a placeholder")
    if im.mode not in ("RGBA", "P", "LA"):
        rep.warn(where, f"{path.name} has no alpha channel (mode {im.mode})")
    for rx, wrule, hmul, desc in IMG_TARGETS:
        if rx.search(target) and "{{" not in target:
            w, h = im.size
            if not wrule(w) or h % hmul:
                rep.err(where, f"{path.name} is {w}x{h}: {desc}")


def check_cp(root: Path, man: dict, rep: Report):
    content = root / "content.json"
    if not content.exists():
        rep.err(str(root), "content.json missing"); return
    data = read_json(content, rep)
    if data is None:
        return
    fmt = data.get("Format")
    if not fmt:
        rep.err("content.json", "missing Format")
    elif not re.match(r"^2\.", str(fmt)):
        rep.warn("content.json", f"Format {fmt} predates SDV 1.6 data formats; use the installed Content Patcher version")

    i18n_def = {}
    i18n_path = root / "i18n" / "default.json"
    if i18n_path.exists():
        i18n_def = read_json(i18n_path, rep) or {}

    files = [(content, data.get("Changes") or [])]
    seen = {content.resolve()}
    used_i18n = set()
    for s in walk_strings(data):
        used_i18n.update(I18N_RE.findall(s))
    while files:
        src, changes = files.pop(0)
        where0 = src.relative_to(root).as_posix()
        if not isinstance(changes, list):
            rep.err(where0, "Changes must be a list"); continue
        for n, ch in enumerate(changes):
            if not isinstance(ch, dict):
                rep.err(where0, f"change #{n} is not an object"); continue
            where = f"{where0} #{n}" + (f" ({ch['LogName']})" if ch.get("LogName") else "")
            act = ch.get("Action")
            if act not in ACTIONS:
                rep.err(where, f"unknown Action '{act}'"); continue
            if act != "Include" and not ch.get("Target"):
                rep.err(where, "missing Target")
            if act in ("Load", "EditImage", "Include") and not ch.get("FromFile"):
                rep.err(where, "missing FromFile")
            ff = ch.get("FromFile")
            if ff:
                for part in [p.strip() for p in str(ff).split(",")] if act == "Include" else [str(ff)]:
                    if TOKEN_RE.search(part):
                        rep.info(where, f"FromFile uses tokens, not checked: {part}"); continue
                    fp = root / part
                    if not fp.exists():
                        rep.err(where, f"FromFile not found: {part}"); continue
                    if act == "Include":
                        if fp.resolve() in seen:
                            continue
                        seen.add(fp.resolve())
                        inc = read_json(fp, rep)
                        if inc is not None:
                            for s in walk_strings(inc):
                                used_i18n.update(I18N_RE.findall(s))
                            files.append((fp, inc.get("Changes") or []))
                    elif fp.suffix.lower() == ".png":
                        targets = [t.strip() for t in str(ch.get("Target", "")).split(",")]
                        for t in targets:
                            check_image(fp, t, rep, where)
                    elif fp.suffix.lower() == ".json":
                        read_json(fp, rep)
            if act == "EditData":
                tgt = str(ch.get("Target", ""))
                for key in (ch.get("Entries") or {}):
                    if tgt.split("/")[0] == "Data" and tgt not in ("Data/NPCGiftTastes", "Data/mail") \
                            and not tgt.startswith("Data/Events") and ch.get("TargetField") is None:
                        base = key.split("/")[0]
                        if "{{ModId}}" not in base and "." not in base and "_" not in base and not base.startswith("("):
                            rep.warn(where, f"entry '{key}' in {tgt} has no mod prefix; vanilla keys are fine if you meant to edit them, new ones should use {{{{ModId}}}}_")

    missing = sorted(k for k in used_i18n if k not in i18n_def)
    if missing:
        rep.err("i18n/default.json", f"{len(missing)} key(s) used but not defined: {', '.join(missing[:15])}{' …' if len(missing) > 15 else ''}")
    unused = sorted(k for k in i18n_def if k not in used_i18n)
    if unused and used_i18n:
        rep.info("i18n/default.json", f"{len(unused)} key(s) defined but not referenced in JSON (may be used elsewhere): {', '.join(unused[:10])}")
    for lang in (root / "i18n").glob("*.json") if (root / "i18n").exists() else []:
        if lang.name != "default.json":
            d = read_json(lang, rep) or {}
            extra = [k for k in d if k not in i18n_def]
            if extra:
                rep.warn(f"i18n/{lang.name}", f"keys not in default.json: {', '.join(extra[:10])}")


def check_fs(root: Path, rep: Report):
    for kind, jname in [("Hairs", "hair.json"), ("Accessories", "accessory.json"), ("Hats", "hat.json"), ("Shirts", "shirt.json"),
                        ("Pants", "pants.json"), ("Sleeves", "sleeves.json"), ("Shoes", "shoes.json")]:
        d = root / kind
        if not d.exists():
            continue
        for item in d.iterdir():
            if not item.is_dir():
                continue
            j, p = item / jname, item / jname.replace(".json", ".png")
            if not j.exists():
                rep.err(f"{kind}/{item.name}", f"missing {jname}"); continue
            if not p.exists():
                rep.err(f"{kind}/{item.name}", f"missing {p.name}"); continue
            data = read_json(j, rep) or {}
            im = Image.open(p)
            for k, v in data.items():
                if isinstance(v, dict) and "StartingPosition" in v:
                    sp = v["StartingPosition"]
                    size = next((vv for kk, vv in v.items() if kk.endswith("Size") and isinstance(vv, dict)), None)
                    if size and (sp.get("X", 0) + size.get("Width", 0) > im.width or sp.get("Y", 0) + size.get("Height", 0) > im.height):
                        rep.err(f"{kind}/{item.name}", f"{k} rect exceeds {p.name} ({im.width}x{im.height})")


def check_at(root: Path, rep: Report):
    d = root / "Textures"
    for item in d.iterdir() if d.exists() else []:
        if not item.is_dir():
            continue
        j = item / "texture.json"
        if not j.exists():
            rep.err(f"Textures/{item.name}", "missing texture.json"); continue
        data = read_json(j, rep) or {}
        pngs = sorted(item.glob("texture*.png"))
        if not pngs:
            rep.err(f"Textures/{item.name}", "no texture.png"); continue
        w, h, v = data.get("TextureWidth"), data.get("TextureHeight"), data.get("Variations", 1)
        if w and h:
            im = Image.open(pngs[0])
            if im.width < w or im.height < h * v:
                rep.err(f"Textures/{item.name}", f"{pngs[0].name} is {im.size}, expected at least {w}x{h * v} for {v} variation(s)")


SID_KNOWN = {"Target", "FromFile", "SpriteWidth", "SpriteHeight", "WidthScale", "HeightScale", "SpriteOriginX", "SpriteOriginY", "BreathType"}


def check_sid(root: Path, rep: Report):
    """Sprites in Detail: fields as used by real packs (Target, FromFile, scales, sprite size, origin). Others are only reported."""
    content = root / "content.json"
    if not content.exists():
        rep.err(str(root), "content.json missing"); return
    data = read_json(content, rep)
    if data is None:
        return
    sprites = data.get("Sprites")
    if not isinstance(sprites, list):
        rep.err("content.json", "needs a Sprites list"); return
    for n, e in enumerate(sprites):
        where = f"content.json Sprites[{n}]" + (f" ({e.get('Target')})" if isinstance(e, dict) else "")
        if not isinstance(e, dict):
            rep.err(where, "entry is not an object"); continue
        for k in ("Target", "FromFile", "WidthScale", "HeightScale"):
            if k not in e:
                rep.err(where, f"missing {k}")
        for k in e:
            if k not in SID_KNOWN:
                rep.info(where, f"field '{k}' is not one the skill knows (not checked)")
        if e.get("Target") and not str(e["Target"]).lower().startswith("characters/"):
            rep.warn(where, "Target is not under Characters/ (NPC sheets are Characters/<Name>)")
        ws, hs = e.get("WidthScale"), e.get("HeightScale")
        if not all(isinstance(x, (int, float)) and x > 0 for x in (ws, hs) if x is not None):
            rep.err(where, "WidthScale/HeightScale must be positive numbers")
        ff = e.get("FromFile")
        if not ff or "{{" in str(ff):
            continue
        fp = root / str(ff)
        if not fp.exists():
            rep.err(where, f"FromFile not found: {ff}"); continue
        try:
            im = Image.open(fp)
        except Exception as ex:
            rep.err(where, f"cannot open {ff}: {ex}"); continue
        if im.info.get("sdv_placeholder") == "1":
            rep.warn(where, f"{ff} is still a placeholder")
        if ws and hs:
            if im.width % ws or im.height % hs:
                rep.err(where, f"{ff} is {im.width}x{im.height}: not divisible by the scale ({ws}x{hs}), so it is not a whole vanilla sheet")
            else:
                vw, vh = im.width // ws, im.height // hs
                if vw % 16:
                    rep.warn(where, f"{ff} / scale is {vw}x{vh}: vanilla NPC sheet width is a multiple of 16 (usually 64)")
                sw, sh = e.get("SpriteWidth"), e.get("SpriteHeight")
                if sw and sh and abs(sw * 2 - sh) > 0:
                    rep.warn(where, f"SpriteWidth:SpriteHeight is {sw}:{sh}; keep 1:2 like the vanilla 16x32 frame")
                ox, oy = e.get("SpriteOriginX"), e.get("SpriteOriginY")
                frame_w, frame_h = int(16 * ws), int(32 * hs)  # HD size of a vanilla 16x32 frame
                if ox is not None and not 0 <= ox < frame_w or oy is not None and not 0 <= oy < frame_h:
                    rep.err(where, f"SpriteOrigin ({ox},{oy}) is outside the {frame_w}x{frame_h} frame")


def check_portraiture(root: Path, rep: Report):
    for p in root.glob("*.png"):
        im = Image.open(p)
        if im.width % 2 or (im.height % (im.width // 2)):
            rep.err(p.name, f"{im.width}x{im.height}: needs 2 square frames per row (height multiple of width/2)")


def check_smapi(root: Path, man: dict, rep: Report):
    projs = list(root.glob("*.csproj"))
    if not projs:
        rep.warn(str(root), "EntryDll set but no .csproj here (fine for a built release folder)")
        return
    txt = projs[0].read_text(encoding="utf-8", errors="ignore")
    if "Pathoschild.Stardew.ModBuildConfig" not in txt:
        rep.warn(projs[0].name, "no ModBuildConfig reference")
    if "net6.0" not in txt:
        rep.warn(projs[0].name, "SDV 1.6 mods target net6.0")
    asm = re.search(r"<AssemblyName>(.+?)</AssemblyName>", txt)
    name = asm.group(1) if asm else projs[0].stem
    if man.get("EntryDll") != f"{name}.dll":
        rep.err("manifest.json", f"EntryDll '{man.get('EntryDll')}' != assembly '{name}.dll'")


def check_mod(root: Path, rep: Report):
    mpath = root / "manifest.json"
    if not mpath.exists():
        rep.err(str(root), "manifest.json missing"); return
    man = read_json(mpath, rep)
    if man is None:
        return
    for f in ("Name", "Author", "Version", "UniqueID"):
        if not man.get(f):
            rep.err("manifest.json", f"missing {f}")
    uid = man.get("UniqueID", "")
    if uid and not ID_RE.match(uid):
        rep.err("manifest.json", f"UniqueID '{uid}' has invalid characters")
    if not re.match(r"^\d+\.\d+\.\d+", str(man.get("Version", ""))):
        rep.err("manifest.json", "Version must be semantic (1.0.0)")
    if "UpdateKeys" not in man:
        rep.info("manifest.json", "no UpdateKeys")
    has_entry, cpf = "EntryDll" in man, man.get("ContentPackFor")
    if has_entry and cpf:
        rep.err("manifest.json", "cannot have both EntryDll and ContentPackFor")
    if not has_entry and not cpf:
        rep.err("manifest.json", "needs EntryDll (C# mod) or ContentPackFor (content pack)")
    for dep in man.get("Dependencies") or []:
        if not dep.get("UniqueID"):
            rep.err("manifest.json", "dependency without UniqueID")
    kind = KNOWN_PACKS.get((cpf or {}).get("UniqueID", "").lower()) if cpf else None
    if kind == "cp":
        check_cp(root, man, rep)
    elif kind == "fs":
        check_fs(root, rep)
    elif kind == "at":
        check_at(root, rep)
    elif kind == "portraiture":
        check_portraiture(root, rep)
    elif kind == "sid":
        check_sid(root, rep)
    elif has_entry:
        check_smapi(root, man, rep)
        if (root / "i18n" / "default.json").exists():
            read_json(root / "i18n" / "default.json", rep)
    for junk in list(root.rglob("*_preview.png")) + list(root.rglob("Thumbs.db")) + list(root.rglob(".DS_Store")):
        rep.warn(str(junk.relative_to(root)), "stray file will ship with the mod")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--recursive", action="store_true", help="validate every mod folder below path")
    a = ap.parse_args()
    root = Path(a.path)
    mods = [p.parent for p in root.rglob("manifest.json")] if a.recursive else [root]
    total = 0
    for m in mods:
        print(f"=== {m}")
        rep = Report()
        check_mod(m, rep)
        total += rep.print()
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()

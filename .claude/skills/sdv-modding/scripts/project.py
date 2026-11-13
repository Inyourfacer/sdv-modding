#!/usr/bin/env python3
"""The skill's per-project memory: sdv-project.json (mods, custom IDs, characters, art assets, status).

  python project.py sync                      # create or refresh from the mod folders under the project root (cwd)
  python project.py sync --root "Mods/My Project" --prefix Me.MyMod
  python project.py status [--json]           # assets by status, per mod; lists placeholders
  python project.py ids list [--kind npc]     # custom IDs found in the mods
  python project.py ids check                 # duplicate / unprefixed IDs
  python project.py import-csv docs/asset_manifest.csv [--spec-col category]
  python project.py export-csv out.csv

`sync` is non-destructive: it adds mods/assets/IDs it finds and updates facts it can measure (size,
placeholder flag, version) but never changes a status you or the art pipeline set beyond placeholder<->installed,
and never touches characters, art_style, test or notes.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from PIL import Image

from sdvlib import PROJECT_NAME, find_project, load_config, load_json, load_manifest, load_project, new_project, save_project

SKIP_DIRS = {".git", "bin", "obj", "node_modules", "__pycache__", "runs", "releases", "art-source", "backups"}
PACKS = {"pathoschild.contentpatcher": "cp", "platonymous.portraiture": "portraiture", "peacefulend.fashionsense": "fs",
         "peacefulend.alternativetextures": "at", "bleakcodex.spritesindetail": "sid"}
TARGET_KIND = {
    "Data/Objects": "object", "Data/BigCraftables": "big_craftable", "Data/Crops": "crop", "Data/FruitTrees": "fruit_tree",
    "Data/Characters": "npc", "Data/Locations": "location", "Data/Shops": "shop", "Data/mail": "mail",
    "Data/TriggerActions": "trigger_action", "Data/Buildings": "building", "Data/CookingRecipes": "recipe",
    "Data/CraftingRecipes": "recipe", "Data/Furniture": "furniture", "Data/Weapons": "weapon", "Data/Shirts": "shirt",
    "Data/Pants": "pants", "Data/hats": "hat", "Data/Quests": "quest", "Data/SpecialOrders": "special_order",
    "Data/Machines": "machine", "Data/AdditionalFarms": "farm_type",
}
SPEC_FOR_TARGET = [(re.compile(r"^Portraits/", re.I), "portrait"), (re.compile(r"^Characters/(?!Dialogue|schedules|Farmer)", re.I), "character_sprite")]


# ---------------------------------------------------------------- scanning
def find_mod_folders(root: Path) -> list[Path]:
    out = []
    for mf in sorted(root.rglob("manifest.json")):
        parts = set(mf.relative_to(root).parts[:-1])
        if parts & SKIP_DIRS or len(mf.relative_to(root).parts) > 3:
            continue
        out.append(mf.parent)
    return out


def mod_type(man: dict) -> str:
    if man.get("EntryDll"):
        return "smapi"
    return PACKS.get(str((man.get("ContentPackFor") or {}).get("UniqueID", "")).lower(), "other")


def cp_changes(mod: Path):
    """Yield (changes_file, change_dict) across content.json and literal Include files."""
    content = mod / "content.json"
    if not content.exists():
        return
    seen, queue = set(), [content]
    while queue:
        f = queue.pop(0)
        if f.resolve() in seen:
            continue
        seen.add(f.resolve())
        try:
            data = load_json(f)
        except Exception:
            continue
        for ch in (data.get("Changes") or []) if isinstance(data, dict) else []:
            if not isinstance(ch, dict):
                continue
            if ch.get("Action") == "Include" and ch.get("FromFile"):
                for part in str(ch["FromFile"]).split(","):
                    part = part.strip()
                    if part and "{{" not in part and (mod / part).exists():
                        queue.append(mod / part)
            else:
                yield f, ch


def collect_ids(mod: Path, uid: str, prefix: str | None):
    """{id: {kind, owner}} for custom entries a CP pack adds, plus {png path: target} for its image loads."""
    ids, targets = {}, {}
    for f, ch in cp_changes(mod):
        act, tgt = ch.get("Action"), str(ch.get("Target", ""))
        rel = f.relative_to(mod).as_posix()
        if act in ("Load", "EditImage") and ch.get("FromFile") and "{{" not in str(ch["FromFile"]):
            targets.setdefault(str(ch["FromFile"]).replace("\\", "/"), tgt.split(",")[0].strip())
        if act != "EditData" or ch.get("TargetField") is not None:
            continue
        kind = TARGET_KIND.get(tgt)
        is_event = tgt.startswith("Data/Events/")
        if not kind and not is_event:
            continue
        for key in (ch.get("Entries") or {}):
            base = key.split("/")[0] if is_event else key
            base = re.sub(r"^\([A-Z]+\)", "", base)
            full = base.replace("{{ModId}}", uid)
            if full.startswith(uid) or (prefix and full.startswith(prefix)):
                ids.setdefault(full, {"kind": "event" if is_event else kind, "owner": f"{mod.name}/{rel}"})
    return ids, targets


def png_facts(p: Path):
    try:
        with Image.open(p) as im:
            return list(im.size), im.info.get("sdv_placeholder") == "1"
    except Exception:
        return None, False


def spec_for(target: str | None):
    for rx, spec in SPEC_FOR_TARGET:
        if target and rx.search(target):
            return spec
    return None


# ---------------------------------------------------------------- sync
def sync(root: Path, prefix: str | None, existing: dict | None):
    proj = existing or new_project()
    mods_by_folder = {m["folder"]: m for m in proj["mods"]}
    assets_by_file = {f: a for a in proj["assets"] for f in a.get("files", [])}
    uids = []
    report = {"mods_added": 0, "assets_added": 0, "ids_added": 0, "assets_updated": 0}

    for mod in find_mod_folders(root):
        try:
            man = load_manifest(mod / "manifest.json")
        except Exception:
            continue
        rel = mod.relative_to(root).as_posix()
        uid = man.get("UniqueID", "")
        uids.append(uid)
        entry = mods_by_folder.get(rel)
        if entry is None:
            entry = {"folder": rel, "type": mod_type(man), "unique_id": uid, "version": man.get("Version")}
            proj["mods"].append(entry); mods_by_folder[rel] = entry; report["mods_added"] += 1
        else:
            entry.update(type=mod_type(man), unique_id=uid, version=man.get("Version"))

    if not proj.get("id_prefix"):
        proj["id_prefix"] = prefix or (uids[0].split(".")[0] if uids and "." in uids[0] else None)
    pfx = proj["id_prefix"]

    for m in proj["mods"]:
        mod = root / m["folder"]
        if not mod.exists():
            continue
        ids, targets = {}, {}
        if m["type"] == "cp":
            ids, targets = collect_ids(mod, m["unique_id"], pfx)
        for i, info in ids.items():
            if i not in proj["ids"]:
                proj["ids"][i] = info; report["ids_added"] += 1
        for png in sorted(mod.rglob("*.png")):
            if set(png.relative_to(mod).parts[:-1]) & SKIP_DIRS or png.name.endswith("_preview.png"):
                continue
            relpng = png.relative_to(mod).as_posix()
            fpath = f"{m['folder']}/{relpng}"
            size, ph = png_facts(png)
            a = assets_by_file.get(fpath)
            if a is None:
                target = targets.get(relpng)
                a = {"id": re.sub(r"[^a-z0-9]+", "_", f"{Path(m['folder']).name}_{relpng}".lower()).strip("_"),
                     "mod": m["folder"], "spec": spec_for(target), "character": None, "files": [fpath],
                     "targets": [{"kind": "vanilla"}], "status": "placeholder" if ph else "installed",
                     "take": None, "prompt": {"positive": None, "negative": None}, "notes": ""}
                if target:
                    a["game_asset"] = target
                a["size"] = size
                proj["assets"].append(a); assets_by_file[fpath] = a; report["assets_added"] += 1
            else:
                a["size"] = size
                if ph and a["status"] in ("installed", "approved"):
                    a["status"] = "placeholder"; report["assets_updated"] += 1  # reverted to a placeholder
                elif not ph and a["status"] == "placeholder":
                    a["status"] = "installed"; report["assets_updated"] += 1  # real art landed
    return proj, report


# ---------------------------------------------------------------- reports
def status_report(proj: dict) -> dict:
    by_status, by_mod = {}, {}
    for a in proj["assets"]:
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1
        by_mod.setdefault(a.get("mod", "?"), {}).setdefault(a["status"], 0)
        by_mod[a.get("mod", "?")][a["status"]] += 1
    return {"mods": [m["folder"] for m in proj["mods"]], "id_prefix": proj.get("id_prefix"),
            "characters": list(proj["characters"]), "ids": len(proj["ids"]),
            "assets_total": len(proj["assets"]), "by_status": by_status, "by_mod": by_mod,
            "placeholders": [a["id"] for a in proj["assets"] if a["status"] == "placeholder"],
            "style_locked": bool((proj.get("art_style") or {}).get("checkpoint"))}


def check_ids(proj: dict):
    issues = []
    pfx = proj.get("id_prefix")
    uids = [m["unique_id"] for m in proj["mods"] if m.get("unique_id")]
    for i, info in proj["ids"].items():
        if not (any(i.startswith(u) for u in uids) or (pfx and i.startswith(pfx))):
            issues.append(("WARN", i, f"{info['kind']} id has no mod/author prefix (owner {info.get('owner')})"))
        if not re.match(r"^[A-Za-z0-9_.\-]+$", i):
            issues.append(("ERROR", i, "id has characters other than letters, digits, _ . -"))
    return issues


def duplicate_scan(root: Path, proj: dict):
    """Ids defined in more than one place (can be legitimate conditional patches, so reported as INFO)."""
    seen: dict[tuple, list] = {}
    for m in proj["mods"]:
        mod = root / m["folder"]
        if m["type"] != "cp" or not mod.exists():
            continue
        for f, ch in cp_changes(mod):
            tgt = str(ch.get("Target", ""))
            kind = TARGET_KIND.get(tgt)
            if ch.get("Action") == "EditData" and kind and ch.get("TargetField") is None:
                for key in (ch.get("Entries") or {}):
                    k = (tgt, key.replace("{{ModId}}", m["unique_id"]))
                    seen.setdefault(k, []).append(f"{m['folder']}/{f.relative_to(mod).as_posix()}")
    return [("INFO", f"{t}:{k}", "defined in " + ", ".join(v)) for (t, k), v in seen.items() if len(v) > 1]


# ---------------------------------------------------------------- csv
CSV_ALIASES = {
    "id": ("id", "asset_id", "name"), "spec": ("spec", "category", "type", "kind"),
    "character": ("character", "npc"), "file": ("art_source", "file", "path", "dest", "destination"),
    "game_asset": ("game_asset", "target"), "positive": ("positive", "prompt"), "negative": ("negative",),
    "gen_width": ("gen_width", "width"), "gen_height": ("gen_height", "height"),
    "transparent_bg": ("transparent_bg", "transparent"), "notes": ("notes", "note", "description"),
    "status": ("status",),
}


def import_csv(proj: dict, path: Path, spec_col: str | None):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("CSV has no rows")
    cols = {c.lower().strip(): c for c in rows[0]}

    def get(row, field):
        for alias in ([spec_col] if field == "spec" and spec_col else []) + list(CSV_ALIASES[field]):
            c = cols.get(alias.lower())
            if c and row.get(c, "").strip():
                return row[c].strip()
        return None

    by_id = {a["id"]: a for a in proj["assets"]}
    added = updated = 0
    for row in rows:
        aid = get(row, "id")
        if not aid:
            continue
        aid = re.sub(r"[^A-Za-z0-9_.-]+", "_", aid)
        a = by_id.get(aid)
        new = a is None
        if new:
            a = {"id": aid, "mod": None, "spec": None, "character": None, "files": [], "targets": [{"kind": "vanilla"}],
                 "status": "placeholder", "take": None, "prompt": {"positive": None, "negative": None}, "notes": ""}
            proj["assets"].append(a); by_id[aid] = a
        for field in ("spec", "character", "game_asset", "notes"):
            v = get(row, field)
            if v:
                a[field] = v
        a.setdefault("prompt", {})
        for field in ("positive", "negative"):
            v = get(row, field)
            if v:
                a["prompt"][field] = v
        w, h = get(row, "gen_width"), get(row, "gen_height")
        if w and h and w.isdigit() and h.isdigit():
            a["gen_size"] = [int(w), int(h)]
        t = get(row, "transparent_bg")
        if t:
            a["transparent_bg"] = t.lower() in ("yes", "true", "1", "y")
        src = get(row, "file")
        if src:
            a["art_source"] = src.replace("\\", "/")
        st = get(row, "status")
        if st in ("placeholder", "generated", "approved", "installed"):
            a["status"] = st
        extra = {c: row[c] for c in row if c and c.lower().strip() not in {x for al in CSV_ALIASES.values() for x in al} and row[c]}
        if extra:
            a["extra"] = extra
        added += new; updated += not new
    return added, updated


def export_csv(proj: dict, path: Path):
    cols = ["id", "mod", "spec", "character", "status", "files", "art_source", "game_asset", "size", "positive", "negative", "notes"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for a in proj["assets"]:
            w.writerow([a["id"], a.get("mod"), a.get("spec"), a.get("character"), a["status"], ";".join(a.get("files", [])),
                        a.get("art_source"), a.get("game_asset"), "x".join(map(str, a["size"])) if a.get("size") else "",
                        (a.get("prompt") or {}).get("positive"), (a.get("prompt") or {}).get("negative"), a.get("notes")])


# ---------------------------------------------------------------- cli
def project_path(args) -> Path:
    if getattr(args, "project", None):
        return Path(args.project)
    return find_project() or (Path(getattr(args, "root", None) or Path.cwd()) / PROJECT_NAME)


def main():
    ap = argparse.ArgumentParser(description="Per-project memory for the sdv-modding skill.")
    ap.add_argument("--project", help=f"path to {PROJECT_NAME} (default: nearest above cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", aliases=["init"]); s.add_argument("--root"); s.add_argument("--prefix")
    st = sub.add_parser("status"); st.add_argument("--json", action="store_true")
    ids = sub.add_parser("ids"); ids.add_argument("action", choices=["list", "check"]); ids.add_argument("--kind"); ids.add_argument("--json", action="store_true")
    ic = sub.add_parser("import-csv"); ic.add_argument("csv"); ic.add_argument("--spec-col")
    ec = sub.add_parser("export-csv"); ec.add_argument("csv")
    a = ap.parse_args()

    path = project_path(a)
    proj = load_project(path)

    if a.cmd in ("sync", "init"):
        root = Path(a.root).resolve() if a.root else path.parent.resolve()
        proj, rep = sync(root, a.prefix, proj)
        save_project(proj, path)
        print(f"{path}: +{rep['mods_added']} mods, +{rep['assets_added']} assets, +{rep['ids_added']} ids, "
              f"{rep['assets_updated']} asset status updates; {len(proj['mods'])} mods, {len(proj['assets'])} assets, {len(proj['ids'])} ids total")
        return
    if proj is None:
        raise SystemExit(f"No {PROJECT_NAME} found. Run: python project.py sync")

    if a.cmd == "status":
        r = status_report(proj)
        if a.json:
            print(json.dumps(r, indent=2)); return
        print(f"prefix {r['id_prefix']}  mods {len(r['mods'])}  ids {r['ids']}  characters {len(r['characters'])}  style locked: {r['style_locked']}")
        for m, c in r["by_mod"].items():
            print(f"  {m:<40} " + "  ".join(f"{k} {v}" for k, v in sorted(c.items())))
        print(f"assets {r['assets_total']}: " + ", ".join(f"{k} {v}" for k, v in sorted(r["by_status"].items())))
        if r["placeholders"]:
            print("placeholders:", ", ".join(r["placeholders"][:25]) + (" ..." if len(r["placeholders"]) > 25 else ""))
    elif a.cmd == "ids":
        if a.action == "list":
            rows = [(i, v["kind"], v.get("owner")) for i, v in sorted(proj["ids"].items()) if not a.kind or v["kind"] == a.kind]
            if a.json:
                print(json.dumps([{"id": i, "kind": k, "owner": o} for i, k, o in rows], indent=2))
            else:
                for i, k, o in rows:
                    print(f"{k:<14} {i}  ({o})")
        else:
            issues = check_ids(proj) + duplicate_scan(path.parent, proj)
            for lvl, i, msg in issues:
                print(f"[{lvl}] {i}: {msg}")
            errs = sum(1 for x in issues if x[0] == "ERROR")
            print(f"\n{errs} error(s), {sum(1 for x in issues if x[0] == 'WARN')} warning(s)")
            sys.exit(1 if errs else 0)
    elif a.cmd == "import-csv":
        added, updated = import_csv(proj, Path(a.csv), a.spec_col)
        save_project(proj, path)
        print(f"imported {a.csv}: {added} added, {updated} updated; {len(proj['assets'])} assets total")
    elif a.cmd == "export-csv":
        export_csv(proj, Path(a.csv))
        print(f"wrote {a.csv} ({len(proj['assets'])} rows)")


if __name__ == "__main__":
    main()

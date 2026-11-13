#!/usr/bin/env python3
"""Create, inspect, edit, check and render Stardew Valley .tmx maps without Tiled.

  python tmx.py info    Cottage.tmx
  python tmx.py new     Cottage.tmx --size 12x9 --like Trailer            # interior starter: Trailer's tilesheets, its commonest floor tile
  python tmx.py new     stub.tmx --size 6x4 --like Town --empty           # blank patch map for EditMap (same tilesheets as Town)
  python tmx.py set-prop Cottage.tmx --map Warp="5 9 Town 60 71"          # map property (also: Music, Outdoors, Light, ...)
  python tmx.py add-warp Cottage.tmx --from 5,9 --to Town 60 71           # appends to the Warp property
  python tmx.py set-tile Cottage.tmx --layer Buildings --at 3,2 --gid 2113 [--to 5,4]   # one tile or a filled rectangle
  python tmx.py check   Cottage.tmx [--mod "[CP] My Mod"] [--known Town,Farm]
  python tmx.py render  Cottage.tmx --out cottage.png [--scale 2]         # look at the map without starting the game

Format facts (read from the game's own maps): tilesheets are referenced by asset name WITHOUT extension (`townInterior`), layer data is
CSV, layers are Back, Buildings, Front, AlwaysFront (Paths for farm hints), map properties hold Warp ("x y Location tx ty ..." groups),
and an exit warp sits one tile outside the map edge. Per-tile properties (Action, TouchAction, ...) are NOT written here: add them with
Content Patcher `EditMap` MapTiles so they survive tilesheet changes. Tilesheets come from the unpacked game (vanilla.py) or the folder
next to the .tmx. Editing an existing .tmx rewrites it in this tool's layout; Tiled does the same when it saves.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import quoteattr

from PIL import Image

from vanilla import Vanilla

TILE = 16
STANDARD_LAYERS = ["Back", "Buildings", "Front", "AlwaysFront"]
FLIP_H, FLIP_V, FLIP_D = 0x80000000, 0x40000000, 0x20000000
GID_MASK = 0x0FFFFFFF


# ---------------------------------------------------------------- model
class Tileset:
    def __init__(self, firstgid, name, source, w, h, tilecount=None, columns=None):
        self.firstgid, self.name, self.source, self.w, self.h = firstgid, name, source, w, h
        self.columns = columns or max(1, w // TILE)
        self.tilecount = tilecount or self.columns * (h // TILE)

    @property
    def lastgid(self):
        return self.firstgid + self.tilecount - 1


class Layer:
    def __init__(self, name, width, height, data=None):
        self.name, self.width, self.height = name, width, height
        self.data = data if data is not None else [0] * (width * height)

    def used(self):
        return sum(1 for g in self.data if g)


class TMap:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.props: dict[str, str] = {}
        self.tilesets: list[Tileset] = []
        self.layers: list[Layer] = []

    # -- parsing (regex over the Tiled XML: maps written by Tiled and by this tool share one layout)
    @classmethod
    def load(cls, path: Path) -> "TMap":
        t = Path(path).read_text(encoding="utf-8")
        m = re.search(r"<map\b([^>]*)>", t)
        if not m:
            raise SystemExit(f"{path} is not a Tiled map")
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        if a.get("infinite", "0") != "0":
            raise SystemExit("infinite maps are not supported by the game")
        tm = cls(int(a["width"]), int(a["height"]))
        head = t[m.end():t.find("<tileset") if "<tileset" in t else len(t)]
        for pm in re.finditer(r'<property name="([^"]*)"(?: type="\w+")? value="([^"]*)"', head.split("<layer")[0]):
            tm.props[pm.group(1)] = _unesc(pm.group(2))
        for ts in re.finditer(r"<tileset\b([^>]*)>(.*?)</tileset>", t, re.S):
            ta = dict(re.findall(r'(\w+)="([^"]*)"', ts.group(1)))
            im = dict(re.findall(r'(\w+)="([^"]*)"', re.search(r"<image\b([^>]*)/?>", ts.group(2)).group(1)))
            tm.tilesets.append(Tileset(int(ta["firstgid"]), ta["name"], im["source"], int(im.get("width", 0)), int(im.get("height", 0)),
                                       int(ta["tilecount"]) if "tilecount" in ta else None, int(ta["columns"]) if "columns" in ta else None))
        for ly in re.finditer(r"<layer\b([^>]*)>(.*?)</layer>", t, re.S):
            la = dict(re.findall(r'(\w+)="([^"]*)"', ly.group(1)))
            d = re.search(r'<data encoding="(\w+)"[^>]*>(.*?)</data>', ly.group(2), re.S)
            if not d or d.group(1) != "csv":
                raise SystemExit(f"layer '{la.get('name')}' is not CSV-encoded (save from Tiled with 'Tile Layer Format: CSV')")
            nums = [int(x) for x in re.findall(r"\d+", d.group(2))]
            tm.layers.append(Layer(la["name"], int(la["width"]), int(la["height"]), nums))
        return tm

    def layer(self, name):
        return next((l for l in self.layers if l.name.lower() == name.lower()), None)

    def tileset_for(self, gid: int):
        g = gid & GID_MASK
        return next((ts for ts in self.tilesets if ts.firstgid <= g <= ts.lastgid), None)

    def to_xml(self) -> str:
        out = ['<?xml version="1.0"?>',
               f'<map version="1.4" tiledversion="1.4.2" orientation="orthogonal" renderorder="right-down" compressionlevel="0" '
               f'width="{self.width}" height="{self.height}" tilewidth="{TILE}" tileheight="{TILE}" infinite="0" nextlayerid="{len(self.layers) + 1}" nextobjectid="1">']
        if self.props:
            out.append("  <properties>")
            for k, v in self.props.items():
                out.append(f'    <property name={quoteattr(k)} type="string" value={quoteattr(v)} />')
            out.append("  </properties>")
        for ts in self.tilesets:
            out.append(f'  <tileset firstgid="{ts.firstgid}" name={quoteattr(ts.name)} tilewidth="{TILE}" tileheight="{TILE}" tilecount="{ts.tilecount}" columns="{ts.columns}">')
            out.append(f'    <image source={quoteattr(ts.source)} width="{ts.w}" height="{ts.h}" />')
            out.append("  </tileset>")
        for i, l in enumerate(self.layers, 1):
            out.append(f'  <layer id="{i}" name={quoteattr(l.name)} width="{l.width}" height="{l.height}" opacity="1" offsetx="0" offsety="0">')
            out.append("    <properties />")
            out.append('    <data encoding="csv">')
            for y in range(l.height):
                row = ",".join(str(g) for g in l.data[y * l.width:(y + 1) * l.width])
                out.append(row + ("," if y < l.height - 1 else ""))
            out.append("</data>")
            out.append("  </layer>")
        out.append("</map>")
        return "\n".join(out) + "\n"

    def save(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.to_xml(), encoding="utf-8")

    def warps(self) -> list[tuple]:
        toks = self.props.get("Warp", "").split()
        return [tuple(toks[i:i + 5]) for i in range(0, len(toks) - len(toks) % 5, 5)]


def _unesc(s: str) -> str:
    return s.replace("&quot;", '"').replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


# ---------------------------------------------------------------- tilesheet images
def sheet_image(tmx_dir: Path | None, source: str, v: Vanilla | None) -> Image.Image | None:
    names = [source, source + ".png"]
    for n in names:
        if tmx_dir and (tmx_dir / n).is_file():
            return Image.open(tmx_dir / n).convert("RGBA")
    if v and v.available:
        p = v._file(f"Maps/{Path(source).stem}", (".png",))
        if p:
            return Image.open(p).convert("RGBA")
    return None


def sheet_size(tmx_dir: Path | None, source: str, v: Vanilla | None):
    im = sheet_image(tmx_dir, source, v)
    return im.size if im else None


# ---------------------------------------------------------------- creation
def vanilla_map(v: Vanilla, name: str) -> TMap:
    p = v._file(f"Maps/{name}", (".tmx",)) if v.available else None
    if not p:
        raise SystemExit(f"Vanilla map 'Maps/{name}' not found (is the game content unpacked? see doctor.py / references/validation.md).")
    return TMap.load(p)


def tile_image(tm: TMap, gid: int, d: Path | None, v: Vanilla | None) -> Image.Image | None:
    ts = tm.tileset_for(gid)
    im = sheet_image(d, ts.source, v) if ts else None
    if not im:
        return None
    idx = (gid & GID_MASK) - ts.firstgid
    sx, sy = (idx % ts.columns) * TILE, (idx // ts.columns) * TILE
    return im.crop((sx, sy, sx + TILE, sy + TILE))


def looks_like_floor(img: Image.Image) -> bool:
    """Opaque and not near-black: rules out the blank/void filler tile that is the commonest tile of most interior maps."""
    px = list(img.getdata())
    opaque = sum(1 for p in px if p[3] > 200) / len(px)
    bright = sum(sum(p[:3]) / 3 for p in px if p[3] > 200) / max(1, sum(1 for p in px if p[3] > 200))
    return opaque > 0.95 and bright > 70


def new_like(size: tuple[int, int], like: str, v: Vanilla, empty: bool = False, floor_gid: int | None = None) -> TMap:
    """A starter map using another map's tilesheets (so gids mean the same thing). Floor = that map's commonest Back tile unless empty."""
    src = vanilla_map(v, like)
    tm = TMap(*size)
    tm.tilesets = [Tileset(t.firstgid, t.name, t.source, t.w, t.h, t.tilecount, t.columns) for t in src.tilesets]
    names = STANDARD_LAYERS if like.lower() != "town" else STANDARD_LAYERS
    tm.layers = [Layer(n, *size) for n in names]
    if not empty:
        back = src.layer("Back")
        if floor_gid is None:
            common = Counter(g for g in back.data if g) if back else Counter()
            floor_gid = 0
            for g, _ in common.most_common():               # commonest tile that really looks like a floor
                img = tile_image(src, g, None, v)
                if img is not None and looks_like_floor(img):
                    floor_gid = g
                    break
        tm.layers[0].data = [floor_gid] * (size[0] * size[1])
    return tm


# ---------------------------------------------------------------- checks
def check_map(tm: TMap, path: Path, v: Vanilla | None, known: set[str]) -> list[tuple[str, str]]:
    out = []
    d = path.parent
    for n in ("Back", "Buildings", "Front"):
        if not tm.layer(n):
            out.append(("ERROR", f"missing layer '{n}'"))
    for l in tm.layers:
        if (l.width, l.height) != (tm.width, tm.height):
            out.append(("ERROR", f"layer '{l.name}' is {l.width}x{l.height}, map is {tm.width}x{tm.height}"))
        if len(l.data) != l.width * l.height:
            out.append(("ERROR", f"layer '{l.name}' has {len(l.data)} tiles, expected {l.width * l.height}"))
    names = [t.name for t in tm.tilesets]
    if len(set(names)) != len(names):
        out.append(("ERROR", "two tilesheets share a name; the game identifies tilesheets by name"))
    expected = 1
    for ts in tm.tilesets:
        if ts.firstgid != expected:
            out.append(("WARN", f"tilesheet '{ts.name}' firstgid {ts.firstgid} leaves a gap (expected {expected})"))
        expected = ts.firstgid + ts.tilecount
        size = sheet_size(d, ts.source, v)
        if size is None:
            out.append(("WARN" if (v is None or not v.available) else "ERROR", f"tilesheet image '{ts.source}' not found next to the map or in the game content"))
        elif ts.w and (size[0] != ts.w or size[1] != ts.h):
            out.append(("WARN", f"tilesheet '{ts.name}' is {size[0]}x{size[1]} on disk but the map says {ts.w}x{ts.h}: tile indices will shift if the real sheet differs"))
        if ts.source.lower().endswith(".png") and not (d / ts.source).is_file():
            out.append(("WARN", f"tilesheet '{ts.name}' source '{ts.source}' has an extension but no such file beside the map; vanilla sheets are referenced WITHOUT extension"))
    last = tm.tilesets[-1].lastgid if tm.tilesets else 0
    for l in tm.layers:
        bad = sorted({g & GID_MASK for g in l.data if g and (g & GID_MASK) > last})
        if bad:
            out.append(("ERROR", f"layer '{l.name}' uses tile id(s) {bad[:4]} beyond the last tilesheet (max {last})"))
    if all(g == 0 for g in (tm.layer("Back").data if tm.layer("Back") else [0])):
        out.append(("WARN", "the Back layer is empty: the player would see the void"))
    for i, w in enumerate(tm.warps()):
        try:
            x, y, loc, tx, ty = int(w[0]), int(w[1]), w[2], int(w[3]), int(w[4])
        except ValueError:
            out.append(("ERROR", f"Warp group {i + 1} is malformed: {' '.join(w)}")); continue
        if not (-1 <= x <= tm.width and -1 <= y <= tm.height):
            out.append(("WARN", f"warp {i + 1} starts at {x},{y}, outside the map ({tm.width}x{tm.height}; one tile beyond the edge is normal for exits)"))
        if known and loc not in known and "{{" not in loc:
            out.append(("WARN", f"warp {i + 1} goes to '{loc}', which is not a known location"))
    if len(tm.props.get("Warp", "").split()) % 5:
        out.append(("ERROR", "Warp property is not made of 'x y Location tx ty' groups"))
    if not tm.warps():
        out.append(("INFO", "the map has no Warp property (no way out unless a patch adds warps)"))
    return out


# ---------------------------------------------------------------- render
def render(tm: TMap, path: Path, v: Vanilla | None, scale: int = 1) -> Image.Image:
    d = path.parent
    sheets = {}
    for ts in tm.tilesets:
        im = sheet_image(d, ts.source, v)
        if im is None:
            raise SystemExit(f"cannot render: tilesheet image '{ts.source}' not found beside the map or in the game content")
        sheets[ts.firstgid] = (ts, im)
    out = Image.new("RGBA", (tm.width * TILE, tm.height * TILE), (24, 24, 32, 255))
    order = [l for l in tm.layers if l.name.lower() != "paths"]
    for l in order:
        for i, g in enumerate(l.data):
            if not g:
                continue
            gid = g & GID_MASK
            ts = tm.tileset_for(gid)
            if ts is None:
                continue
            idx = gid - ts.firstgid
            sx, sy = (idx % ts.columns) * TILE, (idx // ts.columns) * TILE
            tile = sheets[ts.firstgid][1].crop((sx, sy, sx + TILE, sy + TILE))
            if g & FLIP_D:
                tile = tile.transpose(Image.TRANSPOSE)
            if g & FLIP_H:
                tile = tile.transpose(Image.FLIP_LEFT_RIGHT)
            if g & FLIP_V:
                tile = tile.transpose(Image.FLIP_TOP_BOTTOM)
            out.alpha_composite(tile, ((i % l.width) * TILE, (i // l.width) * TILE))
    if scale != 1:
        out = out.resize((out.width * scale, out.height * scale), Image.NEAREST)
    return out


# ---------------------------------------------------------------- cli
def xy(text: str) -> tuple[int, int]:
    a, b = re.split(r"[,x ]", text.strip())
    return int(a), int(b)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="unpacked game content (default: from the config / ~/.sdv-skill)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info").add_argument("map")
    n = sub.add_parser("new"); n.add_argument("map"); n.add_argument("--size", required=True); n.add_argument("--like", required=True)
    n.add_argument("--empty", action="store_true"); n.add_argument("--floor", type=int, help="gid for the Back fill (default: the --like map's commonest Back tile)")
    n.add_argument("--force", action="store_true")
    sp = sub.add_parser("set-prop"); sp.add_argument("map"); sp.add_argument("--map", dest="prop", action="append", required=True, help="Key=Value")
    aw = sub.add_parser("add-warp"); aw.add_argument("map"); aw.add_argument("--from", dest="src", required=True); aw.add_argument("--to", nargs=3, required=True, metavar=("LOCATION", "X", "Y"))
    st = sub.add_parser("set-tile"); st.add_argument("map"); st.add_argument("--layer", required=True); st.add_argument("--at", required=True)
    st.add_argument("--to", help="opposite corner: fills the rectangle"); st.add_argument("--gid", type=int, required=True)
    ck = sub.add_parser("check"); ck.add_argument("map"); ck.add_argument("--mod"); ck.add_argument("--known")
    rd = sub.add_parser("render"); rd.add_argument("map"); rd.add_argument("--out", required=True); rd.add_argument("--scale", type=int, default=2)
    a = ap.parse_args()
    v = Vanilla(a.root)
    path = Path(a.map)

    if a.cmd == "new":
        if path.exists() and not a.force:
            raise SystemExit(f"{path} exists (use --force)")
        w, h = [int(x) for x in re.split(r"[xX,]", a.size)]
        tm = new_like((w, h), a.like, v, a.empty, a.floor)
        tm.save(path)
        print(f"wrote {path}: {w}x{h}, tilesheets from {a.like}: " + ", ".join(t.name for t in tm.tilesets)
              + ("" if a.empty else f", Back filled with gid {tm.layers[0].data[0]}"))
        return
    tm = TMap.load(path)
    if a.cmd == "info":
        print(f"{path.name}: {tm.width}x{tm.height} tiles")
        print("properties: " + (", ".join(f"{k}={v_!r}" for k, v_ in tm.props.items()) or "-"))
        for t in tm.tilesets:
            print(f"  tilesheet {t.name:<22} source {t.source:<22} gid {t.firstgid}-{t.lastgid} ({t.columns} columns)")
        for l in tm.layers:
            print(f"  layer {l.name:<14} {l.used():>5} tile(s)")
        for w in tm.warps():
            print(f"  warp {w[0]},{w[1]} -> {w[2]} {w[3]},{w[4]}")
    elif a.cmd == "set-prop":
        for kv in a.prop:
            k, _, val = kv.partition("=")
            tm.props[k] = val
        tm.save(path); print("ok")
    elif a.cmd == "add-warp":
        x, y = xy(a.src)
        tm.props["Warp"] = (tm.props.get("Warp", "") + f" {x} {y} {a.to[0]} {a.to[1]} {a.to[2]}").strip()
        tm.save(path); print("Warp = " + tm.props["Warp"])
    elif a.cmd == "set-tile":
        l = tm.layer(a.layer)
        if not l:
            raise SystemExit(f"no layer '{a.layer}' (layers: {', '.join(x.name for x in tm.layers)})")
        x0, y0 = xy(a.at); x1, y1 = xy(a.to) if a.to else (x0, y0)
        for yy in range(min(y0, y1), max(y0, y1) + 1):
            for xx in range(min(x0, x1), max(x0, x1) + 1):
                if not (0 <= xx < tm.width and 0 <= yy < tm.height):
                    raise SystemExit(f"tile {xx},{yy} is outside the map ({tm.width}x{tm.height})")
                l.data[yy * tm.width + xx] = a.gid
        tm.save(path); print(f"set {abs(x1 - x0) + 1}x{abs(y1 - y0) + 1} tile(s) on {l.name}")
    elif a.cmd == "check":
        known = set((a.known or "").split(",")) - {""}
        if v.available:
            known |= set((v.data("Data/Locations") or {}).keys())
            known |= {Path(x).name for x in v.assets() if x.startswith("Maps/") and "/" not in x[5:]}      # every vanilla map is a location too
        if a.mod:
            from project import cp_changes
            from vcheck import sub_modid
            from sdvlib import load_manifest
            mod = Path(a.mod)
            uid = load_manifest(mod / "manifest.json")["UniqueID"]
            for _, ch in cp_changes(mod):
                if ch.get("Target") == "Data/Locations":
                    known |= {sub_modid(k, uid) for k in (ch.get("Entries") or {})}
        res = check_map(tm, path, v, known)
        for lvl, msg in res:
            print(f"[{lvl}] {msg}")
        errs = sum(1 for r in res if r[0] == "ERROR")
        print(f"\n{errs} error(s), {sum(1 for r in res if r[0] == 'WARN')} warning(s)")
        sys.exit(1 if errs else 0)
    elif a.cmd == "render":
        render(tm, path, v, a.scale).save(a.out)
        print(f"wrote {a.out} ({tm.width * TILE * a.scale}x{tm.height * TILE * a.scale}); open it and look at it")


if __name__ == "__main__":
    main()

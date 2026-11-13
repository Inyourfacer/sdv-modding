#!/usr/bin/env python3
"""Generate the Observatory mod's maps, placeholder tilesheet and UI sprites.

  python tools/observatory/build_assets.py

Writes:
  mods/[CP] Observatory/assets/maps/z_Observatory_tiles.png   (placeholder tilesheet, 16x8 tiles)
  mods/[CP] Observatory/assets/maps/Observatory.tmx           (interior, 13x11)
  mods/[CP] Observatory/assets/maps/ObservatoryRoof.tmx       (roof deck for the finale, 13x9)
  mods/[CP] Observatory/assets/maps/ObservatoryExterior.tmx   (5x6 patch overlaid on Backwoods)
  mods/Observatory/assets/ui.png                              (star, glow, reset icon)

The tilesheet layout (tile indices) is fixed. Generated art goes in tools/observatory/art/<piece>.png
(see PIECES below and comfy/observatory/README.md) and is pasted into its slot on every run.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo

ROOT = Path(__file__).resolve().parents[2]
CP = ROOT / "mods" / "[CP] Observatory"
CS = ROOT / "mods" / "Observatory"
MAPS = CP / "assets" / "maps"
SHEET_NAME = "z_Observatory_tiles"
OBS = "Inyourfacer.Observatory"
T = 16
COLS, ROWS = 16, 8

# ---------------------------------------------------------------- tile indices
EMPTY = -1
FLOOR, FLOOR2, WALL_CAP, WALL, WINDOW, SIDE_WALL, MAT, RUG, SKY, SKY_STARS, DECK, RAIL = range(12)
DESK_L, DESK_R = 14, 15
BOARD = [[16, 17], [32, 33]]
SCOPE = [[18, 19, 20], [34, 35, 36], [50, 51, 52]]
DOME = [[r * 16 + c for c in range(5, 10)] for r in range(1, 7)]  # 5 wide x 6 tall

# ---------------------------------------------------------------- palette
WOOD = (150, 98, 58); WOOD_D = (110, 68, 40); WOOD_L = (182, 128, 80)
NAVY = (36, 40, 82); NAVY_D = (22, 24, 54); NAVY_L = (62, 70, 128)
STONE = (196, 198, 210); STONE_D = (140, 144, 162); STONE_L = (232, 234, 242)
BRASS = (214, 170, 72); BRASS_D = (150, 110, 40)
SKYC = (14, 18, 48); STAR = (240, 240, 255)
CORK = (184, 140, 92); PAPER = (240, 232, 206)


def tile_box(d: ImageDraw.ImageDraw, idx: int):
    x, y = (idx % COLS) * T, (idx // COLS) * T
    return x, y


def draw_tiles() -> Image.Image:
    im = Image.new("RGBA", (COLS * T, ROWS * T), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    def fill(idx, color):
        x, y = tile_box(d, idx)
        d.rectangle([x, y, x + T - 1, y + T - 1], fill=color)
        return x, y

    # floors
    for idx, base in ((FLOOR, WOOD), (FLOOR2, WOOD_L)):
        x, y = fill(idx, base)
        for row in (3, 7, 11, 15):
            d.line([x, y + row, x + T - 1, y + row], fill=WOOD_D)
        d.point([(x + 5, y + 1), (x + 12, y + 5), (x + 3, y + 9), (x + 10, y + 13)], fill=WOOD_D)
    # walls
    x, y = fill(WALL_CAP, NAVY_D); d.line([x, y + T - 2, x + T - 1, y + T - 2], fill=BRASS_D)
    x, y = fill(WALL, NAVY)
    for sx, sy in ((3, 4), (11, 9), (7, 13)):
        d.point((x + sx, y + sy), fill=NAVY_L)
    x, y = fill(WINDOW, NAVY); d.rectangle([x + 3, y + 2, x + 12, y + 13], fill=SKYC, outline=BRASS_D)
    d.point([(x + 6, y + 5), (x + 10, y + 9), (x + 5, y + 11)], fill=STAR)
    x, y = fill(SIDE_WALL, NAVY_D); d.line([x + 7, y, x + 7, y + T - 1], fill=NAVY)
    x, y = fill(MAT, WOOD); d.rectangle([x + 1, y + 3, x + 14, y + 12], fill=(120, 40, 50), outline=(80, 24, 30))
    x, y = fill(RUG, (60, 50, 110)); d.rectangle([x, y, x + T - 1, y + T - 1], outline=BRASS_D)
    d.point((x + 8, y + 8), fill=BRASS)
    # sky / roof
    x, y = fill(SKY, SKYC)
    x, y = fill(SKY_STARS, SKYC); d.point([(x + 3, y + 4), (x + 12, y + 2), (x + 8, y + 11)], fill=STAR)
    x, y = fill(DECK, STONE_D)
    d.line([x, y + 7, x + T - 1, y + 7], fill=STONE); d.line([x + 7, y, x + 7, y + 7], fill=STONE)
    x, y = fill(RAIL, (0, 0, 0, 0))
    d.rectangle([x, y + 9, x + T - 1, y + 15], fill=STONE_D)
    d.line([x, y + 4, x + T - 1, y + 4], fill=BRASS, width=2)
    for px in (2, 13):
        d.line([x + px, y + 4, x + px, y + 9], fill=BRASS_D)
    # desk with open journal
    for idx in (DESK_L, DESK_R):
        x, y = fill(idx, (0, 0, 0, 0))
        d.rectangle([x, y + 4, x + T - 1, y + 13], fill=WOOD_D)
        d.rectangle([x, y + 4, x + T - 1, y + 6], fill=WOOD_L)
    x, y = tile_box(d, DESK_L); d.rectangle([x + 8, y + 1, x + 15, y + 5], fill=PAPER, outline=WOOD_D)
    x, y = tile_box(d, DESK_R); d.rectangle([x, y + 1, x + 7, y + 5], fill=PAPER, outline=WOOD_D)
    d.point([(x + 12, y + 2)], fill=BRASS)  # candle
    # star-chart board (2x2)
    bx, by = tile_box(d, BOARD[0][0])
    d.rectangle([bx, by + 2, bx + 31, by + 31], fill=CORK, outline=WOOD_D)
    for (px, py) in ((4, 6), (17, 5), (6, 18), (19, 17)):
        d.rectangle([bx + px, by + py, bx + px + 9, by + py + 9], fill=PAPER)
        d.point((bx + px + 4, by + py + 4), fill=NAVY)
        d.point((bx + px + 4, by + py), fill=(200, 40, 40))
    # telescope (3x3): tube angled up-right, brass mount on a tripod
    sx, sy = tile_box(d, SCOPE[0][0])
    d.line([sx + 10, sy + 34, sx + 40, sy + 4], fill=BRASS_D, width=8)
    d.line([sx + 10, sy + 32, sx + 40, sy + 2], fill=BRASS, width=5)
    d.ellipse([sx + 36, sy, sx + 46, sy + 10], fill=NAVY_D, outline=BRASS)
    d.ellipse([sx + 18, sy + 22, sx + 30, sy + 34], fill=BRASS_D)
    for fx in (8, 24, 40):
        d.line([sx + 24, sy + 30, sx + fx, sy + 46], fill=WOOD_D, width=2)
    # exterior dome (5x6 tiles = 80x96)
    ex, ey = tile_box(d, DOME[0][0])
    d.rectangle([ex + 6, ey + 40, ex + 73, ey + 95], fill=STONE, outline=STONE_D)          # drum
    d.pieslice([ex + 2, ey + 4, ex + 77, ey + 76], 180, 360, fill=STONE_L, outline=STONE_D)  # dome
    d.rectangle([ex + 36, ey + 6, ex + 43, ey + 40], fill=NAVY_D)                           # slit
    d.line([ex + 2, ey + 40, ex + 77, ey + 40], fill=STONE_D, width=2)
    for wx in (14, 56):
        d.rectangle([ex + wx, ey + 52, ex + wx + 9, ey + 63], fill=SKYC, outline=BRASS_D)
    d.rectangle([ex + 32, ey + 66, ex + 47, ey + 95], fill=WOOD, outline=WOOD_D)            # door
    d.point((ex + 44, ey + 81), fill=BRASS)
    d.line([ex + 6, ey + 95, ex + 73, ey + 95], fill=STONE_D)
    return im


# Generated art: postprocess.py writes each piece to tools/observatory/art/<piece>.png at the exact pixel size,
# and it's pasted over the drawn placeholder at its fixed slot. Missing pieces keep the placeholder.
ART = Path(__file__).resolve().parent / "art"
PIECES = {
    # piece: (top-left tile col, row, width px, height px)
    "dome":      (5, 1, 80, 96),
    "telescope": (2, 1, 48, 48),
    "board":     (0, 1, 32, 32),
    "desk":      (14, 0, 32, 16),
    "floor":     (FLOOR % COLS, FLOOR // COLS, 16, 16),
    "wall":      (WALL % COLS, WALL // COLS, 16, 16),
    "rug":       (RUG % COLS, RUG // COLS, 16, 16),
    "deck":      (DECK % COLS, DECK // COLS, 16, 16),
}


def write_sheet():
    out = MAPS / f"{SHEET_NAME}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    im = draw_tiles()
    missing = []
    for name, (col, row, w, h) in PIECES.items():
        src = ART / f"{name}.png"
        if not src.exists():
            missing.append(name)
            continue
        piece = Image.open(src).convert("RGBA")
        if piece.size != (w, h):
            raise SystemExit(f"{src} is {piece.size[0]}x{piece.size[1]}, expected {w}x{h} (run postprocess.py with --frame {w}x{h})")
        x, y = col * T, row * T
        im.paste((0, 0, 0, 0), (x, y, x + w, y + h))
        im.alpha_composite(piece, (x, y))
    meta = PngInfo()
    if missing:
        meta.add_text("sdv_placeholder", "1"); meta.add_text("sdv_spec", "tilesheet")
    im.save(out, pnginfo=meta)
    print(f"wrote {out}" + (f" (placeholder pieces: {', '.join(missing)})" if missing else " (all generated art)"))


# ---------------------------------------------------------------- TMX writer
def tmx(w: int, h: int, layers: dict[str, list[list[int]]], props: dict[str, str] | None = None,
        tile_props: dict[str, dict[tuple[int, int], dict[str, str]]] | None = None) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<map version="1.10" tiledversion="1.10.2" orientation="orthogonal" renderorder="right-down" '
        f'width="{w}" height="{h}" tilewidth="{T}" tileheight="{T}" infinite="0" nextlayerid="10" nextobjectid="100">',
    ]
    if props:
        out.append(" <properties>")
        for k, v in props.items():
            out.append(f'  <property name="{k}" value="{xml(v)}"/>')
        out.append(" </properties>")
    out.append(f' <tileset firstgid="1" name="{SHEET_NAME}" tilewidth="{T}" tileheight="{T}" tilecount="{COLS * ROWS}" columns="{COLS}">')
    out.append(f'  <image source="{SHEET_NAME}.png" width="{COLS * T}" height="{ROWS * T}"/>')
    out.append(" </tileset>")
    lid, oid = 1, 1
    for name in ("Back", "Buildings", "Paths", "Front", "AlwaysFront"):
        grid = layers.get(name) or [[EMPTY] * w for _ in range(h)]
        csv = ",\n".join(",".join(str(t + 1 if t >= 0 else 0) for t in row) for row in grid)
        out.append(f' <layer id="{lid}" name="{name}" width="{w}" height="{h}">')
        out.append(f'  <data encoding="csv">\n{csv}\n</data>')
        out.append(" </layer>")
        lid += 1
    for layer, tiles in (tile_props or {}).items():
        out.append(f' <objectgroup id="{lid}" name="{layer}">')
        for (x, y), p in tiles.items():
            out.append(f'  <object id="{oid}" name="TileData" x="{x * T}" y="{y * T}" width="{T}" height="{T}">')
            out.append("   <properties>")
            for k, v in p.items():
                out.append(f'    <property name="{k}" value="{xml(v)}"/>')
            out.append("   </properties>")
            out.append("  </object>")
            oid += 1
        out.append(" </objectgroup>")
        lid += 1
    out.append("</map>")
    return "\n".join(out) + "\n"


def xml(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def grid(w, h, v=EMPTY):
    return [[v] * w for _ in range(h)]


def blit(g, x, y, block):
    for r, row in enumerate(block):
        for c, t in enumerate(row):
            g[y + r][x + c] = t


# ---------------------------------------------------------------- maps
def interior():
    w, h = 13, 11
    back, bld, front = grid(w, h, FLOOR), grid(w, h), grid(w, h)
    for y in range(h):
        for x in range(w):
            if (x + y) % 5 == 0:
                back[y][x] = FLOOR2
    for x in range(w):
        bld[0][x] = WALL_CAP
        bld[1][x] = WALL
        bld[2][x] = WALL
    bld[1][4] = bld[1][8] = WINDOW
    for y in range(3, h):
        bld[y][0] = bld[y][w - 1] = SIDE_WALL
    blit(bld, 1, 1, BOARD)                      # star-chart board on the wall
    bld[3][10], bld[3][11] = DESK_L, DESK_R     # journal desk
    blit(front, 5, 2, [SCOPE[0], SCOPE[1]])     # telescope top draws over the player
    for x in range(5, 8):
        bld[4][x] = SCOPE[2][x - 5]             # telescope base blocks movement
    for y in range(6, 9):
        for x in range(4, 9):
            back[y][x] = RUG
    back[10][6] = MAT

    # Tile actions (board, desk, telescope) and the warp back to Backwoods are added by the [CP] pack
    # (data/locations.json MapTiles / MapProperties), per the skill's rule that tile properties live in patches.
    return tmx(w, h, {"Back": back, "Buildings": bld, "Front": front}, props={"Light": "6 8 4"})


def roof():
    w, h = 13, 9
    back, bld = grid(w, h, SKY), grid(w, h)
    for y in range(h):
        for x in range(w):
            if (x * 7 + y * 3) % 5 == 0:
                back[y][x] = SKY_STARS
    for y in range(3, h):
        for x in range(1, w - 1):
            back[y][x] = DECK
    for x in range(w):
        bld[2][x] = RAIL
        bld[0][x] = bld[1][x] = SKY  # keep the sky rows impassable
    for y in range(3, h):
        bld[y][0] = bld[y][w - 1] = RAIL
    # exit one tile below the bottom edge, back into the observatory (the finale event normally moves the player itself)
    return tmx(w, h, {"Back": back, "Buildings": bld}, props={"Outdoors": "T", "Warp": f"6 {h} {OBS}_Observatory 6 9"})


def exterior():
    w, h = 5, 6
    bld, front = grid(w, h), grid(w, h)
    for r in range(h):
        for c in range(w):
            (front if r < 2 else bld)[r][c] = DOME[r][c]
    # Back layer left empty on purpose: this is an Overlay patch, so the Backwoods ground shows through.
    # The door action at (2,5) is added by the [CP] pack as a MapTiles patch on Maps/Backwoods.
    return tmx(w, h, {"Buildings": bld, "Front": front})


# ---------------------------------------------------------------- UI sheet (real art, not placeholder)
def ui_sheet():
    im = Image.new("RGBA", (48, 16), (0, 0, 0, 0))
    px = im.load()
    # 9x9 four-point star at (0,0)
    star = [
        "....#....",
        "....#....",
        "...###...",
        "..#####..",
        "#########",
        "..#####..",
        "...###...",
        "....#....",
        "....#....",
    ]
    for y, row in enumerate(star):
        for x, ch in enumerate(row):
            if ch == "#":
                core = abs(x - 4) + abs(y - 4) <= 1
                px[x, y] = (255, 255, 255, 255) if core else (220, 228, 255, 230)
    # 15x15 radial glow at (16,0)
    for y in range(15):
        for x in range(15):
            dist = math.hypot(x - 7, y - 7) / 7.5
            a = max(0.0, 1.0 - dist) ** 2
            if a > 0:
                px[16 + x, y] = (255, 255, 255, int(a * 200))
    # 16x16 reset icon at (32,0): circular arrow
    d = ImageDraw.Draw(im)
    d.arc([34, 2, 45, 13], 40, 330, fill=(90, 60, 30, 255), width=2)
    d.polygon([(44, 1), (46, 7), (40, 6)], fill=(90, 60, 30, 255))
    out = CS / "assets" / "ui.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    print(f"wrote {out}")


def main():
    write_sheet()
    for name, text in (("Observatory", interior()), ("ObservatoryRoof", roof()), ("ObservatoryExterior", exterior())):
        p = MAPS / f"{name}.tmx"
        p.write_text(text, encoding="utf-8")
        print(f"wrote {p}")
    ui_sheet()


if __name__ == "__main__":
    main()

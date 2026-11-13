"""tmx.py: map model, creation from vanilla tilesheets, edits, checks, rendering, and add.py location."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import tmx  # noqa: E402
from vanilla import Vanilla  # noqa: E402

REAL = Path.home() / ".sdv-skill" / "Content (unpacked)"

MINI_TMX = '''<?xml version="1.0"?>
<map version="1.4" tiledversion="1.4.2" orientation="orthogonal" renderorder="right-down" compressionlevel="0" width="4" height="3" tilewidth="16" tileheight="16" infinite="0" nextlayerid="5" nextobjectid="1">
  <properties>
    <property name="Warp" type="string" value="1 3 Town 5 6" />
  </properties>
  <tileset firstgid="1" name="mini" tilewidth="16" tileheight="16" tilecount="4" columns="2">
    <image source="mini" width="32" height="32" />
  </tileset>
  <layer id="1" name="Back" width="4" height="3" opacity="1" offsetx="0" offsety="0">
    <properties />
    <data encoding="csv">
1,1,1,1,
1,2,2,1,
1,2,2,1</data>
  </layer>
  <layer id="2" name="Buildings" width="4" height="3" opacity="1" offsetx="0" offsety="0">
    <properties />
    <data encoding="csv">
0,0,0,0,
0,3,0,0,
0,0,0,0</data>
  </layer>
  <layer id="3" name="Front" width="4" height="3" opacity="1" offsetx="0" offsety="0">
    <properties />
    <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,0,0</data>
  </layer>
</map>
'''


@pytest.fixture()
def fake(tmp_path):
    """Unpacked-content stand-in: a 2x2-tile sheet (void, floor, red, blue) and a tiny map using it."""
    root = tmp_path / "unpacked"
    (root / "Maps").mkdir(parents=True)
    sheet = Image.new("RGBA", (32, 32), (0, 0, 0, 0))                    # tile 0: void (transparent)
    for (x, y), col in {(16, 0): (200, 160, 80, 255), (0, 16): (220, 30, 30, 255), (16, 16): (30, 30, 220, 255)}.items():
        sheet.paste(Image.new("RGBA", (16, 16), col), (x, y))
    sheet.save(root / "Maps" / "mini.png")
    (root / "Maps" / "Mini.tmx").write_text(MINI_TMX, encoding="utf-8")
    (root / "Data").mkdir()
    (root / "Data" / "Locations.json").write_text(json.dumps({"Town": {}, "Farm": {}}), encoding="utf-8")
    return root


def run(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPTS / "tmx.py"), *map(str, args)], capture_output=True, text=True, cwd=cwd)


# ------------------------------------------------------------------ model
def test_parse_and_roundtrip(fake, tmp_path):
    tm = tmx.TMap.load(fake / "Maps" / "Mini.tmx")
    assert (tm.width, tm.height) == (4, 3) and tm.props["Warp"] == "1 3 Town 5 6"
    assert [t.name for t in tm.tilesets] == ["mini"] and tm.tilesets[0].lastgid == 4
    assert [l.name for l in tm.layers] == ["Back", "Buildings", "Front"] and tm.layer("Back").data[5] == 2
    assert tm.warps() == [("1", "3", "Town", "5", "6")]
    out = tmp_path / "rt.tmx"
    tm.save(out)
    again = tmx.TMap.load(out)
    assert [l.data for l in again.layers] == [l.data for l in tm.layers] and again.props == tm.props
    assert again.tilesets[0].source == "mini"                       # vanilla-style: no extension


def test_infinite_and_non_csv_maps_are_refused(tmp_path):
    p = tmp_path / "x.tmx"
    p.write_text(MINI_TMX.replace('infinite="0"', 'infinite="1"'), encoding="utf-8")
    with pytest.raises(SystemExit, match="infinite"):
        tmx.TMap.load(p)
    p.write_text(MINI_TMX.replace('encoding="csv"', 'encoding="base64"'), encoding="utf-8")
    with pytest.raises(SystemExit, match="CSV"):
        tmx.TMap.load(p)


# ------------------------------------------------------------------ creation
def test_new_like_uses_a_real_floor_not_the_void_tile(fake, tmp_path):
    # in Mini the commonest Back tile is gid 1 (void); the floor must be gid 2
    out = tmp_path / "new.tmx"
    r = run("--root", fake, "new", out, "--size", "5x4", "--like", "Mini")
    assert r.returncode == 0, r.stdout + r.stderr
    tm = tmx.TMap.load(out)
    assert set(tm.layer("Back").data) == {2} and len(tm.layer("Back").data) == 20
    assert [t.source for t in tm.tilesets] == ["mini"]
    assert all(set(tm.layer(n).data) == {0} for n in ("Buildings", "Front", "AlwaysFront"))


def test_empty_patch_stub_and_overwrite_protection(fake, tmp_path):
    out = tmp_path / "stub.tmx"
    assert run("--root", fake, "new", out, "--size", "2x2", "--like", "Mini", "--empty").returncode == 0
    assert set(tmx.TMap.load(out).layer("Back").data) == {0}
    assert run("--root", fake, "new", out, "--size", "2x2", "--like", "Mini").returncode != 0          # exists
    assert run("--root", fake, "new", out, "--size", "2x2", "--like", "Mini", "--force").returncode == 0
    assert run("--root", fake, "new", tmp_path / "n.tmx", "--size", "2x2", "--like", "NoSuchMap").returncode != 0


# ------------------------------------------------------------------ edits
def test_edit_commands(fake, tmp_path):
    p = tmp_path / "m.tmx"
    p.write_text(MINI_TMX, encoding="utf-8")
    assert run("set-prop", p, "--map", "Music=Cowboy_Overworld", "--map", "Outdoors=T").returncode == 0
    assert run("add-warp", p, "--from", "2,3", "--to", "Farm", "64", "15").returncode == 0
    assert run("set-tile", p, "--layer", "Buildings", "--at", "0,0", "--to", "1,1", "--gid", "4").returncode == 0
    tm = tmx.TMap.load(p)
    assert tm.props["Music"] == "Cowboy_Overworld" and tm.props["Warp"] == "1 3 Town 5 6 2 3 Farm 64 15"
    b = tm.layer("Buildings").data
    assert [b[0], b[1], b[4], b[5]] == [4, 4, 4, 4] and b[2] == 0
    assert run("set-tile", p, "--layer", "Buildings", "--at", "9,9", "--gid", "1").returncode != 0      # outside
    assert run("set-tile", p, "--layer", "Nope", "--at", "0,0", "--gid", "1").returncode != 0


# ------------------------------------------------------------------ check
def check(fake, tmp_path, text, *extra):
    p = tmp_path / "c.tmx"
    p.write_text(text, encoding="utf-8")
    r = run("--root", fake, "check", p, *extra)
    return r.returncode, r.stdout


def test_check_passes_a_good_map_and_names_problems_in_bad_ones(fake, tmp_path):
    code, out = check(fake, tmp_path, MINI_TMX)
    assert code == 0 and "0 error(s)" in out
    assert check(fake, tmp_path, MINI_TMX.replace('name="Front"', 'name="Nope"'))[0] == 1
    code, out = check(fake, tmp_path, MINI_TMX.replace("0,3,0,0", "0,9,0,0"))
    assert code == 1 and "beyond the last tilesheet" in out
    code, out = check(fake, tmp_path, MINI_TMX.replace('value="1 3 Town 5 6"', 'value="1 3 Town 5"'))
    assert code == 1 and "groups" in out
    code, out = check(fake, tmp_path, MINI_TMX.replace('value="1 3 Town 5 6"', 'value="1 3 Atlantis 5 6"'))
    assert "Atlantis" in out and "not a known location" in out
    assert "outside the map" in check(fake, tmp_path, MINI_TMX.replace('value="1 3 Town 5 6"', 'value="9 9 Town 5 6"'))[1]
    code, out = check(fake, tmp_path, MINI_TMX.replace('source="mini"', 'source="gone"'))
    assert code == 1 and "tilesheet image 'gone' not found" in out


def test_check_knows_locations_the_pack_adds(fake, tmp_path):
    subprocess.run([sys.executable, str(SCRIPTS / "new_mod.py"), "--type", "cp", "--name", "L", "--author", "T", "--out", str(tmp_path)], check=True, capture_output=True)
    mod = tmp_path / "[CP] L"
    (mod / "content.json").write_text(json.dumps({"Format": "2.9.0", "Changes": [
        {"Action": "EditData", "Target": "Data/Locations", "Entries": {"{{ModId}}_Hall": {"DisplayName": "Hall"}}}]}), encoding="utf-8")
    code, out = check(fake, tmp_path, MINI_TMX.replace('value="1 3 Town 5 6"', 'value="1 3 T.L_Hall 1 1"'), "--mod", mod)
    assert "not a known location" not in out


# ------------------------------------------------------------------ render
def test_render_draws_layers_in_order_with_real_tile_pixels(fake, tmp_path):
    p = tmp_path / "m.tmx"
    p.write_text(MINI_TMX, encoding="utf-8")
    out = tmp_path / "m.png"
    assert run("--root", fake, "render", p, "--out", out, "--scale", "2").returncode == 0
    im = Image.open(out).convert("RGBA")
    assert im.size == (4 * 16 * 2, 3 * 16 * 2)
    assert im.getpixel((2, 2))[:3] == (24, 24, 32)                  # gid 1 is the void tile: nothing drawn, background shows
    assert im.getpixel((16 * 2 + 4, 16 * 2 + 4))[:3] == (220, 30, 30)   # Buildings gid 3 (sheet index 2, red) is drawn over the floor
    assert im.getpixel((16 * 2 * 2 + 4, 16 * 2 + 4))[:3] == (200, 160, 80)   # a floor tile (gid 2)


def test_render_flips_follow_the_gid_flags(fake, tmp_path):
    flipped = MINI_TMX.replace("0,3,0,0", f"0,{3 | tmx.FLIP_H},0,0")
    p = tmp_path / "f.tmx"
    p.write_text(flipped, encoding="utf-8")
    tm = tmx.TMap.load(p)
    assert tm.layer("Buildings").data[5] & tmx.FLIP_H
    im = tmx.render(tm, p, Vanilla(fake), 1)
    assert im.getpixel((16 + 3, 16 + 3))[:3] == (220, 30, 30)


# ------------------------------------------------------------------ real game maps
@pytest.mark.skipif(not REAL.exists(), reason="needs the unpacked game content")
def test_real_farmhouse_parses_checks_and_renders(tmp_path):
    p = REAL / "Maps" / "FarmHouse.tmx"
    tm = tmx.TMap.load(p)
    assert (tm.width, tm.height) == (12, 12) and tm.layer("Back").used() == 144 and tm.warps() == [("3", "12", "Farm", "64", "15")]
    r = run("check", p)
    assert r.returncode == 0, r.stdout
    out = tmp_path / "fh.png"
    assert run("render", p, "--out", out, "--scale", "1").returncode == 0
    assert Image.open(out).size == (192, 192)


@pytest.mark.skipif(not REAL.exists(), reason="needs the unpacked game content")
def test_every_vanilla_map_parses():
    """The reader handles all 190 maps the game ships (CSV layers, tilesheets, properties)."""
    bad = []
    for p in sorted((REAL / "Maps").glob("*.tmx")):
        try:
            tm = tmx.TMap.load(p)
            assert tm.layers and tm.tilesets
        except BaseException as ex:       # noqa: BLE001
            bad.append(f"{p.name}: {ex}")
    assert not bad, bad[:5]


# ------------------------------------------------------------------ add.py location
def test_add_location_writes_map_patches_and_return_warp(fake, tmp_path):
    work = tmp_path / "w"
    subprocess.run([sys.executable, str(SCRIPTS / "new_mod.py"), "--type", "cp", "--name", "Loc", "--author", "T", "--out", str(work)], check=True, capture_output=True)
    mod = work / "[CP] Loc"
    r = subprocess.run([sys.executable, str(SCRIPTS / "add.py"), "location", "--mod", str(mod), "--name", "Cottage", "--door", "60 70", "--like", "Mini",
                        "--size", "6x5", "--root", str(fake)], cwd=work, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    ch = json.loads((mod / "data" / "Locations" / "Cottage.json").read_text(encoding="utf-8"))["Changes"]
    assert ch[0] == {"Action": "Load", "Target": "Maps/{{ModId}}_Cottage", "FromFile": "assets/Maps/Cottage.tmx"}
    loc = ch[1]["Entries"]["{{ModId}}_Cottage"]
    assert loc["CreateOnLoad"] == {"MapPath": "Maps/{{ModId}}_Cottage", "AlwaysActive": False} and loc["DefaultArrivalTile"] == {"X": 3, "Y": 3}
    assert ch[2] == {"Action": "EditMap", "Target": "Maps/Town", "AddWarps": ["60 70 {{ModId}}_Cottage 3 3"]}
    tm = tmx.TMap.load(mod / "assets" / "Maps" / "Cottage.tmx")
    assert (tm.width, tm.height) == (6, 5) and tm.warps() == [("3", "5", "Town", "60", "71")]          # exit one tile below the last row
    assert (mod / "content.json").read_text(encoding="utf-8").count("data/Locations/Cottage.json") == 1
    v = subprocess.run([sys.executable, str(SCRIPTS / "validate_mod.py"), str(mod), "--root", str(fake)], capture_output=True, text=True)
    assert "0 error(s)" in v.stdout, v.stdout
    proj = json.loads((work / "sdv-project.json").read_text(encoding="utf-8"))
    assert proj["ids"]["T.Loc_Cottage"]["kind"] == "location"


def test_add_location_without_unpacked_content_explains(tmp_path):
    work = tmp_path / "w"
    subprocess.run([sys.executable, str(SCRIPTS / "new_mod.py"), "--type", "cp", "--name", "Loc", "--author", "T", "--out", str(work)], check=True, capture_output=True)
    r = subprocess.run([sys.executable, str(SCRIPTS / "add.py"), "location", "--mod", str(work / "[CP] Loc"), "--name", "X", "--door", "1 1", "--root", str(tmp_path / "none")],
                       cwd=work, capture_output=True, text=True)
    assert r.returncode != 0 and "not unpacked" in (r.stdout + r.stderr)


# ------------------------------------------------------------------ validator integration
def pack(tmp_path, changes, files):
    subprocess.run([sys.executable, str(SCRIPTS / "new_mod.py"), "--type", "cp", "--name", "V", "--author", "T", "--out", str(tmp_path)], check=True, capture_output=True)
    mod = tmp_path / "[CP] V"
    (mod / "content.json").write_text(json.dumps({"Format": "2.9.0", "Changes": changes}), encoding="utf-8")
    for rel, text in files.items():
        (mod / rel).parent.mkdir(parents=True, exist_ok=True)
        (mod / rel).write_text(text, encoding="utf-8")
    return mod


def test_validator_checks_shipped_maps_and_addwarps(fake, tmp_path):
    bad_map = MINI_TMX.replace("0,3,0,0", "0,77,0,0")
    mod = pack(tmp_path, [
        {"Action": "Load", "Target": "Maps/{{ModId}}_Room", "FromFile": "assets/Room.tmx"},
        {"Action": "EditData", "Target": "Data/Locations", "Entries": {"{{ModId}}_Room": {"DisplayName": "Room"}}},
        {"Action": "EditMap", "Target": "Maps/Town", "AddWarps": ["1 1 {{ModId}}_Room 2 2", "3 3 Atlantis 1 1", "4 4 Town 1"]}],
        {"assets/Room.tmx": bad_map})
    r = subprocess.run([sys.executable, str(SCRIPTS / "validate_mod.py"), str(mod), "--json", "--root", str(fake), "--mods-dir", str(tmp_path / "none")], capture_output=True, text=True)
    res = json.loads(r.stdout)
    errs = [x["message"] for x in res["results"] if x["level"] == "ERROR"]
    warns = [x["message"] for x in res["results"] if x["level"] == "WARN"]
    assert any("Room.tmx" in m and "beyond the last tilesheet" in m for m in errs)
    assert any("'4 4 Town 1' is not made of" in m for m in errs)
    assert any("'Atlantis'" in m for m in warns) and not any("T.V_Room" in m for m in warns)         # a location the pack adds is known


def test_validator_accepts_a_patch_map_fragment(fake, tmp_path):
    stub = MINI_TMX.replace('<layer id="3" name="Front"', '<layer id="3" name="Extra"')              # no Front layer: fine for an EditMap fragment
    mod = pack(tmp_path, [{"Action": "EditMap", "Target": "Maps/Town", "FromFile": "assets/stub.tmx", "ToArea": {"X": 0, "Y": 0, "Width": 4, "Height": 3}}], {"assets/stub.tmx": stub})
    r = subprocess.run([sys.executable, str(SCRIPTS / "validate_mod.py"), str(mod), "--json", "--root", str(fake), "--mods-dir", str(tmp_path / "none")], capture_output=True, text=True)
    assert not any("missing layer" in x["message"] for x in json.loads(r.stdout)["results"])

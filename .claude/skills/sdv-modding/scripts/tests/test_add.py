"""add.py generators: output is valid, matches the game's real data models, and never damages the author's files."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import cptext  # noqa: E402
import gamedata  # noqa: E402
import sdvlib  # noqa: E402

HAS_FIELDS = bool(gamedata.types())


# ------------------------------------------------------------------ cptext
CASES = {
    "empty one line": '{"Format": "2.7.0", "Changes": []}',
    "empty with comment": '{\n  "Format": "2.7.0",\n  "Changes": [\n    // { "Action": "Include", "FromFile": "data/example.json" }\n  ]\n}\n',
    "comment after last element": '{\n  "Changes": [\n    { "Action": "Load", "Target": "A", "FromFile": "a.png" } // keep me\n  ]\n}\n',
    "trailing commas": '{\n  "Changes": [\n    { "Action": "Load", "Target": "A", "FromFile": "a.png" },\n  ],\n}\n',
    "tabs": '{\n\t"Changes": [\n\t\t{ "Action": "Load", "Target": "A", "FromFile": "a.png" }\n\t]\n}\n',
    "brackets inside strings": '{\n  "Note": "see [Changes] ] here",\n  "Changes": [\n    { "Action": "Load", "Target": "A]", "FromFile": "a.png" }\n  ]\n}\n',
    "block comment": '{\n  /* "Changes": [ ] */\n  "Changes": [\n    { "Action": "Load", "Target": "A", "FromFile": "a.png" }\n  ]\n}\n',
}


@pytest.mark.parametrize("name", list(CASES))
def test_include_insert_keeps_every_original_line_and_stays_valid(name):
    src = CASES[name]
    out = cptext.add_include(src, "data/x.json")
    data = sdvlib.loads_tolerant(out)
    assert data["Changes"][-1] == {"Action": "Include", "FromFile": "data/x.json"}
    for line in ([] if name == "empty one line" else src.splitlines()):      # a one-line [] must expand to hold the new item
        if line.strip() and line.strip() not in ("]", "],", "}", "},"):
            keep = line[line.index("//"):] if "//" in line and not line.strip().startswith("//") else line.rstrip(",")   # a comma may be inserted before a trailing comment
            assert keep in out, f"original line lost: {line!r}"        # comments and layout survive
    assert cptext.add_include(out, "data/x.json") == out                           # idempotent


def test_i18n_insert_preserves_comments_and_escapes():
    out = cptext.insert_in_object('{\n  // names\n  "a.name": "A",\n  "b": "B" // x\n}\n', {"c.name": 'C "quoted"'})
    assert "// names" in out and "// x" in out
    assert sdvlib.loads_tolerant(out) == {"a.name": "A", "b": "B", "c.name": 'C "quoted"'}
    assert sdvlib.loads_tolerant(cptext.insert_in_object("{}", {"k": "v"})) == {"k": "v"}


# ------------------------------------------------------------------ the generators
@pytest.fixture()
def rig(tmp_path):
    root = tmp_path / "proj"
    subprocess.run([sys.executable, str(SCRIPTS / "new_mod.py"), "--type", "cp", "--name", "Mine", "--author", "T", "--out", str(root)], check=True, capture_output=True)
    mod = root / "[CP] Mine"
    (mod / "content.json").write_text('{\n  // my pack\n  "Format": "2.9.0",\n  "Changes": [\n    // existing patches go here\n  ]\n}\n', encoding="utf-8")
    (mod / "i18n" / "default.json").write_text('{\n  // text\n  "hello": "Hello"\n}\n', encoding="utf-8")
    return root, mod


def add(rig, *args, ok=True):
    root, mod = rig
    p = subprocess.run([sys.executable, str(SCRIPTS / "add.py"), *args, *(["--mod", str(mod)] if args[0] not in ("portrait-set",) and "--mod" not in args else [])],
                       cwd=root, capture_output=True, text=True)
    if ok:
        assert p.returncode == 0, p.stdout + p.stderr
    return p


def data_changes(mod: Path):
    out = []
    for f in sorted((mod / "data").rglob("*.json")):
        out += json.loads(f.read_text(encoding="utf-8"))["Changes"]
    return out


def assert_models_ok(mod: Path):
    """Every EditData entry a generator wrote only uses fields the game's own model for that asset has."""
    if not HAS_FIELDS:
        return
    for ch in data_changes(mod):
        model = gamedata.TARGET_MODEL.get(ch.get("Target", ""))
        if ch.get("Action") == "EditData" and model and "TargetField" not in ch:
            for k, v in ch["Entries"].items():
                assert gamedata.check_entry(v, model) == [], (ch["Target"], k)
        if ch.get("Action") == "EditData" and ch.get("Target") == "Data/Shops" and ch.get("TargetField"):
            for v in ch["Entries"].values():
                assert gamedata.check_entry(v, "ShopItemData") == []


def validates(mod: Path):
    r = subprocess.run([sys.executable, str(SCRIPTS / "validate_mod.py"), str(mod)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert "0 error(s)" in r.stdout


def test_item_writes_everything_and_leaves_the_authors_files_alone(rig):
    root, mod = rig
    before = (mod / "content.json").read_text(encoding="utf-8")
    add(rig, "item", "--name", "Moonberry Jam", "--price", "220", "--category", "-26", "--edibility", "30")
    # data file: golden shape
    ch = json.loads((mod / "data" / "Items" / "MoonberryJam.json").read_text(encoding="utf-8"))["Changes"]
    assert ch[0] == {"Action": "Load", "Target": "Mods/{{ModId}}/Objects/MoonberryJam", "FromFile": "assets/Objects/MoonberryJam.png"}
    assert ch[1]["Entries"]["{{ModId}}_MoonberryJam"] == {
        "Name": "{{ModId}}_MoonberryJam", "DisplayName": "{{i18n:moonberry-jam.name}}", "Description": "{{i18n:moonberry-jam.description}}",
        "Type": "Basic", "Category": -26, "Price": 220, "Texture": "Mods/{{ModId}}/Objects/MoonberryJam", "SpriteIndex": 0, "Edibility": 30}
    # the author's content.json: every original line kept, one Include added
    after = (mod / "content.json").read_text(encoding="utf-8")
    for line in before.splitlines():
        if line.strip() not in ("]", "}"):
            assert line in after
    assert after.count('"FromFile": "data/Items/MoonberryJam.json"') == 1
    assert "// text" in (mod / "i18n" / "default.json").read_text(encoding="utf-8")
    assert json.loads((mod / "i18n" / "default.json").read_text(encoding="utf-8").replace("// text", ""))["moonberry-jam.name"] == "Moonberry Jam"
    assert Image.open(mod / "assets" / "Objects" / "MoonberryJam.png").size == (16, 16)
    proj = json.loads((root / "sdv-project.json").read_text(encoding="utf-8"))
    assert proj["ids"]["T.Mine_MoonberryJam"]["kind"] == "object"
    assert any(a["files"] == ["[CP] Mine/assets/Objects/MoonberryJam.png"] for a in proj["assets"])
    assert list((root / "backups").rglob("content.json")) and list((root / "backups").rglob("default.json"))
    assert_models_ok(mod)
    validates(mod)


def test_every_generator_validates_and_uses_real_game_fields(rig):
    root, mod = rig
    add(rig, "item", "--name", "Moonberry Jam", "--price", "220")
    add(rig, "item", "--name", "Plain Cloth")
    add(rig, "big-craftable", "--name", "Jam Press")
    add(rig, "machine", "--craftable", "Jam Press", "--input", "(O)613", "--output", "Moonberry Jam", "--minutes", "600")
    add(rig, "crop", "--name", "Moonberry", "--seasons", "spring,summer", "--days", "1,2,2,3", "--regrow", "3", "--shop", "SeedShop", "--seed-price", "40")
    add(rig, "fruit-tree", "--name", "Plum", "--season", "summer")
    add(rig, "recipe", "--kind", "cooking", "--name", "Moonberry Pie", "--ingredients", "613 3 245 1", "--yield", "Moonberry Jam")
    add(rig, "recipe", "--kind", "crafting", "--name", "Jam Press Recipe", "--ingredients", "388 50", "--yield", "Jam Press", "--big-craftable")
    add(rig, "shop-item", "--shop", "Carpenter", "--item", "Plain Cloth", "--price", "50", "--condition", "SEASON spring")
    add(rig, "shop", "--name", "Island Store", "--items", "Moonberry Jam:300,(O)388:20")
    add(rig, "mail", "--name", "Welcome", "--text", "Hello farmer!", "--item", "72 1")
    add(rig, "npc", "--name", "Mira", "--home", "Town 52 70 2", "--birthday", "fall 12", "--subject", "1girl, teal hair")
    add(rig, "event", "--name", "MiraIntro", "--location", "Town", "--npc", "Mira")
    assert_models_ok(mod)
    validates(mod)
    ch = data_changes(mod)
    machine = next(c for c in ch if c.get("Target") == "Data/Machines")
    assert list(machine["Entries"]) == ["(BC){{ModId}}_JamPress"]
    assert machine["Entries"]["(BC){{ModId}}_JamPress"]["OutputRules"][0]["OutputItem"][0]["ItemId"] == "(O){{ModId}}_MoonberryJam"
    crop = next(c for c in ch if c.get("Target") == "Data/Crops")["Entries"]["{{ModId}}_MoonberrySeeds"]
    assert crop["Seasons"] == ["Spring", "Summer"] and crop["DaysInPhase"] == [1, 2, 2, 3] and crop["HarvestItemId"] == "(O){{ModId}}_Moonberry"
    cooking = next(c for c in ch if c.get("Target") == "Data/CookingRecipes")["Entries"]["{{ModId}}_MoonberryPie"]
    assert cooking == "613 3 245 1/10 10/{{ModId}}_MoonberryJam/default/{{i18n:moonberry-pie.name}}"
    npc = next(c for c in ch if c.get("Target") == "Data/Characters")["Entries"]["{{ModId}}_Mira"]
    assert npc["Home"][0] == {"Id": "Default", "Location": "Town", "Tile": {"X": 52, "Y": 70}, "Direction": "down"}
    assert npc["BirthSeason"] == "Fall" and npc["BirthDay"] == 12
    assert Image.open(mod / "assets" / "Portraits" / "Mira.png").size == (128, 192)
    assert Image.open(mod / "assets" / "Characters" / "Mira.png").size == (64, 128)
    assert Image.open(mod / "assets" / "Crops" / "Moonberry.png").size == (128, 32)
    assert Image.open(mod / "assets" / "FruitTrees" / "Plum.png").size == (432, 80)
    proj = json.loads((root / "sdv-project.json").read_text(encoding="utf-8"))
    assert "T.Mine_Mira" in proj["characters"] and proj["characters"]["T.Mine_Mira"]["subject"] == "1girl, teal hair"
    assert {proj["ids"][i]["kind"] for i in ("T.Mine_Mira", "T.Mine_MoonberrySeeds", "T.Mine_JamPress")} == {"npc", "object", "big_craftable"}


def test_existing_id_is_refused_unless_forced(rig):
    root, mod = rig
    add(rig, "item", "--name", "Gem")
    p = add(rig, "item", "--name", "Gem", ok=False)
    assert p.returncode != 0 and "already exists" in (p.stdout + p.stderr)
    assert (mod / "content.json").read_text(encoding="utf-8").count("data/Items/Gem.json") == 1


def test_dry_run_changes_nothing(rig):
    root, mod = rig
    snap = {p: p.read_bytes() for p in mod.rglob("*") if p.is_file()}
    p = add(rig, "npc", "--name", "Mira", "--dry-run")
    assert "[dry-run] write data/Characters/Mira.json" in p.stdout
    assert {q: q.read_bytes() for q in mod.rglob("*") if q.is_file()} == snap
    assert not (root / "sdv-project.json").exists()


def test_real_art_is_never_overwritten(rig):
    root, mod = rig
    (mod / "assets" / "Objects").mkdir(parents=True)
    Image.new("RGBA", (16, 16), (7, 7, 7, 255)).save(mod / "assets" / "Objects" / "Gem.png")      # real art (no placeholder tag)
    add(rig, "item", "--name", "Gem")
    assert Image.open(mod / "assets" / "Objects" / "Gem.png").getpixel((0, 0)) == (7, 7, 7, 255)


def test_sid_sprite_inserts_into_existing_pack_without_reformatting(tmp_path):
    out = tmp_path / "work"
    subprocess.run([sys.executable, str(SCRIPTS / "new_mod.py"), "--type", "sid", "--name", "Mira SID", "--author", "T", "--out", str(out)], check=True, capture_output=True)
    mod = out / "[SID] Mira SID"
    before = (mod / "content.json").read_text(encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "add.py"), "sid-sprite", "--mod", str(mod), "--npc", "Characters/T.Mira", "--scale", "8"], cwd=out, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    after = (mod / "content.json").read_text(encoding="utf-8")
    assert "// WidthScale/HeightScale" in after and after.startswith(before.split("\"Sprites\"")[0])
    entry = sdvlib.loads_tolerant(after)["Sprites"][0]
    assert entry["Target"] == "Characters/T.Mira" and entry["WidthScale"] == 8
    assert Image.open(mod / "assets" / "Mira_hd.png").size == (512, 1024)
    v = subprocess.run([sys.executable, str(SCRIPTS / "validate_mod.py"), str(mod)], capture_output=True, text=True)
    assert "0 error(s)" in v.stdout


def test_portrait_set_scaffold(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPTS / "add.py"), "portrait-set", "--out", str(tmp_path), "--name", "HD Faces", "--npcs", "Abigail,Leo", "--frame", "256", "--author", "T"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    pack = tmp_path / "[Portraiture] HD Faces"
    assert Image.open(pack / "Abigail.png").size == (512, 768) and (pack / "Leo.png").exists()
    v = subprocess.run([sys.executable, str(SCRIPTS / "validate_mod.py"), str(pack)], capture_output=True, text=True)
    assert "0 error(s)" in v.stdout


@pytest.mark.skipif(not HAS_FIELDS, reason="needs assets/gamedata_fields.json")
def test_game_model_checker_catches_typos_and_nested_errors():
    assert gamedata.check_entry({"Name": "x", "Prize": 3}, "ObjectData") == ["Prize"]
    assert gamedata.check_entry({"Items": [{"Id": "a", "ItemId": "b", "Cost": 2}], "Owners": [{"Name": "x", "Id": "d"}]}, "ShopData") == ["Items[0].Cost"]
    assert gamedata.check_entry({"Home": [{"Id": "Default", "Location": "Town", "Tile": {"X": 1, "Y": 2}, "Direction": "down", "Facing": 2}]}, "CharacterData") == ["Home[0].Facing"]

"""Validator v2 (vcheck.py): each deep check has a failing and a passing case; vanilla.py against a fake unpacked game."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import sdvlib  # noqa: E402

REAL_CACHE = Path.home() / ".sdv-skill" / "Content (unpacked)"


@pytest.fixture()
def fake(tmp_path):
    """A tiny stand-in for 'Content (unpacked)'."""
    root = tmp_path / "unpacked"
    for rel, size in (("Maps/springobjects.png", (384, 624)), ("TileSheets/crops.png", (256, 1024)), ("Portraits/Abigail.png", (128, 320))):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", size).save(root / rel)
    (root / "Data").mkdir(parents=True, exist_ok=True)
    (root / "Data" / "Objects.json").write_text(json.dumps({"72": {"Name": "Diamond"}, "245": {"Name": "Sugar"}}), encoding="utf-8")
    (root / "Data" / "Locations.json").write_text(json.dumps({"Town": {}, "Farm": {}}), encoding="utf-8")
    return root


def make_mod(tmp_path, changes, *, extra_files=None, manifest=None, content=None):
    d = tmp_path / "[CP] T"
    d.mkdir()
    man = {"Name": "T", "Author": "A", "Version": "1.0.0", "UniqueID": "A.T", "ContentPackFor": {"UniqueID": "Pathoschild.ContentPatcher"}, **(manifest or {})}
    (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    (d / "content.json").write_text(json.dumps({"Format": "2.9.0", "Changes": changes, **(content or {})}), encoding="utf-8")
    (d / "i18n").mkdir()
    (d / "i18n" / "default.json").write_text("{}", encoding="utf-8")
    for rel, data in (extra_files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, Image.Image):
            data.save(p)
        else:
            p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return d


def validate(mod, fake_root=None, *extra, cwd=None):
    args = [sys.executable, str(SCRIPTS / "validate_mod.py"), str(mod), "--json", "--mods-dir", str(mod.parent / "no-mods"), *extra]
    if fake_root:
        args += ["--root", str(fake_root)]
    p = subprocess.run(args, capture_output=True, text=True, cwd=cwd or mod.parent)
    return json.loads(p.stdout), p.returncode


def msgs(res, level):
    return [r["message"] for r in res["results"] if r["level"] == level]


def has(res, level, text):
    return any(text in m for m in msgs(res, level))


def objects(entries, tgt="Data/Objects"):
    return {"Action": "EditData", "Target": tgt, "Entries": entries}


# ------------------------------------------------------------------ model fields
def test_unknown_field_is_flagged_even_when_nested(tmp_path, fake):
    mod = make_mod(tmp_path, [objects({"{{ModId}}_A": {"Name": "A", "Prize": 3, "Buffs": [{"Id": "x", "Dur": 1}]}}),
                              {"Action": "EditData", "Target": "Data/Crops", "Entries": {"{{ModId}}_Seeds": {"DaysInEachPhase": [1, 2]}}}])
    res, _ = validate(mod, fake)
    assert has(res, "WARN", "not fields of ObjectData: Prize, Buffs[0].Dur")
    assert has(res, "WARN", "not fields of CropData: DaysInEachPhase")


def test_real_fields_pass(tmp_path, fake):
    mod = make_mod(tmp_path, [{"Action": "EditData", "Target": "Data/Crops", "Entries": {"{{ModId}}_Seeds": {"DaysInPhase": [1, 2], "Seasons": ["Spring"]}}}])
    res, _ = validate(mod, fake)
    assert not has(res, "WARN", "not fields of")


# ------------------------------------------------------------------ textures
def test_texture_nobody_loads_is_flagged_and_loaded_or_vanilla_is_not(tmp_path, fake):
    mod = make_mod(tmp_path, [
        {"Action": "Load", "Target": "Mods/{{ModId}}/Objects", "FromFile": "assets/o.png"},
        objects({"{{ModId}}_Good": {"Name": "g", "Texture": "Mods/{{ModId}}/Objects", "SpriteIndex": 0},
                 "{{ModId}}_Vanilla": {"Name": "v", "Texture": "Maps/springobjects", "SpriteIndex": 5},
                 "{{ModId}}_Bad": {"Name": "b", "Texture": "Mods/{{ModId}}/Nope", "SpriteIndex": 0}})],
        extra_files={"assets/o.png": Image.new("RGBA", (32, 32))})
    res, _ = validate(mod, fake)
    assert has(res, "WARN", "Texture 'Mods/A.T/Nope'")
    assert not has(res, "WARN", "A.T_Good") and not has(res, "WARN", "springobjects")


def test_sprite_index_outside_the_sheet_is_an_error(tmp_path, fake):
    mod = make_mod(tmp_path, [
        {"Action": "Load", "Target": "Mods/{{ModId}}/Objects", "FromFile": "assets/o.png"},
        objects({"{{ModId}}_Ok": {"Name": "ok", "Texture": "Mods/{{ModId}}/Objects", "SpriteIndex": 3},
                 "{{ModId}}_Far": {"Name": "far", "Texture": "Mods/{{ModId}}/Objects", "SpriteIndex": 4},
                 "{{ModId}}_VanillaFar": {"Name": "vf", "SpriteIndex": 99999}})],
        extra_files={"assets/o.png": Image.new("RGBA", (32, 32))})       # 2x2 cells of 16x16 -> indices 0-3
    res, code = validate(mod, fake)
    errs = msgs(res, "ERROR")
    assert any("A.T_Far" in m and "outside the sheet" in m for m in errs)
    assert any("A.T_VanillaFar" in m for m in errs)
    assert not any("A.T_Ok" in m for m in errs)
    assert code == 1


# ------------------------------------------------------------------ NPCs
def npc_changes(parts=("sprite", "portrait", "dialogue", "gift")):
    ch = [{"Action": "EditData", "Target": "Data/Characters", "Entries": {"{{ModId}}_Mira": {
        "DisplayName": "Mira", "Home": [{"Id": "Default", "Location": "Nowhere", "Tile": {"X": 1, "Y": 2}}]}}}]
    if "sprite" in parts:
        ch.append({"Action": "Load", "Target": "Characters/{{ModId}}_Mira", "FromFile": "assets/m.png"})
    if "portrait" in parts:
        ch.append({"Action": "Load", "Target": "Portraits/{{ModId}}_Mira", "FromFile": "assets/p.png"})
    if "dialogue" in parts:
        ch.append({"Action": "EditData", "Target": "Characters/Dialogue/{{ModId}}_Mira", "Entries": {"Mon": "Hi$5", "Tue": "Hi$1"}})
    if "gift" in parts:
        ch.append({"Action": "EditData", "Target": "Data/NPCGiftTastes", "Entries": {"{{ModId}}_Mira": "a/72/b/395/c/330/d/168/e//"}})
    return ch


NPC_FILES = {"assets/m.png": Image.new("RGBA", (64, 128)), "assets/p.png": Image.new("RGBA", (128, 128))}   # portrait sheet = 4 frames


def test_incomplete_npc_is_an_error_and_complete_one_is_not(tmp_path, fake):
    bad = make_mod(tmp_path, npc_changes(("sprite",)), extra_files=NPC_FILES)
    res, code = validate(bad, fake)
    err = " ".join(msgs(res, "ERROR"))
    assert "portrait sheet" in err and "dialogue" in err and code == 1
    assert has(res, "WARN", "no Data/NPCGiftTastes entry")


def test_complete_npc_passes_and_checks_home_and_portrait_index(tmp_path, fake):
    mod = make_mod(tmp_path, npc_changes(), extra_files=NPC_FILES)
    res, code = validate(mod, fake)
    assert not msgs(res, "ERROR") and code == 0
    assert has(res, "WARN", "Home location 'Nowhere'")                              # vanilla (fake) knows only Town and Farm
    assert has(res, "WARN", "portrait $5 but the portrait sheet only has 4 frames")  # 128x128 sheet = 2 rows x 2 cols
    assert not has(res, "WARN", "portrait $1")


# ------------------------------------------------------------------ references
def test_own_item_reference_must_exist_but_flags_and_ids_are_not_items(tmp_path, fake):
    mod = make_mod(tmp_path, [
        objects({"{{ModId}}_Gem": {"Name": "gem"}}),
        {"Action": "EditData", "Target": "Data/Shops", "TargetField": ["SeedShop", "Items"],
         "Entries": {"{{ModId}}_S1": {"Id": "{{ModId}}_S1", "ItemId": "(O){{ModId}}_Gem"}, "{{ModId}}_S2": {"Id": "{{ModId}}_S2", "ItemId": "(O){{ModId}}_Ghost"}}},
        {"Action": "EditData", "Target": "Data/TriggerActions", "Entries": {"{{ModId}}_T": {"Id": "{{ModId}}_T", "Trigger": "DayStarted", "Actions": ["AddMail Current {{ModId}}_SomeFlag"]}}}])
    res, _ = validate(mod, fake)
    errs = msgs(res, "ERROR")
    assert any("A.T_Ghost" in m for m in errs)
    assert not any("A.T_Gem" in m or "SomeFlag" in m for m in errs)               # existing items and mail flags are fine


def test_missing_vanilla_item_id_is_a_warning(tmp_path, fake):
    mod = make_mod(tmp_path, [{"Action": "EditData", "Target": "Data/CookingRecipes",
                               "Entries": {"{{ModId}}_Pie": "245 1 999999 2/10 10/245/default/Pie"}}])
    res, _ = validate(mod, fake)
    assert has(res, "WARN", "item id 999999") and not has(res, "WARN", "item id 245")


def test_no_unpacked_content_is_reported_not_guessed(tmp_path):
    mod = make_mod(tmp_path, [objects({"{{ModId}}_X": {"Name": "x", "Texture": "Maps/whatever"}})])
    res, _ = validate(mod, tmp_path / "does-not-exist")
    assert has(res, "INFO", "not unpacked")


# ------------------------------------------------------------------ dependencies, tokens, text
def test_dependencies_declared_installed_and_used(tmp_path, fake):
    mod = make_mod(tmp_path, [{"Action": "EditData", "Target": "Data/Objects", "When": {"Other.Mod/Flag": "true"}, "Entries": {"{{ModId}}_X": {"Name": "x"}}},
                              {"Action": "EditImage", "Target": "Mods/Third.Mod/Thing", "FromFile": "assets/o.png"}],
                    manifest={"Dependencies": [{"UniqueID": "Needed.Mod"}]}, extra_files={"assets/o.png": Image.new("RGBA", (16, 16))})
    res, _ = validate(mod, fake)
    assert has(res, "WARN", "required dependency 'Needed.Mod' is not installed")
    assert has(res, "WARN", "'Other.Mod'") and has(res, "WARN", "'Third.Mod'")


def test_fromfile_missing_for_only_some_token_values(tmp_path, fake):
    files = {f"assets/p_{s}.png": Image.new("RGBA", (128, 192)) for s in ("spring", "summer", "fall")}    # winter forgotten
    mod = make_mod(tmp_path, [{"Action": "Load", "Target": "Portraits/Abigail", "FromFile": "assets/p_{{Season}}.png"}], extra_files=files)
    res, code = validate(mod, fake)
    assert any("1 of 4 token value(s)" in m and "p_winter.png" in m for m in msgs(res, "ERROR")) and code == 1
    ok = make_mod(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, [], extra_files={})
    assert ok.exists()


def test_config_tokens_expand_too(tmp_path, fake):
    mod = make_mod(tmp_path, [{"Action": "Load", "Target": "Portraits/Abigail", "FromFile": "assets/{{Outfit}}.png"}],
                   content={"ConfigSchema": {"Outfit": {"AllowValues": "Default, Beach", "Default": "Default"}}},
                   extra_files={"assets/Default.png": Image.new("RGBA", (128, 192))})
    res, _ = validate(mod, fake)
    assert any("Beach.png" in m for m in msgs(res, "ERROR"))


def test_schedule_event_and_duplicate_key_checks(tmp_path, fake):
    mod = make_mod(tmp_path, [
        {"Action": "EditData", "Target": "Characters/schedules/{{ModId}}_Mira", "Entries": {"good": "900 Town 10 10 2/1200 Farm 5 5 1 anim", "bad": "900 Town ten 10"}},
        {"Action": "EditData", "Target": "Data/Events/Town", "Entries": {"{{ModId}}_E1/t 600 700": "continue/64 15/pause 100", "{{ModId}}_E2/t 600 700": "continue/64 15/pause 100/end"}}])
    (mod / "data").mkdir()
    (mod / "data" / "dup.json").write_text('{"Changes": [], "Changes": []}', encoding="utf-8")
    res, _ = validate(mod, fake)
    assert has(res, "WARN", "schedule 'bad'") and not has(res, "WARN", "schedule 'good'")
    assert has(res, "WARN", "event 'A.T_E1'") or has(res, "WARN", "event '{{ModId}}_E1'")
    assert not has(res, "WARN", "E2' does not finish")


# ------------------------------------------------------------------ --fix, --json, HD portraits
def test_fix_stubs_missing_i18n_and_deletes_strays_and_is_repeatable(tmp_path, fake):
    mod = make_mod(tmp_path, [objects({"{{ModId}}_X": {"Name": "x", "DisplayName": "{{i18n:x.name}}"}})],
                   extra_files={"Thumbs.db": "junk", "assets/a_preview.png": Image.new("RGBA", (4, 4))})
    (mod / "i18n" / "default.json").write_text('{\n  // keep\n  "hello": "Hello"\n}\n', encoding="utf-8")
    res, code = validate(mod, fake)
    assert code == 1 and res["fixable"] >= 2
    res, code = validate(mod, fake, "--fix")
    assert code == 0 and any("stub key" in f for f in res["fixed"])
    text = (mod / "i18n" / "default.json").read_text(encoding="utf-8")
    assert "// keep" in text and '"x.name": "TODO: x.name"' in text
    assert not (mod / "Thumbs.db").exists() and not (mod / "assets" / "a_preview.png").exists()
    assert list((tmp_path / "backups").rglob("default.json"))                      # the original was backed up first
    res, _ = validate(mod, fake, "--fix")
    assert res["fixed"] == []


def test_hd_portrait_in_project_gets_the_hd_rule_instead_of_128(tmp_path, fake):
    mod = make_mod(tmp_path, [{"Action": "Load", "Target": "Portraits/Abigail", "FromFile": "assets/hd.png"}], extra_files={"assets/hd.png": Image.new("RGBA", (512, 768))})
    res, code = validate(mod, fake)
    assert any("128 wide" in m for m in msgs(res, "ERROR")) and code == 1            # vanilla rule applies by default
    (tmp_path / "sdv-project.json").write_text(json.dumps({"version": 1, "assets": [
        {"id": "hd", "spec": "portrait_hd", "status": "placeholder", "files": ["[CP] T/assets/hd.png"], "targets": [{"kind": "portraiture", "frame": 256}]}]}), encoding="utf-8")
    res, code = validate(mod, fake, cwd=tmp_path)
    assert not any("128 wide" in m for m in msgs(res, "ERROR")) and code == 0


def test_no_deep_switch_turns_the_cross_checks_off(tmp_path, fake):
    mod = make_mod(tmp_path, [objects({"{{ModId}}_A": {"Name": "A", "Prize": 3}})])
    res, _ = validate(mod, fake, "--no-deep")
    assert not has(res, "WARN", "not fields of")


# ------------------------------------------------------------------ vanilla.py
def vanilla(fake_root, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / "vanilla.py"), "--root", str(fake_root), *args], capture_output=True, text=True)


def test_vanilla_lookups_against_a_fake_cache(fake):
    assert "384x624" in vanilla(fake, "size", "Maps/springobjects").stdout
    assert vanilla(fake, "exists", "Maps/springobjects").returncode == 0 and vanilla(fake, "exists", "Maps/nope").returncode == 1
    assert "Diamond" in vanilla(fake, "entry", "Data/Objects", "72").stdout
    assert "245" in vanilla(fake, "keys", "Data/Objects", "--like", "sugar").stdout
    assert "Data/Objects" in vanilla(fake, "item", "(O)72").stdout and vanilla(fake, "item", "999999").returncode == 1
    assert "Maps/springobjects" in vanilla(fake, "find", "springobj").stdout
    assert "72" in vanilla(fake, "find", "diamond", "--data").stdout


def test_vanilla_without_content_says_how_to_get_it(tmp_path):
    p = vanilla(tmp_path / "nothing", "size", "Portraits/Abigail")
    assert p.returncode != 0 and "StardewXnbHack" in (p.stdout + p.stderr)


@pytest.mark.skipif(not REAL_CACHE.exists(), reason="needs the unpacked game content")
def test_every_spec_rule_holds_against_the_real_game():
    p = subprocess.run([sys.executable, str(SCRIPTS / "vanilla.py"), "specs"], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.count("[ok]") >= 9

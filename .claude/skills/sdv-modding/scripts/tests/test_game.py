"""game.py: log parsing, isolated mods folder, step building, the save-safety rule (Python mirror vs the C# one), and the whole
`test` flow against a fake game process. Nothing here starts Stardew Valley."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import game  # noqa: E402
import sdvlib  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_game.py"
HAS_DOTNET = shutil.which("dotnet") is not None

LOG = """[10:00:00 INFO  SMAPI] SMAPI 4.5.2 with Stardew Valley 1.6.15 build 24356 on Windows 10 (10.0.19045.0)
[10:00:01 DEBUG SMAPI] Loading mods...
[10:00:01 TRACE SMAPI]    Content Patcher (from Mods\\ContentPatcher\\ContentPatcher.dll, ID: Pathoschild.ContentPatcher, assembly version: 2.9.1)...
[10:00:01 TRACE SMAPI]    SDV Test Harness (from Mods\\SdvTestHarness\\SdvTestHarness.dll, ID: SdvSkill.TestHarness, assembly version: 1.0.0)...
[10:00:02 WARN  SMAPI]    Skipped mods
[10:00:02 WARN  SMAPI]    --------------------------------------------------
[10:00:02 WARN  SMAPI]       These mods could not be added to your game.
[10:00:02 WARN  SMAPI]       - Broken Pack 1.0.0 because it requires Some.Missing.Mod 2.0+ which isn't installed.
[10:00:03 ERROR Content Patcher] [Mira Pack] Patch error: My Mod > Load Portraits/Mira has a FromFile which matches non-existent file 'assets/Mira.png'.
[10:00:04 ERROR My Mod] Failed loading asset 'Mods/Aust.Test/Objects' from SMAPI/mod: System.IO.FileNotFoundException: Could not find file.
   at StardewModdingAPI.Framework.ContentManagers.ModContentManager.Load(String)
   at MyMod.ModEntry.OnAssetRequested()
[10:00:05 WARN  SMAPI] Found MSI Afterburner installed, which may conflict with SMAPI; try adding an exception for SMAPI.
[10:00:06 INFO  SdvTestHarness] [harness] world ready; running steps.
[10:00:07 INFO  SdvTestHarness] [harness] step 0 warp: ok
"""


def test_parse_log_structure_and_categories():
    rep = game.parse_log(LOG, ["Mira Pack", "My Mod", "Broken Pack"])
    assert rep["header"] == {"smapi": "4.5.2", "game": "1.6.15"}
    assert rep["mods_loaded"] == 2
    assert rep["errors"] == 2 and rep["warnings"] == 5
    assert any("Broken Pack" in s for s in rep["skipped_mods"])
    assert rep["categories"]["missing_dependency"] and rep["categories"]["patch_failure"] and rep["categories"]["asset_load"]
    assert len(rep["categories"]["exception"]) == 1                       # the real exception only, not "add an exception for"
    assert "at StardewModdingAPI" in rep["mine"]["errors"][1]["message"]    # the stack trace stays with its error
    assert rep["ok_for_mine"] is False and rep["mine"]["skipped"]
    assert rep["harness"][-1].endswith("step 0 warp: ok")
    assert list(rep["by_source"])[0] in ("Content Patcher", "My Mod")


def test_parse_log_clean_for_unrelated_mod():
    rep = game.parse_log(LOG, ["Totally Other Mod"])
    assert rep["ok_for_mine"] is True


def test_cli_log_exit_code_and_missing_file(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(LOG, encoding="utf-8")
    run = lambda *a: subprocess.run([sys.executable, str(SCRIPTS / "game.py"), *a], capture_output=True, text=True, cwd=tmp_path)
    assert run("log", "--file", str(f), "--mods", "My Mod").returncode == 1
    assert run("log", "--file", str(f), "--mods", "Nobody").returncode == 0
    assert run("log", "--file", str(tmp_path / "nope.txt")).returncode != 0
    assert json.loads(run("log", "--file", str(f), "--json").stdout)["errors"] == 2


SAVE_CASES = [("SdvTest_123456789", "SdvTest", True), ("sdvtest_1", "SdvTest", True), ("Bitter_386707078", "SdvTest", False),
              ("Hoes_403288654", "Hoes", False), ("MyTestFarm_9", "MyTest", True), ("Hoes_403288654", "Ho", False),
              ("Anything_1", "", False), ("Anything_1", "   ", False), (None, "SdvTest", False), ("", "SdvTest", False),
              ("SdvTest_1/../Bitter_386707078", "SdvTest", False), ("SdvTest_1\\..\\Bitter", "SdvTest", False),
              ("SdvTest..Bitter", "SdvTest", False), ("C:SdvTest_1", "SdvTest", False), ("MySdvTest_1", "SdvTest", False)]


@pytest.mark.parametrize("folder,prefix,expected", SAVE_CASES)
def test_save_policy_python_mirror(folder, prefix, expected):
    assert game.is_test_save(folder, prefix) is expected


@pytest.mark.skipif(not HAS_DOTNET, reason="needs dotnet")
def test_save_policy_csharp_unit_tests_pass():
    r = subprocess.run(["dotnet", "run", "-v", "q"], cwd=SCRIPTS.parent / "harness" / "tests", capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def mod(root: Path, name: str, uid: str, **man):
    d = root / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"Name": name, "Author": "T", "Version": "1.0.0", "UniqueID": uid, **man}), encoding="utf-8")
    return d


def test_isolated_mods_copies_required_dependencies_only(tmp_path):
    installed = tmp_path / "installed"
    mod(installed, "ContentPatcher", "Pathoschild.ContentPatcher")
    mod(installed, "SpaceCore", "spacechase0.SpaceCore")
    mod(installed, "GMCM", "spacechase0.GenericModConfigMenu")
    mod(installed, "ConsoleCommands", "SMAPI.ConsoleCommands")
    mod(installed, "Unrelated", "Someone.Unrelated")
    proj = mod(tmp_path / "work", "[CP] Mine", "Me.Mine", ContentPackFor={"UniqueID": "Pathoschild.ContentPatcher"},
               Dependencies=[{"UniqueID": "spacechase0.SpaceCore"}, {"UniqueID": "spacechase0.GenericModConfigMenu", "IsRequired": False},
                             {"UniqueID": "Not.Installed"}])
    dest = tmp_path / "iso"
    info = game.build_isolated([proj], [installed], dest)
    assert sorted(info["copied"]) == sorted(["[CP] Mine", "ContentPatcher", "SpaceCore", "ConsoleCommands"])
    assert info["missing_dependencies"] == ["Not.Installed"]
    assert not (dest / "Unrelated").exists() and not (dest / "GMCM").exists()      # optional and unrelated mods stay out
    assert (proj / "manifest.json").exists()                                      # the original is untouched (copied, not moved)


def test_check_to_steps_mapping():
    steps = game.check_to_steps({"name": "mira", "time": 1200, "warp": "Town 52 70", "give": ["(O)Me_Gem 2"],
                                 "commands": ["debug ebi Me_Intro", "patch summary Me.Mine"], "dialogue": "Mira", "screenshot": True})
    types = [s["type"] for s in steps]
    assert types == ["time", "warp", "give", "debug", "console", "dialogue", "wait", "screenshot"]
    assert steps[1] == {"type": "warp", "location": "Town", "x": 52, "y": 70}
    assert steps[3]["command"] == "ebi Me_Intro" and steps[4]["command"] == "patch summary Me.Mine"


# ------------------------------------------------------------------ the whole `test` flow against a fake game
@pytest.fixture()
def rig(tmp_path):
    installed = tmp_path / "installed"
    mod(installed, "ContentPatcher", "Pathoschild.ContentPatcher")
    mod(installed, "ConsoleCommands", "SMAPI.ConsoleCommands")
    work = tmp_path / "work"
    subprocess.run([sys.executable, str(SCRIPTS / "new_mod.py"), "--type", "cp", "--name", "Mine", "--author", "T", "--out", str(work)], check=True, capture_output=True)
    (work / sdvlib.CONFIG_NAME).write_text(json.dumps({"mods_path": str(installed)}), encoding="utf-8")
    (work / "sdv-project.json").write_text(json.dumps({"version": 1, "test": {"save": "SdvTest_1", "checks": [
        {"name": "look", "warp": "Town 1 2", "commands": ["patch summary T.Mine"], "screenshot": True}]}}), encoding="utf-8")
    good_log = tmp_path / "good.txt"
    good_log.write_text("[10:00:00 INFO  SMAPI] SMAPI 4.5.2 with Stardew Valley 1.6.15 build 1 on Windows\n[10:00:01 INFO  SdvTestHarness] [harness] all steps done.\n", encoding="utf-8")
    env = {**os.environ, "SDV_GAME_CMD": json.dumps([sys.executable, str(FAKE)]), "SDV_FAKE_SCREENSHOT": "1", "SDV_GAME_LOG": str(good_log)}
    return work, env, tmp_path


def run_test(rig, *extra, confirmed=True):
    work, env, _ = rig
    args = [sys.executable, str(SCRIPTS / "game.py"), "test", *(["--confirmed-by-owner"] if confirmed else []), "--mods", str(work / "[CP] Mine"), *extra]
    return subprocess.run(args, cwd=work, capture_output=True, text=True, env=env, timeout=240)


def report_of(work):
    return json.loads(next((work / "tests").glob("*/report.json")).read_text(encoding="utf-8"))


@pytest.mark.skipif(not HAS_DOTNET, reason="needs dotnet to build the harness")
def test_full_flow_pass_with_screenshot_and_console_handshake(rig):
    work, env, _ = rig
    p = run_test(rig, "--check", "look")
    assert p.returncode == 0, p.stdout + p.stderr
    rep = report_of(work)
    assert rep["verdict"] == "PASS" and rep["harness_ok"] is True
    assert [s["type"] for s in rep["steps"]] == ["warp", "console", "screenshot"]
    assert (next((work / "tests").glob("*/shots")) / "look.png").exists()
    assert "screenshots (open and LOOK" in p.stdout
    # the isolated folder held the mod, its required dependency and the harness, and is gone afterwards
    assert not Path(rep["isolated_dir"]).exists()                                  # the temporary copy is deleted afterwards
    assert rep["isolated_mods"]["copied"] and "ContentPatcher" in rep["isolated_mods"]["copied"]
    assert not (work / game.PID_FILE_NAME).exists()


def test_refuses_without_owner_confirmation(rig):
    p = run_test(rig, confirmed=False)
    assert p.returncode != 0 and "--confirmed-by-owner" in (p.stdout + p.stderr)
    assert not (rig[0] / "tests").exists()


def test_refuses_a_real_save_name(rig):
    p = run_test(rig, "--save", "Bitter_386707078")
    assert p.returncode != 0 and "TEST save" in (p.stdout + p.stderr)
    assert not (rig[0] / "tests").exists()


def test_blocked_by_validation_errors_before_anything_starts(rig):
    work = rig[0]
    (work / "[CP] Mine" / "content.json").write_text("{ not json", encoding="utf-8")
    p = run_test(rig, "--check", "look")
    assert p.returncode != 0 and "validate_mod.py reports errors" in (p.stdout + p.stderr)
    assert "BLOCKED" in report_of(work)["verdict"]
    assert not (work / game.PID_FILE_NAME).exists()


@pytest.mark.skipif(not HAS_DOTNET, reason="needs dotnet to build the harness")
def test_failed_step_or_error_in_log_gives_fail(rig):
    work, env, tmp = rig
    steps = tmp / "steps.json"
    steps.write_text(json.dumps({"steps": [{"type": "fail_me"}]}), encoding="utf-8")
    p = run_test(rig, "--steps", str(steps))
    assert p.returncode == 1 and report_of(work)["verdict"] == "FAIL"
    shutil.rmtree(work / "tests")
    bad = tmp / "bad.txt"
    bad.write_text("[10:00:00 INFO  SMAPI] SMAPI 4.5.2 with Stardew Valley 1.6.15 build 1 on Windows\n[10:00:02 ERROR Mine] Failed loading asset 'x'\n", encoding="utf-8")
    env["SDV_GAME_LOG"] = str(bad)
    p = run_test(rig, "--check", "look")
    rep = report_of(work)
    assert p.returncode == 1 and rep["harness_ok"] is True and rep["log"]["ok_for_mine"] is False and rep["verdict"] == "FAIL"


@pytest.mark.skipif(not HAS_DOTNET, reason="needs dotnet to build the harness")
def test_non_test_save_in_script_is_refused_by_the_game_side_too(rig):
    """Even if the python check were bypassed, the harness side applies the same rule (simulated by the fake)."""
    work, env, tmp = rig
    steps = tmp / "steps.json"
    steps.write_text(json.dumps({"steps": [{"type": "wait"}]}), encoding="utf-8")
    p = run_test(rig, "--steps", str(steps), "--save", "SdvTest_1", "--prefix", "Hoes")
    assert p.returncode != 0 and not (work / "tests").exists()


def test_launch_and_stop_need_confirmation_and_stop_without_game_is_harmless(tmp_path):
    run = lambda *a: subprocess.run([sys.executable, str(SCRIPTS / "game.py"), *a], capture_output=True, text=True, cwd=tmp_path)
    assert run("launch").returncode != 0
    p = run("stop")
    assert p.returncode == 0 and "no game of ours" in p.stdout

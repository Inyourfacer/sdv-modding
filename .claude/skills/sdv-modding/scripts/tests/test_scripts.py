"""Smoke tests for the sdv-modding scripts. Run: python -m pytest scripts/tests -q

Every test works in a temp folder; nothing touches the real game or the user's mods.
"""
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

SPEC_KEYS = [k for k in sdvlib.load_specs()]


def run(script: str, *args, cwd: Path, ok: bool = True):
    p = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                       cwd=cwd, capture_output=True, text=True)
    if ok:
        assert p.returncode == 0, f"{script} {args}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}"
    return p


@pytest.fixture()
def work(tmp_path):
    # a config that points everything into the temp folder so nothing real is touched
    cfg = {"game_path": str(tmp_path / "game"), "content_patcher_format": "2.7.0",
           "comfyui": {"input_dir": None, "output_dir": None, "checkpoint": "test.safetensors"}}
    (tmp_path / "game" / "Mods").mkdir(parents=True)
    (tmp_path / sdvlib.CONFIG_NAME).write_text(json.dumps(cfg), encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------ new_mod
@pytest.mark.parametrize("kind", ["cp", "smapi", "smapi+cp", "portraiture", "fashionsense", "alttextures"])
def test_new_mod_scaffolds_and_validates(work, kind):
    run("new_mod.py", "--type", kind, "--name", "Test Mod", "--author", "Tester", "--out", work / "mods", cwd=work)
    folders = [p for p in (work / "mods").iterdir() if p.is_dir()]
    assert folders
    for f in folders:
        assert (f / "manifest.json").exists()
        p = run("validate_mod.py", f, cwd=work, ok=False)
        assert "[ERROR]" not in p.stdout, p.stdout


def test_new_mod_refuses_to_overwrite(work):
    run("new_mod.py", "--type", "cp", "--name", "Dup", "--author", "T", "--out", work / "mods", cwd=work)
    p = run("new_mod.py", "--type", "cp", "--name", "Dup", "--author", "T", "--out", work / "mods", cwd=work, ok=False)
    assert p.returncode != 0


# ------------------------------------------------------------------ placeholders
@pytest.mark.parametrize("key", SPEC_KEYS)
def test_placeholder_matches_spec(work, key):
    out = work / f"{key}.png"
    run("make_placeholder.py", "--spec", key, "--out", out, "--label", "T", cwd=work)
    spec = sdvlib.get_spec(key)
    im = Image.open(out)
    assert im.size == (spec["sheet_w"], spec["sheet_h"])
    assert im.info.get("sdv_placeholder") == "1"


def test_placeholder_does_not_overwrite_real_art(work):
    out = work / "art.png"
    Image.new("RGBA", (128, 192), (1, 2, 3, 255)).save(out)  # no placeholder tag = real art
    p = run("make_placeholder.py", "--spec", "portrait", "--out", out, cwd=work, ok=False)
    assert p.returncode != 0
    assert Image.open(out).getpixel((0, 0)) == (1, 2, 3, 255)


# ------------------------------------------------------------------ workflow + postprocess
def test_workflow_and_postprocess_roundtrip(work):
    out_dir = work / "comfy" / "Mira_portrait"
    run("make_comfy_workflow.py", "--spec", "portrait", "--name", "Mira", "--subject", "1girl, teal hair",
        "--out-dir", out_dir, "--api", cwd=work)
    jobs = json.loads((out_dir / "jobs.json").read_text(encoding="utf-8"))
    assert len(jobs["jobs"]) == 6
    assert (out_dir / "Mira_portrait_neutral.json").exists()
    assert (out_dir / "Mira_portrait_neutral.api.json").exists()

    # fake ComfyUI outputs, one per job
    outputs = work / "output" / "sdv"
    outputs.mkdir(parents=True)
    for i, j in enumerate(jobs["jobs"]):
        Image.new("RGB", (1024, 1024), (40 * i, 100, 200)).save(outputs / (Path(j["output_prefix"]).name + "_00001_.png"))

    sheet = work / "mod" / "Mira.png"
    run("postprocess.py", "--jobs", out_dir / "jobs.json", "--images", work / "output", "--out", sheet, cwd=work)
    im = Image.open(sheet)
    assert im.size == (128, 192)
    assert im.info.get("sdv_placeholder") != "1"  # all frames covered


def test_sprite_workflow_mirror_left(work):
    out_dir = work / "comfy" / "spr"
    run("make_comfy_workflow.py", "--spec", "character_sprite", "--name", "Mira", "--subject", "1girl",
        "--per-row", "--mirror-left", "--out-dir", out_dir, cwd=work)
    jobs = json.loads((out_dir / "jobs.json").read_text(encoding="utf-8"))["jobs"]
    assert any(j.get("mirror_of") for j in jobs)
    assert len([j for j in jobs if not j.get("mirror_of")]) == 3  # down, right, up generated


def test_postprocess_partial_stays_placeholder(work):
    sheet = work / "s.png"
    run("make_placeholder.py", "--spec", "object_icon", "--out", sheet, cwd=work)
    Image.new("RGB", (64, 64), (255, 255, 255)).save(work / "a.png")
    # nothing supplied for the only frame -> still a placeholder
    run("postprocess.py", "--spec", "object_icon", "--inputs", "--out", sheet, cwd=work, ok=False)
    assert Image.open(sheet).info.get("sdv_placeholder") == "1"


# ------------------------------------------------------------------ validator
def make_cp(work, content: dict, name="[CP] V"):
    root = work / name
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({
        "Name": "V", "Author": "T", "Version": "1.0.0", "UniqueID": "T.V",
        "ContentPatcherFor": None, "ContentPackFor": {"UniqueID": "Pathoschild.ContentPatcher"}}), encoding="utf-8")
    (root / "content.json").write_text(json.dumps(content), encoding="utf-8")
    (root / "i18n").mkdir()
    (root / "i18n" / "default.json").write_text("{}", encoding="utf-8")
    return root


def test_validator_passes_good_pack(work):
    root = make_cp(work, {"Format": "2.7.0", "Changes": []})
    p = run("validate_mod.py", root, cwd=work)
    assert "0 error(s)" in p.stdout


def test_validator_catches_problems(work):
    root = make_cp(work, {"Format": "2.7.0", "Changes": [
        {"Action": "Load", "Target": "Portraits/Mira", "FromFile": "assets/missing.png"},
        {"Action": "Load", "Target": "Portraits/Bad", "FromFile": "assets/bad.png"},
        {"Action": "EditData", "Target": "Data/Objects", "Entries": {"Thing": {"DisplayName": "{{i18n:nokey}}"}}},
    ]})
    (root / "assets").mkdir()
    Image.new("RGBA", (100, 100)).save(root / "assets" / "bad.png")  # wrong portrait size
    p = run("validate_mod.py", root, cwd=work, ok=False)
    assert p.returncode == 1
    assert "FromFile not found" in p.stdout
    assert "128 wide" in p.stdout
    assert "nokey" in p.stdout


def test_validator_flags_invalid_json_and_placeholder(work):
    root = make_cp(work, {"Format": "2.7.0", "Changes": []})
    (root / "bad.json").write_text("{ not json", encoding="utf-8")
    root2 = make_cp(work, {"Format": "2.7.0", "Changes": [
        {"Action": "Load", "Target": "Portraits/X", "FromFile": "assets/x.png"}]}, name="[CP] W")
    run("make_placeholder.py", "--spec", "portrait", "--out", root2 / "assets" / "x.png", cwd=work)
    p = run("validate_mod.py", root2, cwd=work, ok=False)
    assert "placeholder" in p.stdout


def test_tolerant_json_parser():
    assert sdvlib.loads_tolerant('{"a": 1, // c\n "b": [1,2,], /* x */ "u": "http://x"}') == {"a": 1, "b": [1, 2], "u": "http://x"}


# ------------------------------------------------------------------ deploy
def test_deploy_and_zip(work):
    run("new_mod.py", "--type", "cp", "--name", "Dep", "--author", "T", "--out", work / "mods", cwd=work)
    src = work / "mods" / "[CP] Dep"
    mods = work / "game" / "Mods"
    (mods / "[CP] Dep").mkdir()
    (mods / "[CP] Dep" / "config.json").write_text('{"keep": true}', encoding="utf-8")
    run("deploy.py", src, "--mods", mods, "--zip", cwd=work)
    assert (mods / "[CP] Dep" / "manifest.json").exists()
    assert json.loads((mods / "[CP] Dep" / "config.json").read_text(encoding="utf-8")) == {"keep": True}
    assert (work / "mods" / "[CP] Dep 1.0.0.zip").exists()


# ------------------------------------------------------------------ doctor
def test_doctor_json_runs_and_is_read_only(work):
    p = run("doctor.py", "--json", cwd=work)
    rep = json.loads(p.stdout)
    assert set(rep) >= {"game", "comfyui", "tools", "advice"}
    assert rep["game"]["game_path"] in (None, str(work / "game")) or Path(rep["game"]["game_path"]).exists()


def test_doctor_write_config_never_overwrites_user_values(work):
    cfgp = work / sdvlib.CONFIG_NAME
    before = json.loads(cfgp.read_text(encoding="utf-8"))
    run("doctor.py", "--write-config", cwd=work)
    after = json.loads(cfgp.read_text(encoding="utf-8"))
    for k, v in before.items():
        if not isinstance(v, dict):
            assert after[k] == v
    assert after["comfyui"]["checkpoint"] == "test.safetensors"


def test_workflow_refuses_without_checkpoint(tmp_path):
    (tmp_path / sdvlib.CONFIG_NAME).write_text("{}", encoding="utf-8")
    p = run("make_comfy_workflow.py", "--spec", "portrait", "--name", "X", "--subject", "a", "--out-dir", tmp_path / "o",
            cwd=tmp_path, ok=False)
    assert p.returncode != 0 and "checkpoint" in (p.stderr + p.stdout)


# ------------------------------------------------------------------ project file
def make_project_mod(work: Path):
    run("new_mod.py", "--type", "cp", "--name", "Proj", "--author", "Tester", "--out", work / "root", cwd=work)
    mod = work / "root" / "[CP] Proj"
    (mod / "data").mkdir(exist_ok=True)
    (mod / "data" / "npc.json").write_text(json.dumps({"Changes": [
        {"Action": "EditData", "Target": "Data/Characters", "Entries": {"{{ModId}}_Mira": {}}},
        {"Action": "EditData", "Target": "Data/Objects", "Entries": {"{{ModId}}_Gem": {}, "BareName": {}}},
        {"Action": "EditData", "Target": "Data/Events/Town", "Entries": {"{{ModId}}_Intro/f x 500": "end"}},
        {"Action": "Load", "Target": "Portraits/{{ModId}}_Mira", "FromFile": "assets/Mira.png"},
    ]}), encoding="utf-8")
    (mod / "content.json").write_text(json.dumps({"Format": "2.7.0", "Changes": [
        {"Action": "Include", "FromFile": "data/npc.json"}]}), encoding="utf-8")
    run("make_placeholder.py", "--spec", "portrait", "--out", mod / "assets" / "Mira.png", cwd=work)
    return mod


def test_project_sync_status_ids(work):
    make_project_mod(work)
    root = work / "root"
    run("project.py", "sync", cwd=root)
    proj = json.loads((root / "sdv-project.json").read_text(encoding="utf-8"))
    assert proj["id_prefix"] == "Tester"
    assert proj["ids"]["Tester.Proj_Mira"]["kind"] == "npc"
    assert proj["ids"]["Tester.Proj_Intro"]["kind"] == "event"
    assert "BareName" not in proj["ids"]  # unprefixed vanilla-style keys are not custom ids
    a = proj["assets"][0]
    assert a["spec"] == "portrait" and a["status"] == "placeholder" and a["size"] == [128, 192]
    p = run("project.py", "status", "--json", cwd=root)
    assert json.loads(p.stdout)["by_status"] == {"placeholder": 1}
    assert run("project.py", "ids", "check", cwd=root).returncode == 0


def test_project_sync_is_nondestructive_and_tracks_real_art(work):
    mod = make_project_mod(work)
    root = work / "root"
    run("project.py", "sync", cwd=root)
    pj = root / "sdv-project.json"
    proj = json.loads(pj.read_text(encoding="utf-8"))
    proj["characters"]["x"] = {"subject": "keep me"}
    proj["assets"][0]["notes"] = "my note"
    pj.write_text(json.dumps(proj), encoding="utf-8")
    Image.new("RGBA", (128, 192), (9, 9, 9, 255)).save(mod / "assets" / "Mira.png")  # real art replaces placeholder
    run("project.py", "sync", cwd=root)
    after = json.loads(pj.read_text(encoding="utf-8"))
    assert after["characters"]["x"]["subject"] == "keep me"
    assert after["assets"][0]["notes"] == "my note"
    assert after["assets"][0]["status"] == "installed"


def test_project_csv_roundtrip(work):
    make_project_mod(work)
    root = work / "root"
    run("project.py", "sync", cwd=root)
    (root / "manifest.csv").write_text(
        "id,category,positive,negative,gen_width,gen_height,transparent_bg,art_source,character\n"
        "salt_portrait,portrait,\"1girl, salt\",bad,1024,1024,no,art/salt.png,Salt\n", encoding="utf-8")
    run("project.py", "import-csv", "manifest.csv", cwd=root)
    proj = json.loads((root / "sdv-project.json").read_text(encoding="utf-8"))
    row = next(a for a in proj["assets"] if a["id"] == "salt_portrait")
    assert row["spec"] == "portrait" and row["gen_size"] == [1024, 1024] and row["prompt"]["positive"] == "1girl, salt"
    run("project.py", "export-csv", "out.csv", cwd=root)
    assert "salt_portrait" in (root / "out.csv").read_text(encoding="utf-8")


def test_workflow_uses_project_character_and_style(work):
    proj = {"version": 1, "art_style": {"checkpoint": "locked.safetensors", "steps": 11},
            "characters": {"Mira": {"subject": "1girl, teal hair", "outfits": {"beach": "bikini"}, "seed": 424242,
                                    "loras": [{"name": "mira.safetensors", "strength_model": 0.7}]}}}
    (work / "sdv-project.json").write_text(json.dumps(proj), encoding="utf-8")
    out = work / "wf"
    run("make_comfy_workflow.py", "--spec", "portrait", "--name", "Mira", "--character", "Mira", "--outfit", "beach",
        "--out-dir", out, cwd=work)
    jobs = json.loads((out / "jobs.json").read_text(encoding="utf-8"))
    assert jobs["seed"] == 424242
    assert jobs["checkpoint"] == "locked.safetensors"
    assert any(l["name"] == "mira.safetensors" for l in jobs["loras"])
    assert "teal hair, bikini" in jobs["jobs"][0]["prompt"]

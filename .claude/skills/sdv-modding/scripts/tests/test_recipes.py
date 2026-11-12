"""Consistency recipes: structure of the generated graphs, jobs.json compatibility with postprocess.py."""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import sdvlib  # noqa: E402

CORE_NODES = {"CheckpointLoaderSimple", "CLIPSetLastLayer", "LoraLoader", "CLIPTextEncode", "EmptyLatentImage", "KSampler",
              "VAEDecode", "VAEEncode", "SaveImage", "LoadImage", "ImageScale", "EmptyImage", "ImageStitch", "SolidMask",
              "MaskComposite", "SetLatentNoiseMask", "ImageCrop"}


@pytest.fixture()
def work(tmp_path):
    (tmp_path / sdvlib.CONFIG_NAME).write_text(json.dumps({"comfyui": {"checkpoint": "test.safetensors"}}), encoding="utf-8")
    ref = tmp_path / "ref.png"
    Image.new("RGB", (512, 512), (120, 160, 90)).save(ref)
    return tmp_path


def make(work, *args, ok=True):
    p = subprocess.run([sys.executable, str(SCRIPTS / "make_comfy_workflow.py"), *map(str, args)], cwd=work, capture_output=True, text=True)
    if ok:
        assert p.returncode == 0, p.stdout + p.stderr
    return p


def load(work, out, stem):
    return json.loads((work / out / f"{stem}.api.json").read_text(encoding="utf-8"))


def by_class(g, cls):
    return [n for n in g.values() if n["class_type"] == cls]


def check_graph(g):
    assert {n["class_type"] for n in g.values()} <= CORE_NODES  # core nodes only
    for nid, n in g.items():
        for v in n["inputs"].values():
            if isinstance(v, list):
                assert v[0] in g, f"dangling link in node {nid}"


def test_portrait_sheet_one_base_many_expressions(work):
    make(work, "--recipe", "portrait_sheet", "--name", "Mira", "--subject", "1girl, teal hair", "--seed", "5", "--out-dir", "o")
    g = load(work, "o", "Mira_portrait")
    check_graph(g)
    assert len(by_class(g, "SaveImage")) == 6
    kss = by_class(g, "KSampler")
    assert len(kss) == 1 + 5                      # one txt2img base + five expressions
    assert sorted(k["inputs"]["denoise"] for k in kss) == [0.55] * 5 + [1.0]
    assert {k["inputs"]["seed"] for k in kss} == {5}   # same seed everywhere
    jobs = json.loads((work / "o" / "jobs.json").read_text(encoding="utf-8"))
    assert [j["id"] for j in jobs["jobs"]] == ["neutral", "happy", "sad", "unique", "love", "angry"]
    assert all(j["output_prefix"].startswith("sdv/Mira_portrait_") for j in jobs["jobs"])


def test_portrait_sheet_outfit_stage_and_reference(work):
    make(work, "--recipe", "portrait_sheet", "--name", "Mira", "--subject", "1girl", "--outfit-tags", "bikini, sun hat",
         "--reference", "ref.png", "--out-dir", "o")
    g = load(work, "o", "Mira_portrait")
    check_graph(g)
    assert len(by_class(g, "KSampler")) == 1 + 1 + 5     # reference->neutral, outfit stage, 5 expressions
    assert len(by_class(g, "LoadImage")) == 1
    assert (work / "o" / "input" / "sdv_Mira_ref.png").exists()
    texts = [n["inputs"]["text"] for n in by_class(g, "CLIPTextEncode")]
    assert any("bikini" in t and "smile" in t for t in texts)


def test_portrait_sheet_extended_rows(work):
    make(work, "--recipe", "portrait_sheet", "--name", "Mira", "--subject", "x", "--rows", "5", "--out-dir", "o")
    jobs = json.loads((work / "o" / "jobs.json").read_text(encoding="utf-8"))["jobs"]
    assert [j["id"] for j in jobs][6:] == ["surprised", "worried", "laughing", "thinking"]


def test_sprite_sheet_inpaint_structure_and_postprocess(work):
    p = make(work, "--recipe", "sprite_sheet", "--name", "Mira", "--subject", "1girl, teal hair", "--reference", "ref.png", "--out-dir", "o")
    g = load(work, "o", "Mira_sprite")
    check_graph(g)
    assert len(by_class(g, "SetLatentNoiseMask")) == 1
    assert by_class(g, "ImageStitch")[0]["inputs"]["direction"] == "right"
    assert len(by_class(g, "SaveImage")) == 3          # down, right, up; left is mirrored
    crops = by_class(g, "ImageCrop")
    assert len(crops) == 3 and all(c["inputs"]["x"] == 832 and c["inputs"]["width"] == 832 for c in crops)
    jobs = json.loads((work / "o" / "jobs.json").read_text(encoding="utf-8"))
    assert any(j.get("mirror_of") == "right" for j in jobs["jobs"])
    # fake generated outputs -> postprocess builds the 64x128 sheet from this jobs.json
    outs = work / "out" / "sdv"
    outs.mkdir(parents=True)
    for j in jobs["jobs"]:
        if j.get("output_prefix"):
            Image.new("RGB", (832, 1216), (255, 255, 255)).save(outs / (Path(j["output_prefix"]).name + "_00001_.png"))
    sheet = work / "Mira.png"
    r = subprocess.run([sys.executable, str(SCRIPTS / "postprocess.py"), "--jobs", work / "o" / "jobs.json", "--images", work / "out",
                        "--out", sheet], cwd=work, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert Image.open(sheet).size == (64, 128)


def test_sprite_sheet_requires_reference(work):
    p = make(work, "--recipe", "sprite_sheet", "--name", "Mira", "--subject", "x", "--out-dir", "o", ok=False)
    assert p.returncode != 0 and "reference" in (p.stdout + p.stderr)


def test_reference_sheet(work):
    make(work, "--recipe", "reference_sheet", "--name", "Mira", "--subject", "1girl, teal hair", "--out-dir", "o")
    g = load(work, "o", "Mira_reference")
    check_graph(g)
    assert by_class(g, "EmptyLatentImage")[0]["inputs"]["width"] == 1536
    assert "turnaround" in " ".join(n["inputs"]["text"] for n in by_class(g, "CLIPTextEncode"))


def test_character_from_project_with_outfit_and_preset(work):
    proj = {"version": 1, "art_style": {"checkpoint": "locked.safetensors"},
            "characters": {"Mira": {"subject": "1girl, teal hair", "outfits": {"beach": "bikini"}, "seed": 9,
                                    "reference_image": "ref.png"}}}
    (work / "sdv-project.json").write_text(json.dumps(proj), encoding="utf-8")
    make(work, "--recipe", "portrait_sheet", "--name", "Mira_beach", "--character", "Mira", "--outfit", "beach",
         "--preset", "illustrious", "--out-dir", "o")
    g = load(work, "o", "Mira_beach_portrait")
    assert g["1"]["inputs"]["ckpt_name"] == "locked.safetensors"
    ks = by_class(g, "KSampler")[0]["inputs"]
    assert ks["seed"] == 9 and ks["cfg"] == 5.5 and ks["steps"] == 28
    assert len(by_class(g, "KSampler")) == 1 + 1 + 5      # reference taken from the character, plus outfit stage
    assert any("masterpiece" in n["inputs"]["text"] for n in by_class(g, "CLIPTextEncode"))


def _comfy_up():
    try:
        urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=1)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _comfy_up(), reason="needs a running ComfyUI")
def test_recipes_pass_live_preflight(work):
    """Only runs when ComfyUI happens to be up: every node class and input of every recipe exists on the server."""
    info = json.load(urllib.request.urlopen("http://127.0.0.1:8188/object_info", timeout=30))
    for cls in CORE_NODES:
        assert cls in info, f"{cls} missing from this ComfyUI"


# ------------------------------------------------------------------ batch.py (plan only: no ComfyUI needed)
def batch(work, *args, ok=True):
    p = subprocess.run([sys.executable, str(SCRIPTS / "batch.py"), *map(str, args)], cwd=work, capture_output=True, text=True)
    if ok:
        assert p.returncode == 0, p.stdout + p.stderr
    return p


def project_with_assets(work, with_reference):
    ref = "ref.png" if with_reference else None
    proj = {"version": 1, "art_style": {"checkpoint": "locked.safetensors", "takes": 2},
            "characters": {"Mira": {"subject": "1girl, teal hair", "seed": 11, "reference_image": ref}},
            "assets": [
                {"id": "mira_portrait", "spec": "portrait", "character": "Mira", "status": "placeholder", "files": []},
                {"id": "mira_sprite", "spec": "character_sprite", "character": "Mira", "status": "placeholder", "files": []},
                {"id": "gem", "spec": "object_icon", "character": None, "status": "placeholder", "files": [],
                 "prompt": {"positive": "a blue gem", "negative": "text"}},
                {"id": "nospec", "spec": None, "status": "placeholder", "files": []}]}
    (work / "sdv-project.json").write_text(json.dumps(proj), encoding="utf-8")


def test_batch_gate_makes_reference_first(work):
    project_with_assets(work, with_reference=False)
    p = batch(work, "plan", "--character", "Mira")
    assert "making a reference sheet first" in p.stdout
    assert "waiting on reference" in p.stdout                      # the sprite waits behind the portrait's gate
    assert (work / "comfy" / "mira_portrait" / "take_a" / "Mira_reference_reference.api.json").exists() or \
        list((work / "comfy" / "mira_portrait" / "take_a").glob("*reference*.api.json"))
    assert not (work / "comfy" / "mira_sprite").exists()


def test_batch_with_reference_builds_recipes_and_takes(work):
    project_with_assets(work, with_reference=True)
    batch(work, "plan")
    for take in ("take_a", "take_b"):
        assert list((work / "comfy" / "mira_portrait" / take).glob("*_portrait.api.json"))
        assert list((work / "comfy" / "mira_sprite" / take).glob("*_sprite.api.json"))
        assert list((work / "comfy" / "gem" / take).glob("*.api.json"))
    seeds = {json.loads((work / "comfy" / "mira_portrait" / t / "jobs.json").read_text(encoding="utf-8"))["seed"] for t in ("take_a", "take_b")}
    assert seeds == {11, 1011}
    assert not (work / "comfy" / "nospec").exists()


def test_batch_approve_reference_copies_and_records(work):
    project_with_assets(work, with_reference=False)
    batch(work, "approve-reference", "Mira", "ref.png")
    proj = json.loads((work / "sdv-project.json").read_text(encoding="utf-8"))
    assert proj["characters"]["Mira"]["reference_image"] == "art/Mira/reference.png"
    assert (work / "art" / "Mira" / "reference.png").exists()


def test_batch_run_without_server_stops_with_hint(work):
    project_with_assets(work, with_reference=True)
    (work / sdvlib.CONFIG_NAME).write_text(json.dumps({"comfyui": {"checkpoint": "t.safetensors", "url": "http://127.0.0.1:9"}}), encoding="utf-8")
    p = batch(work, "run", "--ids", "gem", "--takes", "1", ok=False)
    assert p.returncode != 0 and "not reachable" in (p.stdout + p.stderr)


# ------------------------------------------------------------------ style.py
def style(work, *args, ok=True):
    p = subprocess.run([sys.executable, str(SCRIPTS / "style.py"), *map(str, args)], cwd=work, capture_output=True, text=True)
    if ok:
        assert p.returncode == 0, p.stdout + p.stderr
    return p


def test_style_test_builds_fixed_test_set_per_candidate(work):
    style(work, "test", "--no-run", "--preset", "illustrious",
          "--candidate", "a=one.safetensors",
          "--candidate", "b=two.safetensors+pix.safetensors:0.7:pixel art")
    for label in ("a", "b"):
        for kind in ("portrait", "apple", "sword", "potion", "tile"):
            assert list((work / "style-test" / label / kind).glob("*.api.json")), (label, kind)
    g = json.loads(next((work / "style-test" / "b" / "apple").glob("*.api.json")).read_text(encoding="utf-8"))
    assert [n["inputs"]["lora_name"] for n in g.values() if n["class_type"] == "LoraLoader"] == ["pix.safetensors"]
    assert next(n for n in g.values() if n["class_type"] == "CheckpointLoaderSimple")["inputs"]["ckpt_name"] == "two.safetensors"
    assert any("pixel art" in n["inputs"].get("text", "") for n in g.values())


def test_style_lock_writes_project_style_that_scripts_then_use(work):
    style(work, "lock", "--checkpoint", "pick.safetensors", "--lora", "pix.safetensors:0.6:pixel art", "--preset", "pony")
    proj = json.loads((work / "sdv-project.json").read_text(encoding="utf-8"))
    assert proj["art_style"]["checkpoint"] == "pick.safetensors" and proj["art_style"]["preset"] == "pony"
    assert proj["art_style"]["loras"][0]["trigger"] == "pixel art"
    make(work, "--recipe", "reference_sheet", "--name", "Mira", "--subject", "x", "--out-dir", "o")
    g = load(work, "o", "Mira_reference")
    assert g["1"]["inputs"]["ckpt_name"] == "pick.safetensors"
    assert by_class(g, "KSampler")[0]["inputs"]["cfg"] == 7.0            # pony preset from the locked style


def test_comparison_sheet_renders(work):
    sys.path.insert(0, str(SCRIPTS))
    import style as st
    paths = {}
    for k, size in (("portrait", (128, 192)), ("apple", (16, 16)), ("sword", (16, 16)), ("potion", (16, 16)), ("tile", (16, 16))):
        p = work / f"{k}.png"
        Image.new("RGBA", size, (200, 40, 40, 255)).save(p)
        paths[k] = p
    out = work / "cmp.png"
    st.build_sheet([("a", paths), ("b", {})], [("vanilla portrait", Image.new("RGBA", (64, 64), (1, 1, 1, 255)))], out)
    assert Image.open(out).width > 800


def test_approve_reference_crop_kind_and_letterbox(work):
    sheet = work / "sheet.png"
    im = Image.new("RGB", (1536, 1024), (255, 255, 255))
    im.paste((200, 0, 0), (0, 0, 300, 1000))       # a "front figure" on the left
    im.save(sheet)
    project_with_assets(work, with_reference=False)
    batch(work, "approve-reference", "Mira", sheet, "--kind", "body", "--crop", "0,0,0.2,1")
    batch(work, "approve-reference", "Mira", sheet, "--kind", "portrait", "--crop", "0,0,0.2,0.25")
    proj = json.loads((work / "sdv-project.json").read_text(encoding="utf-8"))
    ch = proj["characters"]["Mira"]
    assert Image.open(work / ch["reference_image"]).size == (307, 1024)
    assert Image.open(work / ch["portrait_reference_image"]).size == (307, 256)
    # portrait recipe uses the head crop, sprite recipe uses the body; both are letterboxed, never cropped
    make(work, "--recipe", "portrait_sheet", "--name", "Mira", "--character", "Mira", "--out-dir", "p")
    make(work, "--recipe", "sprite_sheet", "--name", "Mira", "--character", "Mira", "--out-dir", "s")
    ref_p = Image.open(work / "p" / "input" / "sdv_Mira_ref.png")
    ref_s = Image.open(work / "s" / "input" / "sdv_Mira_ref.png")
    assert ref_p.size == (1024, 1024) and ref_s.size == (832, 1216)
    assert ref_s.getpixel((2, 2)) == (255, 255, 255)           # white padding, figure kept whole


def test_batch_rebuild_removes_stale_workflows(work):
    project_with_assets(work, with_reference=False)
    batch(work, "plan", "--ids", "mira_portrait", "--takes", "1")            # makes a reference workflow
    assert list((work / "comfy" / "mira_portrait" / "take_a").glob("*reference*.api.json"))
    batch(work, "approve-reference", "Mira", "ref.png")
    batch(work, "plan", "--ids", "mira_portrait", "--takes", "1")
    assert not list((work / "comfy" / "mira_portrait" / "take_a").glob("*reference*.api.json"))

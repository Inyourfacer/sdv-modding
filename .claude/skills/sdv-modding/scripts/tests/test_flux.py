"""Flux mode of make_comfy_workflow.py (simple recipe): graph shape, settings, config-driven family selection."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def _config(work: Path, loader="checkpoint"):
    flux = {"checkpoint": "flux_test.safetensors", "loader": loader, "loras": [{"name": "sv.safetensors", "strength_model": 1.0, "trigger": "STDW"}],
            "guidance": 3.0, "steps": 18}
    if loader == "unet":
        flux.update(clip_l="clip_l.safetensors", t5xxl="t5xxl_fp8.safetensors", vae="ae.safetensors")
    cfg = {"author": "T", "uniqueid_prefix": "T", "comfyui": {
        "checkpoint": "sdxl_test.safetensors", "clip_skip": 2, "loras": [],
        "asset_type_loras": {"tilesheet": [{"name": "pixel.safetensors", "strength_model": 0.8}]},
        "asset_type_family": {"tilesheet": "flux"}, "flux": flux,
        "quality_prefix": "masterpiece", "negative": "lowres", "style_suffix": "sdv", "steps": 28, "cfg": 5.5}}
    (work / "sdv-modding.config.json").write_text(json.dumps(cfg), encoding="utf-8")


def _run(work, *args):
    p = subprocess.run([sys.executable, str(SCRIPTS / "make_comfy_workflow.py"), *map(str, args)], cwd=work, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    return p


def _api(out: Path):
    return json.loads(next(out.glob("*.api.json")).read_text(encoding="utf-8"))


def _by_type(api):
    d = {}
    for n in api.values():
        d.setdefault(n["class_type"], []).append(n["inputs"])
    return d


def test_flux_from_config_family(tmp_path):
    _config(tmp_path)
    out = tmp_path / "o"
    _run(tmp_path, "--spec", "tilesheet", "--frame", "16x16", "--cols", "1", "--rows", "1", "--name", "floor",
         "--subject", "wooden floor", "--seed", "5", "--api", "--out-dir", out)
    t = _by_type(_api(out))
    assert t["CheckpointLoaderSimple"][0]["ckpt_name"] == "flux_test.safetensors"
    assert "CLIPSetLastLayer" not in t
    assert [l["lora_name"] for l in t["LoraLoader"]] == ["sv.safetensors"]  # SDXL asset_type_loras are not used
    assert t["FluxGuidance"][0]["guidance"] == 3.0
    assert "EmptySD3LatentImage" in t and "EmptyLatentImage" not in t
    ks = t["KSampler"][0]
    assert ks["cfg"] == 1.0 and ks["steps"] == 18 and ks["sampler_name"] == "euler" and ks["scheduler"] == "simple"
    texts = [x["text"] for x in t["CLIPTextEncode"]]
    assert "" in texts  # empty negative
    pos = next(x for x in texts if x)
    assert pos.startswith("STDW") and "masterpiece" not in pos
    jobs = json.loads((out / "jobs.json").read_text(encoding="utf-8"))
    assert jobs["family"] == "flux" and jobs["checkpoint"] == "flux_test.safetensors"


def test_flux_unet_loader(tmp_path):
    _config(tmp_path, loader="unet")
    out = tmp_path / "o"
    _run(tmp_path, "--spec", "tilesheet", "--frame", "16x16", "--cols", "1", "--rows", "1", "--name", "w", "--subject", "wall",
         "--api", "--out-dir", out)
    t = _by_type(_api(out))
    assert "CheckpointLoaderSimple" not in t
    assert t["UNETLoader"][0]["unet_name"] == "flux_test.safetensors"
    assert t["DualCLIPLoader"][0] == {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8.safetensors", "type": "flux"}
    assert t["VAELoader"][0]["vae_name"] == "ae.safetensors"
    ui = json.loads(next(p for p in out.glob("*.json") if not p.name.endswith(".api.json") and p.name != "jobs.json").read_text())
    linked = {l[0] for l in ui["links"]}
    for n in ui["nodes"]:  # every input of every node is connected
        for i in n.get("inputs", []):
            assert i["link"] in linked, (n["type"], i["name"])


def test_other_specs_stay_sdxl(tmp_path):
    _config(tmp_path)
    out = tmp_path / "o"
    _run(tmp_path, "--spec", "object_icon", "--name", "gem", "--subject", "gem", "--api", "--out-dir", out)
    t = _by_type(_api(out))
    assert t["CheckpointLoaderSimple"][0]["ckpt_name"] == "sdxl_test.safetensors"
    assert "FluxGuidance" not in t and "CLIPSetLastLayer" in t
    assert t["KSampler"][0]["cfg"] == 5.5


def test_family_override_on_cli(tmp_path):
    _config(tmp_path)
    out = tmp_path / "o"
    _run(tmp_path, "--family", "sdxl", "--spec", "tilesheet", "--frame", "16x16", "--cols", "1", "--rows", "1", "--name", "f",
         "--subject", "floor", "--api", "--out-dir", out)
    t = _by_type(_api(out))
    assert t["CheckpointLoaderSimple"][0]["ckpt_name"] == "sdxl_test.safetensors"
    assert [l["lora_name"] for l in t["LoraLoader"]] == ["pixel.safetensors"]

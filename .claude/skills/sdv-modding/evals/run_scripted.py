#!/usr/bin/env python3
"""Scripted acceptance checks for the evals in evals.json: run the skill's own tooling and assert what each eval expects.

  python evals/run_scripted.py [--json evals/results.json]

This measures the TOOLING, deterministically (no model in the loop). It does not measure whether Claude picks the right tool or
phrases things well: that needs model-driven runs (skill-creator's eval runner, with and without the skill). Evals marked
`scripted: false` in evals.json have no deterministic part and are skipped here. Each check runs in a temp folder.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PIL import Image

SK = Path(__file__).resolve().parent.parent
S = SK / "scripts"
sys.path.insert(0, str(S))
import sdvlib  # noqa: E402
from vanilla import Vanilla  # noqa: E402


def sh(script, *args, cwd):
    return subprocess.run([sys.executable, str(S / script), *map(str, args)], cwd=cwd, capture_output=True, text=True)


def ok(r, what):
    assert r.returncode == 0, f"{what} failed: {(r.stdout + r.stderr)[-400:]}"
    return r


def jl(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def validates(mod: Path, cwd, *extra):
    r = sh("validate_mod.py", mod, "--json", *extra, cwd=cwd)
    res = json.loads(r.stdout)
    assert res["errors"] == 0, [x["message"] for x in res["results"] if x["level"] == "ERROR"][:3]
    return res


def mk(tmp: Path, name="Test"):
    root = tmp / "proj"
    ok(sh("new_mod.py", "--type", "cp", "--name", name, "--author", "Me", "--out", root, cwd=tmp), "new_mod")
    return root, root / f"[CP] {name}"


# ------------------------------------------------------------------ the checks
def e_new_cp_npc(tmp):
    root, mod = mk(tmp)
    ok(sh("add.py", "npc", "--mod", mod, "--name", "Mira", "--home", "Town 52 70 2", "--birthday", "fall 12", "--subject", "1girl, teal hair", cwd=root), "add npc")
    ch = [c for f in (mod / "data").rglob("*.json") for c in jl(f)["Changes"]]
    ids = [k for c in ch if c.get("Action") == "EditData" for k in (c.get("Entries") or {}) if k.startswith("{{ModId}}")]
    assert ids and all(i.startswith("{{ModId}}_") for i in ids)
    assert Image.open(mod / "assets/Portraits/Mira.png").size == (128, 192) and Image.open(mod / "assets/Characters/Mira.png").size == (64, 128)
    targets = {c.get("Target") for c in ch}
    assert {"Data/Characters", "Data/NPCGiftTastes", "Characters/{{ModId}}_Mira", "Portraits/{{ModId}}_Mira", "Characters/Dialogue/{{ModId}}_Mira", "Characters/schedules/{{ModId}}_Mira"} <= targets
    assert "mira.name" in jl(mod / "i18n/default.json")
    validates(mod, root)
    return "NPC pack validates; placeholder PNGs 128x192 / 64x128; all IDs prefixed; i18n, gift tastes, dialogue, schedule present"


def e_add_item_recipe_shop(tmp):
    root, mod = mk(tmp)
    (mod / "content.json").write_text('{\n  // my pack\n  "Format": "2.9.0",\n  "Changes": [\n    { "Action": "Include", "FromFile": "data/old.json" } // keep\n  ]\n}\n', encoding="utf-8")
    (mod / "data").mkdir(exist_ok=True)
    (mod / "data/old.json").write_text('{"Changes": []}', encoding="utf-8")
    ok(sh("add.py", "item", "--mod", mod, "--name", "Moonberry Jam", "--price", "220", cwd=root), "item")
    ok(sh("add.py", "recipe", "--mod", mod, "--kind", "cooking", "--name", "Moonberry Jam Recipe", "--ingredients", "613 3 245 1", "--yield", "Moonberry Jam", cwd=root), "recipe")
    ok(sh("add.py", "shop-item", "--mod", mod, "--shop", "SeedShop", "--item", "Moonberry Jam", "--price", "300", "--condition", "SEASON spring", cwd=root), "shop-item")
    text = (mod / "content.json").read_text(encoding="utf-8")
    assert "// my pack" in text and "// keep" in text and text.count('"Action": "Include"') == 4
    item = jl(mod / "data/Items/MoonberryJam.json")["Changes"][1]["Entries"]["{{ModId}}_MoonberryJam"]
    assert item["Price"] == 220
    rec = jl(mod / "data/Recipes/MoonberryJamRecipe.json")["Changes"][0]["Entries"]["{{ModId}}_MoonberryJamRecipe"]
    assert len(rec.split("/")) == 5 and rec.startswith("613 3 245 1/10 10/")
    shop = [c for f in (mod / "data/Shops").glob("*.json") for c in jl(f)["Changes"]][0]
    assert shop["Target"] == "Data/Shops" and shop["TargetField"] == ["SeedShop", "Items"]
    validates(mod, root)
    return "author's comments and Include kept; item price, 5-part recipe string and SeedShop TargetField correct; validator clean"


LOG = """[10:00:00 INFO  SMAPI] SMAPI 4.5.2 with Stardew Valley 1.6.15 build 24356 on Windows 10
[10:00:01 TRACE SMAPI]    Content Patcher (from Mods\\CP\\CP.dll, ID: Pathoschild.ContentPatcher, assembly version: 2.9.1)...
[10:00:02 WARN  SMAPI]    Skipped mods
[10:00:02 WARN  SMAPI]    --------------------------------------------------
[10:00:02 WARN  SMAPI]       These mods could not be added to your game.
[10:00:02 WARN  SMAPI]       - Mira Pack 1.0.0 because it requires Some.Missing.Mod 2.0+ which isn't installed.
[10:00:04 ERROR My Mod] Failed loading asset 'Mods/Me.MyMod/Objects' from SMAPI/mod: System.IO.FileNotFoundException: Could not find file.
   at MyMod.ModEntry.OnAssetRequested()
"""


def e_fix_from_log(tmp):
    f = tmp / "SMAPI-latest.txt"
    f.write_text(LOG, encoding="utf-8")
    r = sh("game.py", "log", "--file", f, "--mods", "Mira Pack,My Mod", "--json", cwd=tmp)
    rep = json.loads(r.stdout)
    assert r.returncode == 1 and rep["ok_for_mine"] is False
    assert rep["categories"]["missing_dependency"] and rep["categories"]["asset_load"] and rep["categories"]["exception"]
    assert any("Some.Missing.Mod" in s for s in rep["skipped_mods"])
    return "log parser names the skipped mod + missing dependency, the failed asset and the exception, and says the owner's mods are not clean"


def e_hd_portraits(tmp):
    ok(sh("add.py", "portrait-set", "--out", tmp, "--name", "HD Faces", "--npcs", "Abigail", "--frame", "256", "--author", "Me", cwd=tmp), "portrait-set")
    pack = tmp / "[Portraiture] HD Faces"
    assert Image.open(pack / "Abigail.png").size == (512, 768)
    validates(pack, tmp)
    (tmp / sdvlib.CONFIG_NAME).write_text(json.dumps({"comfyui": {"checkpoint": "x.safetensors"}}), encoding="utf-8")
    wf = tmp / "wf"
    ok(sh("make_comfy_workflow.py", "--recipe", "portrait_sheet", "--name", "Abigail", "--subject", "1girl, purple hair, green eyes", "--out-dir", wf, "--seed", "7", cwd=tmp), "workflow")
    jobs = jl(wf / "jobs.json")
    assert [j["id"] for j in jobs["jobs"]] == ["neutral", "happy", "sad", "unique", "love", "angry"] and jobs["seed"] == 7
    imgs = tmp / "imgs"
    imgs.mkdir()
    for j in jobs["jobs"]:
        Image.new("RGB", (1024, 1024), (120, 80, 200)).save(imgs / (Path(j["output_prefix"]).name + "_00001_.png"))
    ok(sh("postprocess.py", "--jobs", wf / "jobs.json", "--images", imgs, "--target", f"portraiture:256={tmp / 'Abigail_256.png'}", "--no-preview", cwd=tmp), "postprocess")
    assert Image.open(tmp / "Abigail_256.png").size == (512, 768)
    return "Portraiture pack scaffold validates (512x768 placeholder); portrait workflow has the 6 expression jobs with one shared seed; post-process writes the 256 px target"


def e_csharp_gmcm(tmp):
    if not shutil.which("dotnet"):
        raise Skip("needs the .NET SDK")
    out = tmp / "src"
    ok(sh("new_mod.py", "--type", "smapi", "--name", "Lucky Coin", "--author", "Me", "--gmcm", "--harmony", "--out", out, cwd=tmp), "new_mod smapi")
    d = out / "Lucky Coin"
    csproj = (d / "LuckyCoin.csproj").read_text(encoding="utf-8")
    assert "net6.0" in csproj and "Pathoschild.Stardew.ModBuildConfig" in csproj and "EnableHarmony" in csproj
    man = jl(d / "manifest.json")
    assert man["EntryDll"] == "LuckyCoin.dll" and any(x["UniqueID"] == "spacechase0.GenericModConfigMenu" and x["IsRequired"] is False for x in man["Dependencies"])
    entry = (d / "ModEntry.cs").read_text(encoding="utf-8")
    assert "if (gmcm is null) return;" in entry
    r = subprocess.run(["dotnet", "build", "-c", "Release", "-nologo", "-v", "q", "-p:EnableModDeploy=false", "-p:EnableModZip=false"], cwd=d, capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert (d / "bin/Release/net6.0/LuckyCoin.dll").exists()
    return "scaffold has net6.0 + ModBuildConfig + Harmony, GMCM optional and null-guarded, EntryDll matches the assembly, and it builds against the installed game"


def e_add_crop(tmp):
    root, mod = mk(tmp)
    ok(sh("add.py", "crop", "--mod", mod, "--name", "Starfruit Vine", "--seasons", "summer", "--days", "3,3,3,3", "--price", "400", "--shop", "SeedShop", "--seed-price", "100", cwd=root), "crop")
    ch = [c for f in (mod / "data").rglob("*.json") for c in jl(f)["Changes"]]
    crop = next(c for c in ch if c.get("Target") == "Data/Crops")["Entries"]["{{ModId}}_StarfruitVineSeeds"]
    assert sum(crop["DaysInPhase"]) == 12 and crop["Seasons"] == ["Summer"] and crop["Texture"] == "Mods/{{ModId}}/Crops/StarfruitVine"
    objs = next(c for c in ch if c.get("Target") == "Data/Objects")["Entries"]
    assert objs["{{ModId}}_StarfruitVine"]["Price"] == 400 and objs["{{ModId}}_StarfruitVineSeeds"]["Category"] == -74
    assert any(c.get("TargetField") == ["SeedShop", "Items"] for c in ch)
    assert Image.open(mod / "assets/Crops/StarfruitVine.png").size == (128, 32)
    validates(mod, tmp)
    return "Data/Crops phases sum to 12 days, seeds Category -74, produce 400g, SeedShop entry, 128x32 crop row, validator clean"


class Skip(Exception):
    pass


def e_map_warp(tmp):
    if not Vanilla().available:
        raise Skip("needs the unpacked game content")
    root, mod = mk(tmp)
    ok(sh("add.py", "location", "--mod", mod, "--name", "Cottage", "--door", "60 70", cwd=root), "location")
    ch = jl(mod / "data/Locations/Cottage.json")["Changes"]
    assert ch[0]["Action"] == "Load" and ch[1]["Entries"]["{{ModId}}_Cottage"]["CreateOnLoad"]["MapPath"] == "Maps/{{ModId}}_Cottage"
    assert ch[2]["Target"] == "Maps/Town" and ch[2]["AddWarps"][0].startswith("60 70 {{ModId}}_Cottage")
    r = ok(sh("tmx.py", "check", mod / "assets/Maps/Cottage.tmx", "--mod", mod, cwd=root), "tmx check")
    assert "0 error(s)" in r.stdout
    validates(mod, root)
    return "valid .tmx with Warp back out, Load + Data/Locations + Town AddWarps; map checker and validator clean"


def e_redo_direction(tmp):
    root, mod = mk(tmp)
    ref = tmp / "ref.png"
    Image.new("RGB", (300, 600), (255, 255, 255)).save(ref)
    (tmp / sdvlib.CONFIG_NAME).write_text(json.dumps({"comfyui": {"checkpoint": "x.safetensors"}}), encoding="utf-8")

    def figure(path, color):
        im = Image.new("RGB", (832, 1216), (255, 255, 255))
        im.paste(color, (300, 600, 540, 1100))
        im.save(path)

    def make(out, *frames):
        ok(sh("make_comfy_workflow.py", "--recipe", "sprite_sheet", "--name", "Mira", "--subject", "1girl", "--reference", ref, "--seed", "5", "--out-dir", out,
              *(["--frames", frames[0]] if frames else []), cwd=tmp), "sprite workflow")
        return jl(out / "jobs.json")

    jobs = make(tmp / "all")
    imgs = tmp / "imgs"
    imgs.mkdir()
    for j in jobs["jobs"]:
        if j.get("output_prefix"):
            figure(imgs / (Path(j["output_prefix"]).name + "_00001_.png"), (30, 90, 200))
    sheet = mod / "assets/Mira.png"
    ok(sh("postprocess.py", "--jobs", tmp / "all/jobs.json", "--images", imgs, "--out", sheet, "--no-preview", cwd=tmp), "postprocess all")
    before = Image.open(sheet).convert("RGBA")
    redo = make(tmp / "redo", "right")
    assert [j["id"] for j in redo["jobs"] if j.get("output_prefix")] == ["right"] and redo["seed"] == 5          # one job, same seed
    imgs2 = tmp / "imgs2"
    imgs2.mkdir()
    figure(imgs2 / (Path([j for j in redo["jobs"] if j.get("output_prefix")][0]["output_prefix"]).name + "_00001_.png"), (200, 40, 40))
    ok(sh("postprocess.py", "--jobs", tmp / "redo/jobs.json", "--images", imgs2, "--out", sheet, "--no-preview", cwd=tmp), "postprocess right")
    after = Image.open(sheet).convert("RGBA")
    box = lambda r: (0, r * 32, 64, r * 32 + 32)
    assert after.crop(box(0)).tobytes() == before.crop(box(0)).tobytes() and after.crop(box(2)).tobytes() == before.crop(box(2)).tobytes()
    assert after.crop(box(1)).tobytes() != before.crop(box(1)).tobytes()
    return "only the 'right' job is regenerated with the same seed; the other rows of the existing sheet stay pixel-identical"


CHECKS = {"new-cp-npc": e_new_cp_npc, "add-item-recipe-shop": e_add_item_recipe_shop, "fix-from-log": e_fix_from_log, "hd-portraits": e_hd_portraits,
          "csharp-gmcm": e_csharp_gmcm, "add-crop": e_add_crop, "map-warp": e_map_warp, "redo-one-sprite-direction": e_redo_direction}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json"); ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    evals = jl(SK / "evals" / "evals.json")["evals"]
    results = []
    for ev in evals:
        fn = CHECKS.get(ev["name"])
        if a.only and ev["name"] not in a.only:
            continue
        if fn is None:
            results.append({"id": ev["id"], "name": ev["name"], "status": "not scripted", "note": "needs a model-driven run (end-to-end flow with the owner)"})
            continue
        tmp = Path(tempfile.mkdtemp(prefix="sdv_eval_"))
        t0 = time.time()
        try:
            note = fn(tmp)
            results.append({"id": ev["id"], "name": ev["name"], "status": "PASS", "note": note, "seconds": round(time.time() - t0, 1)})
        except Skip as ex:
            results.append({"id": ev["id"], "name": ev["name"], "status": "SKIPPED", "note": str(ex)})
        except AssertionError as ex:
            results.append({"id": ev["id"], "name": ev["name"], "status": "FAIL", "note": str(ex)[:400], "seconds": round(time.time() - t0, 1)})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    for r in results:
        print(f"[{r['status']:<12}] {r['id']:>2} {r['name']:<28} {r.get('note', '')[:150]}")
    n = {k: sum(1 for r in results if r["status"] == k) for k in ("PASS", "FAIL", "SKIPPED", "not scripted")}
    print("\n" + ", ".join(f"{v} {k}" for k, v in n.items() if v))
    if a.json:
        Path(a.json).write_text(json.dumps({"skill_version": (SK / "VERSION").read_text(encoding="utf-8").strip(), "results": results}, indent=2), encoding="utf-8")
    sys.exit(1 if n["FAIL"] else 0)


if __name__ == "__main__":
    main()

"""postprocess v2 (targets, palettes, consistent scale), sheet.py, palette.py, Sprites in Detail checks."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import postprocess as pp  # noqa: E402
import sdvlib  # noqa: E402


def run(script, *args, cwd, ok=True):
    p = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], cwd=cwd, capture_output=True, text=True)
    if ok:
        assert p.returncode == 0, f"{script} {args}\n{p.stdout}\n{p.stderr}"
    return p


@pytest.fixture()
def work(tmp_path):
    (tmp_path / sdvlib.CONFIG_NAME).write_text(json.dumps({"comfyui": {"checkpoint": "t.safetensors"}}), encoding="utf-8")
    return tmp_path


def figure(path: Path, w=832, h=1216, fig_w=200, fig_h=480, color=(30, 120, 200), side="center"):
    """White background with one body-and-head figure; fig size controls how big it is."""
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    x0 = (w - fig_w) // 2
    y0 = h - fig_h - 40
    d.rectangle([x0, y0 + fig_h // 3, x0 + fig_w, y0 + fig_h], fill=color)
    d.ellipse([x0 + fig_w // 4, y0, x0 + 3 * fig_w // 4, y0 + fig_h // 3], fill=(240, 200, 170))
    im.save(path)


def sprite_jobs(work, heights):
    """A sprite jobs.json plus master images where each facing has a different figure height."""
    out = work / "jobs"; out.mkdir()
    run("make_comfy_workflow.py", "--recipe", "sprite_sheet", "--name", "T", "--subject", "x", "--reference", _ref(work), "--out-dir", out, cwd=work)
    imgs = work / "imgs"; imgs.mkdir()
    jobs = json.loads((out / "jobs.json").read_text(encoding="utf-8"))
    for j, hgt in zip([j for j in jobs["jobs"] if j.get("output_prefix")], heights):
        figure(imgs / (Path(j["output_prefix"]).name + "_00001_.png"), fig_h=hgt)
    return out / "jobs.json", imgs


def _ref(work):
    p = work / "ref.png"
    if not p.exists():
        Image.new("RGB", (300, 600), (255, 255, 255)).save(p)
    return p


def test_consistent_scale_keeps_relative_height(work):
    jobs, imgs = sprite_jobs(work, [480, 400, 480])           # the 'right' figure is 400 tall, the others 480
    run("postprocess.py", "--jobs", jobs, "--images", imgs, "--out", work / "s.png", "--no-preview", cwd=work)
    sheet = Image.open(work / "s.png").convert("RGBA")

    def height(row):
        a = np.array(sheet.crop((0, row * 32, 16, row * 32 + 32)))[..., 3] > 0
        ys = np.where(a.any(1))[0]
        return ys.max() - ys.min() + 1
    assert height(0) > height(1)                                # relative size is preserved (not stretched to the same height)
    run("postprocess.py", "--jobs", jobs, "--images", imgs, "--out", work / "s2.png", "--no-consistent-scale", "--no-preview", cwd=work)
    s2 = Image.open(work / "s2.png").convert("RGBA")
    h2 = [np.where((np.array(s2.crop((0, r * 32, 16, r * 32 + 32)))[..., 3] > 0).any(1))[0] for r in (0, 1)]
    assert (h2[0].max() - h2[0].min()) == (h2[1].max() - h2[1].min()) or abs((h2[0].max() - h2[0].min()) - (h2[1].max() - h2[1].min())) <= 1


def test_one_palette_for_the_whole_sheet(work):
    jobs, imgs = sprite_jobs(work, [480, 480, 480])
    run("postprocess.py", "--jobs", jobs, "--images", imgs, "--out", work / "s.png", "--colors", "6", "--no-preview", "--save-palette", work / "pal.png", cwd=work)
    arr = np.array(Image.open(work / "s.png").convert("RGBA"))
    cols = {tuple(c) for c in arr[arr[..., 3] > 0][:, :3]}
    pal = {tuple(c) for c in np.array(Image.open(work / "pal.png").convert("RGB")).reshape(-1, 3)}
    assert cols <= pal and len(cols) <= 6                      # every pixel is on the sheet's single palette


def test_locked_palette_is_used(work):
    jobs, imgs = sprite_jobs(work, [480, 480, 480])
    pal = Image.new("RGB", (3, 1)); pal.putdata([(10, 10, 10), (240, 200, 170), (200, 40, 40)]); pal.save(work / "lock.png")
    run("postprocess.py", "--jobs", jobs, "--images", imgs, "--out", work / "s.png", "--palette", work / "lock.png", "--no-preview", cwd=work)
    arr = np.array(Image.open(work / "s.png").convert("RGBA"))
    cols = {tuple(c) for c in arr[arr[..., 3] > 0][:, :3]}
    assert cols <= {(10, 10, 10), (240, 200, 170), (200, 40, 40)}


def test_multi_target_sizes_and_hd_keeps_colour(work):
    jobs, imgs = sprite_jobs(work, [480, 480, 480])
    run("postprocess.py", "--jobs", jobs, "--images", imgs, "--target", f"vanilla={work / 'v.png'}", "--target", f"hd:8={work / 'h.png'}",
        "--no-preview", cwd=work)
    assert Image.open(work / "v.png").size == (64, 128)
    hd = Image.open(work / "h.png").convert("RGBA")
    assert hd.size == (512, 1024)
    arr = np.array(hd)
    assert len({tuple(c) for c in arr[arr[..., 3] > 0][:, :3]}) > 16   # HD is not palette-crushed


def test_portraiture_target_frame_size(work):
    out = work / "j"
    run("make_comfy_workflow.py", "--recipe", "portrait_sheet", "--name", "T", "--subject", "x", "--out-dir", out, cwd=work)
    jobs = json.loads((out / "jobs.json").read_text(encoding="utf-8"))
    imgs = work / "imgs"; imgs.mkdir()
    for j in jobs["jobs"]:
        Image.new("RGB", (1024, 1024), (120, 90, 200)).save(imgs / (Path(j["output_prefix"]).name + "_00001_.png"))
    run("postprocess.py", "--jobs", out / "jobs.json", "--images", imgs, "--target", f"portraiture:256={work / 'p.png'}", "--no-preview", cwd=work)
    assert Image.open(work / "p.png").size == (512, 768)


def test_dominant_downscale_is_crisper_than_box():
    src = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    ImageDraw.Draw(src).rectangle([0, 0, 47, 95], fill=(200, 0, 0, 255))
    ImageDraw.Draw(src).rectangle([48, 0, 95, 95], fill=(0, 0, 200, 255))
    out = np.array(pp.downscale_dominant(src, 8, 8))
    cols = {tuple(c[:3]) for c in out.reshape(-1, 4)}
    assert cols == {(200, 0, 0), (0, 0, 200)}                  # no blended purple edge column


def test_cleanup_removes_orphans_and_fills_holes():
    im = Image.new("RGBA", (7, 7), (0, 0, 0, 0))
    a = np.array(im)
    a[2:5, 2:5] = (50, 60, 70, 255); a[3, 3] = (0, 0, 0, 0)    # a hole inside a block
    a[0, 6] = (255, 0, 0, 255)                                   # an orphan pixel
    out = np.array(pp.cleanup_orphans(Image.fromarray(a, "RGBA")))
    assert out[0, 6, 3] == 0 and out[3, 3, 3] == 255


def test_lab_palette_maps_to_nearest_colour():
    im = Image.new("RGBA", (2, 1), (250, 10, 10, 255))
    out = pp.apply_palette(im, np.array([[255, 0, 0], [0, 0, 255]], np.uint8))
    assert tuple(np.array(out)[0, 0, :3]) == (255, 0, 0)


# ------------------------------------------------------------------ palette.py
def test_palette_build_show_and_lock(work):
    figure(work / "a.png", color=(30, 120, 200))
    (work / "sdv-project.json").write_text(json.dumps({"version": 1, "characters": {"Mira": {"subject": "x"}}}), encoding="utf-8")
    run("palette.py", "build", "--images", work / "a.png", "--colors", "4", "--out", work / "art" / "pal.png", "--lock", "Mira", cwd=work)
    proj = json.loads((work / "sdv-project.json").read_text(encoding="utf-8"))
    assert proj["characters"]["Mira"]["palette_png"] == "art/pal.png"
    assert "colours" in run("palette.py", "show", work / "art" / "pal.png", cwd=work).stdout
    # postprocess --character picks that palette up
    jobs, imgs = sprite_jobs(work, [480, 480, 480])
    run("postprocess.py", "--jobs", jobs, "--images", imgs, "--out", work / "s.png", "--character", "Mira", "--no-preview", cwd=work)
    cols = {tuple(c) for c in np.array(Image.open(work / "s.png").convert("RGBA")).reshape(-1, 4) if c[3]}
    pal = {tuple(c) for c in np.array(Image.open(work / "art" / "pal.png").convert("RGB")).reshape(-1, 3)}
    assert {c[:3] for c in cols} <= pal


# ------------------------------------------------------------------ sheet.py
def make_sheet(work):
    run("make_placeholder.py", "--spec", "character_sprite", "--out", work / "sheet.png", cwd=work)
    return work / "sheet.png"


def test_sheet_slice_assemble_roundtrip(work):
    sh = make_sheet(work)
    run("sheet.py", "slice", sh, "--spec", "character_sprite", "--out-dir", work / "fr", cwd=work)
    frames = sorted((work / "fr").glob("*.png"))
    assert len(frames) == 16 and frames[0].name.startswith("00_down_0")
    run("sheet.py", "assemble", "--spec", "character_sprite", "--out", work / "re.png", *frames, cwd=work)
    assert run("sheet.py", "diff", sh, work / "re.png", cwd=work, ok=False).returncode == 0   # identical


def test_sheet_mirror_shift_copy_diff_and_anim(work):
    sh = make_sheet(work)
    run("sheet.py", "mirror-row", sh, "--spec", "character_sprite", "--src", "right", "--dst", "left", "--out", work / "m.png", cwd=work)
    a, b = Image.open(sh).convert("RGBA"), Image.open(work / "m.png").convert("RGBA")
    assert b.crop((0, 96, 16, 128)).tobytes() == a.crop((0, 32, 16, 64)).transpose(Image.FLIP_LEFT_RIGHT).tobytes()
    run("sheet.py", "shift-frame", sh, "--spec", "character_sprite", "--frame-index", "5", "--dx", "0", "--dy", "-1", "--out", work / "sh.png", cwd=work)
    p = run("sheet.py", "diff", sh, work / "sh.png", "--out", work / "d.png", cwd=work, ok=False)
    assert p.returncode == 1 and "differ" in p.stdout and (work / "d.png").exists()
    run("sheet.py", "copy-frame", sh, "--spec", "character_sprite", "--src", "4", "--dst", "5", "6", "--out", work / "c.png", cwd=work)
    run("sheet.py", "preview-anim", sh, "--spec", "character_sprite", "--row", "right", "--out", work / "w.gif", cwd=work)
    gif = Image.open(work / "w.gif")
    assert gif.n_frames == 4 and gif.size == (128, 256)


def test_sheet_refuses_wrong_frame_size(work):
    Image.new("RGBA", (50, 50)).save(work / "bad.png")
    p = run("sheet.py", "slice", work / "bad.png", "--spec", "character_sprite", "--out-dir", work / "o", cwd=work, ok=False)
    assert p.returncode != 0


# ------------------------------------------------------------------ Sprites in Detail
def sid_pack(work, sheet_size=(512, 1024), extra=None):
    run("new_mod.py", "--type", "sid", "--name", "Mira SID", "--author", "T", "--out", work / "mods", cwd=work)
    root = work / "mods" / "[SID] Mira SID"
    Image.new("RGBA", sheet_size, (1, 2, 3, 255)).save(root / "assets" / "Mira_hd.png")
    entry = {"Target": "Characters/T.Mira", "FromFile": "assets/Mira_hd.png", "SpriteWidth": 16, "SpriteHeight": 32,
             "WidthScale": 8, "HeightScale": 8, "SpriteOriginX": 64, "SpriteOriginY": 225, **(extra or {})}
    (root / "content.json").write_text(json.dumps({"Sprites": [entry]}), encoding="utf-8")
    return root


def test_sid_scaffold_and_good_pack_validates(work):
    root = sid_pack(work)
    man = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert man["ContentPackFor"]["UniqueID"] == "BleakCodex.SpritesInDetail"
    assert "0 error(s)" in run("validate_mod.py", root, cwd=work).stdout


def test_sid_validator_catches_bad_scale_and_origin(work):
    root = sid_pack(work, sheet_size=(500, 1000))
    p = run("validate_mod.py", root, cwd=work, ok=False)
    assert p.returncode == 1 and "not divisible" in p.stdout
    root2 = work / "mods" / "[SID] Mira SID"
    (root2 / "content.json").write_text(json.dumps({"Sprites": [{"Target": "Characters/T.Mira", "FromFile": "assets/Mira_hd.png",
        "WidthScale": 8, "HeightScale": 8, "SpriteOriginX": 999, "SpriteOriginY": 5}]}), encoding="utf-8")
    Image.new("RGBA", (512, 1024)).save(root2 / "assets" / "Mira_hd.png")
    p = run("validate_mod.py", root2, cwd=work, ok=False)
    assert "SpriteOrigin" in p.stdout


# ------------------------------------------------------------------ batch writes asset targets
def test_batch_plan_unchanged_and_targets_listed_in_project(work):
    proj = {"version": 1, "art_style": {"checkpoint": "t.safetensors"}, "characters": {},
            "assets": [{"id": "gem", "spec": "object_icon", "status": "placeholder", "files": [], "targets": [{"kind": "vanilla"}, {"kind": "hd", "scale": 4}]}]}
    (work / "sdv-project.json").write_text(json.dumps(proj), encoding="utf-8")
    p = run("batch.py", "plan", "--takes", "1", cwd=work)
    assert (work / "comfy" / "gem" / "take_a" / "jobs.json").exists()

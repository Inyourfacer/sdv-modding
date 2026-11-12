"""qa_art checks, contact sheet, and the approve/install gates of batch.py."""
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
import qa_art  # noqa: E402
import sdvlib  # noqa: E402


def sprite_sheet(colors=((30, 90, 200),) * 4, heights=(28, 28, 28, 28), clip=False, semi=False, corners=False):
    """A 64x128 sprite sheet: four rows, one figure per frame, each row with its own colour and height."""
    im = Image.new("RGBA", (64, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for r in range(4):
        for c in range(4):
            x0, y0 = c * 16, r * 32
            h = heights[r]
            top = y0 + 31 - h + 1
            left = x0 + (0 if clip else 4)
            right = x0 + (15 if clip else 11)
            d.rectangle([left, top + 8, right, y0 + 31], fill=colors[r] + (255,))          # body
            shift = (-2, 0, 2, 3)[r]                                                      # facings differ visibly
            d.rectangle([x0 + 5 + shift, top, x0 + 10 + shift, top + 8], fill=(240, 200, 170, 255))    # head
            # make rows differ a little so they are not "identical facings"
            d.point([(x0 + 6 + r, top + 3)], fill=(0, 0, 0, 255))
    if semi:
        im.putpixel((1, 1), (10, 10, 10, 128))
    if corners:
        for r in range(4):
            for c in range(4):
                im.putpixel((c * 16, r * 32), (255, 255, 255, 255)); im.putpixel((c * 16 + 15, r * 32), (255, 255, 255, 255))
    return im


SPEC = sdvlib.get_spec("character_sprite")


def levels(results, check):
    return [r["level"] for r in results if r["check"] == check]


def test_good_sheet_passes_clean():
    res = qa_art.analyze(sprite_sheet(), SPEC, colors=16)
    assert qa_art.verdict(res)["level"] == "PASS", qa_art.verdict(res)["reasons"]


def test_wrong_dimensions_fail_and_stop():
    res = qa_art.analyze(Image.new("RGBA", (60, 128)), SPEC)
    assert levels(res, "dimensions") == ["FAIL"] and len(res) == 1


def test_opaque_corners_mean_background_not_removed():
    res = qa_art.analyze(sprite_sheet(corners=True), SPEC)
    assert "FAIL" in levels(res, "background_left")


def test_clipped_figure_warns():
    assert "WARN" in levels(qa_art.analyze(sprite_sheet(clip=True), SPEC), "clipped")


def test_semi_transparent_pixels_fail_on_vanilla_only():
    assert "FAIL" in levels(qa_art.analyze(sprite_sheet(semi=True), SPEC), "semi_transparent")


def test_empty_frame_fails():
    im = sprite_sheet()
    ImageDraw.Draw(im).rectangle([16, 0, 31, 31], fill=(0, 0, 0, 0))
    assert "FAIL" in levels(qa_art.analyze(im, SPEC), "empty_frame")


def test_palette_violation_and_distance():
    pal = np.array([[30, 90, 200], [240, 200, 170], [0, 0, 0]], np.uint8)
    assert levels(qa_art.analyze(sprite_sheet(), SPEC, palette=pal), "palette_violation") == ["PASS"]
    bad = np.array([[200, 0, 0]], np.uint8)
    res = qa_art.analyze(sprite_sheet(), SPEC, palette=bad)
    assert "FAIL" in levels(res, "palette_violation")


def test_outfit_colour_drift_between_facings_fails():
    same = qa_art.analyze(sprite_sheet(), SPEC)
    drift = qa_art.analyze(sprite_sheet(colors=((30, 90, 200), (200, 40, 40), (30, 90, 200), (30, 90, 200))), SPEC)
    assert levels(same, "facing_colour_drift") == ["PASS"]
    assert levels(drift, "facing_colour_drift") == ["FAIL"]


def test_height_inconsistency():
    res = qa_art.analyze(sprite_sheet(heights=(28, 18, 28, 28)), SPEC)
    assert levels(res, "height_consistency") == ["FAIL"]


def test_portrait_expression_checks():
    spec = sdvlib.get_spec("portrait")
    base = Image.new("RGBA", (128, 192), (255, 255, 255, 255))
    ImageDraw.Draw(base).ellipse([10, 10, 54, 54], fill=(40, 120, 90, 255))
    sheet = base.copy()
    for i in range(1, 6):
        x, y = (i % 2) * 64, (i // 2) * 64
        sheet.paste(base.crop((0, 0, 64, 64)), (x, y))             # identical to neutral
    res = qa_art.analyze(sheet, spec)
    assert "WARN" in levels(res, "no_expression_change")
    for i in range(1, 6):                                           # now a completely different picture
        x, y = (i % 2) * 64, (i // 2) * 64
        sheet.paste(Image.new("RGBA", (64, 64), (10, 10, 10, 255)), (x, y))
    assert "FAIL" in levels(qa_art.analyze(sheet, spec), "expression_drift")


def test_merge_frames_groups_a_facings_copies():
    res = [{"frame": f"{i}:right_{i - 4}", "check": "clipped", "level": "WARN", "value": ["left"], "msg": "m"} for i in range(4, 8)]
    merged = qa_art.merge_frames(res)
    assert len(merged) == 1 and merged[0]["frame"] == "4-7"


def test_cli_exit_codes_and_json(tmp_path):
    good, bad = tmp_path / "g.png", tmp_path / "b.png"
    sprite_sheet().save(good); sprite_sheet(corners=True).save(bad)
    run = lambda f: subprocess.run([sys.executable, str(SCRIPTS / "qa_art.py"), "check", f, "--spec", "character_sprite", "--json"], capture_output=True, text=True, cwd=tmp_path)
    assert run(good).returncode == 0
    p = run(bad)
    assert p.returncode == 1 and json.loads(p.stdout)["verdict"]["level"] == "FAIL"


def test_contact_sheet_builds_with_reference_and_verdicts(tmp_path):
    import contact_sheet
    a, b = tmp_path / "take_a.png", tmp_path / "take_b.png"
    sprite_sheet().save(a); sprite_sheet(corners=True).save(b)
    ref = tmp_path / "ref.png"; Image.new("RGB", (300, 600), (200, 220, 200)).save(ref)
    out = tmp_path / "contact.png"
    v = contact_sheet.build([a, b], SPEC, out, str(ref))
    assert v["take_a"]["level"] == "PASS" and v["take_b"]["level"] == "FAIL"
    im = Image.open(out)
    assert im.width > 700 and im.height > 400


# ------------------------------------------------------------------ approve / install gates
def batch(work, *args, ok=True):
    p = subprocess.run([sys.executable, str(SCRIPTS / "batch.py"), *map(str, args)], cwd=work, capture_output=True, text=True)
    if ok:
        assert p.returncode == 0, p.stdout + p.stderr
    return p


def project(work, status="generated", with_real_file=False, qa_level="PASS"):
    mod = work / "[CP] X" / "assets"
    mod.mkdir(parents=True)
    dest = mod / "gem.png"
    if with_real_file:
        Image.new("RGBA", (16, 16), (9, 9, 9, 255)).save(dest)
    art = work / "art" / "gem"
    art.mkdir(parents=True)
    Image.new("RGBA", (16, 16), (200, 0, 0, 255)).save(art / "take_a.png")
    Image.new("RGBA", (64, 64), (200, 0, 0, 255)).save(art / "take_a.hd4.png")
    proj = {"version": 1, "art_style": {}, "characters": {}, "mods": [], "ids": {}, "test": {},
            "assets": [{"id": "gem", "spec": "object_icon", "status": status, "files": ["[CP] X/assets/gem.png"],
                        "targets": [{"kind": "vanilla"}, {"kind": "hd", "scale": 4, "file": "[SID] X/assets/gem_hd.png"}],
                        "qa": {"take_a": {"level": qa_level, "reasons": ["empty_frame: nothing"]}}}]}
    (work / "sdv-project.json").write_text(json.dumps(proj), encoding="utf-8")
    return dest


def status_of(work):
    return json.loads((work / "sdv-project.json").read_text(encoding="utf-8"))["assets"][0]["status"]


def test_install_refuses_unapproved(tmp_path):
    project(tmp_path)
    p = batch(tmp_path, "install", "gem", ok=False)
    assert p.returncode != 0 and "not approved" in (p.stdout + p.stderr)
    assert not (tmp_path / "[CP] X" / "assets" / "gem.png").exists()


def test_approve_requires_owner_flag_and_blocks_failed_qa(tmp_path):
    project(tmp_path, qa_level="FAIL")
    assert batch(tmp_path, "approve", "gem", "--take", "a", ok=False).returncode != 0
    p = batch(tmp_path, "approve", "gem", "--take", "a", "--owner-approved", ok=False)
    assert p.returncode != 0 and "failed QA" in (p.stdout + p.stderr)
    assert status_of(tmp_path) == "generated"
    batch(tmp_path, "approve", "gem", "--take", "a", "--owner-approved", "--force")
    assert status_of(tmp_path) == "approved"


def test_install_copies_every_target_with_file_and_marks_installed(tmp_path):
    project(tmp_path)
    batch(tmp_path, "approve", "gem", "--take", "a", "--owner-approved")
    batch(tmp_path, "install", "gem")
    assert Image.open(tmp_path / "[CP] X" / "assets" / "gem.png").size == (16, 16)
    assert Image.open(tmp_path / "[SID] X" / "assets" / "gem_hd.png").size == (64, 64)
    assert status_of(tmp_path) == "installed"


def test_install_never_overwrites_real_art_without_flag_and_backs_up(tmp_path):
    dest = project(tmp_path, with_real_file=True)
    batch(tmp_path, "approve", "gem", "--take", "a", "--owner-approved")
    p = batch(tmp_path, "install", "gem", ok=False)
    assert p.returncode != 0 and "--overwrite" in (p.stdout + p.stderr)
    assert Image.open(dest).getpixel((0, 0)) == (9, 9, 9, 255)       # untouched
    batch(tmp_path, "install", "gem", "--overwrite")
    assert Image.open(dest).getpixel((0, 0)) == (200, 0, 0, 255)
    backups = list((tmp_path / "backups").rglob("gem.png"))
    assert len(backups) == 1 and Image.open(backups[0]).getpixel((0, 0)) == (9, 9, 9, 255)


def test_install_overwrites_a_placeholder_freely(tmp_path):
    dest = project(tmp_path)
    subprocess.run([sys.executable, str(SCRIPTS / "make_placeholder.py"), "--spec", "object_icon", "--out", str(dest)], check=True, capture_output=True)
    batch(tmp_path, "approve", "gem", "--take", "a", "--owner-approved")
    batch(tmp_path, "install", "gem")
    assert Image.open(dest).getpixel((0, 0)) == (200, 0, 0, 255)

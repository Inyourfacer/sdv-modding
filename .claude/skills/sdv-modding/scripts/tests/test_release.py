"""release.py (validate, versions, changelog, zips, draft) and package_skill.py (lint, zip, compare)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import package_skill  # noqa: E402
import sdvlib  # noqa: E402


def run(script, *args, cwd):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], cwd=cwd, capture_output=True, text=True)


@pytest.fixture()
def proj(tmp_path):
    root = tmp_path / "proj"
    for name in ("A", "B"):
        subprocess.run([sys.executable, str(SCRIPTS / "new_mod.py"), "--type", "cp", "--name", name, "--author", "T", "--out", str(root)], check=True, capture_output=True)
    a, b = root / "[CP] A", root / "[CP] B"
    man_b = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
    man_b["Dependencies"] = [{"UniqueID": "T.A"}]
    (b / "manifest.json").write_text(json.dumps(man_b, indent=4), encoding="utf-8")
    assert run("add.py", "item", "--mod", str(a), "--name", "Gem", cwd=root).returncode == 0
    return root, a, b


def real_art(a: Path):
    p = a / "assets" / "Objects" / "Gem.png"
    Image.new("RGBA", (16, 16), (200, 0, 0, 255)).save(p)                          # no placeholder tag = real art


def release(root, *mods, extra=()):
    return run("release.py", *mods, "--version", extra[0] if extra else "1.1.0", *extra[1:], cwd=root)


def test_release_is_blocked_by_validation_errors_and_writes_nothing(proj):
    root, a, b = proj
    real_art(a)
    (a / "content.json").write_text("{ not json", encoding="utf-8")
    before = (a / "manifest.json").read_text(encoding="utf-8")
    r = release(root, a)
    assert r.returncode == 1 and "Release blocked" in r.stdout
    assert (a / "manifest.json").read_text(encoding="utf-8") == before and not (root / "releases").exists() and not (root / "CHANGELOG.md").exists()


def test_leftover_placeholder_art_blocks_unless_allowed(proj):
    root, a, b = proj
    r = release(root, a)
    assert r.returncode == 1 and "placeholder" in r.stdout
    assert release(root, a, extra=("1.1.0", "--allow-placeholders")).returncode == 0


def test_full_release_versions_zips_changelog_and_draft(proj):
    root, a, b = proj
    real_art(a)
    (a / "config.json").write_text("{}", encoding="utf-8")                     # per-player file: must not ship
    (a / "assets" / "x_preview.png").write_bytes(b"x")
    (root / "backups" / "t").mkdir(parents=True)
    (a / "backups").mkdir()
    (a / "backups" / "old.json").write_text("{}", encoding="utf-8")
    man_a_before = (a / "manifest.json").read_text(encoding="utf-8")
    r = run("release.py", a, b, "--version", "1.1.0", "--note", "Added the Gem", "--update-key", "Nexus:999", cwd=root)
    assert r.returncode == 0, r.stdout + r.stderr
    # versions: only the Version value changes in A (formatting kept); B's dependency gets MinimumVersion
    man_a = (a / "manifest.json").read_text(encoding="utf-8")
    assert '"Version": "1.1.0"' in man_a and man_a.replace("1.1.0", "1.0.0").splitlines()[:3] == man_a_before.splitlines()[:3]
    assert json.loads(man_a)["UpdateKeys"] == ["Nexus:999"]
    man_b = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
    assert man_b["Version"] == "1.1.0" and man_b["Dependencies"][0]["MinimumVersion"] == "1.1.0"
    # zips
    rel = root / "releases"
    za = rel / "[CP] A 1.1.0.zip"
    names = zipfile.ZipFile(za).namelist()
    assert "[CP] A/manifest.json" in names and "[CP] A/data/Items/Gem.json" in names and "[CP] A/assets/Objects/Gem.png" in names
    assert not any(n.endswith(("config.json", "_preview.png")) or "/backups/" in n for n in names)
    allz = zipfile.ZipFile(rel / "proj 1.1.0 (all).zip").namelist()
    assert "[CP] B/manifest.json" in allz and "[CP] A/manifest.json" in allz
    # changelog, project record, draft
    cl = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert cl.startswith("# Changelog") and "## 1.1.0" in cl and "Added the Gem" in cl and "object T.A_Gem" in cl
    p = json.loads((root / "sdv-project.json").read_text(encoding="utf-8"))
    assert p["release"]["version"] == "1.1.0" and "T.A_Gem" in p["release"]["ids"]
    desc = (rel / "proj 1.1.0 - description.md").read_text(encoding="utf-8")
    assert "Pathoschild.ContentPatcher" in desc and "Nothing was uploaded" in desc and "Added the Gem" in desc


def test_second_release_changelog_lists_only_what_is_new(proj):
    root, a, b = proj
    real_art(a)
    assert run("release.py", a, "--version", "1.1.0", "--note", "first", cwd=root).returncode == 0
    assert run("add.py", "item", "--mod", str(a), "--name", "Pearl", cwd=root).returncode == 0
    Image.new("RGBA", (16, 16), (1, 1, 1, 255)).save(a / "assets" / "Objects" / "Pearl.png")
    r = run("release.py", a, "--version", "1.2.0", "--note", "second", cwd=root)
    assert r.returncode == 0, r.stdout + r.stderr
    top = (root / "CHANGELOG.md").read_text(encoding="utf-8").split("## 1.1.0")[0]
    assert "second" in top and "T.A_Pearl" in top and "T.A_Gem" not in top
    assert "## 1.1.0" in (root / "CHANGELOG.md").read_text(encoding="utf-8")                  # older section kept


def test_dry_run_and_version_rules(proj):
    root, a, b = proj
    real_art(a)
    snap = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    r = run("release.py", a, "--version", "1.1.0", "--dry-run", cwd=root)
    assert r.returncode == 0 and "[dry-run]" in r.stdout
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == snap
    assert run("release.py", a, "--version", "1.0.0", cwd=root).returncode == 1            # not higher than the current 1.0.0
    assert run("release.py", a, "--version", "1.0.0", "--force-version", cwd=root).returncode == 0
    assert run("release.py", a, "--version", "banana", cwd=root).returncode != 0


# ------------------------------------------------------------------ package_skill
def test_skill_lints_clean_and_packages_without_tests_or_build_output(tmp_path):
    assert package_skill.lint() == []
    z = package_skill.build(tmp_path)
    names = zipfile.ZipFile(z).namelist()
    assert "sdv-modding/SKILL.md" in names and "sdv-modding/VERSION" in names and "sdv-modding/PACKAGE_MANIFEST.json" in names
    assert "sdv-modding/harness/SdvTestHarness/ModEntry.cs" in names and "sdv-modding/assets/gamedata_fields.json" in names
    assert not any("/tests/" in n or "/bin/" in n or "/obj/" in n or "__pycache__" in n or "/evals/" in n or n.endswith(".pyc") for n in names)
    assert package_skill.check(z) == 0                                                      # identical to the repo


def test_package_check_detects_drift_and_lint_catches_broken_references(tmp_path, monkeypatch):
    z = package_skill.build(tmp_path)
    copy = tmp_path / "copy"
    shutil.copytree(SKILL, copy, ignore=shutil.ignore_patterns("__pycache__", "bin", "obj", "out", ".pytest_cache"))
    monkeypatch.setattr(package_skill, "SKILL", copy)
    assert package_skill.check(z) == 0
    (copy / "references" / "troubleshooting.md").write_text("changed", encoding="utf-8")
    assert package_skill.check(z) == 1                                                      # a changed file is reported
    sk = copy / "SKILL.md"
    sk.write_text(sk.read_text(encoding="utf-8") + "\nSee `references/ghost.md` and scripts/ghost_tool.py.\n", encoding="utf-8")
    problems = package_skill.lint()
    assert any("references/ghost.md" in p for p in problems) and any("ghost_tool.py" in p for p in problems)
    sk.write_text("---\nname: other\ndescription: x\n---\n", encoding="utf-8")
    assert any("name must be" in p for p in package_skill.lint())

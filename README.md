# sdv-modding

Stardew Valley 1.6 mods, plus the `sdv-modding` Claude skill in `.claude/skills/sdv-modding/`. Any Claude Code session opened on this repo loads the skill automatically; ask for a Stardew modding task or type `/sdv-modding`.

## Layout
- `.claude/skills/sdv-modding/` — the skill (see its `SKILL.md`, `VERSION`)
  - `SKILL.md`, `references/` — instructions and topic references
  - `scripts/` — generators (`add.py`), validator (`validate_mod.py`, `vcheck.py`), art pipeline (`make_comfy_workflow.py`, `comfy.py`, `batch.py`, `postprocess.py`, `qa_art.py`, ...), in-game tests (`game.py`), maps (`tmx.py`), release (`release.py`), packaging (`package_skill.py`)
  - `harness/` — C# SMAPI test harness (source) and its unit tests; `tools/apidump` — game-DLL inspector
  - `assets/` — specs, presets, game-data field list, project example; `evals/` — eval prompts and scripted checks
- `mods/` — your mods (for example `mods/[CP] My Mod/`)
- `sdv-modding.config.json` — machine settings (`scripts/doctor.py --write-config` fills it); `sdv-project.json` — per-project memory

## Local use (Windows)
Clone and run `claude` inside the repo, or copy `.claude/skills/sdv-modding` to `%USERPROFILE%\.claude\skills\`. Needs Python 3.10+ with `pip install pillow numpy`; the .NET SDK for C# mods, the harness and `gamedata_fields.py`; ComfyUI for art generation.

## Developing the skill
```
python -m pytest .claude/skills/sdv-modding/scripts/tests -q        # ~2 minutes; some tests need dotnet / the unpacked game and skip without
python .claude/skills/sdv-modding/evals/run_scripted.py             # acceptance checks for the evals (tooling only, no model)
python .claude/skills/sdv-modding/scripts/package_skill.py --lint   # SKILL.md size, frontmatter, every referenced file exists, every reference routed
```
The repo is the single source of truth for the skill.

## Releasing the skill (to your claude.ai account)
1. Change the skill here; keep `SKILL.md` under 150 lines (detail goes in `references/`).
2. Bump `.claude/skills/sdv-modding/VERSION` (semantic version) and note the change in the commit message.
3. Run the tests and the scripted evals above; `package_skill.py --lint` must pass.
4. `python .claude/skills/sdv-modding/scripts/package_skill.py` writes `dist/sdv-modding-<version>.zip` (skill folder at the root, no tests/build output, plus `PACKAGE_MANIFEST.json`).
5. Upload the zip yourself in claude.ai Settings > Skills (replace the previous copy). Nothing here uploads anything.
6. `package_skill.py --check dist/<zip>` compares a zip with the repo (version and per-file hashes) so you can tell whether the account copy is current.

## Releasing a mod
`scripts/release.py "<mod folder>" ... --version 1.2.0 --note "..."` validates, bumps versions, writes the changelog, builds the zips and a draft description in `releases/`. It never uploads; see `references/release.md`.

# Handoff: Observatory mod (from the cloud session)

Read this first in a new Claude Code session. It summarizes decisions made in the cloud session that built this branch (`claude/fervent-fermi-35u25k`).

## What exists
- `mods/Observatory/`: C# SMAPI mod (telescope dial menu, connect-the-stars puzzle, star journal, star-chart bundle board, riddle and reveal-spot system, 3-day construction timer, 7 constellation perks). **Never compiled yet** (the cloud had no .NET SDK or game DLLs).
- `mods/[CP] Observatory/`: Content Patcher pack (interior, roof and Backwoods-exterior maps, Data/Locations, Maru 6-heart letter and town special-order unlocks, riddle letters, welcome and finale events, Maru/Wizard dialogue). Tile actions are `MapTiles` patches in `data/locations.json`.
- `tools/observatory/build_assets.py`: regenerates the maps and placeholder tilesheet, and pastes generated art from `tools/observatory/art/<piece>.png` into fixed slots.
- `comfy/observatory/`: 8 ComfyUI workflows (dome, telescope, board, desk, floor, wall, rug, deck). Steps are in its README.
- Design and test commands: `mods/Observatory/README.md`.

## Decisions
- Author/ID prefix `Inyourfacer`. Every shared ID uses `Inyourfacer.Observatory` (C# `Ids.cs`, CP token `{{Obs}}`), not the CP pack's `{{ModId}}`.
- Perks stack with professions. Seven constellations in v1.
- Art models (`sdv-modding.config.json`):
  - Locations and tilesheets (`tilesheet`, `building` specs, plus the telescope, board and desk via `--family flux`): Flux, `flux_dev.safetensors` (all-in-one, about 16 GB, in Stability Matrix `Data\Models\StableDiffusion`) + `stardew-valley-style-000012.safetensors`, trigger `STDW`.
  - Sprites and items: WAI Illustrious v17 (`waiIllustriousSDXL_v170.safetensors`, file name **unconfirmed**) + `coropata_pixel.safetensors` (0.8) + `pixel-art-xl.safetensors` (0.5) (file names **unconfirmed**).
  - Portraits: WAI v17 + `jab_illustrious_V1.5.safetensors` (**unconfirmed**).
- Stability Matrix / ComfyUI at `D:\stable defussion\Data\Packages\ComfyUI` (`comfyui_root`).
- Skill 2.0.0 is merged in. This branch also adds **Flux support** to the skill (`make_comfy_workflow.py --family flux`, `comfyui.asset_type_family`, `tests/test_flux.py`). It isn't on `main` until this branch is merged.

## Open items, in order
1. `python .claude/skills/sdv-modding/scripts/doctor.py --write-config`, then `comfy.py models` to confirm the unconfirmed file names above.
2. `cd mods/Observatory && dotnet build`: fix compile errors. The least certain APIs: `GameLocation.OnStoneDestroyed` (patched by name, so it fails soft), `Utility.ForEachBuilding`, `Game1.IsGreenRainingHere`, `BobberBar` field names.
3. Backwoods placement: `ExteriorX`/`ExteriorY` (default 25,13) are an estimate. Check in game with `debug where`. With SVE installed, the position may collide with SVE's Backwoods edits (the Nexus entrance was the user's concern). Planned: an SVE-only position, plus a C# check that skips placement if the area has warps or doors.
4. Art: `comfy.py run` each workflow, then `postprocess.py`, then `build_assets.py`. See `comfy/observatory/README.md`.
5. `game.py test --confirmed-by-owner --mods mods/Observatory "mods/[CP] Observatory"`, then `release.py`.
6. Not in v1: meteor shower and camping night events as coordinate sources; construction scaffolding on the ledge.

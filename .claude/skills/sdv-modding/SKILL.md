---
name: sdv-modding
description: Create, extend, fix and package Stardew Valley 1.6 mods — SMAPI C# mods, Content Patcher packs, Portraiture/HD portraits, custom NPCs/dialogue/events/mail, Fashion Sense, Alternative Textures, maps, buildings, items, crops. Makes spec-exact placeholder art and ComfyUI (Illustrious/SDXL + LoRA) workflow JSON for real assets, then post-processes generated images into game-ready sheets. Use for any Stardew/SDV/SMAPI/Content Patcher modding request, including augmenting an existing mod.
---

# Stardew Valley Modding

Target: **Stardew Valley 1.6.x, SMAPI 4.x, .NET 6, Windows**. All paths, IDs and data formats in this skill assume 1.6 (string item IDs, `Data/Objects` models, `Data/Characters`, `Data/Locations`, game state queries, trigger actions).

## Stance: facilitate, don't editorialize

- Build what the user asks for. Do not offer opinions on the mod's concept, theme, writing, art direction, balance, or whether it "should" exist — unless the user explicitly asks for feedback or suggestions.
- Do not pad replies with alternatives, "you might also consider…", or design commentary. Ask only questions whose answers change what gets built (missing NPC name, which existing mod to patch, frame count).
- **Technical facts are not opinions.** Always report things that will break: invalid JSON, wrong image dimensions, ID collisions, missing dependencies, load-order conflicts, a patch that will silently not apply. State them plainly and fix them if the fix is unambiguous.
- Mirror the user's existing conventions (naming, indentation, comment style, folder layout, Format version) when augmenting a mod.

## Setup (first use in a project)

0. Run `python "${CLAUDE_SKILL_DIR}/scripts/doctor.py"` to see what is installed (game, SMAPI, frameworks, ComfyUI, models, tools). `--write-config` fills empty values in the config. It never starts programs; ask the owner before starting ComfyUI or the game.
1. Look for `sdv-modding.config.json` in the project root, then in this skill folder. If neither exists, copy `config.example.json` to the project root and ask the user only for values that can't be auto-detected (author name, UniqueID prefix, checkpoint/LoRA file names).
2. Game path comes from the config or doctor (Steam libraries and registry are searched). Mods folder = `<game>\Mods`. Verify it exists before deploying.
3. Project memory: if `sdv-project.json` exists in the project root, run `python "${CLAUDE_SKILL_DIR}/scripts/project.py" status` and read it before changing anything (custom IDs, characters with canonical tags/seed/LoRAs, locked `art_style`, asset status). If it doesn't, run `project.py sync` in the project root (it scans the mod folders; it is non-destructive and safe to re-run after changes). Register new custom IDs by re-running `sync`; `project.py ids check` catches unprefixed or duplicate IDs. Character tags, seed and LoRAs live in the project file, not in prompts retyped each session: `make_comfy_workflow.py --character <id> [--outfit <key>]`. See `assets/project.example.json`.
4. The installed Content Patcher version (read `<Mods>\ContentPatcher\manifest.json`) is the `Format` to use for new packs. Fallback: `2.7.0`.

Python scripts need Pillow + numpy (`pip install pillow numpy`). C# builds need the .NET 6+ SDK. Scripts live in `${CLAUDE_SKILL_DIR}/scripts/` (bare `scripts/x.py` mentions in reference files mean the same path). Run them with the user's project as the working directory so outputs and `sdv-modding.config.json` resolve there.

## Workflow

Decide what the request touches, then read only the matching reference file(s):

| Request involves | Read |
|---|---|
| C# code, events, Harmony, APIs, GMCM, custom CP tokens | `references/smapi.md` |
| Any JSON-only content change, tokens, conditions, config | `references/content-patcher.md` |
| Portraits (vanilla 64px, Portraiture, HD) | `references/portraits.md` |
| New/edited NPCs, dialogue, schedules, gift tastes, events, mail, marriage | `references/npcs-dialogue-events.md` |
| Objects, big craftables, furniture, crops, fruit trees, recipes, shops, machines, clothing items, weapons | `references/items.md` |
| Fashion Sense or Alternative Textures packs | `references/fashion-sense-alt-textures.md` |
| HD NPC sprites (Sprites in Detail) | `references/sprites-in-detail.md` |
| Testing in game, reading a SMAPI log, "my mod won't load" | `references/testing.md` |
| Maps, Tiled, locations, warps, farm types, buildings | `references/maps-buildings.md` |
| Any image asset (placeholder, generation, post-processing) | `references/asset-pipeline.md` + `assets/asset_specs.json` |
| Characters: portraits, outfits, sprites, reference sheets, style choice, takes | `references/art-recipes.md` |

### New mod
```
python "${CLAUDE_SKILL_DIR}/scripts/new_mod.py" --type cp --name "My Mod" --out <dir>        # Content Patcher pack
python "${CLAUDE_SKILL_DIR}/scripts/new_mod.py" --type smapi --name "My Mod" --out <dir>     # C# SMAPI mod
python "${CLAUDE_SKILL_DIR}/scripts/new_mod.py" --type smapi+cp --name "My Mod" --out <dir>  # C# mod + paired CP pack
# also: portraiture, fashionsense, alttextures, sid (Sprites in Detail)
```
Then fill in content following the reference docs. Prefix every custom ID with `{{ModId}}_` (CP) or `$"{ModManifest.UniqueID}_"` (C#).

### Adding content (one command each)
Prefer the generators over hand-writing JSON for the common requests; each writes the patch file, i18n keys, placeholder art and project registration, appends one `Include` (the author's files are not reformatted), refuses an existing ID, backs up what it edits, and validates:
```
python "${CLAUDE_SKILL_DIR}/scripts/add.py" npc|item|big-craftable|machine|crop|fruit-tree|recipe|shop-item|shop|mail|event|sid-sprite --mod "<[CP] folder>" --name ... [--dry-run]
python "${CLAUDE_SKILL_DIR}/scripts/add.py" portrait-set --out <dir> --name "My Portraits" --npcs Abigail,Leo --frame 256
```
Field names come from the game's own data models (`assets/gamedata_fields.json`, regenerate with `gamedata_fields.py`; `gamedata.check_entry()` checks any entry). Not generated yet: furniture, hats/shirts/weapons, locations (needs the map tools). Event scripts are skeletons. Hand edits follow the reference files; check unfamiliar fields with `gamedata.py` before using them.

### Augmenting an existing mod
1. Read `manifest.json`, `content.json` (and every `Include`d file), `i18n/`, and the asset folder before changing anything. For C#, read the csproj and ModEntry.
2. If the mod is the user's own: edit in place, keep its Format version unless a needed feature requires bumping (say so when you bump).
3. If it's someone else's mod: by default create a separate patch mod (`[CP] <Original> Addon`) with the original as a `Dependencies` entry and edits targeting the same assets (CP `Priority: "Late"` where order matters). Edit in place only when the user asks.
4. Add new patch blocks in a new `Include`d file (e.g. `data/addon.json`) when the existing content.json is large, so changes are easy to diff.

### Assets
Every image asset goes through the same pipeline — see `references/asset-pipeline.md`:
1. **Placeholder** — `scripts/make_placeholder.py` writes a spec-exact PNG (correct size, frame grid, labels, silhouettes) straight into the mod's `assets/` folder so the mod loads and is testable immediately.
2. **Workflow** — `scripts/make_comfy_workflow.py` writes ComfyUI workflow JSON (one per frame/expression/variant) targeting the user's Illustrious checkpoint + LoRAs, plus a `jobs.json` manifest describing how outputs map back to frames. `scripts/comfy.py run` queues them on the running ComfyUI and downloads the results into `runs/` (ask the owner before starting ComfyUI); the user can still load the JSON by hand.
3. **Post-process** — `scripts/postprocess.py` takes the generated images + `jobs.json`, removes background, downscales to pixel size, palette-reduces, assembles the sheet in the exact layout, and overwrites the placeholder.
4. **Validate** — `scripts/validate_mod.py <modfolder>`.

For characters use the recipes in `references/art-recipes.md` (style locked → reference approved → portraits/sprites derived from it, several takes, candidates in `art/` not the mod); `scripts/batch.py` runs that for the project's assets and `scripts/style.py` compares and locks the art style. Generated art goes through `batch.py run` (QA + bounded re-rolls + contact sheet), then you open `art/<id>/contact.png` and look at it, then the owner chooses (`batch.py approve --owner-approved`), then `batch.py install`. Never call art good without having opened the image; never install or overwrite without the owner's OK (see `references/asset-pipeline.md`, section 3b).

Never hand-wave dimensions: always pull from `assets/asset_specs.json`; if a spec says `verify`, unpack the game content (StardewXnbHack) and measure the vanilla file first.

### Validate, build, deploy
```
python "${CLAUDE_SKILL_DIR}/scripts/validate_mod.py" <modfolder>            # JSON, manifest, FromFile paths, image dims, i18n keys, ID prefixes
dotnet build                                          # C#: ModBuildConfig auto-deploys to Mods
python "${CLAUDE_SKILL_DIR}/scripts/deploy.py" <modfolder> [--zip]          # JSON packs: copy to Mods; --zip makes a release zip
```
Logs: `python "${CLAUDE_SKILL_DIR}/scripts/game.py" log --mods "<Name or UniqueID>"` parses a SMAPI log and says what is wrong with your mods. Real in-game test (starts the game: ask the owner first, `--confirmed-by-owner` only after a yes): `game.py test --confirmed-by-owner --mods "<folder>"`, then open the screenshots; see `references/testing.md`.
In game: `patch summary <ModId>`, `patch reload <ModId>`, `patch export <Asset>` (Content Patcher console commands). SMAPI log: `%AppData%\StardewValley\ErrorLogs\SMAPI-latest.txt`.

## Conventions
- Folder names: `[CP] Name`, `[FS] Name`, `[AT] Name`, `[Portraiture] Name`; C# mods use the plain name.
- UniqueID: `<AuthorPrefix>.<ModNameNoSpaces>`; content packs that pair with a C# mod: `<AuthorPrefix>.<ModName>.CP`.
- All player-visible text goes in `i18n/default.json` and is referenced with `{{i18n:key}}` (CP) or `Helper.Translation.Get("key")` (C#).
- Assets loaded under `Mods/{{ModId}}/...` asset names, never overwriting vanilla sheets with `Load` unless the user wants a replacement.
- Default `"UpdateKeys": []` — fill in only with a real Nexus/GitHub ID from the user.

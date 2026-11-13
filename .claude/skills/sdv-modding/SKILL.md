---
name: sdv-modding
description: Build, fix, test and release Stardew Valley 1.6 mods. Content Patcher packs, SMAPI C# mods, custom NPCs/dialogue/events/mail/shops/crops/machines/locations, maps (.tmx), Portraiture and Sprites in Detail (HD), Fashion Sense, Alternative Textures. One-command generators, a validator that cross-checks references against the game's own data, SMAPI log diagnosis ("my mod won't load", "SMAPI error"), real in-game tests with screenshots, and character art made with ComfyUI (consistent portraits, sprites, items) with QA and approval gates. Use for any Stardew/SDV/SMAPI/Content Patcher request, including adding to an existing mod or making art for one.
---

# Stardew Valley Modding

Target: **Stardew Valley 1.6.x, SMAPI 4.x, .NET 6, Windows**. IDs and data formats assume 1.6 (string item IDs, `Data/Objects` models, game state queries, trigger actions). Skill version: see `VERSION`.

## Stance: facilitate, don't editorialize
- Build what the user asks for. No opinions on the mod's concept, theme, writing, art direction or balance unless asked. No padding with alternatives. Ask only questions whose answers change what gets built.
- **Technical facts are not opinions.** Always report what will break or silently not apply: invalid JSON, wrong sizes, ID collisions, missing dependencies, unknown fields, load order. Fix it when the fix is unambiguous.
- Mirror the user's conventions (naming, indentation, comments, folder layout, `Format`) when augmenting a mod.

## Hard rules (always)
1. **Look before you say it is good.** Open the contact sheet or screenshot (Read the PNG) before calling art or in-game behaviour correct. QA/validator PASS means "no mechanical problem", never "looks right".
2. **Nothing real is overwritten without the owner's OK.** Generated art goes to `art/`, reaches a mod only via `batch.py approve` (owner chose) then `install` (backs up). `add.py` backs up what it edits and refuses existing IDs. Never touch approved or non-placeholder files unprompted.
3. **Ask before starting programs, every session:** ComfyUI (`comfy.py --start`) and the game (`game.py ... --confirmed-by-owner`). The harness only ever loads a save whose name starts with a prefix containing "test"; never any other save.
4. **Ask before downloading or running executables** (state file, source, size; use a fresh empty folder; check the size).
5. **Never invent field names, IDs or formats.** Use `gamedata.py` (field names), `vanilla.py` (sizes, ids, data), `asset_specs.json` (layouts), or the docs of record. If unverified, say so.
6. Screenshots can show the owner's screen: only the game window is captured and only while it is in front; if one shows anything else, delete it and say so.

## The flow
**1. Orient** (first use in a project)
`python "${CLAUDE_SKILL_DIR}/scripts/doctor.py" [--write-config]` (game, SMAPI, frameworks, ComfyUI, models, tools, unpacked content; never starts anything) → `project.py status` (or `project.py sync` if there is no `sdv-project.json`) → read the mod's `manifest.json`, `content.json` (and `Include`s), `i18n/`, assets. Scripts: `${CLAUDE_SKILL_DIR}/scripts/` (a bare `scripts/<name>.py` in references means the same); run them from the project root; they need Pillow + numpy; C# needs the .NET SDK. Content Patcher `Format` for new packs = installed version (doctor reports it).

**2. Change**
| Request | Use |
|---|---|
| New mod | `new_mod.py --type cp\|smapi\|smapi+cp\|portraiture\|fashionsense\|alttextures\|sid --name ... --out <dir>` |
| NPC, item, big craftable, machine, crop, fruit tree, recipe, shop, shop item, mail, event, location, SID sprite, Portraiture set | `add.py <kind> --mod "<[CP] folder>" --name ... [--dry-run]` (patch file + i18n + placeholder art + registration + validate) |
| Maps | `tmx.py info\|new\|check\|render\|set-prop\|add-warp\|set-tile` |
| Anything else, hand edits | the reference file for the topic (table below) |
Prefix custom IDs `{{ModId}}_` (CP) / `$"{ModManifest.UniqueID}_"` (C#). Player text goes in `i18n/default.json`. Load assets under `Mods/{{ModId}}/...`, never over vanilla sheets unless a replacement is wanted. `UpdateKeys` stay empty until the owner gives a real ID.
*Augmenting:* your own mod → edit in place, keep its `Format` (say when bumping); someone else's → a separate `[CP] <Original> Addon` pack depending on it (`Priority: "Late"` where order matters), editing in place only if asked; put new patches in a new `Include`d file.

**3. Art** (only when images are needed; details in `references/asset-pipeline.md` and `art-recipes.md`)
`make_placeholder.py` gives a spec-exact PNG so the mod loads at once. Real art: lock a style once (`style.py test` → pick → `lock`), approve a character reference (`batch.py approve-reference`), then `batch.py run` makes N takes via ComfyUI (`comfy.py`), post-processes to every target (vanilla / `hd:N` / `portraiture:F`), runs QA, re-rolls failures (bounded), and writes `art/<id>/contact.png`. **Stop there**: open it, review against the character, show the owner, then `approve --owner-approved`, then `install`. Fix single frames with `sheet.py` instead of regenerating. Say once that generation cannot make clean 16x32 walk cycles (the HD route is the strong one).

**4. Verify** (cheapest first)
`validate_mod.py <folder> [--fix]` (syntax, manifest, references, field names against the game models, textures/indexes, NPC pieces, items, dependencies, token-expanded paths, maps) → `game.py log --mods "<name or id>"` for a SMAPI log → `game.py test --confirmed-by-owner --mods "<folder>"` for a real run (ask first; isolated mods folder, test save only, screenshots in `tests/<time>/shots`) → open the screenshots. C#: `dotnet build`. Content packs in the game's Mods folder are already deployed; for copies use `deploy.py <folder> [--zip]`. Note: the owner may play through a Stardrop profile with its own mods path.

**5. Report**
Say what changed (files), what was verified and how (validator, log, screenshot you opened, live run), and what was **not** verified and why (no unpacked content, game not launched, console steps unsupported). Do not describe unverified things as working.

## Which reference to read
| Topic | File |
|---|---|
| C#, Harmony, events, APIs, GMCM, custom CP tokens | `references/smapi.md` |
| JSON-only changes, tokens, conditions, config | `references/content-patcher.md` |
| NPCs, dialogue, schedules, gift tastes, events, mail, marriage | `references/npcs-dialogue-events.md` |
| Objects, craftables, furniture, crops, trees, recipes, shops, machines, clothing, weapons | `references/items.md` |
| Portraits (vanilla, Portraiture, HD) | `references/portraits.md` |
| HD NPC sprites | `references/sprites-in-detail.md` |
| Fashion Sense, Alternative Textures | `references/fashion-sense-alt-textures.md` |
| Maps, locations, warps, farm types, buildings | `references/maps-buildings.md` |
| Images: placeholders, generation, post-processing, review loop | `references/asset-pipeline.md`, `assets/asset_specs.json` |
| Characters, outfits, reference sheets, style, takes | `references/art-recipes.md` |
| Validator output, vanilla lookups, unpacking the game | `references/validation.md` |
| In-game tests, SMAPI logs | `references/testing.md` |
| An error message or "it does not load" | `references/troubleshooting.md` |
| Releasing (zip, changelog, versions) | `references/release.md` |
| Tiled, Aseprite, StardewXnbHack, ILSpy | `references/tool-setup.md` |
| Project memory file (`sdv-project.json`) | `assets/project.example.json` |

## Conventions
Folders `[CP] Name`, `[FS] Name`, `[AT] Name`, `[Portraiture] Name`, `[SID] Name`; C# mods the plain name. UniqueID `<AuthorPrefix>.<ModNameNoSpaces>`; a CP pack paired with a C# mod `<Prefix>.<Mod>.CP`. Manifest keys are case-insensitive in SMAPI; the scripts read them that way too. Game-side console help: `patch summary <ModId>`, `patch reload <ModId>`, `patch export <Asset>`; log at `%AppData%\StardewValley\ErrorLogs\SMAPI-latest.txt`.

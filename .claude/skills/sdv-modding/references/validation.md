# Validation and vanilla lookups

```
python "${CLAUDE_SKILL_DIR}/scripts/validate_mod.py" "<mod folder>" [--json] [--fix] [--no-deep] [--mods-dir <Mods>] [--root <unpacked>]
python "${CLAUDE_SKILL_DIR}/scripts/vanilla.py" size|exists|find|keys|entry|item|specs ...
```
Exit code 1 means ERRORs. Levels: **ERROR** = will break or is certainly wrong; **WARN** = silently ignored by the game or very likely a mistake; **INFO** = something that could not be checked or is merely worth knowing.

## What the validator checks
Basics: manifest fields and ID format (keys are read case-insensitively like SMAPI), JSON syntax (comments/trailing commas allowed), Content Patcher `Format`, Action/Target/FromFile, `Include` files, image sizes for portrait/sprite targets, i18n keys used vs defined, custom IDs without a mod prefix, leftover placeholders, Fashion Sense / Alternative Textures / Portraiture / Sprites in Detail layouts, C# csproj vs manifest.

Deep checks (`vcheck.py`, on by default for Content Patcher packs):
| Check | Level | Notes |
|---|---|---|
| Field names against the game's own data models | WARN | `EditData` on Data/Objects, BigCraftables, Crops, FruitTrees, Characters, Shops (incl. list items), Machines, Locations, Buildings, Weapons, Shirts, Pants, TriggerActions, nested too. The game ignores unknown fields silently. Real example found in a shipping pack: `DaysInEachPhase` (the field is `DaysInPhase`), so the crop had no growth data. |
| `Texture` that nothing loads and vanilla does not have | WARN | resolved with `{{ModId}}`; dependency textures (`Mods/<declared id>/...`) are accepted |
| `SpriteIndex` / `TextureSpriteRow` outside the sheet | ERROR | sheet size from the pack's own PNG or the vanilla sheet; cells: objects 16x16, big craftables 16x32, crops 128x32, fruit trees 80 px rows |
| New NPC without sprite, portrait or dialogue asset | ERROR | gift tastes missing = WARN, schedule missing = INFO, `Home` location unknown to vanilla and this pack = WARN |
| Own item referenced but never defined | ERROR | only real item fields (`ItemId`, `RequiredItemId`, `HarvestItemId`, ...), qualified ids `(O)...`, machine keys and recipe/gift-taste strings; mail flags, event ids and quest steps are not items |
| Vanilla item id that does not exist | WARN | numeric ids only; needs unpacked content |
| Dependency not installed / used but not declared | WARN | `{{Other.Mod/Token}}`, `"Other.Mod/Token"` in `When`, `Mods/Other.Mod/...` targets |
| `FromFile` with tokens missing for some values | ERROR | expands `{{Season}}`, `{{Weather}}`, config `AllowValues` and DynamicTokens (up to 200 combinations) |
| Portrait `$N` beyond the portrait sheet; malformed schedule entries; events without `end` | WARN | |
| Duplicate keys inside one JSON object | WARN | the parser keeps only the last |
Portrait sheet width rule follows the asset: an asset the project lists as `portrait_hd` or Portraiture-only gets "2 square frames per row" instead of "128 wide".

Anything it could not check says so as an INFO (for example "game content is not unpacked"). It never guesses.

## `--fix`
Only unambiguous repairs: stubs missing i18n keys (`"key": "TODO: key"`, original backed up to `backups/`), deletes stray `*_preview.png`, `Thumbs.db`, `.DS_Store`. Everything else is reported, not changed. Output lists what was fixed and the result is re-checked.

## Vanilla lookups (`vanilla.py`)
Reads the game's own unpacked content, so nothing is guessed:
`size Portraits/Abigail` (pixels), `exists`, `find <text> [--data]`, `keys Data/Objects [--like jam]`, `entry Data/Objects 245`, `item 245` (which Data asset defines it), `specs` (re-checks every `vanilla_ref` rule in `assets/asset_specs.json`).
It looks for `Content (unpacked)` in the config (`unpacked_content`), `~/.sdv-skill/`, then next to the game; `--root` overrides and is never replaced by a fallback.

### Getting the unpacked content (needs the owner's OK)
1. Ask the owner. The tool is Pathoschild's StardewXnbHack (github.com/Pathoschild/StardewXnbHack/releases, "for Windows" zip). State the file name, source and size when asking.
2. Download into its own empty folder, check the size matches the release, extract, copy `StardewXnbHack.exe` next to `Stardew Valley.dll` (it must run from the game folder), close the game and SMAPI.
3. Run it in a real terminal window (it needs a console; a redirected shell fails). It writes `Content (unpacked)` (about 180 MB, 3,500 files, under a minute).
4. Move that folder out of the game folder (for example `~/.sdv-skill/Content (unpacked)`), delete the exe, run `doctor.py --write-config`.
Re-run after a game update; `vanilla.py specs` shows whether the layout rules still hold.

## Game-data model fields
`assets/gamedata_fields.json` lists the public fields of every `StardewValley.GameData.*` model, read from the installed game DLL (`gamedata_fields.py`, source in `tools/apidump`). `gamedata.check_entry(entry, "ObjectData")` returns the keys that are not real fields. Regenerate after a game update.

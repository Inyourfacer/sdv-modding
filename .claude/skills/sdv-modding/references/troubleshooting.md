# Troubleshooting: from symptom to cause

Start with `python "${CLAUDE_SKILL_DIR}/scripts/game.py" log --mods "<Name or UniqueID>"` (or `--file` for a log the owner pasted/saved), then `validate_mod.py <folder>`. The log parser groups findings into the categories below. Patterns marked (seen) were observed in real SMAPI 4.5.2 / Stardew 1.6.15 logs; the rest are generic causes, not exact message texts.

| Log category / pattern | Usual cause | Fix |
|---|---|---|
| **Skipped mods** list: "...because it requires X which isn't installed" (`missing_dependency`) | A required `Dependencies` entry (or the framework named in `ContentPackFor`) is not in the Mods folder the game was started with | Install it, or mark it `"IsRequired": false` if the pack works without it. Remember the owner may start through Stardrop with another mods path (`doctor.py` says) |
| Skipped mod: manifest problems (`manifest`) | Invalid JSON, missing `UniqueID`/`Name`/`Version`, both `EntryDll` and `ContentPackFor` | `validate_mod.py` names the line; keys are case-insensitive for SMAPI |
| Content Patcher error mentioning a `FromFile` that "matches non-existent file" (`patch_failure`) | Wrong path, wrong case, a token value with no file (e.g. no `_winter.png`) | `validate_mod.py` expands `{{Season}}`/config tokens and lists the missing paths |
| "Failed loading asset ... FileNotFoundException" / "content file was not found" (`asset_load`) | A `Load` target nobody provides, or a texture name that differs from the `Texture` field | Check the `Target` and the `Texture` string match (validator: "Texture ... not loaded by this pack") |
| (seen) "NPC X can't load portraits from 'Portraits/X': ContentLoadException" | The NPC exists in the save/data but its mod (or its portrait `Load`) is not loaded | In an isolated test this is expected for NPCs of mods not loaded; for your own NPC add the `Load` (validator: "NPC ... is missing portrait sheet") |
| (seen) "Ignored unknown location 'X' in save data" | The save contains locations from mods that are not loaded | Expected in `game.py test` (isolated mods); harmless |
| Exception with a stack trace from a C# mod (`exception`) | A bug in the mod's code or a Harmony patch target that changed | Read the first `at` lines for your namespace; check `Context.IsWorldReady` guards; rebuild against the installed game |
| Pack loads, nothing changes in game, no error | A field name the game ignores (typo or wrong nesting), a `When` that is never true, or a patch that targets the wrong asset | `validate_mod.py` (field names against the game models); `patch summary <ModId>` shows which patches applied and why not; log line "Content Patcher edited X (for the 'Pack' content pack)" proves one applied |
| Crop never grows / grows instantly | `DaysInPhase` missing or misspelled (a real pack had `DaysInEachPhase`) | Validator flags unknown `CropData` fields |
| Item shows an error sprite / wrong icon | `SpriteIndex` outside the sheet, or `Texture` points at a sheet with a different cell size | Validator ERROR "SpriteIndex ... outside the sheet" |
| NPC does not appear | `Data/Characters` entry exists but sprite/portrait/dialogue asset missing, `Home` location unknown, or `SpawnIfMissing`/`UnlockConditions` | Validator "NPC '...' is missing"; `game.py test` with an `assert_npc` step proves she exists |
| Warp does nothing / crashes | `AddWarps` string not `x y Location tx ty`, unknown destination, exit tile not one outside the edge | `tmx.py check`; validator checks `AddWarps` |
| Image looks wrong size/blurry in game | Sheet not the vanilla size, or an HD sheet loaded without Sprites in Detail / Portraiture | `asset_specs.json`; `vanilla.py size`; `sprites-in-detail.md` |
| Event stuck | Script does not end with `end`, an actor never arrives | Validator warns; test with `debug ebi <eventId>` or a harness `debug` step |
| `dotnet build` cannot find the game | Game path not detected | Set `<GamePath>` in the csproj or run `doctor.py`; ModBuildConfig auto-detects Steam installs |
| "MSI Afterburner ... may conflict with SMAPI" (seen) | Not a mod problem | Ignore unless the owner reports crashes |

## When the log is clean but it still looks wrong
Take a real screenshot (`game.py test` with a `screenshot` step, with the owner's OK) and open it. A clean log plus a wrong picture usually means placeholder art still installed, a `When`/season condition, or the wrong tile/NPC position.

## Reporting a diagnosis
Quote the exact log line, name the file and the key you changed, say whether you re-ran the validator and the log parser afterwards, and say plainly if the fix was not tested in the game.

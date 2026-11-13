# Observatory

A domed observatory on the Backwoods ledge. Solve riddles to find telescope coordinates, then connect stars into constellations for permanent perks.

Two folders, both go in `Mods/`:
- `Observatory/`: C# SMAPI mod (telescope, star puzzle, journal, star-chart board, perks, construction timer). Build with `dotnet build` (ModBuildConfig deploys it).
- `[CP] Observatory/`: Content Patcher pack (maps, location data, mail, special order, events, dialogue). Deploy with `scripts/deploy.py`.

All shared IDs use the prefix `Inyourfacer.Observatory` (`Ids.cs` in C#, the `{{Obs}}` token in CP).

## How it works

| Design | Implementation |
|---|---|
| Unlock: Maru at 6 hearts | `[CP]/data/unlock.json`: trigger action mails `…_MaruLetter`. Reading it starts construction. |
| Unlock: town project | `[CP]/data/unlock.json`: special order `…_TownProject` on the town board (ship quartz, gold bars, batteries). The reward flag starts construction. |
| Robin builds it in 3 days | `WorldHooks.UpdateConstruction` (host, DayStarted) sets `…_Built` after `ConstructionDays`. The Backwoods map edit is conditioned on that flag. |
| Telescope (clear nights, 8pm to 2am) | Tile action `…_Telescope` opens `TelescopeMenu`. RA 0–23h, Dec −80…+80 in steps of 10. Time window and clear-sky check are in `config.json`. |
| Connect the stars | `StarPuzzleMenu`: click two stars to toggle a line; right-click undoes. Decoys are placed so they never sit on an outline. The outline is `Visible`, `Fades` (after 5s), or `None` (shape riddle shown instead). |
| Star journal | Tile action `…_Journal` opens `StarJournalMenu`. |
| Star-chart bundles | Tile action `…_StarCharts` opens `StarChartBoardMenu`. Items are taken from inventory (any quality). A completed bundle reveals coordinates. |
| Riddles | Learned by: Maru's welcome event (Sprout), entering mines floor 40 (Pickaxe), entering the Community Center (Junimo), Wizard letter after 5 charted (Stardrop), unsigned letter after Sprout + Angler (Old Farmer). |
| Solving a riddle | Stand where the riddle points (`RevealSpot` in `constellations.json`): Pierre's shop, Clint's shop, the Wizard's tower, the Secret Woods at night, or within 2 tiles of Grandpa's shrine. |
| Finale | Event `…_Finale` in the observatory at night once all 7 are charted. It moves to the roof map with Maru and the Wizard. |

Constellations and bundles are data (`Mods/Inyourfacer.Observatory/Constellations` and `/StarCharts`), so other packs can add or change them with `EditData`.

### Perks (they stack with professions)
| Constellation | Perk | Hook |
|---|---|---|
| Sprout | 5%: a watered crop grows an extra day | DayEnding, host, any farmer with the perk |
| Angler | Fishing bar +8% | `MenuChanged` → `BobberBar.bobberBarHeight` |
| Pickaxe | 10%: extra ore from ore nodes | Harmony postfix `GameLocation.OnStoneDestroyed` |
| Hearth | Cooked food +15% energy | Harmony postfix `Object.staminaRecoveredAmount` |
| Junimo | Junimo huts +3 tiles radius | DayStarted, `JunimoHut.cropHarvestRadius` |
| Stardrop | +15 max energy | Granted once on completion |
| Old Farmer | Skill XP +5% (fractions carried over) | Harmony prefix `Farmer.gainExperience` |

Progress is stored as mail flags per player (`…_Riddle_<id>`, `…_Coords_<id>`, `…_Done_<id>`), so it's per-farmer in multiplayer and readable with CP `HasFlag` and game state queries.

## Validate, test, release (skill 2.0.0, from the repo root; `S=.claude/skills/sdv-modding/scripts`)
```
python $S/doctor.py --write-config                                   # game, SMAPI, ComfyUI, models -> config
python $S/validate_mod.py "mods/[CP] Observatory"                    # deep checks (needs unpacked content for vanilla IDs)
python $S/tmx.py check "mods/[CP] Observatory/assets/maps/Observatory.tmx"
cd mods/Observatory && dotnet build                                  # builds + deploys the C# mod
python $S/deploy.py "mods/[CP] Observatory"                          # copies the content pack to Mods
python $S/game.py test --confirmed-by-owner --mods mods/Observatory "mods/[CP] Observatory"   # builds the C# mod, isolated Mods folder, test save only
python $S/release.py mods/Observatory "mods/[CP] Observatory" --version 1.0.0 --note "First release"   # zips + changelog into releases/
```
`release.py` stops while the tilesheet is still placeholder art, unless you pass `--allow-placeholders`.

## Testing (SMAPI console)
```
obs_build                 # finish construction now (host)
obs_status                # progress table
obs_riddle all | obs_reveal all | obs_complete <id> | obs_reset all
obs_puzzle Stardrop       # open a puzzle directly
debug warp Backwoods 27 20
debug time 2100
patch summary Inyourfacer.Observatory.CP
```

## Check in game before release
- **Exterior position:** `ExteriorX`/`ExteriorY` default to 25,13 on Backwoods. That's an estimate. Stand on the ledge, run `debug where`, and set the config so the 5×6 area is open ground. The patch uses `Overlay`, so anything already on the Buildings layer there stays.
- **Not compiled yet.** This environment has no .NET SDK or game DLLs. On first `dotnet build`, fix any API name mismatches. The least certain names are `GameLocation.OnStoneDestroyed` (this one is patched by string name, so if it's missing the perk logs a warning and turns off), `Utility.ForEachBuilding`, and `Game1.IsGreenRainingHere`.
- **Dialogue keys:** the Maru (`Tue`, `Fri`) and Wizard (`Mon`, `Thu`, `Sat`) appends create the key if the NPC doesn't have it. Check with `patch export Characters/Dialogue/Maru`.
- **Art:** `[CP]/assets/maps/z_Observatory_tiles.png` is placeholder art. ComfyUI workflows and steps are in `comfy/observatory/README.md`.
- **Tile actions** (telescope, board, desk, the exterior door) are `MapTiles` patches in `[CP]/data/locations.json`, not in the `.tmx` files. If you move furniture in a map, move its action tiles there too.

## Not in v1 yet
- Night events (meteor shower, camping) as coordinate sources. The hook is ready: any event or dialogue can run `action AddMail Current Inyourfacer.Observatory_Coords_<id> received`.
- A Robin construction sprite or scaffolding on the ledge during the 3 build days.

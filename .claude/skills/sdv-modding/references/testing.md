# Testing in the real game

Static checks (`validate_mod.py`) come first and are free. In-game checks start Stardew Valley, so **ask the owner first, in this conversation, every session** and pass `--confirmed-by-owner` only after a yes. Nothing here ever starts the game on its own.

## Reading a SMAPI log (no game needed)
```
python "${CLAUDE_SKILL_DIR}/scripts/game.py" log --mods "My Mod,Me.MyMod"        # default: %AppData%\StardewValley\ErrorLogs\SMAPI-latest.txt
python "${CLAUDE_SKILL_DIR}/scripts/game.py" log --file path\to\log.txt --json
```
Reports SMAPI/game versions, mods loaded, errors and warnings grouped by source, skipped mods, and the usual causes: `missing_dependency`, `patch_failure` (Content Patcher), `asset_load`, `exception` (with stack), `manifest`. With `--mods` it says whether *your* mods are clean (exit code 1 if not). "Fix my mod from this log" starts here: read the report, open the named files, fix, re-run `validate_mod.py`. The same parser handles logs pasted by the owner or from smapi.io (save them to a file).

## One-time setup: a TEST save
The harness only ever loads a save whose folder name starts with a prefix that contains "test" (default `SdvTest`). Ask the owner to create one throwaway farm in the game, farmer name `SdvTest` (any farm type, no mods needed), play past day 1 so it saves, and tell you its folder name (`%AppData%\StardewValley\Saves\SdvTest_<number>`). Put it in `sdv-project.json` → `test.save`. Never use a real save, never create one for the owner.

## The test run
```
python "${CLAUDE_SKILL_DIR}/scripts/game.py" test --confirmed-by-owner --mods "<mod folder>" ["<other folder>" ...] [--check name ...] [--steps steps.json]
```
What it does, in order: `validate_mod.py` (errors stop the run before anything starts) -> `dotnet build` for C# mods -> copies the mods under test **and their required dependencies** (read from manifests, found in the configured Mods folder, `extra_mod_dirs`, or Stardrop's Selected Mods) plus `SMAPI.ConsoleCommands` and the harness into an **isolated temporary mods folder** -> starts `StardewModdingAPI.exe --mods-path <that folder>` -> the harness loads the test save and runs the steps -> `game.py` answers its requests for window screenshots and SMAPI console commands -> the game is closed, the temp folder deleted -> verdict. The owner's normal Mods folder or Stardrop profile is not touched and does not need to match.

Reports: `tests/<timestamp>/report.json`, `SMAPI.txt` (copy of the log), `shots/*.png`. **PASS** needs every harness step OK *and* no ERROR/skipped-mod entry from the mods under test. A PASS does not mean it looks right: **open every screenshot** (Read the PNG), compare with what was asked, and report what you see. If you cannot launch (game already running, owner declined, no display), fall back to `game.py log` / static checks and say that in-game appearance was not checked.

## Steps (in `sdv-project.json` → `test.checks[]`, or a `--steps` file `{"steps":[...]}`)
Check shorthand: `{"name":"mira_home","warp":"Town 52 70","time":1200,"give":["(O)Me.MyMod_Gem 2"],"commands":["debug ebi Me.MyMod_Intro","patch summary Me.MyMod"],"dialogue":"Me.MyMod_Mira","screenshot":true}`. `commands` starting with `debug ` run inside the game (`DebugCommands`); any other command is typed into the SMAPI console by `game.py`.
Raw steps: `warp {location,x,y}`, `time {value}`, `debug {command}`, `give {item,count}`, `wait {ticks}`, `dialogue {npc}` (opens the NPC's current dialogue), `assert_location {location}`, `map_screenshot {name}` (the game's own map screenshot), `screenshot {name}` (window picture incl. menus, taken by `game.py`), `console {command}`.
Defaults per kind: new NPC -> warp to their home tile, `dialogue`, screenshot; item -> `give` it, screenshot; map -> warp in, screenshot; portrait -> `dialogue` + screenshot.

## Safety guarantees (and how they are enforced)
- Only a save whose folder name starts with the prefix (>= 4 chars, contains "test") is ever loaded: checked by `game.py` before launch, by the harness before touching the load menu, immediately before activating the slot, and again after the load (if it somehow is not a test save the harness closes the game without saving). Path tricks (`/`, `\`, `:`, `..`) are refused. The rule is unit-tested in C# (`harness/tests`) and mirrored in `game.py`.
- The harness is dormant unless `harness-commands.json` exists in its folder (it only exists inside the temporary folder during a run) and never triggers a save.
- `stop` and the end of `test` close only the process `game.py` started (PID recorded in `.sdv-game.json`): polite close first, forced only after 20 s. A running game that was not started by us makes `launch`/`test` refuse.

## What has and has not been verified
Verified: the harness compiles against the installed game and SMAPI DLLs (every API used was dumped from them: `SaveGame`, `LoadGameMenu.SaveFileSlot.Activate`, `Game1.warpFarmer`, `DebugCommands.TryHandle`, `Game1.takeMapScreenshot`, ...); the log parser on a real 1.2 MB SMAPI log; the save rule; the whole `test` orchestration against a fake game process.
**Not yet verified live** (needs the owner's go-ahead and a test save): loading the save through the title/load menu from code, window screenshots, and whether SMAPI's console accepts commands from a piped stdin. If a step fails, the result says which; console steps then run only if stdin works. Report what actually happened rather than assuming.

## Rebuilding the harness
`harness/SdvTestHarness` (C#, net6.0, ModBuildConfig; `EnableModDeploy=false` so building never copies it into Mods). `game.py` rebuilds it when the sources are newer than the DLL (`dotnet build -c Release` there). Unit tests for the save rule: `dotnet run` in `harness/tests`.

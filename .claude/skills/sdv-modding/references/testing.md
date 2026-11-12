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
**Verified in a live run** (Stardew 1.6.15, SMAPI 4.5.2, an existing farm named `testing_...` with prefix `testing`): SMAPI starts from an isolated mods folder (CP + the pack under test + harness); the harness loads the test save through the title/load menu from code ("Context: loaded save ..." then "world ready"); `warp`, `give` (a custom item from the pack under test resolved), `wait`; the harness closes the game after `game.py` signals; the harness refused a save when its prefix did not match (the safety rule works in the real game). Also: the harness compiles against the installed DLLs; the log parser on a real 1.2 MB log; the whole `test` orchestration against a fake game.
**Found wrong in that live run and fixed:** the harness read `save_prefix` wrongly (JSON naming), fell back to the default prefix and refused the save; the window screenshot grabbed whatever was on top of the game's screen region (the owner's browser) instead of the game, so it is now only kept while the game window is the foreground window (checked before and after), else it fails with a message and saves nothing; SMAPI did **not** run a piped console command (`patch summary` printed nothing) while the step claimed success, so console steps now fail honestly unless `--console-stdin` (experimental) is given; manifests spelling `UniqueId` (SMAPI is case-insensitive) were missed.
**Not verified yet:** the foreground-checked screenshot on a live run (needs a re-run), the `dialogue`, `debug` and `map_screenshot` steps, and any console route (use `game.py log` and `debug` steps instead). Report what actually happened rather than assuming.

## Rebuilding the harness
`harness/SdvTestHarness` (C#, net6.0, ModBuildConfig; `EnableModDeploy=false` so building never copies it into Mods). `game.py` rebuilds it when the sources are newer than the DLL (`dotnet build -c Release` there). Unit tests for the save rule: `dotnet run` in `harness/tests`.

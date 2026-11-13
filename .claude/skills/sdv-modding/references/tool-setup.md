# Optional tools and how the skill uses them

`doctor.py` reports which of these exist. Everything below is optional: the Python scripts cover the same jobs at a basic level, and the skill never installs anything without the owner's OK (state the file name, source and size when asking).

| Tool | Used for | Status on the owner's PC | Without it |
|---|---|---|---|
| .NET SDK 6+ | building C# mods, the test harness, `gamedata_fields.py` | installed (8.0) | C# work is not possible |
| StardewXnbHack | unpacking the game content (vanilla sizes, data, map files) | **done once**, output in `~/.sdv-skill/Content (unpacked)`; the exe was removed from the game folder | `vanilla.py`, deep validation and `tmx.py` have nothing to read |
| Tiled (mapeditor.org) | visual map editing | not installed | `tmx.py` creates, edits, checks and renders maps from the command line |
| Aseprite | pixel clean-up of sprites, palettes, animation preview | not installed | `postprocess.py`, `palette.py`, `sheet.py` |
| ILSpy (`ilspycmd`) | reading decompiled game code (finding Harmony targets) | not installed | `tools/apidump` lists public members from the DLLs |

## Tiled
- The game's own maps are Tiled 1.4 `.tmx` files (see `maps-buildings.md`). Install the current Tiled from mapeditor.org; open a vanilla map from `~/.sdv-skill/Content (unpacked)/Maps` to see how it is built.
- Tiled needs the tilesheet images beside the `.tmx` to display tiles. Copy the vanilla sheets you use next to your map while editing and **do not ship** them (the game supplies them); keep `image source` as the vanilla asset name without extension, as the game's own maps do. Save with *Tile Layer Format: CSV* (the only format `tmx.py` reads).
- Once Tiled is installed, check `tiled --help` and its command-line export documentation before scripting anything with it (not done yet: it was not installed when the skill was written, and commands are not written from memory). `tmx.py render` already gives a preview image without Tiled.

## Aseprite
- Useful for hand-fixing generated sprites: indexed colour mode with the character palette (`palette.py build`), onion-skinned walk cycles, exporting sheets. Before adding CLI steps to the pipeline, read the installed version's `aseprite --help` and the Aseprite CLI docs (not done yet, tool not installed). Until then: `sheet.py slice` / `assemble` / `preview-anim` give the same round trip with PNGs.

## StardewXnbHack (when the content must be refreshed after a game update)
See `validation.md`: ask, download the release zip into its own folder, copy the exe next to `Stardew Valley.dll`, run it in a real terminal window (not a redirected shell), move `Content (unpacked)` out, delete the exe.

## ILSpy
`dotnet tool install ilspycmd -g` (needs network: ask first) decompiles `Stardew Valley.dll` so Harmony targets and game methods can be read as source. For just listing members, `tools/apidump` (used by `gamedata_fields.py`) needs nothing extra.

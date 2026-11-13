# Maps, locations, farm types, buildings

Editor: Tiled (save as `.tmx`, CSV or base64-uncompressed layers; SDV/xTile reads `.tmx` and `.tbin`). Wiki of record: Modding:Maps, Modding:Location data, Modding:Farm data, Modding:Buildings.

## Tools (no Tiled needed)
```
python "${CLAUDE_SKILL_DIR}/scripts/tmx.py" info|check|render|new|set-prop|add-warp|set-tile <map.tmx> ...
python "${CLAUDE_SKILL_DIR}/scripts/add.py" location --mod "<[CP] folder>" --name Cottage --door "60 70" [--like Trailer --size 12x9]
```
`add.py location` writes a starter interior (the tilesheets and floor of a vanilla map you name with `--like`), the `Data/Locations` entry, an `EditMap AddWarps` on the target map and a warp back out, then checks the map. `tmx.py render` makes a PNG so you can look at a map without the game (it reads the game's own tilesheets from the unpacked content); open the image and look at it. `tmx.py check` finds missing layers, tilesheet images that do not exist, tile ids beyond the tilesheets, malformed or unknown-location warps. `validate_mod.py` runs the same checks on every `.tmx` a pack ships and checks `AddWarps` strings. See `tool-setup.md` for Tiled.

Measured from the game's own maps (190 `.tmx` files, all readable by `tmx.py`): Tiled 1.4 files; tilesheets referenced by **asset name without extension** (`townInterior`); CSV layer data; layers `Back`, `Buildings`, `Front`, `AlwaysFront` (bigger maps add `Back2/3`, `Buildings2`, `Paths`); map properties such as `Warp`, `FloorIDs`, `WallIDs`; `Warp` is `x y Location tx ty` groups; an **exit warp sits one tile outside the map edge** (FarmHouse is 12x12 and warps at `3 12`). Some vanilla maps list an older size for a tilesheet than the file on disk (a harmless warning).
Per-tile properties (`Action`, `TouchAction`, `Passable`, ...) belong in `EditMap` `MapTiles` patches, not in the `.tmx`, so they survive tilesheet changes.

## Map structure
- Layers: `Back` (ground), `Buildings` (collision), `Paths` (spawn/path hints), `Front` (draws over player), `AlwaysFront`.
- Tilesheets: vanilla ones referenced by asset name (`spring_outdoorsTileSheet`, `townInterior`, …) placed next to the .tmx when editing, but not shipped if unchanged. Custom tilesheets: name them `z_{{ModId}}_tiles` so they sort after vanilla and keep indices stable; ship the png beside the .tmx (CP resolves relative paths).
- Map properties: `Warp "x y TargetLocation tx ty …"`, `Music`, `Outdoors T`, `Light`, `NPCWarp`, `DayTiles`/`NightTiles`, `ViewportFollowPlayer`.
- Tile properties (Buildings layer): `Action` (e.g. `Action OpenShop <id>`, `Action Message "<key>"`, `Action Warp x y Loc`, `Action Door <NPC>`), `TouchAction` (Back layer: `TouchAction Warp Loc x y`, `TouchAction PlaySound`), `Passable T`, `Water T`, `Diggable T`, `NoSpawn All`, `Type Dirt/Stone/Wood`.
- Tile size 16×16; tilesheet width must be a multiple of 16 and must not change after maps reference it.

## New location (1.6)
```json
{ "Action": "Load", "Target": "Maps/{{ModId}}_Cottage", "FromFile": "assets/maps/Cottage.tmx" },
{ "Action": "EditData", "Target": "Data/Locations", "Entries": {
  "{{ModId}}_Cottage": { "DisplayName": "{{i18n:loc.cottage}}", "DefaultArrivalTile": { "X": 5, "Y": 9 },
    "CreateOnLoad": { "MapPath": "Maps/{{ModId}}_Cottage", "AlwaysActive": false } }
} },
{ "Action": "EditMap", "Target": "Maps/Town", "AddWarps": [ "60 70 {{ModId}}_Cottage 5 9" ] }
```
(CP's older `CustomLocations` feature also works; prefer `Data/Locations` for new mods.) Fish, forage, artifact spots, music per season are fields on the `Data/Locations` entry.

## Editing existing maps
```json
{ "Action": "EditMap", "Target": "Maps/Town", "FromFile": "assets/maps/town_patch.tmx",
  "FromArea": { "X": 0, "Y": 0, "Width": 6, "Height": 4 }, "ToArea": { "X": 40, "Y": 60, "Width": 6, "Height": 4 },
  "PatchMode": "ReplaceByLayer" },
{ "Action": "EditMap", "Target": "Maps/Town", "MapTiles": [
  { "Position": { "X": 41, "Y": 61 }, "Layer": "Buildings", "SetProperties": { "Action": "Message \"{{i18n:sign}}\"" } } ] }
```

## Farm types — `Data/AdditionalFarms`
```json
{ "Action": "EditData", "Target": "Data/AdditionalFarms", "Entries": {
  "{{ModId}}_RiverFarm": { "Id": "{{ModId}}_RiverFarm", "TooltipStringPath": "Strings/UI:{{ModId}}_RiverFarm",
    "MapName": "{{ModId}}_RiverFarm", "IconTexture": "Mods/{{ModId}}/FarmIcon", "WorldMapTexture": "Mods/{{ModId}}/FarmWorldMap" } } },
{ "Action": "Load", "Target": "Maps/{{ModId}}_RiverFarm", "FromFile": "assets/maps/RiverFarm.tmx" }
```
Tooltip string = `Name_Description` in `Strings/UI`. Icon 22×20. Farm-specific settings (fish, forage, starting items) go in `Data/Locations` under `Farm_{{ModId}}_RiverFarm`. Start from a copy of `Maps/Farm.tmx` to keep required tiles (farmhouse, shipping bin, greenhouse, warps).

## Buildings — `Data/Buildings`
```json
"{{ModId}}_Shed": {
  "Name": "{{i18n:shed.name}}", "Description": "{{i18n:shed.desc}}",
  "Texture": "Buildings/{{ModId}}_Shed",
  "Size": { "X": 3, "Y": 2 },
  "Builder": "Robin", "BuildDays": 2, "BuildCost": 10000,
  "BuildMaterials": [ { "ItemId": "(O)388", "Amount": 300 } ],
  "HumanDoor": { "X": 1, "Y": 1 },
  "IndoorMap": "{{ModId}}_ShedInterior",
  "CollisionMap": null
}
```
Texture: width = Size.X·16, height = Size.Y·16 plus roof overhang above (spec `building`, `--frame 48x64` for this example). Animal buildings add `AnimalDoor`, `ValidOccupantTypes`, `MaxOccupants`. Seasonal skins: `Skins` list; or use Alternative Textures.

## Generation notes
Tilesheets are generated in chunks (per object/area) and assembled; ground tiles benefit from img2img on a tiled placeholder for seamlessness. Keep the tilesheet layout fixed before mapping in Tiled.

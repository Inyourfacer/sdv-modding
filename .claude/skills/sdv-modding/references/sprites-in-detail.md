# Sprites in Detail (HD NPC sprites)

Framework: `BleakCodex.SpritesInDetail` (Nexus 14487, needs Content Patcher). It draws an NPC from a larger sheet while the game still uses the vanilla 16x32 frame grid, so HD art needs no new animation data. Check the installed version with `doctor.py`.

**Source of the facts below:** the framework's manifest and a working pack (`content.json` of a real `[SID]` pack, framework 0.6.1). Fields beyond those listed were not seen and are not checked by the validator; read the Nexus page before using one.

## Pack layout
```
[SID] My Sprites/
  manifest.json        ContentPackFor: BleakCodex.SpritesInDetail
  content.json         { "Sprites": [ ... ] }
  assets/Mira_hd.png
```
Scaffold: `new_mod.py --type sid --name "My Sprites" --author Me --out <dir>`. The framework's own config (`Mods/SpritesInDetail/config.json`) is `{"Enabled": "true"}`.

## Entry
```json
{
  "Target": "Characters/Me.MyMod_Mira",
  "FromFile": "assets/Mira_hd.png",
  "SpriteWidth": 16, "SpriteHeight": 32,
  "WidthScale": 8, "HeightScale": 8,
  "SpriteOriginX": 64, "SpriteOriginY": 225,
  "BreathType": "None"
}
```
- `Target`: the vanilla-side asset the sheet replaces, normally `Characters/<NPC internal name>`. Variants (beach, etc.) are separate entries pointing at the same or another file.
- `WidthScale`/`HeightScale`: HD sheet size divided by the vanilla sheet size. The 4x4 vanilla layout stays: a 64x128 vanilla sheet at scale 8 is **512x1024**, each frame **128x256**, rows down / right / up / left.
- `SpriteWidth`/`SpriteHeight`: how large one frame is drawn, in game pixels (vanilla 16x32). Keep 1:2. Bigger numbers draw the character bigger (18x36, 20x40, 24x48...); use it to match figure height between characters.
- `SpriteOriginX/Y`: the point in the HD frame that stands on the NPC's tile. Put Y a little above the feet (vanilla's origin is 8,24 in a 16x32 frame, so about 75% down), so feet land where vanilla feet do.
- `BreathType`: `"None"` was used in the reference pack; other values were not seen.

## Making the art
Use the `hd:N` target of `postprocess.py`; it never palette-crushes, so the HD sheet keeps the generated detail:
```
python postprocess.py --jobs comfy/Mira_sprite/jobs.json --images runs/Mira/<ts>/outputs \
    --target vanilla=art/Mira.png --target hd:8=art/Mira_hd.png
```
Both come from the same master image, so they match. One frame per facing is generated; the four columns of each row are copies, so the HD sprite does not animate its steps (the framework only swaps frames). Hand-drawn or LoRA-made walk frames can replace row frames afterwards with `sheet.py copy-frame` / `assemble`.

## Checks (`validate_mod.py`)
Required `Target`, `FromFile`, `WidthScale`, `HeightScale`; file exists and is not a placeholder; sheet size divisible by the scale; vanilla-size width a multiple of 16; `SpriteWidth:SpriteHeight` is 1:2; origin inside the HD frame (16·scale x 32·scale). Unknown fields are reported as INFO only.

## In game
`patch summary <your CP/SID UniqueID>` shows whether the pack loaded; a sprite that looks the old size usually means the `Target` name does not match the NPC's internal name.

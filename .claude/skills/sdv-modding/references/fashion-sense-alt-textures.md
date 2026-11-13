# Fashion Sense & Alternative Textures

Both by PeacefulEnd. Docs of record: the Fashion Sense and Alternative Textures GitHub wikis (Floogen). Copy field names from an existing pack when adding an unfamiliar feature.

## Fashion Sense (`PeacefulEnd.FashionSense`)
```
[FS] My Styles/
  manifest.json            (ContentPackFor: PeacefulEnd.FashionSense)
  Hairs/<Name>/hair.json + hair.png
  Accessories/<Name>/accessory.json + accessory.png
  Hats/<Name>/hat.json + hat.png
  Shirts/<Name>/shirt.json + shirt.png
  Pants/<Name>/pants.json + pants.png
  Sleeves/<Name>/sleeves.json + sleeves.png
  Shoes/<Name>/shoes.json + shoes.png
```
hair.json (one model per facing; StartingPosition = top-left of that frame in the png):
```json
{
  "Name": "Long Braid",
  "FrontHair": { "StartingPosition": { "X": 0,  "Y": 0 }, "HairSize": { "Width": 16, "Height": 32 } },
  "RightHair": { "StartingPosition": { "X": 16, "Y": 0 }, "HairSize": { "Width": 16, "Height": 32 } },
  "LeftHair":  { "StartingPosition": { "X": 32, "Y": 0 }, "HairSize": { "Width": 16, "Height": 32 } },
  "BackHair":  { "StartingPosition": { "X": 48, "Y": 0 }, "HairSize": { "Width": 16, "Height": 32 } }
}
```
This matches the `fs_hair` spec layout (front, right, left, back left→right). Other types follow the same pattern with `FrontAccessory`/`AccessorySize`, `FrontHat`/`HatSize`, `FrontShirt`/`ShirtSize`, `FrontPants`/`PantsSize`, etc. Optional per-model features: `Flipped` (reuse right for left), `HeightOffset`, `DisableGrayscale`, `ColorMasks`, `SkinToneMasks`, `UniformAnimation`/`IdleAnimation`/`MovementAnimation` (frame lists), `Conditions`, `DrawBeforeHair`/`DrawBeforePlayer` for accessories, `HideWhileSwimming`. Grayscale art is tinted by the player's chosen color unless `DisableGrayscale: true` — generate/post-process hair in grayscale (`postprocess.py --grayscale`) when the user wants recolorable hair.

## Alternative Textures (`PeacefulEnd.AlternativeTextures`)
```
[AT] My Variants/
  manifest.json            (ContentPackFor: PeacefulEnd.AlternativeTextures)
  Textures/<Name>/texture.json + texture.png
```
```json
{
  "ItemName": "Keg",
  "Type": "Craftable",
  "TextureWidth": 16, "TextureHeight": 32,
  "Variations": 3,
  "Seasons": [],
  "Keywords": [ "rustic" ]
}
```
`Type` values include `Craftable`, `Furniture`, `Building`, `Crop`, `FruitTree`, `Tree`, `GiantCrop`, `ResourceClump`, `Bush`, `Flooring`, `Grass`, `Character`, `Decoration` (not checkable from the game files: see the Alternative Textures wiki for the current list). Variations stack vertically (spec `alt_texture`, `--frame 16x32 --rows <Variations>`). Seasonal textures: set `Seasons` and provide `texture_spring.png` etc. (naming is defined by the framework, not the game: see its wiki). For mod items, `ItemName` is the item's internal name (1.6: often `{{ModId}}_Thing`) or use `ItemId` where supported.

## Augmenting
Add new folders under `Hairs/`, `Textures/` etc. in the user's pack; keep naming and size conventions identical to siblings already in the pack.

# Portraits

## Layout (all methods)
Sheet = 2 columns of square frames, row-major. Frame index → dialogue command:

| idx | cmd | meaning |
|---|---|---|
| 0 | (default) / `$0` | neutral |
| 1 | `$h` / `$1` | happy |
| 2 | `$s` / `$2` | sad |
| 3 | `$u` / `$3` | unique |
| 4 | `$l` / `$4` | love/blush |
| 5 | `$a` / `$5` | angry |
| 6+ | `$6`, `$7`… | custom extras (add rows) |

Vanilla: 64×64 frames → 128 px wide. Height = rows × 64. Spec keys: `portrait` / `portrait_hd` in `assets/asset_specs.json`.

## 1. Vanilla-size via Content Patcher
```json
{ "Action": "Load", "Target": "Portraits/Abigail", "FromFile": "assets/Abigail.png" }
```
Variants by condition use tokens in `FromFile` or `When`. Location/outfit variants: vanilla uses separate assets like `Portraits/Abigail_Beach`; 1.6 NPC `Appearance` entries in `Data/Characters` can point to any portrait asset by season/location/condition (see `npcs-dialogue-events.md`). New NPCs: load `Portraits/<InternalName>`.

## 2. Portraiture (Platonymous.Portraiture) — HD, player-selectable
Recommended HD route on 1.6. Two install forms; both use the same files:

**Folder form** — user copies into `Mods/Portraiture/Portraits/<FolderName>/`.

**Content pack form** — installs directly in `Mods/`:
```
[Portraiture] My HD Portraits/
  manifest.json      (ContentPackFor: Platonymous.Portraiture)
  Abigail.png
  Abigail_winter.png
  Abigail_IslandSouth.png
```
```json
{
  "Name": "My HD Portraits", "Author": "Me", "Version": "1.0.0", "Description": "…",
  "UniqueID": "Me.MyHDPortraits", "UpdateKeys": [],
  "ContentPackFor": { "UniqueID": "Platonymous.Portraiture" }
}
```
Rules:
- File name = the NPC's name as the game shows it in dialogue (e.g. `Leo.png`, not the internal `ParrotBoy`). For mod NPCs check what the dialogue box displays.
- Frame size is inferred from width / 2; any square size works (128, 256, 512). Keep all files in one folder at the same frame size.
- Variant suffixes: `_<season>` lowercase (`_spring`, `_winter`), `_<LocationName>` (`_IslandSouth` for beach outfits). The suffix rules come from the Portraiture mod, not the game files: read its current page before adding new variant kinds.
- Players switch portrait sets in-game with the Portraiture hotkey (default `P`) during dialogue.

## 3. HD Portraits (tlitookilakin) via Content Patcher
CP-driven HD portraits with a size metadata asset. 1.6 compatibility of this framework has varied — check the mod page before choosing it. Only use when the user asks for it.

## Augmenting an existing portrait mod
- Adding expressions: extend height by 64·N (or frame·N); never change width. Reference new frames with `$6`, `$7`…
- Adding an NPC to someone's Portraiture set: create your own content pack with the same frame size rather than writing into theirs.
- Mod NPC portraits: use the mod NPC's internal name for `Portraits/<Name>` loads, display name for Portraiture files.

## Generation notes
Generate one image per expression with the same seed + character LoRA; generate neutral first, then img2img the other expressions from it at denoise 0.45–0.6 for consistency (`make_comfy_workflow.py --init`). Post-process with `--spec portrait` (or `portrait_hd --frame 256`).

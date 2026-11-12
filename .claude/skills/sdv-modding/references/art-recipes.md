# Art recipes: consistent characters and assets

Use these for anything with a character in it. One-off items and tiles can use the `simple` recipe (see `asset-pipeline.md`).
All recipes use core ComfyUI nodes only, write `*.api.json` workflows plus a `jobs.json` that `postprocess.py` reads, and run through `comfy.py`.

## Order of work for a character (enforced by `batch.py`)
1. **Style locked?** `project.py status` shows `style locked`. If not: `style.py test --candidate "label=checkpoint[+lora:0.8:trigger]" ...` builds the same small test set for each candidate, runs it, and writes `style-test/comparison.png` (game-size results, 4x, next to the owner's unpacked vanilla art when available). Look at the image, show it to the owner, then `style.py lock ...`. Do not pick the style yourself.
2. **Reference approved?** Add the character to `sdv-project.json` (`characters.<id>`: `subject` tags, optional `seed`, `outfits`, `loras`). With no approved reference, `batch.py run` makes a `reference_sheet` (front/side/back turnaround) and stops for that character. Show the owner; `batch.py approve-reference <character> <image>` copies the pick to `art/<character>/reference.png` and records it.
3. **Everything else derives from the reference**: portraits, outfits, sprites. Same seed, same canonical tags, same LoRAs, always.
4. **Candidates, not installs.** `batch.py run` writes `art/<asset-id>/take_a|b|c.png` (default 3 takes, seeds `base + 1000*k`) and sets status `generated`. Nothing is written into a mod folder; installing a take is a separate step after the owner approves (and QA, Phase 5).

## Recipes
| Recipe | What it does | Needs | Command |
|---|---|---|---|
| `reference_sheet` | one 1536x1024 turnaround image | style | `make_comfy_workflow.py --recipe reference_sheet --name X --character X --out-dir comfy/X_ref` |
| `portrait_sheet` | one neutral base; every expression re-sampled from the same latent at denoise 0.55 (`--denoise`); with `--outfit-tags`, the outfit is re-drawn from the default look first (0.65) | reference (optional but recommended) | `--recipe portrait_sheet --name X --character X [--outfit beach] [--rows 5 for extended $6-$9]` |
| `sprite_sheet` | in-context inpainting: reference in the left half of an 1664x1216 canvas, only the right half is generated; down/right/up generated, left mirrored | reference (required) | `--recipe sprite_sheet --name X --character X` |
| `simple` | one independent image per frame | nothing | `--spec <key> --subject "..."` |

Add `--preset illustrious|pony` to fill prompt/sampler defaults for a model family (`assets/presets.json`); a locked `art_style` always wins. `--frames neutral,happy` or `--frames right` regenerates only those jobs; `postprocess.py` keeps every other frame of the existing sheet.

Run and collect: `comfy.py run comfy/X/*.api.json --asset-id X`, then `postprocess.py --jobs comfy/X/jobs.json --images runs/X/<ts>/outputs --out <candidate>.png`. `batch.py` does both for every selected asset.

## Honest limits (say this once when doing sprites, not repeatedly)
- Diffusion models do not make clean 16x32 walk cycles. `sprite_sheet` produces one pose per facing and copies it across that row's four frames; the walk bob is not generated.
- Working routes, in order: (1) the HD route: Sprites in Detail with a large clean standing sprite, no walk art needed beyond the offset animation the framework does; (2) hand clean-up of the vanilla sheet in Aseprite when installed; (3) a sprite-sheet LoRA the owner supplies.
- 64x64 portraits lose small facial detail in the downscale. For faces that matter, make the HD (Portraiture) target and treat the vanilla one as the fallback.

## Known failures and fixes
| Symptom | Fix |
|---|---|
| Expressions look like a different person | Lower `--denoise` to 0.40-0.50; keep seed and tags identical |
| Expression barely changes | Raise `--denoise` to 0.60-0.70 or strengthen the emotion tags (add `(tag:1.3)`) |
| Outfit doesn't change enough / changes the face | Outfit stage `ctx.outfit_denoise` is 0.65: raise for the outfit, lower for the face; or use a more specific outfit tag list |
| Sprite facing wrong direction | Regenerate that row: `--recipe sprite_sheet --frames <dir>` with a different seed; put the facing in the subject only if it keeps failing |
| Sprite doesn't match the reference | Use a cleaner reference (full body, plain background); keep the reference at the same style as the sprite LoRA |
| Background fringe after post-process | `postprocess.py --bg-tol 60` (more aggressive); or regenerate with `white background` in the framing |
| ComfyUI says a checkpoint/LoRA/node is missing | `comfy.py models` lists what the server sees; names must match exactly (subfolders use `/`) |
| Everything is one flat colour block at game size | Too few palette colours: raise `postprocess.portrait_colors` / `--colors`; lock a character palette (Phase 4) |

Add new rows here when a failure and its fix are confirmed in a real run.

## Custom nodes
Core-only graphs always work. Reference conditioning (IPAdapter), pose control (ControlNet/OpenPose) and background matting nodes improve consistency and cut-outs; `doctor.py` lists which are installed. Recipes using them must keep a core-node fallback. Installing a node pack is the owner's step; name the pack and ask.

# Observatory art: ComfyUI workflows

Checkpoint `waiIllustriousSDXL_v170.safetensors` (WAI Illustrious v17). LoRAs come from `sdv-modding.config.json` → `comfyui.asset_type_loras`:
- sprites, items, furniture, buildings, tiles: `coropata_pixel.safetensors` (0.8) + `pixel-art-xl.safetensors` (0.5, trigger `pixel art`)
- portraits: `jab_illustrious_V1.5.safetensors` (0.8)

**File names are guesses.** If a loader node turns red in ComfyUI, change the name in `sdv-modding.config.json` to match your file and re-run the `make_comfy_workflow.py` lines below. To use only one pixel LoRA, delete the other from the config.

All pieces share seed `7311042` so the style stays consistent.

| Piece | Folder | Output size | Tilesheet slot |
|---|---|---|---|
| Dome exterior | `dome/` | 80×96 | 5×6 tiles at col 5, row 1 |
| Telescope | `telescope/` | 48×48 | 3×3 at col 2, row 1 |
| Star-chart board | `board/` | 32×32 | 2×2 at col 0, row 1 |
| Journal desk | `desk/` | 32×16 | 2×1 at col 14, row 0 |
| Floor / wall / rug / roof deck | `floor/` `wall/` `rug/` `deck/` | 16×16 | single tiles |

## Steps (on your PC, from the repo root)
1. In ComfyUI (Stability Matrix), drag in `comfy/observatory/<piece>/<piece>_*.json` (not the `.api.json`) and queue it. Change the seed and re-queue until you like the result. Images save to `<ComfyUI output>/sdv/`.
2. Post-process each piece into its exact pixel size:
   ```
   python .claude/skills/sdv-modding/scripts/postprocess.py --jobs comfy/observatory/dome/jobs.json --images "C:\StabilityMatrix\Data\Packages\ComfyUI\output" --out tools/observatory/art/dome.png
   ```
   Same for `telescope`, `board`, `desk`, `floor`, `wall`, `rug`, `deck`. To choose a specific image, use `--pick frame_0=path\to\image.png`.
3. Rebuild the tilesheet: `python tools/observatory/build_assets.py`. Each piece is pasted into its slot. The sheet stays flagged as placeholder until all 8 pieces exist.
4. Validate and install: `validate_mod.py "mods/[CP] Observatory"`, then `deploy.py "mods/[CP] Observatory"`.

Tiles not listed (wall trim, windows, door mat, sky, railing) keep the hand-drawn pixel art from `build_assets.py`.

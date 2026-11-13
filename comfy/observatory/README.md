# Observatory art: ComfyUI workflows

Every piece here is location/tilesheet art, so all 8 use **Flux**: checkpoint `flux_dev.safetensors` with the Stardew Valley Style LoRA (Civitai 769753, `stardew-valley-style-000012.safetensors`, trigger `STDW`, strength 1.0). Settings: CFG 1.0, Flux guidance 3.5, 20 steps, euler / simple, no negative prompt. `sdv-modding.config.json` → `comfyui.asset_type_family` sends the `tilesheet` and `building` specs to Flux; the telescope, board and desk use the furniture spec, so they're generated with `--family flux`.

Everything else in your projects stays on WAI Illustrious v17 (`comfyui.checkpoint`): sprites and items with `coropata_pixel` + `pixel-art-xl`, portraits with `jab_illustrious_V1.5`.

**Models confirmed:** `flux_dev.safetensors` is an all-in-one Flux file (about 16 GB, text encoders and VAE built in) in Stability Matrix's shared `Data\Models\StableDiffusion` folder, so `comfyui.flux.loader` stays `"checkpoint"`. The LoRA is `stardew-valley-style-000012.safetensors`.

All pieces share seed `7311042` so the style stays consistent.

| Piece | Folder | Output size | Tilesheet slot |
|---|---|---|---|
| Dome exterior | `dome/` | 80×96 | 5×6 tiles at col 5, row 1 |
| Telescope | `telescope/` | 48×48 | 3×3 at col 2, row 1 |
| Star-chart board | `board/` | 32×32 | 2×2 at col 0, row 1 |
| Journal desk | `desk/` | 32×16 | 2×1 at col 14, row 0 |
| Floor / wall / rug / roof deck | `floor/` `wall/` `rug/` `deck/` | 16×16 | single tiles |

## Steps (on your PC, from the repo root)
Let `S=.claude/skills/sdv-modding/scripts`.

1. Check the setup: `python $S/doctor.py --write-config` finds the game, SMAPI, ComfyUI and your model files and fills the `null`s in `sdv-modding.config.json`. Then `python $S/comfy.py models` lists the real checkpoint and LoRA names. Fix the config if they differ from the guesses above, and regenerate the workflows (step 5).
2. Generate. Start ComfyUI, then for each piece:
   ```
   python $S/comfy.py run comfy/observatory/dome/*.api.json --asset-id observatory_dome
   ```
   Results land in `runs/observatory_dome/<time>/outputs/`. Or drag the UI-format `.json` (not `.api.json`) into ComfyUI and queue it by hand.
3. Post-process to the exact pixel size (`--resample dominant` gives crisper pixels):
   ```
   python $S/postprocess.py --jobs comfy/observatory/dome/jobs.json --images runs/observatory_dome --resample dominant --out tools/observatory/art/dome.png
   ```
   For a matching palette across pieces, add `--palette tools/observatory/art/dome.png` to the later ones.
4. Rebuild the tilesheet: `python tools/observatory/build_assets.py`. It stays flagged as placeholder until all 8 pieces exist. Check the result with `python $S/tmx.py render "mods/[CP] Observatory/assets/maps/Observatory.tmx" --out obs.png` and look at it.
5. To regenerate after a config change: `make_comfy_workflow.py --seed 7311042 --api --cols 1 --rows 1` with `--spec building --frame 80x96` (dome), `--spec furniture --family flux --frame 48x48 / 32x32 / 32x16` (telescope / board / desk), `--spec tilesheet --frame 16x16` (floor, wall, rug, deck). The subjects are in each folder's `jobs.json`.

Tiles not listed (wall trim, windows, door mat, sky, railing) keep the hand-drawn pixel art from `build_assets.py`.

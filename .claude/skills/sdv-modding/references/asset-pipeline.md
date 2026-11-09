# Asset pipeline: placeholder → ComfyUI → game-ready sheet

Specs live in `assets/asset_specs.json` (keys: `portrait`, `portrait_hd`, `character_sprite`, `object_icon`, `big_craftable`, `crop`, `fruit_tree`, `furniture`, `hat`, `shirt`, `fs_hair`, `fs_accessory`, `alt_texture`, `tilesheet`, `building`). Override per asset with `--frame WxH --cols N --rows N`. If the spec has `"verify": true`, unpack the game first (StardewXnbHack → `Content (unpacked)/`) and match the vanilla layout.

## 1. Placeholder
```
python "${CLAUDE_SKILL_DIR}/scripts/make_placeholder.py" --spec <key> --out "<mod>/assets/<file>.png" [--label Name] [--color hex] [--init-dir comfy/<name>_init]
```
- Exact sheet size, frame grid, labelled frames (≥32 px), silhouettes (portrait head/shoulders with expression hint; character with facing/walk offset; generic block otherwise).
- PNG carries `sdv_placeholder=1`; `validate_mod.py` warns until it is replaced; the script refuses to overwrite real art without `--force`.
- `--init-dir` writes one composition guide per frame at generation size for img2img.

## 2. ComfyUI workflows (Stability Matrix + Illustrious/SDXL + LoRAs)
```
python "${CLAUDE_SKILL_DIR}/scripts/make_comfy_workflow.py" --spec <key> --name <Name> --subject "<tags>" --out-dir comfy/<Name>_<key> [options]
```
Writes `<Name>_<key>_<job>.json` (UI format — drag into ComfyUI or Load) per job and `jobs.json`.
Graph: `CheckpointLoaderSimple → CLIPSetLastLayer(-clip_skip) → LoraLoader×N → CLIPTextEncode(+/−) → EmptyLatentImage | LoadImage+VAEEncode → KSampler(seed fixed) → VAEDecode → SaveImage("sdv/<Name>_<key>_<job>")` + a Note node with the target spec. Only core nodes — no custom nodes required.

Key options:
- `--frames a,b` emit only those jobs; `--per-row` one job per sheet row (sprite directions); `--mirror-left` left row mirrored from right at post-process.
- `--init <file|folder>` img2img from a guide or an earlier result; `--denoise 0.4–0.7`. Files are copied into ComfyUI's `input` folder when `comfyui.input_dir` exists, else into `<out-dir>/input/` for the user to copy.
- `--lora file.safetensors:0.8[:clip][:trigger words]` (repeatable) adds to config LoRAs; `--no-config-loras` uses only these. Per-asset-type LoRAs: `comfyui.asset_type_loras.<spec>` in config.
- `--seed N` shared by all jobs (consistency); `--extra`, `--negative-extra`; `--api` also writes API-format JSON.

Config (`sdv-modding.config.json` → `comfyui`): checkpoint file name as ComfyUI lists it, `clip_skip` (Illustrious: 2), sampler/scheduler/steps/cfg (Illustrious defaults: euler_ancestral, normal, 24–30 steps, CFG 5–7), `quality_prefix`, `negative`, `style_suffix`.

Stability Matrix (Windows) default locations — confirm in its settings:
- checkpoints `…\StabilityMatrix\Data\Models\StableDiffusion\`, LoRAs `…\Data\Models\Lora\`
- ComfyUI input/output `…\Data\Packages\ComfyUI\input\` / `…\output\`

Prompting for Illustrious: Danbooru-style tags work best (`1girl, solo, short hair, teal hair, freckles, overalls, smile`). Keep subject tags identical across all jobs of one asset; only the expression/direction/stage words change (the script does this).

Consistency strategies (use what the user asks for; offer when they report drift):
1. Same seed + same subject tags (default).
2. Generate the anchor (portrait neutral / sprite `down`) first, pick the best, then run the rest with `--init <that image> --denoise 0.45–0.6`.
3. A character LoRA (`--lora`).
4. IPAdapter / ControlNet are custom-node options; only add them if the user has them installed (ask for the node names).

Honest limits: SD models don't produce clean 16×32 walk cycles. The default sprite flow generates one pose per direction and fills that row; animation frames are usually hand-adjusted afterwards (or generated with a sprite-sheet LoRA the user supplies). Say this once when doing sprites, not repeatedly.

## 3. Post-process
```
python "${CLAUDE_SKILL_DIR}/scripts/postprocess.py" --jobs comfy/<dir>/jobs.json --images "<ComfyUI output>" --out "<mod>/assets/<file>.png"
python "${CLAUDE_SKILL_DIR}/scripts/postprocess.py" --jobs jobs.json --pick happy=path.png ...      # choose specific outputs
python "${CLAUDE_SKILL_DIR}/scripts/postprocess.py" --spec object_icon --inputs a.png b.png --out sheet.png   # no jobs.json
```
Per frame: border-connected background removal (sprites/items; `--background keep|remove`, `--bg-tol`) → crop to subject → fit into frame (bottom-anchored for characters/craftables, fill-crop for portraits/tiles) → premultiplied area downscale → hard alpha → median-cut palette (`--colors`, defaults from config by type, or `--palette palette.png` to lock to a shared palette) → optional `--grayscale` (recolorable FS hair) and `--outline`.
Uncovered frames keep the existing sheet's pixels (the placeholder), and the file stays flagged as a placeholder until every frame is filled. A 4× preview is written beside `jobs.json`.

## 4. Validate
`python "${CLAUDE_SKILL_DIR}/scripts/validate_mod.py" "<mod>"` — dimensions for `Portraits/*` and `Characters/*` targets, FS/AT rect bounds, Portraiture frame shape, placeholders still present.

## Manual art
If the user supplies their own images, skip steps 1–2 and run step 3 with `--inputs` (or `--background keep --colors 256` to only resize/arrange).

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

## 2b. Run it: `comfy.py` (ComfyUI API, no manual queueing)
Add `--api` to `make_comfy_workflow.py` so it also writes `*.api.json`, then:
```
python "${CLAUDE_SKILL_DIR}/scripts/comfy.py" status                      # is ComfyUI up? (never starts it)
python "${CLAUDE_SKILL_DIR}/scripts/comfy.py" run comfy/<Name>_<key>/*.api.json --asset-id <id>
```
`run` checks every workflow against the server first (node classes, checkpoint, LoRAs, sampler names; init images are uploaded automatically) and queues nothing if anything is missing, naming it. It then queues, waits, downloads the images into `runs/<asset-id>/<timestamp>/outputs/` with `run.json` and a copy of each workflow, and prints the postprocess command to use (`--images <that outputs folder>`). Raw outputs never go into a mod folder.
- Other commands: `models` (checkpoints/LoRAs the server sees), `check`, `upload`, `queue --wait`, `fetch`, `interrupt`.
- Exit code 2 = ComfyUI unreachable. **Ask the owner before starting ComfyUI**; add `--start` only after they said yes in this conversation (needs `comfyui_root` in the config; `doctor.py --write-config` sets it).
- The URL defaults to `http://127.0.0.1:8188`; override with `--url` or `comfyui.url` in the config.
- If the owner would rather queue by hand, the UI-format JSON files still drag into ComfyUI as before.

## 3. Post-process (one master image -> every target)
```
python "${CLAUDE_SKILL_DIR}/scripts/postprocess.py" --jobs comfy/<dir>/jobs.json --images runs/<asset>/<ts>/outputs --out "<mod>/assets/<file>.png"
python "${CLAUDE_SKILL_DIR}/scripts/postprocess.py" --jobs jobs.json --images outputs --target vanilla=a.png --target hd:8=a_hd.png --target portraiture:256=a_256.png
python "${CLAUDE_SKILL_DIR}/scripts/postprocess.py" --jobs jobs.json --pick happy=path.png ...      # choose specific outputs
python "${CLAUDE_SKILL_DIR}/scripts/postprocess.py" --spec object_icon --inputs a.png b.png --out sheet.png   # no jobs.json
```
Targets: `vanilla` (game size), `hd:N` (vanilla frame x N, full colour; Sprites in Detail, see `sprites-in-detail.md`), `portraiture:F` (square F px frames, full colour; Portraiture, see `portraits.md`). Assets can list their targets in `sdv-project.json` (`"targets": [{"kind":"vanilla"},{"kind":"hd","scale":8}]`); `batch.py` then writes every target beside each take (`take_a.png`, `take_a.hd8.png`).

Vanilla pipeline: border-connected background removal (cut-out specs) -> crop to subject -> **one common scale for the whole sheet** (so a figure keeps its relative size in every facing; `--no-consistent-scale` to fit each frame alone) -> downscale -> hard alpha -> **one palette for the whole sheet** (`--colors N`) -> orphan-pixel and single-pixel-hole cleanup (`--no-cleanup`) -> optional `--outline` / `--grayscale` (recolorable FS hair).
- Downscale: `--resample auto` uses *dominant colour per output pixel* for cut-out subjects (sprites, items: crisp pixel look) and area averaging for portraits and tiles (faces stay readable). Force with `--resample dominant|box`. Live-tested: dominant is crisper but turns small eyes into dark blobs, so judge sprites at game size before accepting; the HD target is the better route for detailed faces.
- Locked palettes: `palette.py build --images <approved reference(s)> --colors 24 --out art/<char>/palette.png --lock <char>` records `characters.<char>.palette_png`; then `postprocess.py --character <char>` (or `--palette <png>`) maps every colour to the nearest palette colour (Lab distance), so portraits, outfits and sprites of one character share colours. `--save-palette` writes the palette a sheet used.
- Frames not covered keep the existing sheet's pixels (the placeholder); the file stays flagged as a placeholder until every frame is filled. A 4x preview is written beside `jobs.json`.

### Fixing one frame without regenerating: `sheet.py`
`slice`, `assemble`, `mirror-row`, `shift-frame`, `copy-frame`, `preview-anim` (GIF of a row at game-like speed), `diff`. Always writes to `--out`. Example: `sheet.py shift-frame sheet.png --spec character_sprite --frame-index 5 --dy -1 --out fixed.png`, then `sheet.py preview-anim fixed.png --spec character_sprite --row right --out right.gif` and look at it.

## 4. Validate
`python "${CLAUDE_SKILL_DIR}/scripts/validate_mod.py" "<mod>"` — dimensions for `Portraits/*` and `Characters/*` targets, FS/AT rect bounds, Portraiture frame shape, placeholders still present.

## Manual art
If the user supplies their own images, skip steps 1–2 and run step 3 with `--inputs` (or `--background keep --colors 256` to only resize/arrange).

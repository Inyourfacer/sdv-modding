#!/usr/bin/env python3
"""Generate ComfyUI workflow JSON (UI format, drag-and-drop loadable) for SDV assets.

One workflow per job (expression / direction / stage / variant) + jobs.json describing how
outputs map back into the sheet. Targets an SDXL/Illustrious checkpoint with a LoRA chain.

  python make_comfy_workflow.py --spec portrait --name Mira \
      --subject "1girl, young woman, short teal hair, freckles, green overalls" --out-dir comfy/Mira_portrait

  # consistent expressions: generate neutral first, then img2img the others from it
  python make_comfy_workflow.py --spec portrait --name Mira --subject "..." --out-dir comfy/Mira_portrait \
      --init comfy/Mira_portrait/neutral_result.png --denoise 0.5 --frames happy,sad,unique,love,angry

  # character sprites: one image per direction, copied across that row's walk frames; left mirrored from right
  python make_comfy_workflow.py --spec character_sprite --name Mira --subject "..." --per-row --mirror-left --out-dir comfy/Mira_sprite

Options: --lora file:model[:clip] (repeatable, adds to config LoRAs), --no-config-loras,
--seed N (fixed seed shared by all jobs; default random per run but fixed across jobs),
--extra "tags", --negative-extra "tags", --api (also write API-format prompt JSON).
"""
from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

from sdvlib import dump_json, get_spec, load_config, load_project, safe_name

DIRECTION_WORDS = {"down": "front", "front": "front", "right": "right side", "left": "left side", "up": "back", "back": "back"}
EXPRESSION_WORDS = {"neutral": "neutral, calm", "happy": "happy, smiling", "sad": "sad, downcast eyes",
                    "unique": "surprised, unique characteristic pose", "love": "blushing, shy smile", "angry": "angry, frowning"}


# ---------------------------------------------------------------- UI-format graph builder
class Graph:
    def __init__(self):
        self.nodes, self.links = [], []
        self.nid = 0
        self.lid = 0

    def node(self, ntype, inputs, outputs, widgets, pos, size=(320, 120), title=None):
        self.nid += 1
        n = {
            "id": self.nid, "type": ntype, "pos": list(pos), "size": list(size), "flags": {},
            "order": self.nid - 1, "mode": 0,
            "inputs": [{"name": nm, "type": tp, "link": None} for nm, tp in inputs],
            "outputs": [{"name": nm, "type": tp, "links": [], "slot_index": i} for i, (nm, tp) in enumerate(outputs)],
            "properties": {"Node name for S&R": ntype},
            "widgets_values": list(widgets),
        }
        if title:
            n["title"] = title
        if not n["inputs"]:
            del n["inputs"]
        self.nodes.append(n)
        return n

    def link(self, src, src_slot, dst, dst_input_name):
        self.lid += 1
        stype = src["outputs"][src_slot]["type"]
        idx = next(i for i, inp in enumerate(dst["inputs"]) if inp["name"] == dst_input_name)
        dst["inputs"][idx]["link"] = self.lid
        src["outputs"][src_slot]["links"].append(self.lid)
        self.links.append([self.lid, src["id"], src_slot, dst["id"], idx, stype])

    def to_ui(self):
        return {"last_node_id": self.nid, "last_link_id": self.lid, "nodes": self.nodes, "links": self.links,
                "groups": [], "config": {}, "extra": {"ds": {"scale": 0.8, "offset": [0, 0]}}, "version": 0.4}

    def to_api(self):
        # API format: {id: {class_type, inputs}} with widget values named.
        widget_names = {
            "CheckpointLoaderSimple": ["ckpt_name"], "CLIPSetLastLayer": ["stop_at_clip_layer"],
            "LoraLoader": ["lora_name", "strength_model", "strength_clip"], "CLIPTextEncode": ["text"],
            "EmptyLatentImage": ["width", "height", "batch_size"], "LoadImage": ["image", "upload"],
            "KSampler": ["seed", "control_after_generate", "steps", "cfg", "sampler_name", "scheduler", "denoise"],
            "SaveImage": ["filename_prefix"], "VAEDecode": [], "VAEEncode": [],
        }
        api = {}
        link_src = {l[0]: (l[1], l[2]) for l in self.links}
        for n in self.nodes:
            if n["type"] == "Note":
                continue
            inputs = {}
            for nm, val in zip(widget_names.get(n["type"], []), n["widgets_values"]):
                if nm in ("control_after_generate", "upload"):
                    continue
                inputs[nm] = val
            for inp in n.get("inputs", []):
                if inp["link"] is not None:
                    s, slot = link_src[inp["link"]]
                    inputs[inp["name"]] = [str(s), slot]
            api[str(n["id"])] = {"class_type": n["type"], "inputs": inputs}
        return api


def build(cfg, ckpt, loras, pos_text, neg_text, w, h, seed, steps, cfg_scale, sampler, scheduler,
          prefix, init_name=None, denoise=1.0, note=""):
    g = Graph()
    ck = g.node("CheckpointLoaderSimple", [], [("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")], [ckpt], (20, 120), (320, 100))
    model_src, clip_src = (ck, 0), (ck, 1)
    clip_skip = int(cfg.get("clip_skip") or 1)
    if clip_skip > 1:
        cs = g.node("CLIPSetLastLayer", [("clip", "CLIP")], [("CLIP", "CLIP")], [-clip_skip], (20, 260), (320, 60))
        g.link(*clip_src, cs, "clip"); clip_src = (cs, 0)
    x = 360
    for i, lo in enumerate(loras):
        ln = g.node("LoraLoader", [("model", "MODEL"), ("clip", "CLIP")], [("MODEL", "MODEL"), ("CLIP", "CLIP")],
                    [lo["name"], float(lo.get("strength_model", 1.0)), float(lo.get("strength_clip", lo.get("strength_model", 1.0)))],
                    (x, 120 + i * 140), (320, 130))
        g.link(*model_src, ln, "model"); g.link(*clip_src, ln, "clip")
        model_src, clip_src = (ln, 0), (ln, 1)
    x = 360 + 340 * (1 if loras else 0)
    pos = g.node("CLIPTextEncode", [("clip", "CLIP")], [("CONDITIONING", "CONDITIONING")], [pos_text], (x, 420), (420, 180), "Positive")
    neg = g.node("CLIPTextEncode", [("clip", "CLIP")], [("CONDITIONING", "CONDITIONING")], [neg_text], (x, 640), (420, 160), "Negative")
    g.link(*clip_src, pos, "clip"); g.link(*clip_src, neg, "clip")

    if init_name:
        li = g.node("LoadImage", [], [("IMAGE", "IMAGE"), ("MASK", "MASK")], [init_name, "image"], (20, 420), (320, 320), "Init / guide image")
        ve = g.node("VAEEncode", [("pixels", "IMAGE"), ("vae", "VAE")], [("LATENT", "LATENT")], [], (20, 780), (220, 50))
        g.link(li, 0, ve, "pixels"); g.link(ck, 2, ve, "vae")
        latent = (ve, 0)
    else:
        el = g.node("EmptyLatentImage", [], [("LATENT", "LATENT")], [w, h, 1], (20, 420), (320, 110))
        latent = (el, 0)
        denoise = 1.0

    ks = g.node("KSampler", [("model", "MODEL"), ("positive", "CONDITIONING"), ("negative", "CONDITIONING"), ("latent_image", "LATENT")],
                [("LATENT", "LATENT")], [seed, "fixed", steps, cfg_scale, sampler, scheduler, round(denoise, 3)], (x + 460, 120), (320, 270))
    g.link(*model_src, ks, "model"); g.link(pos, 0, ks, "positive"); g.link(neg, 0, ks, "negative"); g.link(*latent, ks, "latent_image")
    vd = g.node("VAEDecode", [("samples", "LATENT"), ("vae", "VAE")], [("IMAGE", "IMAGE")], [], (x + 460, 430), (220, 50))
    g.link(ks, 0, vd, "samples"); g.link(ck, 2, vd, "vae")
    sv = g.node("SaveImage", [("images", "IMAGE")], [], [prefix], (x + 820, 120), (420, 460))
    g.link(vd, 0, sv, "images")
    if note:
        g.node("Note", [], [], [note], (x + 460, 520), (340, 200), "SDV target spec")
    return g


def plan_jobs(spec, per_row, mirror_left, only):
    labels = spec["frame_labels"]
    cols = spec["cols"]
    jobs = []
    if per_row:
        for r in range(spec["rows"]):
            frames = list(range(r * cols, (r + 1) * cols))
            lab = labels[frames[0]].split("_")[0]
            jobs.append({"id": lab, "frames": frames, "label": lab})
    else:
        for i, lab in enumerate(labels):
            jobs.append({"id": lab, "frames": [i], "label": lab})
    if mirror_left:
        right = next((j for j in jobs if j["label"].startswith("right")), None)
        for j in jobs:
            if j["label"].startswith("left") and right:
                j["mirror_of"] = right["id"]
    if only:
        keep = set(only)
        for j in jobs:
            if j["id"] not in keep and j["label"] not in keep:
                j["skip"] = True
    return jobs


def fill_prompt(template, subject, label, idx):
    base = label.split("_")[0]
    return (template.replace("{subject}", subject)
            .replace("{expression}", EXPRESSION_WORDS.get(base, base))
            .replace("{direction}", DIRECTION_WORDS.get(base, base))
            .replace("{stage}", label.replace("_", " "))
            .replace("{n}", str(idx + 1)))


def run_recipe(a, cfg, cc, ch):
    """Consistency recipes (sdvcomfy.recipes): API-format workflows + jobs.json, same layout postprocess.py reads."""
    from sdvcomfy import recipes
    from sdvcomfy.graph import settings_from
    spec_key = a.spec or recipes.DEFAULT_SPEC[a.recipe]
    spec = get_spec(spec_key, a.frame, a.cols, a.rows) if spec_key else None
    loras = list(cc.get("loras") or []) + list((cc.get("asset_type_loras") or {}).get(spec_key, [])) if not a.no_config_loras else []
    loras += list(ch.get("loras") or [])
    for x in a.lora:
        parts = x.split(":")
        lo = {"name": parts[0], "strength_model": float(parts[1]) if len(parts) > 1 else 1.0}
        lo["strength_clip"] = float(parts[2]) if len(parts) > 2 and parts[2] else lo["strength_model"]
        if len(parts) > 3:
            lo["trigger"] = ":".join(parts[3:])
        loras.append(lo)
    seed = a.seed if a.seed is not None else random.randint(1, 2**31 - 1)
    preset = a.preset or ((cfg.get("_project_art_style") or {}).get("preset"))
    s = settings_from(cfg, a.subject, seed, loras, preset, steps=a.steps, cfg_scale=a.cfg, extra=a.extra, negative_extra=a.negative_extra)
    ctx = recipes.Ctx(s=s, name=safe_name(a.name), out_dir=Path(a.out_dir), spec=spec, spec_key=spec_key,
                      reference=Path(a.reference) if a.reference else None, outfit_tags=a.outfit_tags,
                      frames=a.frames.split(",") if a.frames else None, mirror_left=not a.no_mirror_left)
    if a.denoise is not None:
        ctx.denoise = a.denoise
    man = recipes.get(a.recipe).build(ctx)
    print(f"{a.recipe}: {len(man['workflows'])} workflow(s), {sum(1 for j in man['jobs'] if j.get('output_prefix'))} output(s) + jobs.json -> {a.out_dir}")
    for w in man["workflows"]:
        print("  ", w)
    print(f"run: python comfy.py run {Path(a.out_dir) / '*.api.json'} --asset-id {ctx.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", default="simple", choices=["simple", "portrait_sheet", "sprite_sheet", "reference_sheet"],
                    help="simple = one independent image per frame (default); the others are consistency recipes (references/art-recipes.md)")
    ap.add_argument("--reference", help="approved reference image (needed by sprite_sheet; used by portrait_sheet when given)")
    ap.add_argument("--outfit-tags", default="", help="recipes: outfit tags re-drawn from the default look")
    ap.add_argument("--preset", help="illustrious | pony: fills quality/negative/sampler defaults (assets/presets.json)")
    ap.add_argument("--checkpoint", help="override the configured checkpoint for this run (style tests)")
    ap.add_argument("--spec")
    ap.add_argument("--name", required=True, help="asset/character name used in file prefixes")
    ap.add_argument("--subject", help="Danbooru-style tags or description of the subject (or use --character)")
    ap.add_argument("--character", help="character id in sdv-project.json: supplies subject tags, seed and LoRAs")
    ap.add_argument("--outfit", help="with --character: outfit key from the character's outfits (tags are appended)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--frame"); ap.add_argument("--cols", type=int); ap.add_argument("--rows", type=int)
    ap.add_argument("--frames", help="comma list of job ids/labels to emit (others skipped)")
    ap.add_argument("--per-row", action="store_true", help="one job per sheet row (sprites/directions)")
    ap.add_argument("--no-mirror-left", action="store_true", help="sprite_sheet: generate the left row instead of mirroring right")
    ap.add_argument("--mirror-left", action="store_true", help="left row = mirrored right row (no generation)")
    ap.add_argument("--init", help="init image file, or folder of <label>.png (from make_placeholder --init-dir)")
    ap.add_argument("--denoise", type=float)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--steps", type=int); ap.add_argument("--cfg", type=float)
    ap.add_argument("--lora", action="append", default=[], help="file.safetensors:model_strength[:clip_strength][:trigger words]")
    ap.add_argument("--no-config-loras", action="store_true")
    ap.add_argument("--extra", default=""); ap.add_argument("--negative-extra", default="")
    ap.add_argument("--api", action="store_true", help="also write API-format JSON")
    ap.add_argument("--config")
    a = ap.parse_args()

    cfg = load_config(a.config)
    ch = {}
    if a.character:
        proj = load_project()
        ch = ((proj or {}).get("characters") or {}).get(a.character)
        if not ch:
            raise SystemExit(f"Character '{a.character}' not found in sdv-project.json (python project.py status).")
        outfit = (ch.get("outfits") or {}).get(a.outfit) if a.outfit else None
        if a.recipe != "simple":
            a.outfit_tags = a.outfit_tags or outfit or ""
            a.subject = a.subject or ch.get("subject")
        elif not a.subject:
            a.subject = ", ".join(x for x in [ch.get("subject"), outfit] if x)
        if a.reference is None and ch.get("reference_image") and Path(ch["reference_image"]).exists():
            a.reference = ch["reference_image"]
        if a.seed is None and ch.get("seed") is not None:
            a.seed = int(ch["seed"])
    if not a.subject:
        raise SystemExit("Give --subject tags or --character <id>.")
    cc = cfg["comfyui"]
    if a.checkpoint:
        cc["checkpoint"] = a.checkpoint
    if not cc.get("checkpoint"):
        raise SystemExit("No checkpoint set: put comfyui.checkpoint (a file name ComfyUI lists) in sdv-modding.config.json. "
                         "Run scripts/doctor.py to list the checkpoints found.")
    if a.recipe != "simple":
        return run_recipe(a, cfg, cc, ch)
    if not a.spec:
        raise SystemExit("--spec is required for the simple recipe.")
    spec = get_spec(a.spec, a.frame, a.cols, a.rows)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)

    loras = [] if a.no_config_loras else list(cc.get("loras") or []) + list((cc.get("asset_type_loras") or {}).get(a.spec, []))
    loras += list(ch.get("loras") or [])
    for s in a.lora:
        parts = s.split(":")
        lo = {"name": parts[0], "strength_model": float(parts[1]) if len(parts) > 1 else 1.0}
        lo["strength_clip"] = float(parts[2]) if len(parts) > 2 and parts[2] else lo["strength_model"]
        if len(parts) > 3:
            lo["trigger"] = ":".join(parts[3:])
        loras.append(lo)
    triggers = ", ".join(lo["trigger"] for lo in loras if lo.get("trigger"))

    seed = a.seed if a.seed is not None else random.randint(1, 2**31 - 1)
    jobs = plan_jobs(spec, a.per_row, a.mirror_left, a.frames.split(",") if a.frames else None)
    neg = ", ".join(x for x in [cc["negative"], a.negative_extra] if x)
    denoise = a.denoise if a.denoise is not None else float(cc.get("img2img_denoise", 0.6))

    init_dir = Path(a.init) if a.init and Path(a.init).is_dir() else None
    init_file = Path(a.init) if a.init and Path(a.init).is_file() else None
    comfy_input = Path(cc["input_dir"]) if cc.get("input_dir") else None
    copied = []

    written = []
    for j in jobs:
        if j.get("skip") or j.get("mirror_of"):
            continue
        idx = j["frames"][0]
        tmpl = spec.get("prompt", "{subject}")
        positive = ", ".join(x for x in [cc.get("quality_prefix", ""), triggers, fill_prompt(tmpl, a.subject, j["label"], idx),
                                          cc.get("style_suffix", ""), a.extra] if x)
        prefix = f"sdv/{safe_name(a.name)}_{a.spec}_{safe_name(j['id'])}"
        j["output_prefix"] = prefix

        init_name = None
        src = None
        cands = [safe_name(j["label"]), safe_name(spec["frame_labels"][idx])]
        found = [init_dir / f"{c}.png" for c in cands if init_dir and (init_dir / f"{c}.png").exists()]
        if found:
            src = found[0]
        elif init_file:
            src = init_file
        if src:
            init_name = f"sdv_{safe_name(a.name)}_{a.spec}_{safe_name(j['id'])}_init.png"
            local = out / "input" / init_name
            local.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, local)
            if comfy_input and comfy_input.exists():
                shutil.copyfile(src, comfy_input / init_name); copied.append(init_name)
            j["init"] = init_name

        note = (f"Spec: {a.spec}  frame {spec['frame_w']}x{spec['frame_h']}  sheet {spec['sheet_w']}x{spec['sheet_h']}\n"
                f"Job '{j['id']}' -> frames {j['frames']}\nGame asset: {spec.get('game_asset', '')}\n"
                f"Generate, pick the best output, then run postprocess.py with jobs.json.")
        g = build(cc, cc["checkpoint"], loras, positive, neg, spec["gen_w"], spec["gen_h"], seed,
                  a.steps or int(cc.get("steps", 28)), a.cfg or float(cc.get("cfg", 6.0)), cc.get("sampler", "euler_ancestral"),
                  cc.get("scheduler", "normal"), prefix, init_name, denoise, note)
        wf = out / f"{safe_name(a.name)}_{a.spec}_{safe_name(j['id'])}.json"
        dump_json(g.to_ui(), wf)
        j["workflow"] = wf.name
        j["prompt"] = positive
        if a.api:
            dump_json(g.to_api(), wf.with_name(wf.stem + ".api.json"))
        written.append(wf.name)

    manifest = {
        "spec": a.spec, "name": a.name, "frame_w": spec["frame_w"], "frame_h": spec["frame_h"],
        "cols": spec["cols"], "rows": spec["rows"], "anchor": spec.get("anchor", "center"),
        "remove_bg": spec.get("remove_bg", False), "colors_key": spec.get("colors"),
        "seed": seed, "checkpoint": cc["checkpoint"], "loras": loras, "negative": neg,
        "game_asset": spec.get("game_asset"), "jobs": jobs,
    }
    dump_json(manifest, out / "jobs.json")
    print(f"{len(written)} workflow(s) + jobs.json -> {out}")
    for w in written:
        print("  ", w)
    if any(j.get("init") for j in jobs):
        if copied:
            print(f"init images copied to ComfyUI input: {comfy_input}")
        else:
            print(f"copy the files in {out / 'input'} into your ComfyUI input folder before queueing")
    print(f"ComfyUI saves to <output>/sdv/{safe_name(a.name)}_{a.spec}_*.png")


if __name__ == "__main__":
    main()

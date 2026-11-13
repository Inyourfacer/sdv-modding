"""Tiny API-format ComfyUI graph builder plus the pieces every recipe shares."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PRESETS_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "presets.json"


def presets() -> dict:
    return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))


class ApiGraph:
    """nodes = {id: {"class_type", "inputs"}}; a link is [node_id, output_slot]."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}

    def add(self, class_type: str, **inputs) -> str:
        nid = str(len(self.nodes) + 1)
        self.nodes[nid] = {"class_type": class_type, "inputs": inputs}
        return nid

    def check(self) -> list[str]:
        """Structural problems: links to missing nodes, empty graph."""
        bad = []
        for nid, n in self.nodes.items():
            for k, v in n["inputs"].items():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in self.nodes:
                    bad.append(f"node {nid}.{k} links to missing node {v[0]}")
        return bad or ([] if self.nodes else ["empty graph"])


@dataclass
class Settings:
    ckpt: str
    clip_skip: int = 2
    loras: list = field(default_factory=list)   # {"name", "strength_model", "strength_clip", "trigger"}
    quality: str = ""
    negative: str = ""
    style_suffix: str = ""
    sampler: str = "euler_ancestral"
    scheduler: str = "normal"
    steps: int = 28
    cfg: float = 6.0
    seed: int = 1
    subject: str = ""
    extra: str = ""
    img2img_denoise: float = 0.6

    @property
    def triggers(self) -> str:
        return ", ".join(l["trigger"] for l in self.loras if l.get("trigger"))

    def positive(self, *parts: str) -> str:
        return ", ".join(p for p in [self.quality, self.triggers, *parts, self.style_suffix, self.extra] if p)


def settings_from(cfg: dict, subject: str, seed: int, loras: list, preset: str | None = None, **over) -> Settings:
    """Config/project values. An explicit preset fills prompt/sampler fields; explicit overrides always win."""
    cc = cfg["comfyui"]
    pre = presets().get(preset, {}) if preset else {}

    def pick(key, default=None):
        okey = "cfg_scale" if key == "cfg" else key   # 'cfg' is the config dict argument
        if over.get(okey) is not None:
            return over[okey]
        if key in pre:
            return pre[key]
        return cc.get(key, default)

    s = Settings(
        ckpt=cc["checkpoint"], clip_skip=int(pick("clip_skip", 2) or 1), loras=loras,
        quality=(pre.get("quality") if preset else None) or cc.get("quality_prefix", "") or "",
        negative=pick("negative", "") or "", style_suffix=cc.get("style_suffix", "") or "",
        sampler=pick("sampler", "euler_ancestral"), scheduler=pick("scheduler", "normal"),
        steps=int(pick("steps", 28)), cfg=float(pick("cfg", 6.0)), seed=seed, subject=subject,
        extra=over.get("extra") or "", img2img_denoise=float(cc.get("img2img_denoise", 0.6)))
    if over.get("negative_extra"):
        s.negative = ", ".join(x for x in [s.negative, over["negative_extra"]] if x)
    return s


class Base:
    """Checkpoint -> clip skip -> LoRA chain, with helpers to encode, sample, decode and save."""

    def __init__(self, g: ApiGraph, s: Settings):
        self.g, self.s = g, s
        ck = g.add("CheckpointLoaderSimple", ckpt_name=s.ckpt)
        self.model, self.clip, self.vae = [ck, 0], [ck, 1], [ck, 2]
        if s.clip_skip > 1:
            cs = g.add("CLIPSetLastLayer", clip=self.clip, stop_at_clip_layer=-s.clip_skip)
            self.clip = [cs, 0]
        for lo in s.loras:
            ln = g.add("LoraLoader", model=self.model, clip=self.clip, lora_name=lo["name"],
                       strength_model=float(lo.get("strength_model", 1.0)),
                       strength_clip=float(lo.get("strength_clip", lo.get("strength_model", 1.0))))
            self.model, self.clip = [ln, 0], [ln, 1]
        self.neg = [g.add("CLIPTextEncode", text=s.negative, clip=self.clip), 0]

    def encode(self, text: str) -> list:
        return [self.g.add("CLIPTextEncode", text=text, clip=self.clip), 0]

    def sample(self, positive: list, latent: list, denoise: float = 1.0, seed: int | None = None, negative: list | None = None) -> list:
        ks = self.g.add("KSampler", model=self.model, positive=positive, negative=negative or self.neg, latent_image=latent,
                        seed=self.s.seed if seed is None else seed, steps=self.s.steps, cfg=self.s.cfg,
                        sampler_name=self.s.sampler, scheduler=self.s.scheduler, denoise=round(denoise, 3))
        return [ks, 0]

    def empty_latent(self, w: int, h: int) -> list:
        return [self.g.add("EmptyLatentImage", width=w, height=h, batch_size=1), 0]

    def encode_image(self, image: list) -> list:
        return [self.g.add("VAEEncode", pixels=image, vae=self.vae), 0]

    def decode(self, latent: list) -> list:
        return [self.g.add("VAEDecode", samples=latent, vae=self.vae), 0]

    def save(self, image: list, prefix: str) -> str:
        return self.g.add("SaveImage", images=image, filename_prefix=prefix)

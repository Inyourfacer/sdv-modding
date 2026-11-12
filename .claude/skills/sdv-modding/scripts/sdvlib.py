"""Shared helpers for the sdv-modding skill scripts."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SPECS_PATH = SKILL_DIR / "assets" / "asset_specs.json"
CONFIG_NAME = "sdv-modding.config.json"

DEFAULT_GAME_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Stardew Valley"
DEFAULT_CP_FORMAT = "2.7.0"


# ---------------------------------------------------------------- JSON (SMAPI-tolerant)
def _strip_json_comments(text: str) -> str:
    out, i, n = [], 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        out.append(c); i += 1
    return "".join(out)


def loads_tolerant(text: str):
    """Parse JSON the way SMAPI/Newtonsoft does: comments and trailing commas allowed."""
    text = text.lstrip("\ufeff")
    text = _strip_json_comments(text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)


def load_json(path) -> object:
    return loads_tolerant(Path(path).read_text(encoding="utf-8"))


def dump_json(obj, path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- config & specs
def find_config(start: Path | None = None) -> Path | None:
    p = (start or Path.cwd()).resolve()
    for d in [p, *p.parents]:
        c = d / CONFIG_NAME
        if c.exists():
            return c
    c = SKILL_DIR / CONFIG_NAME
    return c if c.exists() else None


def load_config(path: str | None = None) -> dict:
    example = load_json(SKILL_DIR / "config.example.json")
    cfg_path = Path(path) if path else find_config()
    cfg = load_json(cfg_path) if cfg_path else {}
    merged = dict(example)
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    merged["_path"] = str(cfg_path) if cfg_path else None
    _apply_project_style(merged)
    return merged


def mods_path(cfg: dict) -> Path:
    if cfg.get("mods_path"):
        return Path(cfg["mods_path"])
    return Path(cfg.get("game_path") or DEFAULT_GAME_PATH) / "Mods"


def cp_format(cfg: dict) -> str:
    if cfg.get("content_patcher_format"):
        return cfg["content_patcher_format"]
    man = mods_path(cfg) / "ContentPatcher" / "manifest.json"
    try:
        v = load_json(man)["Version"]
        m = re.match(r"(\d+)\.(\d+)", v)
        if m:
            return f"{m.group(1)}.{m.group(2)}.0"
    except Exception:
        pass
    return DEFAULT_CP_FORMAT


def load_specs() -> dict:
    return {k: v for k, v in load_json(SPECS_PATH).items() if not k.startswith("_")}


def get_spec(key: str, frame: str | None = None, cols: int | None = None, rows: int | None = None) -> dict:
    specs = load_specs()
    if key not in specs:
        raise SystemExit(f"Unknown spec '{key}'. Known: {', '.join(specs)}")
    s = dict(specs[key])
    s["key"] = key
    if frame:
        s["frame_w"], s["frame_h"] = parse_size(frame)
    if cols:
        s["cols"] = cols
    if rows:
        s["rows"] = rows
    n = s["cols"] * s["rows"]
    labels = list(s.get("frame_labels") or [])
    labels = labels[:n] + [f"frame_{i}" for i in range(len(labels), n)]
    s["frame_labels"] = labels
    s["sheet_w"] = s["frame_w"] * s["cols"]
    s["sheet_h"] = s["frame_h"] * s["rows"]
    return s


def parse_size(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*[xX*]\s*(\d+)\s*", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    if text.strip().isdigit():
        v = int(text); return v, v
    raise SystemExit(f"Bad size '{text}', expected WxH")


def slug(text: str) -> str:
    words = re.split(r"[^A-Za-z0-9]+", text)
    return "".join(w[:1].upper() + w[1:] for w in words if w) or "Mod"


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "asset"


# ---------------------------------------------------------------- project file (sdv-project.json)
PROJECT_NAME = "sdv-project.json"
PROJECT_VERSION = 1


def find_project(start: Path | None = None) -> Path | None:
    p = (start or Path.cwd()).resolve()
    for d in [p, *p.parents]:
        c = d / PROJECT_NAME
        if c.exists():
            return c
    return None


def new_project() -> dict:
    return {"version": PROJECT_VERSION, "id_prefix": None, "mods": [], "ids": {}, "art_style": {},
            "characters": {}, "assets": [], "test": {}}


def load_project(path: str | Path | None = None) -> dict | None:
    p = Path(path) if path else find_project()
    if not p or not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    base = new_project()
    base.update(data)
    base["_path"] = str(p)
    return base


def save_project(proj: dict, path: str | Path) -> None:
    out = {k: v for k, v in proj.items() if not k.startswith("_")}
    dump_json(out, path)


STYLE_KEYS = ("checkpoint", "loras", "quality_prefix", "negative", "style_suffix", "sampler", "scheduler", "steps", "cfg",
              "clip_skip", "img2img_denoise", "asset_type_loras")


def _apply_project_style(cfg: dict) -> None:
    """A locked art_style in sdv-project.json overrides the machine config's comfyui defaults for this project."""
    pp = find_project()
    if not pp:
        return
    try:
        style = json.loads(pp.read_text(encoding="utf-8-sig")).get("art_style") or {}
    except Exception:
        return
    cc = cfg.setdefault("comfyui", {})
    for k in STYLE_KEYS:
        if style.get(k) not in (None, "", []):
            cc[k] = style[k]
    if style.get("palette_png"):
        cfg.setdefault("postprocess", {})["palette_png"] = style["palette_png"]
    cfg["_project"] = str(pp)
    cfg["_project_art_style"] = style


# ---------------------------------------------------------------- manifests (SMAPI reads keys case-insensitively)
_MANIFEST_KEYS = ("Name", "Author", "Version", "Description", "UniqueID", "EntryDll", "ContentPackFor", "MinimumApiVersion",
                  "MinimumGameVersion", "UpdateKeys", "Dependencies", "ExtraFields")
_CANON = {k.lower(): k for k in _MANIFEST_KEYS}
_DEP_KEYS = {"uniqueid": "UniqueID", "minimumversion": "MinimumVersion", "isrequired": "IsRequired"}


def normalize_manifest(man: dict) -> dict:
    """Return the manifest with the standard key spellings (e.g. 'UniqueId' -> 'UniqueID'), as SMAPI would read it."""
    out = {_CANON.get(str(k).lower(), k): v for k, v in man.items()}
    for key in ("Dependencies",):
        if isinstance(out.get(key), list):
            out[key] = [{_DEP_KEYS.get(str(k).lower(), k): v for k, v in d.items()} if isinstance(d, dict) else d for d in out[key]]
    if isinstance(out.get("ContentPackFor"), dict):
        out["ContentPackFor"] = {_DEP_KEYS.get(str(k).lower(), k): v for k, v in out["ContentPackFor"].items()}
    return out


def load_manifest(path) -> dict:
    return normalize_manifest(load_json(path))

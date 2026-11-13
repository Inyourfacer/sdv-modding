#!/usr/bin/env python3
"""Detect the Stardew modding environment and report what the skill can use.

  python doctor.py                 # human-readable table
  python doctor.py --json          # machine-readable
  python doctor.py --write-config  # fill nulls in sdv-modding.config.json (project root = cwd)

Read-only except --write-config. Never starts programs, never downloads anything.
Checks: game + Mods folder, SMAPI version, Content Patcher format, known frameworks (installed
version), ComfyUI (folder, server, checkpoints, LoRAs, ControlNet/IPAdapter-style models),
Python packages, dotnet, Tiled, Aseprite, StardewXnbHack, unpacked game content.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import string
import subprocess
import sys
import urllib.request
from pathlib import Path

from sdvlib import CONFIG_NAME, DEFAULT_GAME_PATH, dump_json, find_config, load_config, load_json, normalize_manifest

FRAMEWORKS = {
    "Pathoschild.ContentPatcher": "Content Patcher",
    "Platonymous.Portraiture": "Portraiture",
    "PeacefulEnd.FashionSense": "Fashion Sense",
    "PeacefulEnd.AlternativeTextures": "Alternative Textures",
    "BleakCodex.SpritesInDetail": "Sprites in Detail",
    "spacechase0.SpaceCore": "SpaceCore",
    "spacechase0.GenericModConfigMenu": "Generic Mod Config Menu",
    "Cherry.ExpandedPreconditionsUtility": "Expanded Preconditions Utility",
    "Esca.EMP": "Event Music/Mail Framework (EMP)",
    "DIGUS.MailFrameworkMod": "Mail Framework Mod",
}
COMFY_URL = "http://127.0.0.1:8188"
APPDATA_STARDROP = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Stardrop"
MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf")


# ---------------------------------------------------------------- helpers
def short_walk(root: Path, depth: int):
    """Yield directories under root up to depth levels, ignoring permission errors."""
    stack = [(root, 0)]
    while stack:
        d, n = stack.pop()
        try:
            kids = [k for k in d.iterdir() if k.is_dir()]
        except OSError:
            continue
        for k in kids:
            yield k
            if n + 1 < depth:
                stack.append((k, n + 1))


def read_version(manifest: Path):
    try:
        m = normalize_manifest(load_json(manifest))
        return m.get("UniqueID"), m.get("Version"), m.get("Name")
    except Exception:
        return None, None, None


def http_json(url: str, timeout: float = 1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (localhost only)
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def run(cmd: list[str], timeout: float = 8):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or p.stderr).strip()
    except Exception:
        return None


def list_models(dirs: list[Path]):
    out = []
    for d in dirs:
        if d.is_dir():
            for f in sorted(d.rglob("*")):
                if f.is_file() and f.suffix.lower() in MODEL_EXTS:
                    out.append(f.relative_to(d).as_posix())
    return out


# ---------------------------------------------------------------- detectors
def steam_library_paths() -> list[Path]:
    roots = []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            roots.append(Path(base) / "Steam")
    try:
        import winreg  # type: ignore
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    libs = []
    for r in roots:
        libs.append(r)
        vdf = r / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
    seen, out = set(), []
    for p in libs:
        if str(p).lower() not in seen:
            seen.add(str(p).lower()); out.append(p)
    return out


def find_game(cfg: dict):
    cands = []
    if cfg.get("game_path"):
        cands.append(Path(cfg["game_path"]))
    cands.append(Path(DEFAULT_GAME_PATH))
    cands += [lib / "steamapps" / "common" / "Stardew Valley" for lib in steam_library_paths()]
    for c in cands:
        if (c / "Stardew Valley.dll").exists() or (c / "Stardew Valley.exe").exists():
            return c
    return None


def detect_game(cfg: dict) -> dict:
    game = find_game(cfg)
    r = {"game_path": str(game) if game else None, "mods_path": None, "smapi_installed": False,
         "smapi_version": None, "frameworks": {}, "content_patcher_format": None, "installed_mods": {}}
    if not game:
        return r
    r["smapi_installed"] = (game / "StardewModdingAPI.exe").exists()
    mods = Path(cfg["mods_path"]) if cfg.get("mods_path") else game / "Mods"
    r["mods_path"] = str(mods) if mods.exists() else None
    log = Path(os.environ.get("APPDATA", "")) / "StardewValley" / "ErrorLogs" / "SMAPI-latest.txt"
    if log.exists():
        with log.open(encoding="utf-8", errors="ignore") as f:
            for _ in range(12):
                m = re.search(r"SMAPI\s+(\d+\.\d+\.\d+\S*)\s+with Stardew Valley\s+(\S+)", f.readline())
                if m:
                    r["smapi_version"], r["game_version"] = m.group(1), m.group(2)
                    break
    if mods.exists():
        for mf in list(mods.glob("*/manifest.json")) + list(mods.glob("*/*/manifest.json")):
            uid, ver, name = read_version(mf)
            if uid:
                r["installed_mods"][uid] = {"version": ver, "name": name, "folder": mf.parent.name}
        for uid, label in FRAMEWORKS.items():
            hit = next((v for k, v in r["installed_mods"].items() if k.lower() == uid.lower()), None)
            r["frameworks"][uid] = {"label": label, "version": hit["version"] if hit else None}
        cp = r["frameworks"].get("Pathoschild.ContentPatcher", {}).get("version")
        if cp:
            m = re.match(r"(\d+)\.(\d+)", cp)
            if m:
                r["content_patcher_format"] = f"{m.group(1)}.{m.group(2)}.0"
    stardrop = APPDATA_STARDROP.exists()
    r["stardrop"] = stardrop
    if log.exists():
        with log.open(encoding="utf-8", errors="ignore") as f:
            head = "".join(f.readline() for _ in range(12))
        m = re.search(r"Mods go here: (.+)", head)
        if m:
            r["last_mods_path"] = m.group(1).strip()
        if "custom --mods-path" in head:
            r["launched_with_custom_mods_path"] = True
    unpacked = None
    for c in (cfg.get("unpacked_content"), Path.home() / ".sdv-skill" / "Content (unpacked)", game / "Content (unpacked)", game.parent / "Content (unpacked)"):
        if c and Path(c).is_dir():
            unpacked = str(c); break
    r["unpacked_content"] = unpacked
    return r


def comfy_roots(cfg: dict) -> list[Path]:
    found, seen = [], set()

    def add(p: Path):
        if p.is_dir() and (p / "main.py").exists() and str(p).lower() not in seen:
            seen.add(str(p).lower()); found.append(p)

    for key in ("comfyui_root",):
        if cfg.get(key):
            add(Path(cfg[key]))
    ci = (cfg.get("comfyui") or {}).get("input_dir")
    if ci:
        add(Path(ci).parent)
    drives = [Path(f"{d}:/") for d in string.ascii_uppercase if Path(f"{d}:/").exists()] if os.name == "nt" else [Path("/")]
    roots = list(drives) + [Path.home(), Path.home() / "Documents", Path.home() / "Desktop"]
    for root in roots:
        add(root / "ComfyUI")
        for d in short_walk(root, 2):
            add(d / "Data" / "Packages" / "ComfyUI")
            add(d / "ComfyUI")
            add(d / "Packages" / "ComfyUI")
    return found


def parse_extra_model_paths(root: Path):
    """Return {'checkpoints': [Path], 'loras': [Path], ...} from extra_model_paths.yaml (minimal parser)."""
    y = root / "extra_model_paths.yaml"
    res: dict[str, list[Path]] = {}
    if not y.exists():
        return res
    key = None
    for line in y.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^  (\w+):\s*(\|-?)?\s*(.*)$", line)  # exactly 2 spaces: a key, not a path line
        if m:
            key = m.group(1)
            if m.group(3):
                res.setdefault(key, []).append(Path(m.group(3).strip()))
            continue
        if key and line.startswith("    ") and line.strip():
            res.setdefault(key, []).append(Path(line.strip()))
    return res


def detect_comfy(cfg: dict) -> dict:
    r = {"root": None, "input_dir": None, "output_dir": None, "server_running": False, "server_url": COMFY_URL,
         "checkpoints": [], "diffusion_models": [], "loras": [], "controlnet_models": [], "other_roots_found": [], "nodes": {}}
    roots = comfy_roots(cfg)
    if roots:
        root = roots[0]
        r["root"] = str(root)
        r["other_roots_found"] = [str(p) for p in roots[1:]]
        r["input_dir"], r["output_dir"] = str(root / "input"), str(root / "output")
        extra = parse_extra_model_paths(root)
        ck = extra.get("checkpoints", []) + [root / "models" / "checkpoints"]
        lo = extra.get("loras", []) + [root / "models" / "loras"]
        cn = extra.get("controlnet", []) + [root / "models" / "controlnet"]
        dm = extra.get("diffusion_models", []) + extra.get("unet", []) + [root / "models" / "diffusion_models"]
        r["checkpoints"], r["loras"], r["controlnet_models"] = list_models(ck), list_models(lo), list_models(cn)
        r["diffusion_models"] = list_models(dm)
    stats = http_json(f"{COMFY_URL}/system_stats")
    if stats is not None:
        r["server_running"] = True
        r["comfy_version"] = (stats.get("system") or {}).get("comfyui_version")
        for node in ("CheckpointLoaderSimple", "LoraLoader", "ControlNetLoader", "IPAdapterModelLoader",
                     "IPAdapterAdvanced", "ImageStitch", "ImageRemoveBackground", "Image Remove Background (rembg)"):
            info = http_json(f"{COMFY_URL}/object_info/{urllib.request.quote(node)}")
            r["nodes"][node] = bool(info and node in info)
        ck = http_json(f"{COMFY_URL}/object_info/CheckpointLoaderSimple")
        try:  # authoritative lists from the running server
            r["checkpoints"] = ck["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
            lo = http_json(f"{COMFY_URL}/object_info/LoraLoader")
            r["loras"] = lo["LoraLoader"]["input"]["required"]["lora_name"][0]
        except Exception:
            pass
    return r


def which_any(names: list[str], extra_paths: list[str] = ()):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    for p in extra_paths:
        if p and Path(p).exists():
            return str(p)
    return None


def detect_tools(cfg: dict) -> dict:
    pf = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    pf = [p for p in pf if p]
    steam = [str(Path(p) / "Steam" / "steamapps" / "common" / "Aseprite" / "Aseprite.exe") for p in pf]
    tiled = which_any(["tiled"], [str(Path(p) / "Tiled" / "tiled.exe") for p in pf])
    ase = which_any(["aseprite"], [str(Path(p) / "Aseprite" / "Aseprite.exe") for p in pf] + steam)
    dotnet = shutil.which("dotnet")
    xnb = which_any(["StardewXnbHack"], [cfg.get("stardewxnbhack")])
    pk = {}
    for mod in ("PIL", "numpy"):
        try:
            __import__(mod); pk[mod] = True
        except ImportError:
            pk[mod] = False
    return {
        "python": sys.version.split()[0], "python_packages": pk,
        "dotnet": run([dotnet, "--version"]) if dotnet else None,
        "tiled": tiled, "aseprite": ase, "stardewxnbhack": xnb,
        "ilspycmd": shutil.which("ilspycmd"),
    }


# ---------------------------------------------------------------- report
def build_report(cfg: dict) -> dict:
    return {"game": detect_game(cfg), "comfyui": detect_comfy(cfg), "tools": detect_tools(cfg),
            "config_file": cfg.get("_path")}


def advice(rep: dict) -> list[str]:
    a = []
    g, c, t = rep["game"], rep["comfyui"], rep["tools"]
    if not g["game_path"]:
        a.append("Stardew Valley not found: set game_path in sdv-modding.config.json.")
    elif not g["smapi_installed"]:
        a.append("SMAPI is not installed in the game folder (smapi.io).")
    if g.get("stardrop") and g.get("launched_with_custom_mods_path"):
        a.append(f"The last SMAPI run used a custom mods path ({g.get('last_mods_path')}), probably a Stardrop profile. "
                 "Copying into <game>/Mods does not change that profile; game.py test builds an isolated mods folder, so it does not depend on either.")
    if g["game_path"] and not g["frameworks"].get("Pathoschild.ContentPatcher", {}).get("version"):
        a.append("Content Patcher is not installed in Mods.")
    if not g.get("unpacked_content"):
        a.append("Game content is not unpacked: run StardewXnbHack once (ask the owner) so vanilla sheet sizes and data can be looked up.")
    if not c["root"]:
        a.append("ComfyUI folder not found: set comfyui_root in sdv-modding.config.json.")
    elif not c["server_running"]:
        a.append("ComfyUI is not running (ask the owner before starting it; default URL " + COMFY_URL + ").")
    if c["root"] and not c["checkpoints"] and not c["diffusion_models"]:
        a.append("No checkpoints or diffusion models found for ComfyUI.")
    elif c["root"] and not c["checkpoints"]:
        a.append("No SDXL-style checkpoints, only diffusion-model files; the Illustrious/Pony recipes need a checkpoint.")
    if not all(t["python_packages"].values()):
        a.append("Install missing Python packages: pip install pillow numpy")
    if not t["dotnet"]:
        a.append("No .NET SDK found (needed only for C# mods).")
    if not t["tiled"]:
        a.append("Tiled not installed (optional, for maps).")
    if not t["aseprite"]:
        a.append("Aseprite not installed (optional, for pixel cleanup).")
    return a


def print_report(rep: dict):
    g, c, t = rep["game"], rep["comfyui"], rep["tools"]

    def row(label, value, ok=None):
        mark = "  " if ok is None else ("ok" if ok else "!!")
        print(f" {mark}  {label:<26} {value if value not in (None, '', []) else '-'}")

    print("Game")
    row("game folder", g["game_path"], bool(g["game_path"]))
    row("Mods folder", g["mods_path"], bool(g["mods_path"]))
    row("SMAPI installed", g["smapi_installed"], g["smapi_installed"])
    row("SMAPI / game version", f"{g.get('smapi_version')} / {g.get('game_version')}" if g.get("smapi_version") else None)
    row("Content Patcher Format", g["content_patcher_format"], bool(g["content_patcher_format"]))
    row("unpacked content", g.get("unpacked_content"), bool(g.get("unpacked_content")))
    print("Frameworks")
    for uid, f in g["frameworks"].items():
        row(f["label"], f["version"] or "not installed")
    print("ComfyUI")
    row("folder", c["root"], bool(c["root"]))
    row("server running", c["server_running"], c["server_running"])
    row("checkpoints", f"{len(c['checkpoints'])} found" + (": " + ", ".join(c["checkpoints"][:5]) if c["checkpoints"] else ""))
    row("diffusion models (UNet)", f"{len(c['diffusion_models'])} found" + (": " + ", ".join(c["diffusion_models"][:5]) if c["diffusion_models"] else ""))
    row("LoRAs", f"{len(c['loras'])} found")
    row("ControlNet models", f"{len(c['controlnet_models'])} found")
    for n, ok in c["nodes"].items():
        row(f"node {n}", ok)
    print("Tools")
    row("python", t["python"])
    row("pillow / numpy", ", ".join(f"{k}={'yes' if v else 'NO'}" for k, v in t["python_packages"].items()),
        all(t["python_packages"].values()))
    row(".NET SDK", t["dotnet"], bool(t["dotnet"]))
    row("Tiled (optional)", t["tiled"])
    row("Aseprite (optional)", t["aseprite"])
    row("StardewXnbHack", t["stardewxnbhack"])
    row("ilspycmd (optional)", t["ilspycmd"])
    print("\nNext steps")
    for a in advice(rep) or ["nothing blocking."]:
        print(" -", a)


def write_config(rep: dict, cfg: dict):
    """Fill only values that are null/missing or still the example placeholder. Never overwrites a user's value."""
    path = Path(cfg["_path"]) if cfg.get("_path") and Path(cfg["_path"]).name == CONFIG_NAME else Path.cwd() / CONFIG_NAME
    cur = load_json(path) if path.exists() else {}
    changes = []

    def setv(d: dict, key: str, val, placeholder=(None, "", "YourName")):
        if val in (None, "", []):
            return
        if d.get(key) in placeholder:
            d[key] = val; changes.append(key)

    g, c = rep["game"], rep["comfyui"]
    setv(cur, "game_path", g["game_path"])
    setv(cur, "mods_path", g["mods_path"])
    setv(cur, "content_patcher_format", g["content_patcher_format"])
    setv(cur, "unpacked_content", g.get("unpacked_content"))
    setv(cur, "comfyui_root", c["root"])
    cur.setdefault("comfyui", {})
    setv(cur["comfyui"], "input_dir", c["input_dir"])
    setv(cur["comfyui"], "output_dir", c["output_dir"])
    if c["checkpoints"] and not cur["comfyui"].get("checkpoint"):
        cur["comfyui"]["checkpoint"] = None  # never guess a style; the owner picks (style.py)
    setv(cur, "tiled", rep["tools"]["tiled"])
    setv(cur, "aseprite", rep["tools"]["aseprite"])
    setv(cur, "stardewxnbhack", rep["tools"]["stardewxnbhack"])
    dump_json(cur, path)
    return path, changes


def main():
    ap = argparse.ArgumentParser(description="Detect the Stardew modding environment.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-config", action="store_true", help="fill empty values in sdv-modding.config.json")
    ap.add_argument("--config")
    a = ap.parse_args()
    cfg = load_config(a.config)
    rep = build_report(cfg)
    rep["advice"] = advice(rep)
    if a.write_config:
        path, changes = write_config(rep, cfg)
        rep["config_written"] = {"path": str(path), "filled": changes}
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        print_report(rep)
        if a.write_config:
            print(f"\nconfig: {rep['config_written']['path']} (filled: {', '.join(rep['config_written']['filled']) or 'nothing new'})")


if __name__ == "__main__":
    main()

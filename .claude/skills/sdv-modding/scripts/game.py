#!/usr/bin/env python3
"""Run Stardew Valley for testing, and read its logs.

  python game.py log     [--file SMAPI-latest.txt] [--mods "My Mod,Other.Id"] [--json]     # parse any SMAPI log (read-only)
  python game.py status                                                                     # is a game started by us running?
  python game.py build   <csproj or folder>                                                  # dotnet build -c Release
  python game.py deploy  <mod folder> ...                                                    # copy content packs into the configured Mods folder
  python game.py test    --confirmed-by-owner --mods "[CP] My Mod" ... [--check name | --steps steps.json] [--save SdvTest_123]
  python game.py launch  --confirmed-by-owner [--mods-path DIR]                              # start SMAPI (we remember its PID)
  python game.py stop                                                                        # close only the game we started

`log`, `status`, `build` and `deploy` are safe to run any time. `launch` and `test` START THE GAME: Claude asks the owner first, in this
conversation, and passes --confirmed-by-owner only after a yes (the scripts refuse without it, every time).

`test` = validate -> build C# mods -> copy the project's mods and their required dependencies into an ISOLATED temporary mods folder
-> add the test harness -> launch SMAPI with --mods-path <that folder> -> the harness loads the dedicated TEST save (name must start
with a prefix containing "test"; no other save is ever loaded) and runs the steps -> this script answers its requests for window
screenshots and SMAPI console commands -> game closed, temp folder removed -> verdict from the harness result and the SMAPI log.
Reports go to tests/<timestamp>/ (report.json, SMAPI.txt, shots/). The player's normal Mods folder (or Stardrop profile) is not touched.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from sdvlib import PROJECT_NAME, find_project, load_config, load_json, load_manifest, load_project, mods_path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
HARNESS_DIR = SKILL / "harness" / "SdvTestHarness"
PID_FILE_NAME = ".sdv-game.json"
CONSOLE_STDIN = False            # set by --console-stdin (experimental: off because a live run showed SMAPI ignores piped input)
GAME_EXES = ("StardewModdingAPI.exe", "Stardew Valley.exe")
APPDATA = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
LOG_PATH = APPDATA / "StardewValley" / "ErrorLogs" / "SMAPI-latest.txt"
SAVES_PATH = APPDATA / "StardewValley" / "Saves"

LINE = re.compile(r"^\[(\d\d:\d\d:\d\d) (TRACE|DEBUG|INFO|WARN|ERROR|ALERT) +([^\]]+)\] ?(.*)$")


# ---------------------------------------------------------------- safety rule (mirrors harness/SavePolicy.cs; tested against it)
def is_test_save(folder: str | None, prefix: str | None) -> bool:
    if not folder or not folder.strip() or not prefix or not prefix.strip():
        return False
    prefix = prefix.strip()
    if len(prefix) < 4 or "test" not in prefix.lower():
        return False
    if any(c in folder for c in "/\\:") or ".." in folder:
        return False
    return folder.lower().startswith(prefix.lower())


# ---------------------------------------------------------------- SMAPI log parsing
def parse_log(text: str, mods: list[str] | None = None) -> dict:
    """Structure a SMAPI log: header, errors/warnings (grouped by source), skipped mods and the usual problem categories."""
    entries: list[dict] = []
    for raw in text.splitlines():
        m = LINE.match(raw)
        if m:
            entries.append({"time": m.group(1), "level": m.group(2), "source": m.group(3).strip(), "message": m.group(4)})
        elif entries:
            entries[-1]["message"] += "\n" + raw          # stack traces and wrapped lines belong to the previous entry
    header = {}
    for e in entries[:6]:
        h = re.match(r"SMAPI (\S+) with Stardew Valley (\S+)", e["message"])
        if h:
            header = {"smapi": h.group(1), "game": h.group(2)}
            break
    mine = [x.lower() for x in (mods or [])]

    def is_mine(e):
        return any(x in e["source"].lower() or x in e["message"].lower() for x in mine)

    errors = [e for e in entries if e["level"] == "ERROR"]
    warns = [e for e in entries if e["level"] == "WARN"]
    skipped = []
    capture = False
    for e in entries:
        if e["source"] == "SMAPI" and e["message"].strip().startswith("Skipped mods"):
            capture = True
            continue
        if capture:
            line = e["message"].strip()
            if line.startswith("- "):
                skipped.append(line[2:])
            elif line and not set(line) <= {"-"} and not line.startswith("These mods"):
                capture = False if not skipped else capture
    cats = {"missing_dependency": [], "patch_failure": [], "asset_load": [], "exception": [], "manifest": []}
    for e in errors + warns + [x for x in entries if x["level"] in ("ALERT",)]:
        msg = e["message"]
        low = msg.lower()
        item = {"source": e["source"], "level": e["level"], "message": msg.splitlines()[0][:300]}
        if re.search(r"requires .+ (mod|but|which)|missing dependenc|dependency .* (not|missing)|which isn't installed", low):
            cats["missing_dependency"].append(item)
        patchy = bool(re.search(r"patch error|patch .* (skipped|failed)|disabled|isn't a valid|invalid .*action|unknown target", low)) and e["source"] != "SMAPI"
        from_cp = "content patcher" in e["source"].lower() and e["level"] in ("ERROR", "WARN")
        if patchy or from_cp:
            cats["patch_failure"].append(item)
        if re.search(r"failed loading asset|could not load asset|can't load|asset .* (doesn't exist|not found)|failed to load|file not found|filenotfound", low):
            cats["asset_load"].append(item)
        if re.search(r"[a-z]exception\b|exception:|unhandled exception", low) or "\n   at " in msg:
            cats["exception"].append(item)
        if re.search(r"manifest|invalid json|json.*(error|invalid)|unexpected character", low):
            cats["manifest"].append(item)
    by_source: dict[str, dict] = {}
    for e in errors + warns:
        s = by_source.setdefault(e["source"], {"errors": 0, "warnings": 0})
        s["errors" if e["level"] == "ERROR" else "warnings"] += 1
    loaded = sum(1 for e in entries if e["source"] == "SMAPI" and re.match(r"\s+.+ \(from .+, ID: ", e["message"]))
    mine_errors = [e for e in errors if is_mine(e)]
    mine_skipped = [s for s in skipped if any(x in s.lower() for x in mine)]
    return {
        "header": header, "mods_loaded": loaded, "entries": len(entries), "errors": len(errors), "warnings": len(warns),
        "by_source": dict(sorted(by_source.items(), key=lambda kv: -(kv[1]["errors"] * 100 + kv[1]["warnings"]))),
        "skipped_mods": skipped, "categories": {k: v for k, v in cats.items() if v},
        "mine": {"errors": [{"source": e["source"], "message": e["message"][:600]} for e in mine_errors], "skipped": mine_skipped},
        "ok_for_mine": not mine_errors and not mine_skipped,
        "harness": [e["message"] for e in entries if "[harness]" in e["message"]][-12:],
    }


def print_log_report(rep: dict, mods: list[str]):
    h = rep["header"]
    print(f"SMAPI {h.get('smapi', '?')} / game {h.get('game', '?')}: {rep['mods_loaded']} mods loaded, {rep['errors']} error(s), {rep['warnings']} warning(s)")
    if mods:
        print(f"your mods ({', '.join(mods)}): " + ("clean" if rep["ok_for_mine"] else "PROBLEMS"))
        for e in rep["mine"]["errors"][:10]:
            print(f"  [ERROR {e['source']}] {e['message'].splitlines()[0]}")
        for s in rep["mine"]["skipped"]:
            print(f"  [SKIPPED] {s}")
    if rep["skipped_mods"] and not mods:
        print("skipped mods:")
        for s in rep["skipped_mods"][:15]:
            print("  -", s)
    for cat, items in rep["categories"].items():
        print(f"{cat} ({len(items)}):")
        for i in items[:5]:
            print(f"  [{i['level']} {i['source']}] {i['message']}")
    if rep["by_source"]:
        print("most affected sources: " + ", ".join(f"{k} ({v['errors']}E/{v['warnings']}W)" for k, v in list(rep["by_source"].items())[:6]))


# ---------------------------------------------------------------- process helpers (Windows)
def tasklist() -> str:
    try:
        return subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    except OSError:
        return ""


def game_running() -> list[str]:
    out = tasklist().lower()
    return [e for e in GAME_EXES if f'"{e.lower()}"' in out]


def pid_alive(pid: int, image: str | None = None) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout.lower()
    return f'"{pid}"' in out and (image is None or image.lower() in out)


def pid_file(root: Path) -> Path:
    return root / PID_FILE_NAME


def project_root() -> Path:
    p = find_project()
    return p.parent if p else Path.cwd()


def require_owner(a):
    if not getattr(a, "confirmed_by_owner", False):
        raise SystemExit("Refusing to start the game: pass --confirmed-by-owner only after the owner said yes in this conversation "
                         "(ask every session; a yes for ComfyUI or an earlier run does not carry over).")


def game_dir(cfg: dict) -> Path:
    g = cfg.get("game_path")
    if not g or not (Path(g) / "StardewModdingAPI.exe").exists():
        raise SystemExit("Game folder with StardewModdingAPI.exe not found: run doctor.py --write-config.")
    return Path(g)


def smapi_command(cfg: dict, mods_dir: Path | None) -> tuple[list[str], Path]:
    override = os.environ.get("SDV_GAME_CMD")            # test hook: a fake game process
    if override:
        return json.loads(override) + (["--mods-path", str(mods_dir)] if mods_dir else []), Path.cwd()
    g = game_dir(cfg)
    cmd = [str(g / "StardewModdingAPI.exe")]
    if mods_dir:
        cmd += ["--mods-path", str(mods_dir)]
    return cmd, g


def start_game(cfg: dict, root: Path, mods_dir: Path | None) -> subprocess.Popen:
    running = game_running()
    if running and not os.environ.get("SDV_GAME_CMD"):
        raise SystemExit(f"A Stardew Valley process is already running ({', '.join(running)}). Close it first; this script never touches a game it did not start.")
    cmd, cwd = smapi_command(cfg, mods_dir)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)  # noqa: S603
    pid_file(root).write_text(json.dumps({"pid": proc.pid, "started": datetime.now().isoformat(timespec="seconds"), "cmd": cmd}), encoding="utf-8")
    return proc


def stop_game(root: Path, proc: subprocess.Popen | None = None, wait: float = 20.0) -> str:
    """Close the game we started: polite close first, forced only after `wait` seconds, only for our recorded PID."""
    pf = pid_file(root)
    info = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else None
    pid = proc.pid if proc else (info or {}).get("pid")
    if not pid:
        return "no game of ours is recorded"
    if proc is not None and proc.poll() is not None:
        pf.unlink(missing_ok=True)
        return "already closed"
    if proc is None and not pid_alive(pid):
        pf.unlink(missing_ok=True)
        return "already closed"
    subprocess.run(["taskkill", "/PID", str(pid), "/T"], capture_output=True)     # asks the window to close
    t0 = time.time()
    while time.time() - t0 < wait:
        if (proc.poll() is not None) if proc else not pid_alive(pid):
            pf.unlink(missing_ok=True)
            return "closed"
        time.sleep(0.5)
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    pf.unlink(missing_ok=True)
    return "closed (forced after the polite close timed out)"


# ---------------------------------------------------------------- isolated mods folder
def read_manifest(folder: Path) -> dict | None:
    mf = folder / "manifest.json"
    try:
        return load_manifest(mf) if mf.exists() else None
    except Exception:
        return None


def find_mods_by_id(search_dirs: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for d in search_dirs:
        if not d.exists():
            continue
        for mf in list(d.glob("*/manifest.json")) + list(d.glob("*/*/manifest.json")):
            m = read_manifest(mf.parent)
            if m and m.get("UniqueID"):
                found.setdefault(m["UniqueID"].lower(), mf.parent)
    return found


def build_isolated(project_mods: list[Path], search_dirs: list[Path], dest: Path) -> dict:
    """Copy the project's mods plus every REQUIRED dependency (recursively) into dest. Returns what was copied/missing."""
    index = find_mods_by_id(search_dirs)
    want: dict[str, Path] = {}
    missing: list[str] = []
    queue = [(m, "project") for m in project_mods]
    queue += [(index[k], "bundled") for k in ("smapi.consolecommands",) if k in index]      # `debug`/`help` commands
    while queue:
        folder, why = queue.pop(0)
        man = read_manifest(folder)
        if not man or not man.get("UniqueID"):
            continue
        uid = man["UniqueID"].lower()
        if uid in want:
            continue
        want[uid] = folder
        deps = list(man.get("Dependencies") or [])
        cp = man.get("ContentPackFor") or {}
        if cp.get("UniqueID"):
            deps.append({"UniqueID": cp["UniqueID"], "IsRequired": True})
        for d in deps:
            did = str(d.get("UniqueID", "")).lower()
            if not did or did in want or d.get("IsRequired") is False:
                continue
            if did in index:
                queue.append((index[did], "dependency"))
            elif did not in [m.lower() for m in missing]:
                missing.append(d.get("UniqueID"))
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for uid, folder in want.items():
        target = dest / folder.name
        if target.exists():
            target = dest / f"{folder.name}__{uid}"
        shutil.copytree(folder, target, ignore=shutil.ignore_patterns("obj", ".git", "backups", "runs", "art-source", "*.bak"))
        copied.append(folder.name)
    return {"copied": copied, "missing_dependencies": missing}


# ---------------------------------------------------------------- harness
def harness_dll_dir() -> Path:
    return HARNESS_DIR / "bin" / "Release" / "net6.0"


def ensure_harness_built() -> Path:
    out = harness_dll_dir()
    if (out / "SdvTestHarness.dll").exists() and (out / "SdvTestHarness.dll").stat().st_mtime >= max((p.stat().st_mtime for p in HARNESS_DIR.glob("*.cs")), default=0):
        return out
    r = subprocess.run(["dotnet", "build", "-c", "Release", "-nologo", "-v", "q"], cwd=HARNESS_DIR, capture_output=True, text=True)
    if r.returncode != 0 or not (out / "SdvTestHarness.dll").exists():
        raise SystemExit("Building the test harness failed:\n" + (r.stdout + r.stderr)[-1500:])
    return out


def install_harness(mods_dir: Path) -> Path:
    dst = mods_dir / "SdvTestHarness"
    dst.mkdir(parents=True, exist_ok=True)
    out = ensure_harness_built()
    for f in ("SdvTestHarness.dll", "manifest.json"):
        shutil.copy2(out / f, dst / f)
    return dst


def check_to_steps(check: dict) -> list[dict]:
    """A project 'test.checks' entry -> harness steps. warp 'Town 52 70'; commands run as debug (game) or console (SMAPI)."""
    steps: list[dict] = list(check.get("steps") or [])
    if check.get("time") is not None:
        steps.append({"type": "time", "value": int(check["time"])})
    if check.get("warp"):
        loc, x, y = str(check["warp"]).rsplit(" ", 2)
        steps.append({"type": "warp", "location": loc, "x": int(x), "y": int(y)})
    for c in check.get("give") or []:
        steps.append({"type": "give", "item": c.split()[0], "count": int(c.split()[1]) if len(c.split()) > 1 else 1})
    for c in check.get("commands") or []:
        if c.startswith("debug "):
            steps.append({"type": "debug", "command": c[6:]})
        else:
            steps.append({"type": "console", "command": c})
    if check.get("dialogue"):
        steps.append({"type": "dialogue", "npc": check["dialogue"]})
        steps.append({"type": "wait", "ticks": 30})
    if check.get("screenshot"):
        steps.append({"type": "screenshot", "name": check.get("name", "shot")})
    if check.get("map_screenshot"):
        steps.append({"type": "map_screenshot", "name": check.get("name", "map")})
    return steps


# ---------------------------------------------------------------- window screenshots (Windows, ctypes + Pillow)
def _user32():
    import ctypes
    u = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            u.SetProcessDPIAware()
        except Exception:
            pass
    return u


def find_window(pid: int):
    """(hwnd, rect) of the largest visible top-level window owned by pid, or None."""
    import ctypes
    from ctypes import wintypes
    user32 = _user32()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left > 300 and r.bottom - r.top > 200:
                found.append((hwnd, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(cb, 0)
    return max(found, key=lambda f: (f[1][2] - f[1][0]) * (f[1][3] - f[1][1])) if found else None


def bring_to_front(hwnd) -> bool:
    user32 = _user32()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)                                   # SW_RESTORE
    user32.keybd_event(0x12, 0, 0, 0)                                # a tapped ALT lets SetForegroundWindow through
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, 2, 0)
    time.sleep(0.6)
    return user32.GetForegroundWindow() == hwnd


def take_window_screenshot(pid: int, out: Path) -> tuple[bool, str]:
    """Grab the game window. Privacy rule: the screen is only copied while the game window itself is the foreground window,
    checked before AND after the grab; otherwise nothing is kept (a screen grab would show whatever is on top of it)."""
    if os.environ.get("SDV_FAKE_SCREENSHOT"):                         # test hook
        from PIL import Image
        Image.new("RGB", (64, 48), (30, 90, 50)).save(out)
        return True, str(out)
    try:
        from PIL import ImageGrab
        win = find_window(pid)
        if not win:
            return False, "could not find the game window (minimised, or owned by another process); nothing was captured"
        hwnd, rect = win
        if not bring_to_front(hwnd):
            return False, "could not bring the game window to the front, so nothing was captured (a screen grab would show other windows)"
        user32 = _user32()
        rect = find_window(pid)[1]
        ImageGrab.grab(bbox=rect, all_screens=True).save(out)
        if user32.GetForegroundWindow() != hwnd:
            out.unlink(missing_ok=True)
            return False, "the game window lost focus during the capture; the picture was discarded"
        return True, str(out)
    except Exception as ex:   # noqa: BLE001
        out.unlink(missing_ok=True)
        return False, f"screenshot failed: {ex}"


# ---------------------------------------------------------------- the test run
def cmd_test(a, cfg):
    require_owner(a)
    root = project_root()
    proj = load_project() or {}
    t = proj.get("test") or {}
    prefix = a.prefix or t.get("save_prefix") or "SdvTest"
    save = a.save or t.get("save")
    if not save:
        saves = sorted(p.name for p in SAVES_PATH.glob("*") if is_test_save(p.name, prefix)) if SAVES_PATH.exists() else []
        if len(saves) == 1:
            save = saves[0]
    if not save or not is_test_save(save, prefix):
        raise SystemExit(f"No usable TEST save. Create one farm whose farmer name starts with '{prefix}' (e.g. 'SdvTest'), then pass --save <its folder name under {SAVES_PATH}>. "
                         "The harness refuses every save whose name does not start with a prefix containing 'test'.")
    if not os.environ.get("SDV_GAME_CMD") and not (SAVES_PATH / save).is_dir():
        raise SystemExit(f"Test save folder not found: {SAVES_PATH / save}")

    mod_dirs = [Path(m).resolve() for m in a.mods]
    for m in mod_dirs:
        if not (m / "manifest.json").exists():
            raise SystemExit(f"{m} has no manifest.json")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = root / "tests" / stamp
    (report_dir / "shots").mkdir(parents=True, exist_ok=True)
    report = {"started": stamp, "mods": [str(m) for m in mod_dirs], "save": save, "steps": [], "verdict": None}

    # 1. static validation
    if not a.skip_validate:
        for m in mod_dirs:
            r = subprocess.run([sys.executable, str(HERE / "validate_mod.py"), str(m)], capture_output=True, text=True)
            if r.returncode != 0:
                (report_dir / "report.json").write_text(json.dumps({**report, "verdict": "BLOCKED: validate_mod.py found errors", "validate": r.stdout}, indent=2), encoding="utf-8")
                print(r.stdout)
                raise SystemExit("validate_mod.py reports errors; fix them first (or --skip-validate). Nothing was started.")
    # 2. C# builds
    for m in mod_dirs:
        csprojs = list(m.glob("*.csproj"))
        if csprojs:
            r = subprocess.run(["dotnet", "build", "-c", "Release", "-nologo", "-v", "q", f"-p:EnableModDeploy=false", f"-p:EnableModZip=false"], cwd=m, capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit(f"dotnet build failed for {m.name}:\n" + (r.stdout + r.stderr)[-1500:])
            built = m / "bin" / "Release" / "net6.0"
            report.setdefault("built", []).append(m.name)
            # the isolated copy takes the built DLL from bin/Release/net6.0
            report.setdefault("csharp_output", {})[m.name] = str(built)
    # 3. steps
    steps: list[dict] = []
    if a.steps:
        steps = json.loads(Path(a.steps).read_text(encoding="utf-8")).get("steps", [])
    else:
        checks = t.get("checks") or []
        chosen = [c for c in checks if not a.check or c.get("name") in a.check]
        if a.check and not chosen:
            raise SystemExit(f"No check named {a.check} in {PROJECT_NAME} test.checks.")
        for c in chosen:
            steps += check_to_steps(c)
    if not steps:
        steps = [{"type": "wait", "ticks": 120}, {"type": "screenshot", "name": "world"}]
    report["steps_requested"] = steps

    # 4. isolated mods folder
    search = [mods_path(cfg)] + [Path(p) for p in (cfg.get("extra_mod_dirs") or [])] + [APPDATA / "Stardrop" / "Data" / "Selected Mods"]
    tmp = Path(tempfile.mkdtemp(prefix="sdvtest_mods_"))
    try:
        info = build_isolated(mod_dirs, search, tmp)
        for m in mod_dirs:                                                    # C# mods: overlay the freshly built DLL
            if (m / "bin" / "Release" / "net6.0").exists() and list(m.glob("*.csproj")):
                dst = tmp / m.name
                for f in (m / "bin" / "Release" / "net6.0").glob("*.dll"):
                    shutil.copy2(f, dst / f.name)
        if info["missing_dependencies"]:
            print("WARNING: required dependencies not found in any mods folder: " + ", ".join(info["missing_dependencies"]))
        harness = install_harness(tmp)
        (harness / "harness-commands.json").write_text(json.dumps({"save": save, "save_prefix": prefix, "timeout_seconds": a.timeout, "steps": steps}, indent=2), encoding="utf-8")
        report["isolated_mods"] = info
        report["isolated_dir"] = str(tmp)

        # 5. run
        print(f"launching SMAPI against an isolated mods folder with {len(info['copied'])} mod(s) + harness; test save {save}")
        proc = start_game(cfg, root, tmp)
        status = run_session(proc, harness, report_dir, a.timeout)
        report.update(status)
    finally:
        msg = stop_game(root, locals().get("proc"))
        report["stop"] = msg
        shutil.rmtree(tmp, ignore_errors=True)                                # our own temp copy only
    # 6. log
    log_copy = report_dir / "SMAPI.txt"
    if os.environ.get("SDV_GAME_LOG"):
        shutil.copy2(os.environ["SDV_GAME_LOG"], log_copy)
    elif LOG_PATH.exists():
        shutil.copy2(LOG_PATH, log_copy)
    names = [read_manifest(m).get("Name", m.name) for m in mod_dirs if read_manifest(m)] + [read_manifest(m).get("UniqueID", "") for m in mod_dirs if read_manifest(m)]
    rep = parse_log(log_copy.read_text(encoding="utf-8", errors="ignore"), [n for n in names if n]) if log_copy.exists() else None
    report["log"] = rep
    harness_ok = bool(report.get("harness_ok"))
    log_ok = bool(rep and rep["ok_for_mine"])
    report["verdict"] = "PASS" if harness_ok and log_ok else "FAIL"
    (report_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nverdict: {report['verdict']}  (harness steps ok: {harness_ok}; log clean for your mods: {log_ok})")
    for st in report.get("steps", []):
        st = {k.lower(): v for k, v in st.items()}
        print(f"  step {st.get('index')} {st.get('type')}: {'ok' if st.get('ok') else 'FAILED ' + str(st.get('error'))}" + (f" - {st.get('info')}" if st.get("info") else ""))
    if rep:
        print_log_report(rep, names)
    shots = sorted((report_dir / "shots").glob("*.png"))
    if shots:
        print("screenshots (open and LOOK at them before saying anything works in game): " + ", ".join(str(s) for s in shots))
    print(f"report: {report_dir / 'report.json'}")
    raise SystemExit(0 if report["verdict"] == "PASS" else 1)


def run_session(proc: subprocess.Popen, harness: Path, report_dir: Path, timeout: int) -> dict:
    """Watch the harness: answer screenshot/console requests until it reports finished, the game dies, or time runs out."""
    results_p, request_p, ack_p, exit_p = (harness / n for n in ("harness-results.json", "harness-request.json", "harness-ack.json", "harness-exit"))
    answered = 0
    t0 = time.time()
    last: dict = {}
    while time.time() - t0 < timeout + 60:
        if proc.poll() is not None:
            break
        if request_p.exists():
            try:
                req = json.loads(request_p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                req = None
            if req and req.get("seq") and req["seq"] > answered:
                answered = req["seq"]
                ok, msg = answer(proc, req, report_dir)
                tmp_ack = ack_p.with_suffix(".tmp")
                tmp_ack.write_text(json.dumps({"seq": req["seq"], "ok": ok, "message": msg}), encoding="utf-8")
                os.replace(tmp_ack, ack_p)
        if results_p.exists():
            try:
                last = json.loads(results_p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
            if last.get("finished"):
                break
        time.sleep(0.5)
    exit_p.write_text("done", encoding="utf-8")                                 # the harness closes the game on its next check
    for _ in range(40):
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    return {"harness_ok": bool(last.get("finished") and last.get("ok")), "steps": last.get("steps", []), "harness_errors": last.get("errors", []),
            "harness_state": last.get("state", "never started (game closed or no results)")}


def answer(proc, req: dict, report_dir: Path) -> tuple[bool, str]:
    if req.get("type") == "screenshot":
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", req.get("name") or f"shot{req['seq']}")
        return take_window_screenshot(proc.pid, report_dir / "shots" / f"{name}.png")
    if req.get("type") == "console":
        if not CONSOLE_STDIN:
            return False, ("SMAPI console commands cannot be sent from here: when SMAPI is started by game.py it does not run commands from a piped "
                           "stdin (verified in a live run: `patch summary` produced no output). Use a 'debug <cmd>' step for game debug commands, "
                           "read results with `game.py log`, or type the command in the SMAPI window yourself.")
        try:
            proc.stdin.write((req.get("command", "") + "\n").encode("utf-8"))
            proc.stdin.flush()
            time.sleep(2.0)
            return True, "sent to the SMAPI console (check SMAPI.txt for the output; if stdin is not attached the command is not run)"
        except (OSError, ValueError) as ex:
            return False, f"could not write to the SMAPI console: {ex}"
    return False, "unknown request type"


# ---------------------------------------------------------------- other commands
def cmd_build(a, cfg):
    target = Path(a.target)
    folder = target.parent if target.suffix == ".csproj" else target
    r = subprocess.run(["dotnet", "build", "-c", "Release", "-nologo", "-v", "q"], cwd=folder, capture_output=True, text=True)
    print((r.stdout + r.stderr)[-3000:])
    raise SystemExit(r.returncode)


def cmd_deploy(a, cfg):
    dest = mods_path(cfg)
    note = ""
    if (APPDATA / "Stardrop").exists():
        note = f"\nnote: Stardrop is installed. If you play through a Stardrop profile, this copy into {dest} is not what that profile loads."
    for m in a.mods:
        r = subprocess.run([sys.executable, str(HERE / "deploy.py"), m, "--mods", str(dest)], capture_output=True, text=True)
        print((r.stdout + r.stderr).strip())
    if note:
        print(note.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("log"); lg.add_argument("--file"); lg.add_argument("--mods", default=""); lg.add_argument("--json", action="store_true")
    sub.add_parser("status")
    b = sub.add_parser("build"); b.add_argument("target")
    d = sub.add_parser("deploy"); d.add_argument("mods", nargs="+")
    for name in ("launch", "test"):
        s = sub.add_parser(name)
        s.add_argument("--confirmed-by-owner", action="store_true", help="only after the owner said yes in this conversation")
        if name == "launch":
            s.add_argument("--mods-path")
        else:
            s.add_argument("--mods", nargs="+", required=True, help="mod folders under test (their required dependencies are copied too)")
            s.add_argument("--check", nargs="*"); s.add_argument("--steps"); s.add_argument("--save"); s.add_argument("--prefix")
            s.add_argument("--timeout", type=int, default=300); s.add_argument("--skip-validate", action="store_true")
            s.add_argument("--console-stdin", action="store_true", help="experimental: type console steps into SMAPI stdin (did not work in a live run)")
    sub.add_parser("stop")
    a = ap.parse_args()
    cfg = load_config(a.config)
    root = project_root()
    global CONSOLE_STDIN
    CONSOLE_STDIN = bool(getattr(a, "console_stdin", False))

    if a.cmd == "log":
        f = Path(a.file) if a.file else LOG_PATH
        if not f.exists():
            raise SystemExit(f"No log at {f}")
        mods = [m.strip() for m in a.mods.split(",") if m.strip()]
        rep = parse_log(f.read_text(encoding="utf-8", errors="ignore"), mods)
        print(json.dumps(rep, indent=2)) if a.json else print_log_report(rep, mods)
        raise SystemExit(0 if rep["ok_for_mine"] else 1)
    if a.cmd == "status":
        pf = pid_file(root)
        info = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else None
        print("game started by us: " + (f"pid {info['pid']} (running: {pid_alive(info['pid'])})" if info else "none"))
        print("any Stardew process running: " + (", ".join(game_running()) or "no"))
        return
    if a.cmd == "build":
        return cmd_build(a, cfg)
    if a.cmd == "deploy":
        return cmd_deploy(a, cfg)
    if a.cmd == "launch":
        require_owner(a)
        proc = start_game(cfg, root, Path(a.mods_path) if a.mods_path else None)
        print(f"started SMAPI (pid {proc.pid}). Close it with: python game.py stop")
        return
    if a.cmd == "stop":
        print(stop_game(root))
        return
    if a.cmd == "test":
        return cmd_test(a, cfg)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Talk to a running ComfyUI over its HTTP API (standard library only).

  python comfy.py status
  python comfy.py models [--json]
  python comfy.py check  comfy/Mira_portrait/Mira_portrait_neutral.api.json ...
  python comfy.py upload art/Mira/reference.png
  python comfy.py run    comfy/Mira_portrait/*.api.json --asset-id mira_portrait      # check + queue + wait + fetch
  python comfy.py queue  wf.api.json [--wait]                                         # lower-level pieces
  python comfy.py fetch  <prompt_id> --out runs/x/outputs
  python comfy.py interrupt

Use the *.api.json files that make_comfy_workflow.py writes with --api (UI-format files are for dragging into ComfyUI).
`run` writes runs/<asset-id>/<timestamp>/ with the workflows, run.json and outputs/ (never inside a mod folder).
Then: postprocess.py --jobs <jobs.json> --images runs/<asset-id>/<timestamp>/outputs --out <mod>/assets/<file>.png

The server is never started unless you pass --start (Claude passes it only after the owner said yes in that conversation).
Exit codes: 0 ok, 1 error/failed run, 2 server not reachable.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from sdvlib import find_project, load_config

DEFAULT_URL = "http://127.0.0.1:8188"


class ComfyDown(Exception):
    pass


class Comfy:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.client_id = uuid.uuid4().hex

    # ---- low level
    def _req(self, path: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 30):
        req = urllib.request.Request(self.url + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (user-configured ComfyUI URL)
                return r.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {e.code} from {path}: {body[:1500]}") from None
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            raise ComfyDown(str(e)) from None

    def get_json(self, path: str, timeout: float = 30):
        return json.loads(self._req(path, timeout=timeout).decode("utf-8"))

    def post_json(self, path: str, obj: dict):
        return json.loads(self._req(path, json.dumps(obj).encode("utf-8"), {"Content-Type": "application/json"}).decode("utf-8") or "{}")

    # ---- API
    def alive(self) -> bool:
        try:
            self.get_json("/system_stats", timeout=3)
            return True
        except (ComfyDown, RuntimeError, ValueError):
            return False

    def object_info(self, cls: str | None = None):
        return self.get_json("/object_info" + (f"/{urllib.parse.quote(cls)}" if cls else ""), timeout=120)

    def upload(self, path: Path, name: str | None = None, overwrite: bool = True) -> dict:
        boundary = uuid.uuid4().hex
        fname = name or path.name
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode(),
            path.read_bytes(),
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\n{"true" if overwrite else "false"}'.encode(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        out = self._req("/upload/image", b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        return json.loads(out.decode("utf-8"))

    def queue(self, workflow: dict) -> str:
        res = self.post_json("/prompt", {"prompt": workflow, "client_id": self.client_id})
        if "prompt_id" not in res:
            raise RuntimeError(f"ComfyUI rejected the workflow: {json.dumps(res)[:1500]}")
        return res["prompt_id"]

    def wait(self, prompt_id: str, timeout: float = 1800, poll: float = 1.0, on_tick=None) -> dict:
        t0 = time.time()
        while True:
            h = self.get_json(f"/history/{urllib.parse.quote(prompt_id)}")
            if prompt_id in h:
                entry = h[prompt_id]
                status = (entry.get("status") or {})
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages", []) if m and m[0] == "execution_error"]
                    detail = json.dumps(msgs[-1][1])[:1200] if msgs else json.dumps(status)[:1200]
                    raise RuntimeError(f"execution failed: {detail}")
                if status.get("completed", True) or entry.get("outputs"):
                    return entry
            if time.time() - t0 > timeout:
                raise TimeoutError(f"prompt {prompt_id} not finished after {int(timeout)}s")
            if on_tick:
                on_tick(int(time.time() - t0))
            time.sleep(poll)

    def view(self, filename: str, subfolder: str = "", ftype: str = "output") -> bytes:
        q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": ftype})
        return self._req(f"/view?{q}", timeout=120)

    def interrupt(self):
        self._req("/interrupt", b"{}", {"Content-Type": "application/json"})


# ---------------------------------------------------------------- pre-flight
def norm(s) -> str:
    return str(s).replace("\\", "/")


def preflight(wf: dict, info: dict, available_uploads: set[str]) -> list[str]:
    """Return human-readable problems: unknown node classes and values not in the server's option lists."""
    problems = []
    for nid, node in wf.items():
        cls = node.get("class_type")
        if cls not in info:
            problems.append(f"node {nid}: node class '{cls}' is not installed in this ComfyUI")
            continue
        spec = {**(info[cls].get("input", {}).get("required") or {}), **(info[cls].get("input", {}).get("optional") or {})}
        for name, val in (node.get("inputs") or {}).items():
            if isinstance(val, list) or name not in spec:
                continue  # links, or inputs we know nothing about
            opts = spec[name][0] if spec[name] else None
            if isinstance(opts, list) and opts:
                if norm(val) not in {norm(o) for o in opts}:
                    problems.append(f"node {nid} ({cls}).{name}: '{val}' is not available in ComfyUI"
                                    + (" (pass --upload-missing or upload it first)" if cls == "LoadImage" else ""))
            elif isinstance(opts, list) and not opts and cls == "LoadImage" and name == "image":
                if val not in available_uploads:
                    problems.append(f"node {nid} (LoadImage).image: '{val}' is not in ComfyUI's input folder")
    return problems


def load_api_workflow(path: Path) -> dict:
    wf = json.loads(path.read_text(encoding="utf-8-sig"))
    if "nodes" in wf and "links" in wf:
        raise SystemExit(f"{path.name} is a UI-format workflow (for dragging into ComfyUI). Use the *.api.json file "
                         f"(re-run make_comfy_workflow.py with --api).")
    return wf


def upload_missing(c: Comfy, wf: dict, wf_path: Path, info: dict) -> list[str]:
    done = []
    try:
        have = {norm(x) for x in info["LoadImage"]["input"]["required"]["image"][0]}
    except (KeyError, IndexError, TypeError):
        have = set()
    for node in wf.values():
        if node.get("class_type") == "LoadImage":
            name = node["inputs"].get("image")
            for cand in (wf_path.parent / "input" / str(name), wf_path.parent / str(name)):
                if name and norm(name) not in have and cand.exists():
                    c.upload(cand, str(name)); have.add(norm(name)); done.append(str(name)); break
    return done


# ---------------------------------------------------------------- starting (only with --start)
def find_launch_command(cfg: dict, url: str):
    root = cfg.get("comfyui_root")
    if not root or not (Path(root) / "main.py").exists():
        return None
    r = Path(root)
    py = next((p for p in (r / "venv" / "Scripts" / "python.exe", r.parent / "venv" / "Scripts" / "python.exe") if p.exists()), None)
    port = urllib.parse.urlparse(url).port or 8188
    return [str(py or sys.executable), "main.py", "--listen", "127.0.0.1", "--port", str(port)], r


def ensure_server(c: Comfy, cfg: dict, start: bool, wait_s: int = 240):
    if c.alive():
        return
    how = ("Start ComfyUI first (Stability Matrix -> Launch ComfyUI), then retry. "
           "Ask the owner before starting it; pass --start only after they said yes.")
    if not start:
        print(f"ComfyUI is not reachable at {c.url}. {how}", file=sys.stderr)
        raise SystemExit(2)
    cmd = find_launch_command(cfg, c.url)
    if not cmd:
        print(f"ComfyUI is not reachable at {c.url} and no comfyui_root is configured to start it. Run doctor.py --write-config.", file=sys.stderr)
        raise SystemExit(2)
    argv, cwd = cmd
    print(f"starting ComfyUI: {' '.join(argv)} (in {cwd})", file=sys.stderr)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)  # noqa: S603
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if c.alive():
            print("ComfyUI is up.", file=sys.stderr)
            return
        time.sleep(2)
    print(f"ComfyUI did not answer within {wait_s}s.", file=sys.stderr)
    raise SystemExit(2)


# ---------------------------------------------------------------- commands
def project_root() -> Path:
    p = find_project()
    return p.parent if p else Path.cwd()


def save_outputs(c: Comfy, entry: dict, out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for nid, o in (entry.get("outputs") or {}).items():
        for im in o.get("images", []):
            if im.get("type", "output") != "output":
                continue
            data = c.view(im["filename"], im.get("subfolder", ""), "output")
            p = out_dir / im["filename"]
            p.write_bytes(data)
            saved.append({"file": str(p), "node": nid, "subfolder": im.get("subfolder", "")})
    return saved


def cmd_run(c: Comfy, a, cfg):
    files = [Path(f) for f in a.workflows]
    wfs = [(f, load_api_workflow(f)) for f in files]
    info = c.object_info()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    runs = Path(a.runs_dir) if a.runs_dir else project_root() / "runs"
    run_dir = runs / (a.asset_id or "adhoc") / stamp
    uploads_done = {}
    all_problems = []
    for f, wf in wfs:
        uploads_done[f.name] = upload_missing(c, wf, f, info) if info else []
    info = c.object_info() if any(uploads_done.values()) else info  # refresh image option list
    for f, wf in wfs:
        all_problems += [f"{f.name}: {p}" for p in preflight(wf, info, set())]
    if all_problems:
        print("Pre-flight failed; nothing was queued:", file=sys.stderr)
        for p in all_problems:
            print(" -", p, file=sys.stderr)
        raise SystemExit(1)

    (run_dir / "workflows").mkdir(parents=True, exist_ok=True)
    record = {"asset_id": a.asset_id, "started": stamp, "server": c.url, "jobs": [], "ok": True}
    failed = 0
    for f, wf in wfs:
        (run_dir / "workflows" / f.name).write_text(json.dumps(wf, indent=2), encoding="utf-8")
        job = {"workflow": f.name, "uploaded": uploads_done.get(f.name, [])}
        try:
            pid = c.queue(wf)
            job["prompt_id"] = pid
            print(f"queued {f.name} -> {pid}", flush=True)
            entry = c.wait(pid, timeout=a.timeout, on_tick=lambda s, n=f.name: print(f"  waiting {n} ({s}s)", flush=True) if s and s % 15 == 0 else None)
            job["outputs"] = save_outputs(c, entry, run_dir / "outputs")
            print(f"  done: {len(job['outputs'])} image(s)", flush=True)
        except (RuntimeError, TimeoutError) as e:
            job["error"] = str(e); failed += 1
            print(f"  FAILED {f.name}: {e}", file=sys.stderr)
            if isinstance(e, TimeoutError):
                try:
                    c.interrupt()
                except Exception:
                    pass
        record["jobs"].append(job)
    record["ok"] = failed == 0
    (run_dir / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"run folder: {run_dir}")
    print(f"next: python postprocess.py --jobs <jobs.json> --images \"{run_dir / 'outputs'}\" --out <mod>/assets/<file>.png")
    raise SystemExit(1 if failed else 0)


def main():
    ap = argparse.ArgumentParser(description="ComfyUI API client for the sdv-modding skill.")
    ap.add_argument("--url", help=f"server URL (default config comfyui.url or {DEFAULT_URL})")
    ap.add_argument("--start", action="store_true", help="start ComfyUI if it is not running (only after the owner said yes)")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    m = sub.add_parser("models"); m.add_argument("--json", action="store_true")
    ck = sub.add_parser("check"); ck.add_argument("workflows", nargs="+")
    up = sub.add_parser("upload"); up.add_argument("file"); up.add_argument("--name")
    q = sub.add_parser("queue"); q.add_argument("workflow"); q.add_argument("--wait", action="store_true"); q.add_argument("--timeout", type=float, default=1800)
    fe = sub.add_parser("fetch"); fe.add_argument("prompt_id"); fe.add_argument("--out", required=True)
    sub.add_parser("interrupt")
    r = sub.add_parser("run"); r.add_argument("workflows", nargs="+"); r.add_argument("--asset-id"); r.add_argument("--runs-dir"); r.add_argument("--timeout", type=float, default=1800)
    a = ap.parse_args()

    cfg = load_config(a.config)
    c = Comfy(a.url or (cfg.get("comfyui") or {}).get("url") or DEFAULT_URL)
    ensure_server(c, cfg, a.start)

    try:
        if a.cmd == "status":
            s = c.get_json("/system_stats")
            sysinfo = s.get("system", {})
            print(f"ComfyUI up at {c.url}  version {sysinfo.get('comfyui_version', '?')}")
            for d in s.get("devices", []):
                print(f"  device {d.get('name')}  vram free {d.get('vram_free', 0) // 2**20} MB of {d.get('vram_total', 0) // 2**20} MB")
            qd = c.get_json("/queue")
            print(f"  queue: {len(qd.get('queue_running', []))} running, {len(qd.get('queue_pending', []))} pending")
        elif a.cmd == "models":
            def opts(cls, inp):
                try:
                    return c.object_info(cls)[cls]["input"]["required"][inp][0]
                except Exception:
                    return []
            res = {"checkpoints": opts("CheckpointLoaderSimple", "ckpt_name"), "loras": opts("LoraLoader", "lora_name"),
                   "controlnets": opts("ControlNetLoader", "control_net_name"), "vaes": opts("VAELoader", "vae_name"),
                   "diffusion_models": opts("UNETLoader", "unet_name"), "text_encoders": opts("DualCLIPLoader", "clip_name1")}
            if a.json:
                print(json.dumps(res, indent=2))
            else:
                for k, v in res.items():
                    print(f"{k} ({len(v)}): " + ", ".join(v[:12]) + (" ..." if len(v) > 12 else ""))
        elif a.cmd == "check":
            info = c.object_info()
            bad = 0
            for f in a.workflows:
                wf = load_api_workflow(Path(f))
                probs = preflight(wf, info, set())
                print(f"{Path(f).name}: " + ("ok" if not probs else ""))
                for p in probs:
                    print(" -", p); bad += 1
            raise SystemExit(1 if bad else 0)
        elif a.cmd == "upload":
            print(json.dumps(c.upload(Path(a.file), a.name)))
        elif a.cmd == "queue":
            wf = load_api_workflow(Path(a.workflow))
            pid = c.queue(wf)
            print(pid)
            if a.wait:
                c.wait(pid, timeout=a.timeout)
                print("finished")
        elif a.cmd == "fetch":
            entry = c.get_json(f"/history/{a.prompt_id}").get(a.prompt_id)
            if not entry:
                raise SystemExit(f"No history for {a.prompt_id}")
            for s in save_outputs(c, entry, Path(a.out)):
                print(s["file"])
        elif a.cmd == "interrupt":
            c.interrupt(); print("interrupt sent")
        elif a.cmd == "run":
            cmd_run(c, a, cfg)
    except ComfyDown as e:
        print(f"Lost connection to ComfyUI at {c.url}: {e}", file=sys.stderr)
        raise SystemExit(2)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

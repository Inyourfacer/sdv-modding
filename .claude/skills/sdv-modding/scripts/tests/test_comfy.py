"""comfy.py against a mock ComfyUI server (no real ComfyUI needed)."""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import sdvlib  # noqa: E402


def png_bytes(color=(200, 50, 50)):
    b = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(b, "PNG")
    return b.getvalue()


def info(images):
    def req(**k):
        return {"input": {"required": k}}
    return {
        "CheckpointLoaderSimple": req(ckpt_name=[["test.safetensors"]]),
        "CLIPSetLastLayer": req(clip=["CLIP"], stop_at_clip_layer=["INT"]),
        "LoraLoader": req(lora_name=[["a.safetensors"]], strength_model=["FLOAT"]),
        "CLIPTextEncode": req(text=["STRING"], clip=["CLIP"]),
        "EmptyLatentImage": req(width=["INT"]),
        "KSampler": req(sampler_name=[["euler_ancestral", "euler"]], scheduler=[["normal", "karras"]], seed=["INT"]),
        "VAEDecode": req(samples=["LATENT"]), "VAEEncode": req(pixels=["IMAGE"]),
        "SaveImage": req(filename_prefix=["STRING"], images=["IMAGE"]),
        "LoadImage": req(image=[list(images), {"image_upload": True}]),
    }


class Mock:
    def __init__(self):
        self.images, self.prompts, self.uploads, self.polls, self.interrupted = [], {}, [], {}, 0
        self.fail_next = False
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _send(self, obj, code=200, raw=None):
                body = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/system_stats":
                    return self._send({"system": {"comfyui_version": "mock"}, "devices": []})
                if u.path == "/queue":
                    return self._send({"queue_running": [], "queue_pending": []})
                if u.path == "/object_info":
                    return self._send(info(mock.images))
                if u.path.startswith("/object_info/"):
                    cls = u.path.split("/")[-1]
                    full = info(mock.images)
                    return self._send({cls: full[cls]} if cls in full else {})
                if u.path.startswith("/history/"):
                    pid = u.path.split("/")[-1]
                    mock.polls[pid] = mock.polls.get(pid, 0) + 1
                    if pid not in mock.prompts or mock.polls[pid] < 2:
                        return self._send({})
                    wf = mock.prompts[pid]
                    if mock.fail_next:
                        return self._send({pid: {"status": {"status_str": "error", "messages": [["execution_error", {"exception_message": "boom"}]]}}})
                    outs = {}
                    for nid, n in wf.items():
                        if n["class_type"] == "SaveImage":
                            sub, _, stem = n["inputs"]["filename_prefix"].rpartition("/")
                            outs[nid] = {"images": [{"filename": f"{stem}_00001_.png", "subfolder": sub, "type": "output"}]}
                    return self._send({pid: {"status": {"status_str": "success", "completed": True}, "outputs": outs}})
                if u.path == "/view":
                    return self._send(None, raw=png_bytes())
                self._send({}, 404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                if self.path == "/prompt":
                    pid = f"p{len(mock.prompts) + 1}"
                    mock.prompts[pid] = json.loads(body)["prompt"]
                    return self._send({"prompt_id": pid})
                if self.path == "/upload/image":
                    m = re.search(rb'filename="([^"]+)"', body)
                    name = m.group(1).decode()
                    mock.uploads.append(name); mock.images.append(name)
                    return self._send({"name": name, "subfolder": "", "type": "input"})
                if self.path == "/interrupt":
                    mock.interrupted += 1
                    return self._send({})
                self._send({}, 404)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture()
def mock():
    m = Mock()
    yield m
    m.close()


@pytest.fixture()
def work(tmp_path):
    (tmp_path / sdvlib.CONFIG_NAME).write_text(json.dumps({"comfyui": {"checkpoint": "test.safetensors"}}), encoding="utf-8")
    return tmp_path


def comfy(work, url, *args, ok=True):
    p = subprocess.run([sys.executable, str(SCRIPTS / "comfy.py"), "--url", url, *map(str, args)],
                       cwd=work, capture_output=True, text=True)
    if ok:
        assert p.returncode == 0, f"{args}\n{p.stdout}\n{p.stderr}"
    return p


def make_workflows(work, *extra):
    out = work / "wf"
    subprocess.run([sys.executable, str(SCRIPTS / "make_comfy_workflow.py"), "--spec", "portrait", "--name", "Mira",
                    "--subject", "1girl", "--out-dir", out, "--api", "--frames", "neutral,happy", *map(str, extra)],
                   cwd=work, check=True, capture_output=True)
    return sorted(out.glob("*.api.json"))


def test_unreachable_server_exits_2_and_does_not_start(work):
    p = comfy(work, "http://127.0.0.1:9", "status", ok=False)
    assert p.returncode == 2
    assert "Ask the owner" in p.stderr


def test_status_and_models(work, mock):
    assert "mock" in comfy(work, mock.url, "status").stdout
    m = json.loads(comfy(work, mock.url, "models", "--json").stdout)
    assert m["checkpoints"] == ["test.safetensors"] and m["loras"] == ["a.safetensors"]


def test_run_fetches_outputs_and_feeds_postprocess(work, mock):
    wfs = make_workflows(work)
    assert len(wfs) == 2
    p = comfy(work, mock.url, "run", *wfs, "--asset-id", "mira_portrait")
    runs = list((work / "runs" / "mira_portrait").iterdir())
    assert len(runs) == 1
    rec = json.loads((runs[0] / "run.json").read_text(encoding="utf-8"))
    assert rec["ok"] and len(rec["jobs"]) == 2
    outs = sorted((runs[0] / "outputs").glob("*.png"))
    assert [o.name for o in outs] == ["Mira_portrait_happy_00001_.png", "Mira_portrait_neutral_00001_.png"]
    # the run's outputs folder is directly usable by postprocess.py
    sheet = work / "mod" / "Mira.png"
    subprocess.run([sys.executable, str(SCRIPTS / "postprocess.py"), "--jobs", work / "wf" / "jobs.json",
                    "--images", runs[0] / "outputs", "--out", sheet], cwd=work, check=True, capture_output=True)
    assert Image.open(sheet).size == (128, 192)


def test_preflight_names_missing_checkpoint_and_lora_and_queues_nothing(work, mock):
    wfs = make_workflows(work, "--lora", "missing.safetensors:0.8")
    cfg = work / sdvlib.CONFIG_NAME
    cfg.write_text(json.dumps({"comfyui": {"checkpoint": "nope.safetensors"}}), encoding="utf-8")
    wfs = make_workflows(work, "--lora", "missing.safetensors:0.8")
    p = comfy(work, mock.url, "run", *wfs, ok=False)
    assert p.returncode == 1
    assert "nope.safetensors" in p.stderr and "missing.safetensors" in p.stderr
    assert mock.prompts == {}


def test_init_images_are_uploaded_automatically(work, mock):
    ref = work / "ref.png"
    ref.write_bytes(png_bytes())
    wfs = make_workflows(work, "--init", ref)
    comfy(work, mock.url, "run", *wfs, "--asset-id", "x")
    assert any(n.endswith("_init.png") for n in mock.uploads)


def test_failed_job_reports_and_exits_1(work, mock):
    mock.fail_next = True
    wfs = make_workflows(work)
    p = comfy(work, mock.url, "run", *wfs, "--asset-id", "bad", ok=False)
    assert p.returncode == 1 and "boom" in p.stderr
    run = next((work / "runs" / "bad").iterdir())
    assert json.loads((run / "run.json").read_text(encoding="utf-8"))["ok"] is False


def test_ui_format_workflow_is_refused_with_hint(work, mock):
    make_workflows(work)
    ui = next((work / "wf").glob("*neutral.json"))
    p = comfy(work, mock.url, "check", ui, ok=False)
    assert p.returncode != 0 and "api.json" in (p.stderr + p.stdout)


def test_batch_run_end_to_end_writes_candidates_for_every_target(work, mock):
    (work / sdvlib.CONFIG_NAME).write_text(json.dumps({"comfyui": {"checkpoint": "test.safetensors", "url": mock.url}}), encoding="utf-8")
    proj = {"version": 1, "art_style": {"takes": 2}, "characters": {},
            "assets": [{"id": "gem", "spec": "object_icon", "status": "placeholder", "files": [], "prompt": {"positive": "a blue gem"},
                        "targets": [{"kind": "vanilla"}, {"kind": "hd", "scale": 4}]}]}
    (work / "sdv-project.json").write_text(json.dumps(proj), encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPTS / "batch.py"), "run", "--takes", "2"], cwd=work, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    for t in ("a", "b"):
        assert Image.open(work / "art" / "gem" / f"take_{t}.png").size == (16, 16)
        assert Image.open(work / "art" / "gem" / f"take_{t}.hd4.png").size == (64, 64)
    after = json.loads((work / "sdv-project.json").read_text(encoding="utf-8"))["assets"][0]
    assert after["status"] == "generated" and len(after["candidates"]) == 2
    seeds = {json.loads((work / "comfy" / "gem" / f"take_{t}" / "jobs.json").read_text(encoding="utf-8"))["seed"] for t in ("a", "b")}
    assert len(seeds) == 2


def test_batch_reroll_loop_is_bounded_records_history_and_stops_for_review(work, mock):
    """The mock always returns a flat red image, which fails QA every time: the loop must re-roll at most max_rounds and then stop."""
    (work / sdvlib.CONFIG_NAME).write_text(json.dumps({"comfyui": {"checkpoint": "test.safetensors", "url": mock.url}}), encoding="utf-8")
    proj = {"version": 1, "art_style": {"takes": 1, "max_rounds": 2}, "characters": {},
            "assets": [{"id": "gem", "spec": "object_icon", "status": "placeholder", "files": [], "prompt": {"positive": "a blue gem"}}]}
    (work / "sdv-project.json").write_text(json.dumps(proj), encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPTS / "batch.py"), "run"], cwd=work, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert len(mock.prompts) == 3                                  # first generation + 2 re-rolls, then it stops
    row = json.loads((work / "sdv-project.json").read_text(encoding="utf-8"))["assets"][0]
    assert [h["round"] for h in row["history"]] == [1, 2] and row["history"][0]["level"] == "FAIL"
    assert row["status"] == "generated" and row["recommended"] == "take_a"       # never installed, never approved
    assert (work / "art" / "gem" / "contact.png").exists() and (work / "art" / "gem" / "qa.json").exists()
    assert "REVIEW NEEDED" in p.stdout and "do not install" in p.stdout
    seeds = [n["inputs"]["seed"] for pr in mock.prompts.values() for n in pr.values() if n["class_type"] == "KSampler"]
    assert len(set(seeds)) == 3                                    # every re-roll used a new seed

"""A stand-in for StardewModdingAPI.exe used by the tests (SDV_GAME_CMD). It behaves like the C# harness protocol:
reads harness-commands.json, applies the same save-safety rule, runs steps, answers screenshot/console through the
request/ack files, writes harness-results.json, and exits when harness-exit appears. It never loads anything real."""
import json
import sys
import time
from pathlib import Path

mods = Path(sys.argv[sys.argv.index("--mods-path") + 1])
h = mods / "SdvTestHarness"
cmds = h / "harness-commands.json"
results = h / "harness-results.json"


def write(state, steps, errors, finished, ok):
    results.write_text(json.dumps({"state": state, "steps": steps, "errors": errors, "finished": finished, "ok": ok}), encoding="utf-8")


def policy(folder, prefix):
    prefix = (prefix or "").strip()
    return bool(folder) and len(prefix) >= 4 and "test" in prefix.lower() and not any(c in folder for c in "/\\:") and ".." not in folder \
        and folder.lower().startswith(prefix.lower())


(h / "loaded_mods.txt").write_text("\n".join(p.name for p in mods.iterdir() if p.is_dir()), encoding="utf-8")
try:
    script = json.loads(cmds.read_text(encoding="utf-8"))
except Exception as ex:                                     # no commands: dormant, just wait to be closed
    script = None
if script is not None:
    if not policy(script.get("save"), script.get("save_prefix")):
        write("Finished", [], ["refusing: not a test save"], True, False)
    else:
        out, seq = [], 0
        for i, s in enumerate(script["steps"]):
            t = s["type"]
            if t in ("screenshot", "console"):
                seq = i + 1
                (h / "harness-request.json").write_text(json.dumps({"seq": seq, "type": t, "name": s.get("name"), "command": s.get("command")}), encoding="utf-8")
                ack = h / "harness-ack.json"
                for _ in range(200):
                    if ack.exists():
                        try:
                            a = json.loads(ack.read_text(encoding="utf-8"))
                        except ValueError:
                            a = {}
                        if a.get("seq") == seq:
                            out.append({"index": i, "type": t, "ok": a.get("ok", True), "info": a.get("message"), "error": None if a.get("ok", True) else a.get("message")})
                            break
                    time.sleep(0.05)
                else:
                    out.append({"index": i, "type": t, "ok": False, "error": "no ack"})
            elif t == "fail_me":
                out.append({"index": i, "type": t, "ok": False, "error": "asked to fail"})
            else:
                out.append({"index": i, "type": t, "ok": True})
            write("Running", out, [], False, False)
        write("Finished", out, [], True, all(r["ok"] for r in out))
for _ in range(600):
    if (h / "harness-exit").exists():
        break
    time.sleep(0.05)

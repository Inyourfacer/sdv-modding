"""The scripted eval acceptance checks run as part of the suite (they exercise the real tooling end to end)."""
import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parent.parent.parent / "evals" / "run_scripted.py"


def test_scripted_evals_all_pass_or_skip_for_a_stated_reason():
    r = subprocess.run([sys.executable, str(RUNNER)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout.split("\n\n")[0].replace("not scripted", "")
    assert r.stdout.count("[PASS") >= 6

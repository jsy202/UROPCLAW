import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PYTHON37 = ROOT / ".venv-carla-e2e" / "bin" / "python"
MODULES = [
    "config",
    "core.session_store",
    "core.pipeline",
    "debug_snap",
    "evaluation.metrics",
    "obs.evaluator",
    "sensors.camera",
    "sensors.manager",
    "start",
]


@pytest.mark.skipif(
    not PYTHON37.exists(),
    reason="Host .venv-carla-e2e environment is not present",
)
def test_production_modules_import_under_isolated_python37():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "harness")
    command = "import " + ", ".join(MODULES)
    completed = subprocess.run(
        [str(PYTHON37), "-c", command],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    assert completed.returncode == 0, completed.stderr

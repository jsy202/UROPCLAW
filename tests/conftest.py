"""Fixtures: run the real UROPCLAW Pipeline without CARLA, GPU, `claude` CLI or Discord.

The workspace (mission.json, detection_event.json, crops, metrics.json) is
redirected into tmp_path, so tests never touch ../workspaces.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "tests"))

import core.mission as mission_mod  # noqa: E402
import core.pipeline as pipeline_mod  # noqa: E402
from fakes.components import FakeAlert, FakeDetector, SuccessVLM  # noqa: E402

MISSION = {"active": True, "target_color": "blue", "mission_id": "m-test", "discord_channel_id": "0"}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(mission_mod, "_MISSION_PATH", tmp_path / "uropclaw1" / "state" / "mission.json")
    monkeypatch.setattr(pipeline_mod, "WORKSPACE_BASE", tmp_path)
    monkeypatch.setattr(pipeline_mod, "_METRICS_PATH", tmp_path / "uropclaw1" / "state" / "metrics.json")
    monkeypatch.setattr(pipeline_mod, "_METRICS_INTERVAL", 0.2)  # production: 5 s; keeps stop() fast
    mission_mod.write_mission(dict(MISSION))
    return tmp_path


@pytest.fixture
def make_pipeline(workspace):
    started = []

    def _make(detector=None, vlm=None, alert=None, baseline_mode="proposed", start=True):
        p = pipeline_mod.Pipeline(world=None, baseline_mode=baseline_mode,
                                  detector=detector or FakeDetector(),
                                  vlm_runner=vlm if vlm is not None else SuccessVLM(),
                                  alert_sender=alert if alert is not None else FakeAlert())
        if start:
            p.start()
            started.append(p)
        return p

    yield _make
    for p in started:
        p.stop()


def wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

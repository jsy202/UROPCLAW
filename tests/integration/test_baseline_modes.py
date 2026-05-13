"""Evaluation baseline modes (harness/evaluation/baseline.py) run through the replay path."""

import pytest

from conftest import wait_until
from fakes.components import FakeAlert, FakeDetector, SuccessVLM
from replay.source import SyntheticSceneSource, replay


def test_baseline_c_never_calls_vlm(make_pipeline):
    vlm = SuccessVLM()
    p = make_pipeline(vlm=vlm, baseline_mode="C")
    replay(p, SyntheticSceneSource(6, colour="blue"), interval_s=0.05)
    assert wait_until(lambda: p.metrics_summary()["frames_processed"] == 6)
    assert wait_until(lambda: p.metrics_summary()["candidates_raised"] >= 1)
    assert vlm.calls == 0


def test_baseline_b_sends_every_detection_to_vlm_without_dedup(make_pipeline):
    # REQ: baseline B = "YOLO -> OpenClaw, no color filter, no dedup" (baseline.py / README §8).
    vlm = SuccessVLM()
    p = make_pipeline(vlm=vlm, baseline_mode="B")
    replay(p, SyntheticSceneSource(5, colour="blue"), interval_s=0.05)
    assert wait_until(lambda: p.metrics_summary()["candidates_raised"] == 5)
    assert wait_until(lambda: vlm.calls == 5, timeout=3.0)
    assert p.metrics_summary()["duplicate_suppressed"] == 0


def test_baseline_a_sends_every_nth_frame_to_vlm_without_dedup(make_pipeline, monkeypatch):
    import core.pipeline as pm
    monkeypatch.setattr(pm, "BASELINE_N", 2)   # production 30; every 2nd frame here
    vlm = SuccessVLM()
    p = make_pipeline(vlm=vlm, baseline_mode="A")
    replay(p, SyntheticSceneSource(6, colour="blue"), interval_s=0.05)
    assert wait_until(lambda: p.metrics_summary()["candidates_raised"] == 3)
    assert wait_until(lambda: vlm.calls == 3, timeout=3.0)

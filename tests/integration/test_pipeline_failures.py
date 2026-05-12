"""Failure-mode tests for the AI pipeline (no CARLA / GPU / VLM / Discord).

Each test injects one fault and checks that (a) the pipeline keeps running and
(b) the outcome is observable. Fault -> expected system behavior is listed in
validation/failure_model.md.
"""

import time
from queue import Queue

import pytest
import threading

import numpy as np

import core.pipeline as pipeline_mod
from conftest import wait_until
from fakes.components import (EmptyDetector, ErrorVLM, FakeAlert, FakeDetector, MalformedResponseVLM,
                              RejectVLM, SuccessVLM, TimeoutVLM)
from replay.source import SyntheticSceneSource, replay


def _run_blue(make_pipeline, n=6, **kw):
    alert = kw.pop("alert", None) or FakeAlert()
    p = make_pipeline(alert=alert, **kw)
    replay(p, SyntheticSceneSource(n, colour="blue"), interval_s=0.05)
    return p, alert


# ── VLM faults ───────────────────────────────────────────────────────────────

def test_vlm_timeout_fails_open_and_still_alerts(make_pipeline):
    # Existing design ("Fail open: LLM 오류 시 통과"): a VLM outage must not stop alerts.
    p, alert = _run_blue(make_pipeline, vlm=TimeoutVLM())
    assert wait_until(lambda: len(alert.attempts) == 1)
    result = alert.attempts[0][1]["openclaw_result"]
    assert result["confirmed"] is True and result["confidence"] == "n/a"


def test_vlm_timeout_is_counted(make_pipeline):
    # REQ: a VLM timeout must be visible in metrics (openclaw_timeouts exists but is never incremented).
    p, alert = _run_blue(make_pipeline, vlm=TimeoutVLM())
    assert wait_until(lambda: alert.attempts)
    assert p.metrics_summary()["openclaw_timeouts"] == 1


def test_vlm_process_error_fails_open_and_is_counted(make_pipeline):
    # REQ: a VLM process error (CLI missing) must be counted, separately from timeouts.
    p, alert = _run_blue(make_pipeline, vlm=ErrorVLM())
    assert wait_until(lambda: alert.attempts)
    assert alert.attempts[0][1]["openclaw_result"]["confidence"] == "n/a"
    assert p.metrics_summary().get("openclaw_errors") == 1


def test_vlm_malformed_response_fails_open_and_is_counted(make_pipeline):
    # REQ: an unparseable VLM answer must be counted.
    p, alert = _run_blue(make_pipeline, vlm=MalformedResponseVLM())
    assert wait_until(lambda: alert.attempts)
    assert alert.attempts[0][1]["openclaw_result"]["confidence"] == "n/a"
    assert p.metrics_summary().get("openclaw_parse_failures") == 1


def test_vlm_rejection_blocks_alert(make_pipeline):
    vlm = RejectVLM()
    p, alert = _run_blue(make_pipeline, vlm=vlm)
    assert wait_until(lambda: vlm.calls == 1)
    assert not wait_until(lambda: alert.attempts, timeout=0.8)
    assert p.metrics_summary()["openclaw_confirmed"] == 0


def test_vlm_is_called_without_body_type_in_mission(make_pipeline):
    # Characterization: README says VLM verification runs "body_type 지정 시" only,
    # but the code verifies every confirmed candidate. The mission here has no body_type.
    vlm = SuccessVLM()
    _run_blue(make_pipeline, vlm=vlm)
    assert wait_until(lambda: vlm.calls == 1)


# ── Alert faults ─────────────────────────────────────────────────────────────

def test_alerts_sent_counts_attempts_not_deliveries(make_pipeline):
    # Characterization: alerts_sent is incremented before the alert is delivered.
    p, alert = _run_blue(make_pipeline, alert=FakeAlert(fail="false"))
    assert wait_until(lambda: alert.attempts)
    assert p.metrics_summary()["alerts_sent"] == 1


def test_alert_delivery_failure_is_counted(make_pipeline):
    # REQ: delivered and failed alerts must be distinguishable in metrics.
    p, alert = _run_blue(make_pipeline, alert=FakeAlert(fail="false"))
    assert wait_until(lambda: alert.attempts)
    m = p.metrics_summary()
    assert m.get("alerts_delivered") == 0 and m.get("alerts_failed") == 1


def test_alert_exception_does_not_stop_pipeline(make_pipeline):
    alert = FakeAlert(fail="raise")
    p = make_pipeline(alert=alert)
    replay(p, SyntheticSceneSource(6, colour="blue", agent_id="uropclaw1"), interval_s=0.05)
    assert wait_until(lambda: len(alert.attempts) == 1)
    replay(p, SyntheticSceneSource(6, colour="blue", agent_id="uropclaw2"), interval_s=0.05)
    assert wait_until(lambda: len(alert.attempts) == 2)   # second agent still processed


# ── Input / detection faults ─────────────────────────────────────────────────

def test_empty_detection_produces_no_candidates(make_pipeline):
    vlm = SuccessVLM()
    p, alert = _run_blue(make_pipeline, detector=EmptyDetector(), vlm=vlm)
    assert wait_until(lambda: p.metrics_summary()["frames_processed"] == 6)
    m = p.metrics_summary()
    assert m["detections_total"] == 0 and m["candidates_raised"] == 0 and vlm.calls == 0 and not alert.attempts


def test_invalid_frame_does_not_stop_pipeline(make_pipeline):
    alert = FakeAlert()
    p = make_pipeline(alert=alert)
    p.push_frame("uropclaw1_front", "uropclaw1", None)                       # not an image
    p.push_frame("uropclaw1_front", "uropclaw1", np.zeros((10,), np.uint8))  # wrong shape
    replay(p, SyntheticSceneSource(6, colour="blue"), interval_s=0.05)
    assert wait_until(lambda: len(alert.attempts) == 1)
    assert p.metrics_summary()["frames_received"] == 8


def test_tracking_loss_resets_temporal_confirmation(make_pipeline):
    # Two frames, a gap > 1 s (TemporalConfirm _MAX_GAP_SECONDS), two frames: never 3 consecutive.
    vlm = SuccessVLM()
    p = make_pipeline(vlm=vlm)
    frames = list(SyntheticSceneSource(4, colour="blue"))
    for rf in frames[:2]:
        p.push_frame(rf.camera_id, rf.agent_id, rf.frame, time.time()); time.sleep(0.05)
    time.sleep(1.3)
    for rf in frames[2:]:
        p.push_frame(rf.camera_id, rf.agent_id, rf.frame, time.time()); time.sleep(0.05)
    assert wait_until(lambda: p.metrics_summary()["frames_processed"] == 4)
    time.sleep(0.3)
    assert vlm.calls == 0


def test_stale_frames_are_dropped(make_pipeline):
    p = make_pipeline()
    p.push_frame("uropclaw1_front", "uropclaw1", next(iter(SyntheticSceneSource(1))).frame, timestamp=time.time() - 5)
    assert wait_until(lambda: p.metrics_summary()["frames_dropped"] == 1)


def test_frame_queue_saturation_drops_and_counts(make_pipeline):
    p = make_pipeline(start=False)  # workers not running: queue (maxsize 4) fills up
    for rf in SyntheticSceneSource(10):
        p.push_frame(rf.camera_id, rf.agent_id, rf.frame)
    m = p.metrics_summary()
    assert p.frame_queue.qsize() == 4 and m["frames_dropped"] == 6


def test_inactive_mission_skips_processing(make_pipeline, workspace):
    import core.mission as mission_mod
    mission_mod.write_mission({"active": False, "mission_id": "m-off"})
    det = FakeDetector()
    p = make_pipeline(detector=det)
    replay(p, SyntheticSceneSource(4), interval_s=0.02)
    assert wait_until(lambda: p.metrics_summary()["frames_received"] == 4)
    assert det.calls == 0


def test_candidate_queue_overflow_is_not_counted_as_frame_drop(workspace):
    # REQ: frames_dropped means dropped *frames* (README: frame_drop_rate = frames_dropped / frames_received);
    # candidates lost because the candidate queue is full must be counted separately.
    metrics = {"frames_received": 0, "frames_dropped": 0, "frames_processed": 0, "detections_total": 0,
               "candidates_raised": 0}
    frame_q, cand_q = Queue(maxsize=8), Queue(maxsize=1)
    cand_q.put({"placeholder": True})            # candidate queue already full (VLM stage stalled)
    stop = threading.Event()
    w = pipeline_mod.YoloWorker(stop, frame_q, cand_q, metrics, baseline_mode="B", detector=FakeDetector())
    for rf in SyntheticSceneSource(3):
        frame_q.put({"camera_id": rf.camera_id, "agent_id": rf.agent_id, "frame": rf.frame, "timestamp": time.time()})
    w.start()
    assert wait_until(lambda: metrics["frames_processed"] == 3)
    stop.set(); w.join(2)
    assert metrics["frames_dropped"] == 0
    assert metrics.get("candidates_dropped") == 3


def test_vlm_broken_json_is_counted_as_parse_failure(make_pipeline):
    # A brace-delimited but invalid JSON answer: previously fell into the generic error path.
    from fakes.components import _VLMBase

    class BrokenJSONVLM(_VLMBase):
        def respond(self, cmd, timeout):
            return self._done(cmd, "{confirmed: yes, confidence: high}")

    p, alert = _run_blue(make_pipeline, vlm=BrokenJSONVLM())
    assert wait_until(lambda: alert.attempts)
    m = p.metrics_summary()
    assert m["openclaw_parse_failures"] == 1 and m["openclaw_errors"] == 0


def test_successful_alert_is_counted_as_delivered(make_pipeline):
    p, alert = _run_blue(make_pipeline)
    assert wait_until(lambda: alert.attempts)
    assert wait_until(lambda: p.metrics_summary()["alerts_delivered"] == 1)
    assert p.metrics_summary()["alerts_failed"] == 0


def test_discord_sender_without_token_reports_not_delivered(workspace, monkeypatch):
    # Production Discord sender: no token -> no HTTP call, returns False (counted as failed).
    import core.pipeline as pm
    import threading
    from queue import Queue
    monkeypatch.setattr(pm, "_BOT_TOKENS", {"uropclaw1": ""})
    called = []
    monkeypatch.setattr(pm.requests, "post", lambda *a, **k: called.append(1))
    w = pm.AlertWorker(threading.Event(), Queue(), {})
    assert w._enqueue_discord_alert("uropclaw1", {"color": "blue", "yolo_class": "car", "yolo_confidence": 0.9,
                                                  "color_score": 0.8, "timestamp": 0}) is False
    assert called == []


def test_discord_sender_http_error_reports_not_delivered(workspace, monkeypatch):
    import core.pipeline as pm
    import threading
    from queue import Queue
    from types import SimpleNamespace
    monkeypatch.setattr(pm, "_BOT_TOKENS", {"uropclaw1": "test-token"})
    monkeypatch.setattr(pm.requests, "post", lambda *a, **k: SimpleNamespace(status_code=500, text="boom"))
    w = pm.AlertWorker(threading.Event(), Queue(), {})
    ev = {"color": "blue", "yolo_class": "car", "yolo_confidence": 0.9, "color_score": 0.8, "timestamp": 0}
    assert w._enqueue_discord_alert("uropclaw1", ev) is False
    monkeypatch.setattr(pm.requests, "post", lambda *a, **k: SimpleNamespace(status_code=200, text="ok"))
    assert w._enqueue_discord_alert("uropclaw1", ev) is True

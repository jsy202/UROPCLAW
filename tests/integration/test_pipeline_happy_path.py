"""End-to-end replay through the real pipeline stages:

SyntheticSceneSource -> push_frame -> FakeDetector -> HSV color_filter (real) -> IoUTracker (real)
-> TemporalConfirm (real) -> Deduplicator (real) -> VLM prompt/parse (real) with SuccessVLM
-> AlertPolicy (real) -> detection_event.json + crop (real) -> FakeAlert
"""

from conftest import read_json, wait_until
from fakes.components import FakeAlert, FakeDetector, SuccessVLM
from replay.source import SyntheticSceneSource, replay


def test_blue_vehicle_replay_produces_one_verified_alert(make_pipeline, workspace):
    det, vlm, alert = FakeDetector(), SuccessVLM(), FakeAlert()
    p = make_pipeline(detector=det, vlm=vlm, alert=alert)

    pushed = replay(p, SyntheticSceneSource(6, colour="blue"), interval_s=0.05)
    assert wait_until(lambda: len(alert.attempts) == 1)

    agent_id, event = alert.attempts[0]
    assert agent_id == "uropclaw1"
    assert event["color"] == "blue" and event["mission_id"] == "m-test"
    assert event["openclaw_result"]["confirmed"] is True
    assert (workspace / "uropclaw1" / "state" / "detection_event.json").exists()
    assert read_json(workspace / "uropclaw1" / "state" / "detection_event.json")["event_id"] == event["event_id"]
    assert any((workspace / "uropclaw1" / "state" / "crops").glob("evt_*.jpg"))

    m = p.metrics_summary()
    assert pushed == 6 and m["frames_received"] == 6 and m["frames_processed"] == 6
    assert det.calls == 6
    assert vlm.calls == 1 and m["openclaw_calls"] == 1     # temporal confirm + 30 s dedup -> one VLM call
    assert m["alerts_sent"] == 1


def test_non_target_colour_produces_no_vlm_call_and_no_alert(make_pipeline):
    vlm, alert = SuccessVLM(), FakeAlert()
    p = make_pipeline(vlm=vlm, alert=alert)
    replay(p, SyntheticSceneSource(6, colour="red"), interval_s=0.05)
    assert not wait_until(lambda: alert.attempts, timeout=1.0)
    assert vlm.calls == 0
    assert p.metrics_summary()["frames_processed"] == 6

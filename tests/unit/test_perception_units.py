"""Unit tests pinning existing behavior of the perception / policy stages."""

import numpy as np

from perception.color_filter import classify_color
from perception.deduplicator import Deduplicator
from perception.iou_tracker import IoUTracker, _iou
from perception.temporal_confirm import TemporalConfirm
from perception.yolo_detector import Detection
from policy.alert_policy import AlertPolicy
from replay.source import ROAD_BGR, SCENE_COLOURS


def _frame(bgr):
    f = np.full((360, 640, 3), ROAD_BGR, np.uint8)
    f[100:200, 200:340] = bgr
    return f


# color_filter
def test_classify_color_blue_and_red():
    assert classify_color(_frame(SCENE_COLOURS["blue"]), [200, 100, 340, 200]) == "blue"
    assert classify_color(_frame(SCENE_COLOURS["red"]), [200, 100, 340, 200]) == "red"


def test_classify_color_degenerate_bbox_is_unknown():
    assert classify_color(_frame(SCENE_COLOURS["blue"]), [10, 10, 10, 50]) == "unknown"


# iou tracker
def test_iou_identical_and_disjoint():
    assert _iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert _iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0


def test_tracker_keeps_id_for_overlapping_boxes():
    t = IoUTracker()
    a = t.update([Detection([100, 100, 200, 200], 2, "car", 0.9)], ["blue"])
    b = t.update([Detection([104, 100, 204, 200], 2, "car", 0.9)], ["blue"])
    assert list(a) == list(b) == [0]
    assert b[0].color_history == ["blue", "blue"]


# temporal confirm
def test_temporal_confirm_needs_three_frames_and_majority():
    tc = TemporalConfirm()
    assert tc.update(1, "blue", 0.0) is None
    assert tc.update(1, "blue", 0.1) is None
    assert tc.update(1, "blue", 0.2) == {"track_id": 1, "color": "blue"}


def test_temporal_confirm_resets_after_gap():
    tc = TemporalConfirm()
    tc.update(1, "blue", 0.0); tc.update(1, "blue", 0.1)
    assert tc.update(1, "blue", 1.5) is None          # gap > 1 s resets the count


def test_temporal_confirm_rejects_unknown_only():
    tc = TemporalConfirm()
    for i in range(3):
        r = tc.update(2, "unknown", i * 0.1)
    assert r is None


# deduplicator
def test_dedup_verify_cooldown_30s():
    d = Deduplicator()
    assert d.should_verify("uropclaw1", 100.0) is True
    assert d.should_verify("uropclaw1", 110.0) is False
    assert d.should_verify("uropclaw1", 131.0) is True


# alert policy
MISSION = {"active": True, "mission_id": "m", "target_color": "blue"}
CAND = {"mission_id": "m", "color": "blue", "color_score": 0.9, "yolo_confidence": 0.9}


def test_policy_allows_confirmed_candidate():
    assert AlertPolicy().should_alert(CAND, MISSION, {"confirmed": True, "confidence": "high"})


def test_policy_blocks_stale_mission_and_low_yolo_confidence():
    assert not AlertPolicy().should_alert({**CAND, "mission_id": "old"}, MISSION, None)
    assert not AlertPolicy().should_alert({**CAND, "yolo_confidence": 0.1}, MISSION, None)


def test_policy_passes_fail_open_result():
    # Existing design: confidence "n/a" (VLM failure) is allowed through.
    assert AlertPolicy().should_alert(CAND, MISSION, {"confirmed": True, "confidence": "n/a"})

"""Regression tests: stale-track temporal evidence and per-target VLM dedup."""

import time

import cv2
import numpy as np

from conftest import wait_until
from perception.deduplicator import Deduplicator
from perception.yolo_detector import Detection


def car(bbox):
    return Detection(bbox=list(bbox), class_id=2, class_name="car", confidence=0.9)


# ---------------------------------------------------------------- B: multi-target dedup

def test_new_target_is_not_blocked_by_previous_target_cooldown():
    d = Deduplicator()
    a, b = [100, 100, 200, 160], [600, 400, 700, 460]
    assert d.should_verify_target("cam", 1, "blue", a, 100.0) == (True, "new_target")       # A first
    assert d.should_verify_target("cam", 1, "blue", a, 100.3) == (False, "same_target_cooldown")
    assert d.should_verify_target("cam", 2, "blue", b, 105.0) == (True, "new_target")       # B first
    assert d.should_verify_target("cam", 1, "blue", a, 110.0) == (False, "same_target_cooldown")  # A repeat
    assert d.should_verify_target("cam", 2, "blue", b, 106.0) == (False, "same_target_cooldown")  # B repeat
    assert d.should_verify_target("cam", 1, "blue", a, 130.5) == (True, "cooldown_expired")  # 30 s later


def test_cameras_do_not_share_targets():
    d = Deduplicator()
    box = [100, 100, 200, 160]
    assert d.should_verify_target("cam1", 1, "blue", box, 100.0)[0] is True
    assert d.should_verify_target("cam2", 1, "blue", box, 100.1)[0] is True


def test_legacy_key_cooldown_api_is_unchanged():
    d = Deduplicator()
    assert d.should_verify("uropclaw1", 100.0) is True
    assert d.should_verify("uropclaw1", 110.0) is False


# ---------------------------------------------------------------- C: fragmentation

def test_fragmented_track_of_same_target_is_suppressed():
    d = Deduplicator()
    assert d.should_verify_target("cam", 9, "blue", [300, 260, 420, 310], 50.0)[0] is True
    # Same vehicle re-tracked as 12, 0.5 s later, moved ~100 px (< box diagonal ~130 px).
    assert d.should_verify_target("cam", 12, "blue", [400, 262, 520, 312], 50.5) == (False, "fragment_continuity")
    # The fragment stays aliased to the target for the rest of the cooldown.
    assert d.should_verify_target("cam", 12, "blue", [480, 262, 600, 312], 52.0) == (False, "same_target_cooldown")


def test_fragment_rule_does_not_merge_far_other_colour_or_late_tracks():
    d = Deduplicator()
    assert d.should_verify_target("cam", 1, "blue", [300, 260, 420, 310], 50.0)[0] is True
    assert d.should_verify_target("cam", 2, "blue", [0, 500, 80, 560], 50.3)[0] is True      # far away
    assert d.should_verify_target("cam", 3, "red", [310, 260, 430, 310], 50.3)[0] is True    # other colour
    assert d.should_verify_target("cam", 4, "blue", [310, 260, 430, 310], 52.5)[0] is True   # > 2 s after last seen


def test_known_limitation_adjacent_same_colour_vehicles_within_window_are_merged():
    # Two different blue cars, nose to tail, the second confirmed 1 s later: indistinguishable
    # without re-identification, so the second is treated as a fragment of the first.
    d = Deduplicator()
    assert d.should_verify_target("cam", 1, "blue", [300, 260, 420, 310], 50.0)[0] is True
    assert d.should_verify_target("cam", 2, "blue", [180, 260, 300, 310], 51.0) == (False, "fragment_continuity")


# ---------------------------------------------------------------- A: stale tracks in the production pipeline

class ScriptedDetector:
    def __init__(self):
        self.by_id = {}

    def __call__(self, frame):
        return self.by_id[id(frame)]


def blue_frame(blue_box, other_box):
    frame = np.full((600, 800, 3), 128, dtype=np.uint8)
    if blue_box:
        x1, y1, x2, y2 = blue_box
        frame[y1:y2, x1:x2] = (200, 0, 0)
    x1, y1, x2, y2 = other_box
    frame[y1:y2, x1:x2] = (0, 0, 200)
    return frame


def feed(pipeline, detector, plan):
    frames = []
    for blue_box, other_box in plan:
        frame = blue_frame(blue_box, other_box)
        frames.append(frame)
        detector.by_id[id(frame)] = ([car(blue_box)] if blue_box else []) + [car(other_box)]
        pipeline.frame_queue.put({"camera_id": "cam", "agent_id": "uropclaw1", "frame": frame,
                                  "timestamp": time.time()})
        count = len(frames)
        assert wait_until(lambda: pipeline._metrics["frames_processed"] >= count)
        time.sleep(0.03)
    time.sleep(0.4)
    return frames


class CropCheckingVLM:
    """Fake VLM that records the mean colour of the crop it receives."""

    def __init__(self):
        self.calls = 0
        self.crop_blue_ratio = []

    def __call__(self, cmd, input=None, **kwargs):
        import json
        import subprocess
        self.calls += 1
        prompt = input.decode() if isinstance(input, bytes) else str(input)
        for line in prompt.splitlines():
            if line.startswith("Analyze the image at "):
                crop = cv2.imread(line[len("Analyze the image at "):].rstrip("."))
                blue = (crop[:, :, 0] > 150) & (crop[:, :, 2] < 80)
                self.crop_blue_ratio.append(float(blue.mean()))
        payload = {"visible_vehicle": True, "color": "blue", "color_match": True, "body_type": "car",
                   "body_type_match": True, "confidence": "high", "confirmed": True, "reason": "test"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload).encode(), stderr=b"")


def test_unmatched_track_never_gains_temporal_evidence(make_pipeline):
    detector, vlm = ScriptedDetector(), CropCheckingVLM()
    pipeline = make_pipeline(detector=detector, vlm=vlm)
    red = [600, 100, 700, 160]
    # Blue matched for 2 frames (below the 3-frame threshold), then gone for 6 frames while
    # the red car keeps the tracker updating (blue track exists but is unmatched).
    feed(pipeline, detector, [([100, 300, 200, 360], red)] * 2 + [(None, red)] * 6)
    m = pipeline.metrics_summary()
    assert m["candidates_raised"] == 0
    assert vlm.calls == 0
    confirmer = pipeline._threads[0]._get_confirmer("cam")
    # The blue track (id 0) keeps exactly its 2 matched observations; no stale votes.
    assert confirmer.pending[0].count == 2


def test_matched_track_still_confirms_and_crop_shows_current_vehicle(make_pipeline):
    detector, vlm = ScriptedDetector(), CropCheckingVLM()
    pipeline = make_pipeline(detector=detector, vlm=vlm)
    red = [600, 100, 700, 160]
    plan = [([100 + 8 * i, 300, 200 + 8 * i, 360], red) for i in range(3)] + [(None, red)] * 6
    feed(pipeline, detector, plan)
    m = pipeline.metrics_summary()
    assert m["candidates_raised"] == 1          # confirmed on the 3rd matched frame only
    assert vlm.calls == 1
    # Production pads 35% per side: a 100x60 car fills 6000/(170*102)=0.35 of the crop;
    # a stale crop of empty road would be ~0.
    assert vlm.crop_blue_ratio and vlm.crop_blue_ratio[0] > 0.25


def test_two_different_targets_within_30s_both_reach_vlm(make_pipeline):
    detector, vlm = ScriptedDetector(), CropCheckingVLM()
    pipeline = make_pipeline(detector=detector, vlm=vlm)
    red = [600, 100, 700, 160]
    a = [([50 + 8 * i, 300, 150 + 8 * i, 360], red) for i in range(6)]
    gap = [(None, red)] * 12
    b = [([500, 420 + 0 * i, 600, 480], red) for i in range(6)]
    feed(pipeline, detector, a + gap + b)
    m = pipeline.metrics_summary()
    assert vlm.calls == 2                      # A first + B first
    assert m["duplicate_suppressed"] >= 1      # A repeat confirmation suppressed
    assert all(ratio > 0.25 for ratio in vlm.crop_blue_ratio)

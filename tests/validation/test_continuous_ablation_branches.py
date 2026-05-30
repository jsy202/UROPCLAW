"""Shadow branches must reproduce the production candidate/VLM decisions."""

import importlib.util
import sys
import time
from pathlib import Path

import numpy as np

from conftest import wait_until
import core.pipeline as pipeline_mod
from perception.deduplicator import Deduplicator
from perception.iou_tracker import IoUTracker
from perception.temporal_confirm import TemporalConfirm
from perception.color_filter import classify_color
from perception.yolo_detector import Detection

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "validation" / "carla_e2e" / "continuous_ablation" / "branches.py"


def load_branches():
    spec = importlib.util.spec_from_file_location("continuous_branches", str(MODULE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_stream(frames=24):
    """Blue and red vehicles moving right; blue disappears for frames 10-13."""
    stream = []
    for index in range(frames):
        frame = np.full((600, 800, 3), 128, dtype=np.uint8)
        detections = []
        if not 10 <= index < 14:
            bx = 50 + index * 8
            frame[300:360, bx:bx + 100] = (200, 0, 0)  # BGR blue
            detections.append(Detection(bbox=[bx, 300, bx + 100, 360], class_id=2, class_name="car", confidence=0.9))
        rx = 400 + index * 6
        frame[100:160, rx:rx + 100] = (0, 0, 200)  # BGR red
        detections.append(Detection(bbox=[rx, 100, rx + 100, 160], class_id=2, class_name="car", confidence=0.9))
        stream.append((frame, detections))
    return stream


class CachedDetector:
    def __init__(self, stream):
        self.by_id = {id(frame): detections for frame, detections in stream}

    def __call__(self, frame):
        return self.by_id[id(frame)]


def test_full_shadow_branch_matches_production_pipeline(make_pipeline):
    stream = synthetic_stream()
    pipeline = make_pipeline(detector=CachedDetector(stream))
    timestamps = []
    for index, (frame, _) in enumerate(stream):
        timestamp = time.time()
        timestamps.append(timestamp)
        pipeline.frame_queue.put({"camera_id": "cam", "agent_id": "uropclaw1", "frame": frame,
                                  "timestamp": timestamp})
        assert wait_until(lambda: pipeline._metrics["frames_processed"] >= index + 1)
        time.sleep(0.03)
    assert wait_until(lambda: pipeline._candidate_queue.empty() and pipeline._result_queue.empty())
    time.sleep(0.3)
    production = pipeline.metrics_summary()

    branches = load_branches()
    full = branches.ShadowBranch("full", IoUTracker, TemporalConfirm, Deduplicator)
    for (frame, detections), timestamp in zip(stream, timestamps):
        full.process(detections, [classify_color(frame, d.bbox) for d in detections], timestamp)

    assert production["candidates_raised"] > 1
    assert full.counters["candidates_raised"] == production["candidates_raised"]
    assert full.counters["vlm_triggers"] == production["openclaw_calls"]
    assert full.counters["duplicate_suppressed"] == production["duplicate_suppressed"]


def test_ablation_flags_change_only_their_stage():
    branches = load_branches()
    stream = synthetic_stream()
    built = branches.make_branches(IoUTracker, TemporalConfirm, Deduplicator)
    for index, (frame, detections) in enumerate(stream):
        colors = [classify_color(frame, d.bbox) for d in detections]
        for branch in built:
            branch.process(detections, colors, 1000.0 + index * 0.1)
    counts = {branch.name: branch.counters for branch in built}
    # Dedup (30 s per agent) allows one trigger in 2.4 s for every dedup branch.
    assert counts["full"]["vlm_triggers"] == 1
    assert counts["no_hsv"]["vlm_triggers"] == 1
    assert counts["no_temporal"]["vlm_triggers"] == 1
    assert counts["no_dedup"]["vlm_triggers"] == counts["full"]["candidates_raised"]
    # Without HSV the red vehicle also becomes a candidate.
    assert counts["no_hsv"]["candidates_raised"] > counts["full"]["candidates_raised"]
    # Without temporal every observed blue frame becomes a candidate.
    assert counts["no_temporal"]["candidates_raised"] > counts["full"]["candidates_raised"]
    # Branch state is independent: separate tracker/temporal/dedup instances.
    assert len({id(b.tracker) for b in built}) == 4
    assert len({id(b.temporal) for b in built}) == 4
    assert len({id(b.dedup) for b in built}) == 4


def test_empty_detection_frames_do_not_update_tracker():
    branches = load_branches()
    branch = branches.ShadowBranch("full", IoUTracker, TemporalConfirm, Deduplicator)
    assert branch.process([], [], 1.0) == []
    assert branch.counters["frames_processed"] == 1
    assert branch.tracker._tracks == {}


def test_disappeared_track_candidates_are_counted_without_changing_decisions():
    branches = load_branches()
    stream = synthetic_stream()
    branch = branches.ShadowBranch("full", IoUTracker, TemporalConfirm, Deduplicator)
    stale = 0
    for index, (frame, detections) in enumerate(stream):
        events = branch.process(detections, [classify_color(frame, d.bbox) for d in detections], 1000.0 + index * 0.1)
        stale += sum(1 for event in events if event["track_disappeared"] > 0)
    # The blue vehicle is missing for frames 10-13; production keeps confirming its stale track.
    assert branch.counters["candidates_from_disappeared_tracks"] == stale
    assert stale > 0
    assert branch.counters["candidates_raised"] == 8

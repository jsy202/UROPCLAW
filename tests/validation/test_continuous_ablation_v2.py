"""v2 shadow branches must reproduce the FIXED production candidate/VLM decisions."""

import importlib.util
import time
from pathlib import Path

import numpy as np

from conftest import wait_until
from perception.color_filter import classify_color
from perception.deduplicator import Deduplicator
from perception.iou_tracker import IoUTracker
from perception.temporal_confirm import TemporalConfirm
from perception.yolo_detector import Detection

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "validation" / "carla_e2e" / "continuous_ablation_v2" / "branches.py"


def load_branches():
    spec = importlib.util.spec_from_file_location("continuous_branches_v2", str(MODULE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def car(bbox):
    return Detection(bbox=list(bbox), class_id=2, class_name="car", confidence=0.9)


def stream():
    """Blue A (gap at frames 8-11), a red car throughout, then a far-away blue B."""
    frames = []
    for index in range(30):
        frame = np.full((600, 800, 3), 128, dtype=np.uint8)
        detections = []
        if index < 16 and not 8 <= index < 12:
            x = 40 + index * 8
            frame[300:360, x:x + 100] = (200, 0, 0)
            detections.append(car([x, 300, x + 100, 360]))
        if index >= 18:
            frame[450:510, 600:700] = (200, 0, 0)
            detections.append(car([600, 450, 700, 510]))
        rx = 400 + index * 5
        frame[100:160, rx:rx + 100] = (0, 0, 200)
        detections.append(car([rx, 100, rx + 100, 160]))
        frames.append((frame, detections))
    return frames


class CachedDetector:
    def __init__(self, frames):
        self.by_id = {id(frame): detections for frame, detections in frames}

    def __call__(self, frame):
        return self.by_id[id(frame)]


def test_full_v2_branch_matches_fixed_production_pipeline(make_pipeline):
    frames = stream()
    pipeline = make_pipeline(detector=CachedDetector(frames))
    timestamps = []
    for index, (frame, _) in enumerate(frames):
        timestamp = time.time()
        timestamps.append(timestamp)
        pipeline.frame_queue.put({"camera_id": "cam", "agent_id": "uropclaw1", "frame": frame,
                                  "timestamp": timestamp})
        assert wait_until(lambda: pipeline._metrics["frames_processed"] >= index + 1)
        time.sleep(0.03)
    time.sleep(0.4)
    production = pipeline.metrics_summary()

    branches = load_branches()
    full = branches.ShadowBranch("full", IoUTracker, TemporalConfirm, Deduplicator)
    for (frame, detections), timestamp in zip(frames, timestamps):
        full.process(detections, [classify_color(frame, d.bbox) for d in detections], timestamp)

    assert production["openclaw_calls"] == 2          # A and B, B not blocked by A's cooldown
    assert full.counters["candidates_raised"] == production["candidates_raised"]
    assert full.counters["vlm_triggers"] == production["openclaw_calls"]
    assert full.counters["duplicate_suppressed"] == production["duplicate_suppressed"]
    assert full.counters["candidates_from_disappeared_tracks"] == 0


def test_v2_branches_are_independent_and_stale_free():
    branches = load_branches()
    built = branches.make_branches(IoUTracker, TemporalConfirm, Deduplicator)
    for index, (frame, detections) in enumerate(stream()):
        colors = [classify_color(frame, d.bbox) for d in detections]
        for branch in built:
            branch.process(detections, colors, 1000.0 + index * 0.1)
    counts = {b.name: b.counters for b in built}
    assert len({id(b.tracker) for b in built}) == 4 and len({id(b.dedup) for b in built}) == 4
    assert all(c["candidates_from_disappeared_tracks"] == 0 for c in counts.values())
    assert counts["full"]["vlm_triggers"] == 2
    assert counts["no_dedup"]["vlm_triggers"] == counts["full"]["candidates_raised"]
    assert counts["no_hsv"]["candidates_raised"] > counts["full"]["candidates_raised"]
    assert counts["no_temporal"]["candidates_raised"] > counts["full"]["candidates_raised"]

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "validation" / "carla_e2e" / "multivehicle" / "instrumentation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("multivehicle_instrumentation", str(MODULE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Detection:
    def __init__(self, bbox, class_id=2, class_name="car", confidence=0.9):
        self.bbox = bbox
        self.class_id = class_id
        self.class_name = class_name
        self.confidence = confidence


class Track:
    def __init__(self, track_id, bbox, color, disappeared=0):
        self.track_id = track_id
        self.bbox = bbox
        self.color_history = [color]
        self.disappeared = disappeared


def test_frame_counters_are_target_colour_specific_and_object_counts_stay_separate():
    module = load_module()
    observation = module.Observation(target_color="blue")
    frame = object()
    observation.accept_frame(frame, frame_id=17, timestamp=1.0, ground_truth={"probe_bbox": [0, 0, 20, 20]})

    observation.record_detections(frame, [Detection([0, 0, 20, 20]), Detection([30, 0, 50, 20])])
    observation.record_classification(frame, [0, 0, 20, 20], "blue")
    observation.record_classification(frame, [30, 0, 50, 20], "red")
    observation.record_tracks(frame, {2: Track(2, [0, 0, 20, 20], "blue")})
    observation.record_confirmation(1.0, {"track_id": 2, "color": "blue"})
    observation.record_vlm_image(frame_id=17)

    metrics = observation.metrics()
    assert metrics["input_frames"] == 1
    assert metrics["frames_with_yolo_detection"] == 1
    assert metrics["frames_passing_hsv"] == 1
    assert metrics["frames_with_active_track"] == 1
    assert metrics["frames_triggering_confirmation"] == 1
    assert metrics["images_sent_to_vlm"] == 1
    assert metrics["yolo_detections"] == 2
    assert metrics["unique_tracks"] == 1
    assert metrics["confirmed_tracks"] == 1
    assert observation.probe_yolo_detected is True
    assert observation.probe_hsv_passed is True


def test_non_target_colour_does_not_count_hsv_tracking_or_confirmation_frames():
    module = load_module()
    observation = module.Observation(target_color="blue")
    frame = object()
    observation.accept_frame(frame, 1, 1.0, {})
    observation.record_detections(frame, [Detection([0, 0, 20, 20])])
    observation.record_classification(frame, [0, 0, 20, 20], "red")
    observation.record_tracks(frame, {1: Track(1, [0, 0, 20, 20], "red")})
    observation.record_confirmation(1.0, {"track_id": 1, "color": "red"})

    metrics = observation.metrics()
    assert metrics["frames_with_yolo_detection"] == 1
    assert metrics["frames_passing_hsv"] == 0
    assert metrics["frames_with_active_track"] == 0
    assert metrics["frames_triggering_confirmation"] == 0
    assert metrics["confirmed_tracks"] == 1


def test_production_wrappers_return_unmodified_detector_tracker_and_temporal_results():
    module = load_module()
    observation = module.Observation("blue")
    frame = object()
    observation.accept_frame(frame, 1, 1.0, {})
    detections = [Detection([1, 2, 3, 4])]

    def detector(input_frame):
        assert input_frame is frame
        return detections

    wrapped_detector = module.InstrumentedDetector(detector, observation)
    assert wrapped_detector(frame) is detections

    class BaseTracker:
        def update(self, input_detections, colors=None):
            assert input_detections is detections
            return {7: Track(7, [1, 2, 3, 4], "blue")}

    class BaseTemporal:
        def update(self, track_id, color, timestamp):
            return {"track_id": track_id, "color": color}

    CountingTracker, CountingTemporal, classifier = module.make_production_wrappers(
        BaseTracker, BaseTemporal, lambda input_frame, bbox: "blue", observation
    )
    tracks = CountingTracker().update(detections, ["blue"])
    result = CountingTemporal().update(7, "blue", 1.0)
    assert tracks[7].bbox == [1, 2, 3, 4]
    assert result == {"track_id": 7, "color": "blue"}
    assert classifier(frame, [1, 2, 3, 4]) == "blue"


def passing_result():
    return {
        "actual_controlled_vehicle_count": 16,
        "background_movement": {"most_background_moving": True, "moving_count": 12},
        "max_yolo_vehicle_boxes_per_frame": 3,
        "probe_fov_enter_frame": 5,
        "probe_fov_exit_frame": 70,
        "probe_yolo_detected": True,
        "probe_hsv_passed": True,
        "target_track_created": True,
        "target_temporal_confirmed": True,
        "fake_vlm_requests": 1,
        "images_sent_to_vlm": 1,
        "cleanup": {"attempted": 17, "destroyed": 17, "failed_actor_ids": []},
        "input_frames": 100,
    }


def test_smoke_gate_requires_every_observed_condition():
    module = load_module()
    evaluation = module.evaluate_smoke_gate(passing_result())
    assert evaluation["status"] == "PASS"
    assert evaluation["failed_gates"] == []

    for key in (
        "actual_controlled_vehicle_count", "background_movement",
        "max_yolo_vehicle_boxes_per_frame", "probe_fov_enter_frame",
        "probe_fov_exit_frame", "probe_yolo_detected", "probe_hsv_passed",
        "target_track_created", "target_temporal_confirmed",
        "fake_vlm_requests", "images_sent_to_vlm", "cleanup", "input_frames",
    ):
        value = passing_result()
        if key == "actual_controlled_vehicle_count":
            value[key] = 15
        elif key == "background_movement":
            value[key]["most_background_moving"] = False
        elif key == "max_yolo_vehicle_boxes_per_frame":
            value[key] = 1
        elif key in ("probe_fov_enter_frame", "probe_fov_exit_frame"):
            value[key] = None
        elif key in ("fake_vlm_requests", "images_sent_to_vlm"):
            value[key] = 0
        elif key == "cleanup":
            value[key]["destroyed"] = 16
        elif key == "input_frames":
            value[key] = 99
        else:
            value[key] = False
        failed = module.evaluate_smoke_gate(value)
        assert failed["status"] == "FAIL", key
        assert failed["failed_gates"], key


def test_frame_retention_uses_only_frame_image_denominators():
    module = load_module()
    result = module.frame_retention({
        "input_frames": 100,
        "frames_with_yolo_detection": 80,
        "frames_passing_hsv": 40,
        "frames_with_active_track": 30,
        "frames_triggering_confirmation": 10,
        "images_sent_to_vlm": 2,
    })
    assert result == {
        "yolo_positive_over_input": 0.8,
        "hsv_pass_over_yolo_positive": 0.5,
        "tracking_over_hsv_pass": 0.75,
        "confirmation_over_tracking": pytest.approx(1 / 3),
        "vlm_images_over_input": 0.02,
    }

"""Validation-only observers around unchanged production perception classes."""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict


def bbox_iou(left, right):
    if left is None or right is None:
        return 0.0
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    left_area = max(0, left[2] - left[0]) * max(0, left[3] - left[1])
    right_area = max(0, right[2] - right[0]) * max(0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / float(union) if union else 0.0


class Observation:
    def __init__(self, target_color="blue"):
        self.target_color = target_color
        self.frame_meta = {}
        self.timestamp_to_frame = {}
        self.current_frame = None
        self.yolo_frames = set()
        self.hsv_frames = set()
        self.tracking_frames = set()
        self.confirmation_frames = set()
        self.vlm_image_frames = []
        self.detection_count = 0
        self.unique_track_ids = set()
        self.confirmed_track_ids = set()
        self.track_lifetime_frames = defaultdict(int)
        self.actor_to_tracks = defaultdict(set)
        self.track_to_actors = defaultdict(set)
        self.detections_per_frame = {}
        self.visible_vehicles_per_frame = {}
        self.probe_bbox_by_frame = {}
        self.probe_state_by_frame = {}
        self.probe_fov_enter_frame = None
        self.probe_fov_exit_frame = None
        self._probe_was_visible = False
        self.probe_yolo_detected = False
        self.first_probe_detection = None
        self.probe_hsv_passed = False
        self.target_track_created = False
        self.target_temporal_confirmed = False
        # Probe-associated evidence: a target-colour result counts for the
        # probe only if the track overlapped the probe's ground-truth bbox.
        self.probe_track_ids = set()
        self.probe_track_created = False
        self.probe_temporal_confirmed = False
        self.non_probe_target_confirmed_track_ids = set()
        # E2E: frame input-queue insertion -> final target-colour rejection or
        # AlertPolicy allow (same boundary as the single-vehicle validation).
        self.accepted_monotonic = {}
        self.latency_keys = set()
        self.latency_rows = []
        self.confirmed_colors = {}
        self._previous_track_ids = set()
        self.removed_track_ids = set()
        self.lock = threading.RLock()

    def accept_frame(self, frame, frame_id, timestamp, ground_truth):
        key = id(frame)
        with self.lock:
            # Keep a strong reference: frames are keyed by id(), and CPython
            # reuses the address of a released array for the next frame.
            self.frame_meta[key] = {
                "frame_id": int(frame_id), "timestamp": float(timestamp),
                "ground_truth": ground_truth or {}, "frame_ref": frame,
            }
            self.probe_bbox_by_frame[int(frame_id)] = (ground_truth or {}).get("probe_bbox")
            self.probe_state_by_frame[int(frame_id)] = {
                key: (ground_truth or {}).get(key)
                for key in ("probe_location", "probe_speed_mps", "probe_route_deviation_m")
            }
            self.timestamp_to_frame[float(timestamp)] = key
            visible_count = len((ground_truth or {}).get("actor_boxes", {}))
            self.visible_vehicles_per_frame[int(frame_id)] = visible_count
            probe_visible = (ground_truth or {}).get("probe_bbox") is not None
            if probe_visible and not self._probe_was_visible and self.probe_fov_enter_frame is None:
                self.probe_fov_enter_frame = int(frame_id)
            if not probe_visible and self._probe_was_visible and self.probe_fov_enter_frame is not None:
                self.probe_fov_exit_frame = int(frame_id)
            self._probe_was_visible = probe_visible

    def register_acceptance(self, wall_timestamp, monotonic_timestamp):
        with self.lock:
            self.accepted_monotonic[float(wall_timestamp)] = monotonic_timestamp

    def terminal(self, timestamp, terminal, track_id):
        decision_monotonic = time.perf_counter()
        key = (terminal, int(track_id), float(timestamp))
        with self.lock:
            if key in self.latency_keys:
                return
            self.latency_keys.add(key)
            accepted = self.accepted_monotonic.get(float(timestamp))
            if accepted is None:
                return
            self.latency_rows.append({
                "sample_index": len(self.latency_rows),
                "source_frame_id": self._frame_id(self.timestamp_to_frame.get(float(timestamp))),
                "accepted_monotonic": accepted,
                "decision_monotonic": decision_monotonic,
                "terminal": terminal,
                "track_id": int(track_id),
                "latency_ms": round(max(0.0, (decision_monotonic - accepted) * 1000.0), 3),
            })

    def _key(self, frame=None, timestamp=None):
        if frame is not None:
            return id(frame)
        if timestamp is not None:
            return self.timestamp_to_frame.get(float(timestamp))
        return id(self.current_frame) if self.current_frame is not None else None

    def _frame_id(self, key):
        meta = self.frame_meta.get(key)
        return meta.get("frame_id") if meta else None

    def record_detections(self, frame, detections):
        key = self._key(frame=frame)
        with self.lock:
            self.current_frame = frame
            count = len(detections)
            self.detection_count += count
            frame_id = self._frame_id(key)
            if frame_id is not None:
                self.detections_per_frame[frame_id] = count
                if count:
                    self.yolo_frames.add(frame_id)
            probe_bbox = self.frame_meta.get(key, {}).get("ground_truth", {}).get("probe_bbox")
            if probe_bbox and any(bbox_iou(det.bbox, probe_bbox) >= 0.10 for det in detections):
                if not self.probe_yolo_detected:
                    self.first_probe_detection = {
                        "frame_id": frame_id, "frame": frame, "probe_bbox": list(probe_bbox),
                        "detections": [list(det.bbox) for det in detections],
                    }
                self.probe_yolo_detected = True

    def record_classification(self, frame, bbox, color):
        key = self._key(frame=frame)
        with self.lock:
            self.current_frame = frame
            frame_id = self._frame_id(key)
            if color == self.target_color and frame_id is not None:
                self.hsv_frames.add(frame_id)
                probe_bbox = self.frame_meta.get(key, {}).get("ground_truth", {}).get("probe_bbox")
                if probe_bbox and bbox_iou(bbox, probe_bbox) >= 0.10:
                    self.probe_hsv_passed = True

    def record_tracks(self, frame, tracks):
        key = self._key(frame=frame)
        with self.lock:
            frame_id = self._frame_id(key)
            actor_boxes = self.frame_meta.get(key, {}).get("ground_truth", {}).get("actor_boxes", {})
            probe_bbox = self.frame_meta.get(key, {}).get("ground_truth", {}).get("probe_bbox")
            current_ids = {int(track_id) for track_id in tracks}
            self.removed_track_ids.update(self._previous_track_ids - current_ids)
            self._previous_track_ids = current_ids
            for track_id, track in tracks.items():
                scoped_id = int(track_id)
                self.unique_track_ids.add(scoped_id)
                if getattr(track, "disappeared", 1) != 0:
                    continue
                self.track_lifetime_frames[scoped_id] += 1
                color_history = getattr(track, "color_history", [])
                color = color_history[-1] if color_history else "unknown"
                if color == self.target_color and frame_id is not None:
                    self.tracking_frames.add(frame_id)
                    self.target_track_created = True
                if probe_bbox and bbox_iou(getattr(track, "bbox", None), probe_bbox) >= 0.30:
                    self.probe_track_ids.add(scoped_id)
                    if color == self.target_color:
                        self.probe_track_created = True
                for actor_id, actor_bbox in actor_boxes.items():
                    if bbox_iou(getattr(track, "bbox", None), actor_bbox) >= 0.30:
                        self.actor_to_tracks[str(actor_id)].add(scoped_id)
                        self.track_to_actors[scoped_id].add(str(actor_id))

    def record_confirmation(self, timestamp, result):
        if result is None:
            return
        key = self._key(timestamp=timestamp)
        with self.lock:
            track_id = int(result["track_id"])
            first_confirmation = track_id not in self.confirmed_track_ids
            self.confirmed_track_ids.add(track_id)
            self.confirmed_colors[track_id] = result.get("color")
            if first_confirmation and result.get("color") != self.target_color:
                self.terminal(timestamp, "target_color_reject", track_id)
            if result.get("color") == self.target_color:
                frame_id = self._frame_id(key)
                if frame_id is not None:
                    self.confirmation_frames.add(frame_id)
                self.target_temporal_confirmed = True
                if track_id in self.probe_track_ids:
                    self.probe_temporal_confirmed = True
                else:
                    self.non_probe_target_confirmed_track_ids.add(track_id)

    def record_vlm_image(self, frame_id=None):
        with self.lock:
            self.vlm_image_frames.append(frame_id)

    def tracking_diagnostics(self):
        return {
            "track_lifetime_frames": {str(key): value for key, value in sorted(self.track_lifetime_frames.items())},
            "fragmented_actor_count": sum(len(values) > 1 for values in self.actor_to_tracks.values()),
            "possible_merged_track_count": sum(len(values) > 1 for values in self.track_to_actors.values()),
            "actor_to_track_ids": {key: sorted(values) for key, values in sorted(self.actor_to_tracks.items())},
            "track_to_actor_ids": {str(key): sorted(values) for key, values in sorted(self.track_to_actors.items())},
        }

    def metrics(self):
        return {
            "input_frames": len(self.frame_meta),
            "frames_with_yolo_detection": len(self.yolo_frames),
            "frames_passing_hsv": len(self.hsv_frames),
            "frames_with_active_track": len(self.tracking_frames),
            "frames_triggering_confirmation": len(self.confirmation_frames),
            "images_sent_to_vlm": len(self.vlm_image_frames),
            "yolo_detections": self.detection_count,
            "unique_tracks": len(self.unique_track_ids),
            "confirmed_tracks": len(self.confirmed_track_ids),
        }


class InstrumentedDetector:
    def __init__(self, detector, observation):
        self.detector = detector
        self.observation = observation

    def __call__(self, frame):
        detections = self.detector(frame)
        self.observation.record_detections(frame, detections)
        return detections


def make_production_wrappers(base_tracker, base_temporal, classifier, observation):
    class InstrumentedTracker(base_tracker):
        def update(self, detections, colors=None):
            tracks = super().update(detections, colors)
            observation.record_tracks(observation.current_frame, tracks)
            return tracks

    class InstrumentedTemporal(base_temporal):
        def update(self, track_id, color, timestamp):
            result = super().update(track_id, color, timestamp)
            observation.record_confirmation(timestamp, result)
            return result

    def instrumented_classifier(frame, bbox):
        color = classifier(frame, bbox)
        observation.record_classification(frame, bbox, color)
        return color

    return InstrumentedTracker, InstrumentedTemporal, instrumented_classifier


def _ratio(numerator, denominator):
    return numerator / float(denominator) if denominator else None


def frame_retention(metrics):
    return {
        "yolo_positive_over_input": _ratio(metrics["frames_with_yolo_detection"], metrics["input_frames"]),
        "hsv_pass_over_yolo_positive": _ratio(metrics["frames_passing_hsv"], metrics["frames_with_yolo_detection"]),
        "tracking_over_hsv_pass": _ratio(metrics["frames_with_active_track"], metrics["frames_passing_hsv"]),
        "confirmation_over_tracking": _ratio(metrics["frames_triggering_confirmation"], metrics["frames_with_active_track"]),
        "vlm_images_over_input": _ratio(metrics["images_sent_to_vlm"], metrics["input_frames"]),
    }


def evaluate_smoke_gate(result, scenario="target"):
    enter = result.get("probe_fov_enter_frame")
    exit_frame = result.get("probe_fov_exit_frame")
    if scenario == "non_target":
        return _evaluate_non_target_gate(result, enter, exit_frame)
    gates = {
        "controlled_actors_16": result.get("actual_controlled_vehicle_count") == 16,
        "most_background_actors_moved": bool(result.get("background_movement", {}).get("most_background_moving")),
        "two_yolo_vehicle_boxes_in_one_frame": result.get("max_yolo_vehicle_boxes_per_frame", 0) >= 2,
        "probe_fov_entry": enter is not None and 0 < enter < 100,
        "probe_fov_exit": exit_frame is not None and enter is not None and enter < exit_frame < 100,
        "probe_followed_planned_corridor": (
            result.get("probe_route_max_deviation_m") is not None
            and result.get("probe_route_max_deviation_m") <= 3.5
        ),
        "probe_yolo_detection": bool(result.get("probe_yolo_detected")),
        "probe_blue_hsv_pass": bool(result.get("probe_hsv_passed")),
        "probe_target_track_created": bool(result.get("probe_track_created")),
        "probe_temporal_confirmation": bool(result.get("probe_temporal_confirmed")),
        "fake_vlm_request": result.get("fake_vlm_requests", 0) > 0,
        "vlm_image_supplied": result.get("images_sent_to_vlm", 0) > 0,
        "exactly_100_input_frames": result.get("input_frames") == 100,
        "owned_actor_cleanup": (
            result.get("cleanup", {}).get("attempted", 0) >= 17
            and result.get("cleanup", {}).get("destroyed") == result.get("cleanup", {}).get("attempted")
            and not result.get("cleanup", {}).get("failed_actor_ids")
        ),
    }
    failed = [name for name, passed in gates.items() if not passed]
    return {"status": "PASS" if not failed else "FAIL", "gates": gates, "failed_gates": failed}


def _common_gates(result, enter, exit_frame):
    cleanup = result.get("cleanup", {})
    return {
        "controlled_actors_16": result.get("actual_controlled_vehicle_count") == 16,
        "most_background_actors_moved": bool(result.get("background_movement", {}).get("most_background_moving")),
        "two_yolo_vehicle_boxes_in_one_frame": result.get("max_yolo_vehicle_boxes_per_frame", 0) >= 2,
        "probe_fov_entry": enter is not None and 0 < enter < 100,
        "probe_fov_exit": exit_frame is not None and enter is not None and enter < exit_frame < 100,
        "probe_followed_planned_corridor": (
            result.get("probe_route_max_deviation_m") is not None
            and result.get("probe_route_max_deviation_m") <= 3.5
        ),
        "probe_yolo_detection": bool(result.get("probe_yolo_detected")),
        "exactly_100_input_frames": result.get("input_frames") == 100,
        "owned_actor_cleanup": (
            cleanup.get("attempted", 0) >= 17
            and cleanup.get("destroyed") == cleanup.get("attempted")
            and not cleanup.get("failed_actor_ids")
        ),
    }


def _evaluate_non_target_gate(result, enter, exit_frame):
    """Non-target: the red probe is observed by the pipeline and never becomes a target."""
    gates = _common_gates(result, enter, exit_frame)
    gates.update({
        "probe_tracked": bool(result.get("probe_track_ids")),
        "no_probe_target_confirmation": not result.get("probe_temporal_confirmed"),
        "no_fake_vlm_request": result.get("fake_vlm_requests", 0) == 0,
        "no_false_target_event": result.get("target_events", result.get("fake_alert_events", 0)) == 0,
    })
    failed = [name for name, passed in gates.items() if not passed]
    return {"status": "PASS" if not failed else "FAIL", "gates": gates, "failed_gates": failed}


def project_actor_bbox(actor, camera_transform, width, height, fov, numpy_module):
    """Project CARLA bounding-box vertices for evidence only."""
    vertices = actor.bounding_box.get_world_vertices(actor.get_transform())
    inverse = numpy_module.asarray(camera_transform.get_inverse_matrix(), dtype=float)
    focal = width / (2.0 * math.tan(math.radians(fov) / 2.0))
    points = []
    for vertex in vertices:
        world = numpy_module.asarray([vertex.x, vertex.y, vertex.z, 1.0], dtype=float)
        sensor = inverse.dot(world)
        depth, right, down = sensor[0], sensor[1], -sensor[2]
        if depth <= 0.1:
            continue
        u = focal * right / depth + width / 2.0
        v = focal * down / depth + height / 2.0
        points.append((u, v))
    if not points:
        return None
    x1, y1 = min(item[0] for item in points), min(item[1] for item in points)
    x2, y2 = max(item[0] for item in points), max(item[1] for item in points)
    if x2 < 0 or y2 < 0 or x1 >= width or y1 >= height:
        return None
    clipped = [max(0, int(x1)), max(0, int(y1)), min(width - 1, int(x2)), min(height - 1, int(y2))]
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        return None
    return clipped

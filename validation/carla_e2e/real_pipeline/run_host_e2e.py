#!/usr/bin/env python3
"""Host-only Real CARLA/YOLO pipeline validation runner.

This runner imports and executes the production Pipeline, HSV classifier,
IoUTracker, TemporalConfirm, VLM parser, and AlertPolicy.  Instrumentation and
deterministic dependencies live here so production behaviour is not forked.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import queue
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
CARLA_E2E_DIR = HERE.parent
REPOSITORY_ROOT = CARLA_E2E_DIR.parents[1]
HARNESS_DIR = REPOSITORY_ROOT / "harness"
DEFAULT_WEIGHT = CARLA_E2E_DIR / "weights" / "yolov8s.pt"
EXPECTED_CARLA_VERSION = "0.9.13"
TARGET_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
RAW_FIELDS = [
    "run_id", "scenario", "repetition", "fault", "status", "input_frames",
    "camera_frames", "yolo_detections", "hsv_target_passes", "unique_tracks",
    "confirmed_tracks", "vlm_requests", "target_events", "false_target_events",
    "scenario_success", "e2e_sample_count", "e2e_mean_ms", "e2e_p50_ms",
    "e2e_p95_ms", "e2e_p99_ms", "e2e_max_ms", "at_or_below_1000",
    "over_1000", "compliance_rate", "max_queue_depth", "max_frame_queue",
    "max_candidate_queue", "max_result_queue", "ending_queue_depth",
    "dropped_frames", "dropped_events", "backlog_accumulation", "pipeline_alive",
    "pipeline_crash", "fault_injected", "fault_detected", "recovered",
    "next_normal_request_success", "duplicate_suppressed", "error",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latency_summary(samples, numpy_module):
    """Summarize event E2E samples without treating an empty set as zero."""
    if not samples:
        return {
            "sample_count": 0, "mean_ms": None, "p50_ms": None,
            "p95_ms": None, "p99_ms": None, "max_ms": None,
            "at_or_below_1000": 0, "over_1000": 0,
            "compliance_rate": None,
        }
    values = numpy_module.asarray(samples, dtype=float)
    below = int((values <= 1000.0).sum())
    return {
        "sample_count": int(values.size),
        "mean_ms": round(float(values.mean()), 3),
        "p50_ms": round(float(numpy_module.percentile(values, 50)), 3),
        "p95_ms": round(float(numpy_module.percentile(values, 95)), 3),
        "p99_ms": round(float(numpy_module.percentile(values, 99)), 3),
        "max_ms": round(float(values.max()), 3),
        "at_or_below_1000": below,
        "over_1000": int(values.size) - below,
        "compliance_rate": round(below / float(values.size), 6),
    }


def scenario_success(scenario, target_events, vlm_requests, yolo_detections, pipeline_alive):
    if scenario == "target":
        return bool(pipeline_alive and yolo_detections > 0 and vlm_requests > 0 and target_events > 0)
    if scenario == "non_target":
        return bool(pipeline_alive and yolo_detections > 0 and vlm_requests == 0 and target_events == 0)
    return False


def _success_payload():
    return json.dumps({
        "visible_vehicle": True, "color": "blue", "color_match": True,
        "body_type": "car", "body_type_match": True,
        "confidence": "high", "confirmed": True,
        "reason": "deterministic validation response",
    }).encode("utf-8")


class DeterministicVLM:
    def __init__(self):
        self.calls = 0
        self.normal_successes = 0

    def __call__(self, command, **kwargs):
        self.calls += 1
        self.normal_successes += 1
        return subprocess.CompletedProcess(command, 0, stdout=_success_payload(), stderr=b"")


class FaultThenSuccessVLM:
    """Inject exactly one fault, then return the deterministic normal response."""

    def __init__(self, fault, delay_seconds=1.2):
        if fault not in ("delay", "timeout", "error", "malformed"):
            raise ValueError("unsupported fault: {0}".format(fault))
        self.fault = fault
        self.delay_seconds = delay_seconds
        self.calls = 0
        self.injected = 0
        self.normal_successes = 0

    def __call__(self, command, **kwargs):
        self.calls += 1
        if self.injected == 0:
            self.injected = 1
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            if self.fault == "timeout":
                raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 25))
            if self.fault == "error":
                raise RuntimeError("injected VLM error")
            if self.fault == "malformed":
                return subprocess.CompletedProcess(command, 0, stdout=b"malformed response", stderr=b"")
            return subprocess.CompletedProcess(command, 0, stdout=_success_payload(), stderr=b"")
        self.normal_successes += 1
        return subprocess.CompletedProcess(command, 0, stdout=_success_payload(), stderr=b"")


class Observation:
    def __init__(self, target_color):
        self.target_color = target_color
        self.unique_tracks = set()
        self.confirmed_tracks = set()
        self.hsv_target_passes = 0
        self.latency_samples = []
        self.latency_keys = set()
        self.latency_rows = []
        self.alert_events = []
        self.accepted_monotonic = {}
        self.lock = threading.Lock()

    def register_acceptance(self, wall_timestamp, monotonic_timestamp):
        with self.lock:
            self.accepted_monotonic[wall_timestamp] = monotonic_timestamp

    def discard_acceptance(self, wall_timestamp):
        with self.lock:
            self.accepted_monotonic.pop(wall_timestamp, None)

    def terminal(self, timestamp, terminal, track_id):
        key = (terminal, track_id, timestamp)
        with self.lock:
            if key in self.latency_keys:
                return
            self.latency_keys.add(key)
            accepted_monotonic = self.accepted_monotonic.get(timestamp)
            if accepted_monotonic is None:
                return
            decision_monotonic = time.perf_counter()
            decision_wall = time.time()
            elapsed = max(0.0, (decision_monotonic - accepted_monotonic) * 1000.0)
            self.latency_samples.append(elapsed)
            self.latency_rows.append({
                "sample_index": len(self.latency_samples) - 1,
                "source_frame_timestamp": timestamp,
                "accepted_monotonic": accepted_monotonic,
                "decision_timestamp": decision_wall,
                "decision_monotonic": decision_monotonic,
                "boundary": "frame_accepted_to_final_decision",
                "terminal": terminal,
                "track_id": track_id,
                "latency_ms": round(elapsed, 3),
            })


class RealYoloAdapter:
    def __init__(self, model, torch_module, detection_type):
        self.model = model
        self.torch = torch_module
        self.detection_type = detection_type
        self.detection_count = 0
        self.latencies_ms = []

    def __call__(self, frame_bgr):
        self.torch.cuda.synchronize()
        started = time.perf_counter()
        results = self.model(frame_bgr, conf=0.40, iou=0.45, device=0, verbose=False)
        self.torch.cuda.synchronize()
        self.latencies_ms.append((time.perf_counter() - started) * 1000.0)
        converted = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                class_id = int(box.cls[0])
                if class_id not in TARGET_CLASSES:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                converted.append(self.detection_type(
                    bbox=[int(x1), int(y1), int(x2), int(y2)],
                    class_id=class_id,
                    class_name=TARGET_CLASSES[class_id],
                    confidence=float(box.conf[0]),
                ))
        self.detection_count += len(converted)
        return converted


class FakeAlert:
    def __init__(self, observation):
        self.observation = observation

    def __call__(self, agent_id, event):
        self.observation.alert_events.append(event)
        self.observation.terminal(event["timestamp"], "alert_policy_allow", event["track_id"])
        return True


def _transform_dict(transform):
    return {
        "location": {"x": float(transform.location.x), "y": float(transform.location.y), "z": float(transform.location.z)},
        "rotation": {"pitch": float(transform.rotation.pitch), "yaw": float(transform.rotation.yaw), "roll": float(transform.rotation.roll)},
    }


def _spawn_scene(carla_module, world, color):
    library = world.get_blueprint_library()
    vehicle_bp = library.find("vehicle.tesla.model3")
    if vehicle_bp.has_attribute("role_name"):
        vehicle_bp.set_attribute("role_name", "uropclaw_validation_{0}".format(color))
    rgb = "0,0,255" if color == "blue" else "255,0,0"
    if vehicle_bp.has_attribute("color"):
        vehicle_bp.set_attribute("color", rgb)
    vehicle = None
    vehicle_transform = None
    for candidate in world.get_map().get_spawn_points():
        vehicle = world.try_spawn_actor(vehicle_bp, candidate)
        if vehicle is not None:
            vehicle_transform = candidate
            break
    if vehicle is None:
        raise RuntimeError("No free CARLA spawn point")
    vehicle.set_simulate_physics(False)
    forward = vehicle_transform.get_forward_vector()
    camera_transform = carla_module.Transform(
        carla_module.Location(
            x=vehicle_transform.location.x + forward.x * 8.0,
            y=vehicle_transform.location.y + forward.y * 8.0,
            z=vehicle_transform.location.z + 1.8,
        ),
        carla_module.Rotation(pitch=-7.0, yaw=vehicle_transform.rotation.yaw + 180.0),
    )
    camera_bp = library.find("sensor.camera.rgb")
    camera_bp.set_attribute("image_size_x", "800")
    camera_bp.set_attribute("image_size_y", "600")
    camera_bp.set_attribute("fov", "90")
    camera_bp.set_attribute("sensor_tick", "0.1")
    camera = world.spawn_actor(camera_bp, camera_transform)
    return vehicle, camera, vehicle_transform, camera_transform


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_csv(path, fieldnames, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _make_counting_classes(pipeline_module, observation):
    base_tracker = pipeline_module.IoUTracker
    base_temporal = pipeline_module.TemporalConfirm
    original_classifier = pipeline_module.classify_color

    class CountingTracker(base_tracker):
        def update(self, detections, colors=None):
            tracks = super().update(detections, colors)
            with observation.lock:
                observation.unique_tracks.update((id(self), tid) for tid in tracks)
            return tracks

    class CountingTemporal(base_temporal):
        def update(self, track_id, color, timestamp):
            result = super().update(track_id, color, timestamp)
            if result is not None:
                key = (id(self), result["track_id"])
                with observation.lock:
                    is_first = key not in observation.confirmed_tracks
                    observation.confirmed_tracks.add(key)
                if is_first and result["color"] != observation.target_color:
                    observation.terminal(timestamp, "target_color_reject", track_id)
            return result

    def counting_classifier(frame, bbox):
        color = original_classifier(frame, bbox)
        if color == observation.target_color:
            with observation.lock:
                observation.hsv_target_passes += 1
        return color

    return CountingTracker, CountingTemporal, counting_classifier


def _queue_monitor(pipeline, stop_event, samples):
    while not stop_event.wait(0.01):
        samples.append((pipeline.frame_queue.qsize(), pipeline._candidate_queue.qsize(), pipeline._result_queue.qsize()))


def _fault_detected(fault, metrics):
    if fault == "timeout":
        return metrics.get("openclaw_timeouts", 0) > 0
    if fault == "error":
        return metrics.get("openclaw_errors", 0) > 0
    if fault == "malformed":
        return metrics.get("openclaw_parse_failures", 0) > 0
    if fault == "delay":
        return True
    return False


def run_repetition(context, scenario, repetition, fault=None):
    """Run one controlled scene. Called only from the normal host namespace."""
    np = context["np"]
    cv2 = context["cv2"]
    pipeline_mod = context["pipeline_mod"]
    mission_mod = context["mission_mod"]
    run_id = "{0}-{1:02d}-{2}".format(scenario, repetition, uuid.uuid4().hex[:8])
    evidence_dir = HERE / "evidence" / "runs" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    observation = Observation("blue")
    adapter = RealYoloAdapter(context["model"], context["torch"], context["Detection"])
    vlm = FaultThenSuccessVLM(fault, context["fault_delay"]) if fault else DeterministicVLM()
    target_color = "blue"
    scene_color = "blue" if scenario in ("target", "fault") else "red"
    mission_id = "validation-{0}".format(run_id)
    workspace = evidence_dir / "workspace"
    mission_path = workspace / "uropclaw1" / "state" / "mission.json"
    mission_path.parent.mkdir(parents=True, exist_ok=True)
    mission_path.write_text(json.dumps({
        "active": True, "mission_id": mission_id, "target_color": target_color,
        "target_body_type": None, "discord_channel_id": "fake-only",
    }), encoding="utf-8")

    originals = (pipeline_mod.IoUTracker, pipeline_mod.TemporalConfirm, pipeline_mod.classify_color,
                 pipeline_mod.WORKSPACE_BASE, pipeline_mod._METRICS_PATH, mission_mod._MISSION_PATH)
    CountingTracker, CountingTemporal, counting_classifier = _make_counting_classes(pipeline_mod, observation)
    pipeline_mod.IoUTracker = CountingTracker
    pipeline_mod.TemporalConfirm = CountingTemporal
    pipeline_mod.classify_color = counting_classifier
    pipeline_mod.WORKSPACE_BASE = workspace
    pipeline_mod._METRICS_PATH = workspace / "uropclaw1" / "state" / "metrics.json"
    pipeline_mod._METRICS_INTERVAL = 0.1
    mission_mod._MISSION_PATH = mission_path

    vehicle = camera = pipeline = None
    monitor_stop = threading.Event()
    monitor_samples = []
    monitor = None
    accepted = {"count": 0, "camera": 0, "callback_drops": 0}
    error = None
    completed = False
    target_frames = context["frames"] * (2 if fault else 1)
    try:
        vehicle, camera, vehicle_transform, camera_transform = _spawn_scene(context["carla"], context["world"], scene_color)
        pipeline = pipeline_mod.Pipeline(
            world=None, detector=adapter, vlm_runner=vlm,
            alert_sender=FakeAlert(observation), baseline_mode="proposed",
        )
        pipeline.start()
        monitor = threading.Thread(target=_queue_monitor, args=(pipeline, monitor_stop, monitor_samples), daemon=True)
        monitor.start()
        first_frame = {"saved": False}

        def on_frame(image):
            accepted["camera"] += 1
            if accepted["count"] >= target_frames:
                return
            bgra = np.frombuffer(image.raw_data, dtype=np.uint8).reshape((image.height, image.width, 4))
            frame = bgra[:, :, :3].copy()
            if not first_frame["saved"]:
                first_frame["saved"] = bool(cv2.imwrite(str(evidence_dir / "first_frame.png"), frame))
            index = accepted["count"]
            phase = 1 if (not fault or index < context["frames"]) else 2
            wall_timestamp = time.time()
            monotonic_timestamp = time.perf_counter()
            item = {
                "camera_id": "validation_camera_{0}".format(phase),
                "agent_id": "uropclaw{0}".format(phase),
                "frame": frame,
                "timestamp": wall_timestamp,
                "cam_location": _transform_dict(camera_transform)["location"],
                "cam_rotation": _transform_dict(camera_transform)["rotation"],
            }
            try:
                observation.register_acceptance(wall_timestamp, monotonic_timestamp)
                pipeline.frame_queue.put_nowait(item)
                accepted["count"] += 1
            except queue.Full:
                observation.discard_acceptance(wall_timestamp)
                accepted["callback_drops"] += 1

        camera.listen(on_frame)
        deadline = time.time() + context["run_timeout"]
        while time.time() < deadline:
            expected_calls = 2 if fault else (1 if scenario == "target" else 0)
            input_done = accepted["count"] >= target_frames
            queues_empty = pipeline.frame_queue.empty() and pipeline._candidate_queue.empty() and pipeline._result_queue.empty()
            processed = pipeline._metrics.get("frames_processed", 0) >= accepted["count"]
            calls_done = vlm.calls >= expected_calls
            if input_done and queues_empty and processed and calls_done:
                time.sleep(0.25)
                if pipeline.frame_queue.empty() and pipeline._candidate_queue.empty() and pipeline._result_queue.empty():
                    completed = True
                    break
            time.sleep(0.05)
        camera.stop()
    except Exception as exc:
        error = "{0}: {1}".format(type(exc).__name__, exc)
        (evidence_dir / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        monitor_stop.set()
        if monitor is not None:
            monitor.join(timeout=1.0)
        alive_before_stop = bool(pipeline is not None and all(t.is_alive() for t in pipeline._threads))
        ending_depth = 0
        metrics = {}
        if pipeline is not None:
            ending_depth = pipeline.frame_queue.qsize() + pipeline._candidate_queue.qsize() + pipeline._result_queue.qsize()
            metrics = pipeline.metrics_summary()
            try:
                pipeline.stop()
            except Exception:
                if error is None:
                    error = "PipelineCleanupError: {0}".format(traceback.format_exc().splitlines()[-1])
        if camera is not None:
            try:
                if camera.is_listening:
                    camera.stop()
            except Exception:
                pass
            try:
                camera.destroy()
            except Exception:
                if error is None:
                    error = "CameraCleanupError: {0}".format(traceback.format_exc().splitlines()[-1])
        if vehicle is not None:
            try:
                vehicle.destroy()
            except Exception:
                if error is None:
                    error = "VehicleCleanupError: {0}".format(traceback.format_exc().splitlines()[-1])
        (pipeline_mod.IoUTracker, pipeline_mod.TemporalConfirm, pipeline_mod.classify_color,
         pipeline_mod.WORKSPACE_BASE, pipeline_mod._METRICS_PATH, mission_mod._MISSION_PATH) = originals

    queue_rows = monitor_samples or [(0, 0, 0)]
    max_frame = max(row[0] for row in queue_rows)
    max_candidate = max(row[1] for row in queue_rows)
    max_result = max(row[2] for row in queue_rows)
    lat = latency_summary(observation.latency_samples, np)
    target_events = len(observation.alert_events)
    success = scenario_success(scenario, target_events, vlm.calls, adapter.detection_count, alive_before_stop)
    if scenario == "fault":
        success = bool(alive_before_stop and vlm.calls >= 2 and vlm.normal_successes >= 1)
    fault_detected = bool(getattr(vlm, "injected", 0) and _fault_detected(fault, metrics)) if fault else False
    row = {
        "run_id": run_id, "scenario": scenario, "repetition": repetition,
        "fault": fault or "", "status": "COMPLETE" if error is None and completed else ("TIMEOUT" if error is None else "ERROR"),
        "input_frames": accepted["count"], "camera_frames": accepted["camera"],
        "yolo_detections": adapter.detection_count,
        "hsv_target_passes": observation.hsv_target_passes,
        "unique_tracks": len(observation.unique_tracks),
        "confirmed_tracks": len(observation.confirmed_tracks),
        "vlm_requests": vlm.calls, "target_events": target_events,
        "false_target_events": target_events if scenario == "non_target" else 0,
        "scenario_success": success,
        "max_queue_depth": max(max_frame, max_candidate, max_result),
        "max_frame_queue": max_frame, "max_candidate_queue": max_candidate,
        "max_result_queue": max_result, "ending_queue_depth": ending_depth,
        "dropped_frames": accepted["callback_drops"] + metrics.get("frames_dropped", 0),
        "dropped_events": metrics.get("candidates_dropped", 0),
        "backlog_accumulation": ending_depth > 0,
        "pipeline_alive": alive_before_stop, "pipeline_crash": not alive_before_stop,
        "fault_injected": getattr(vlm, "injected", 0),
        "fault_detected": fault_detected,
        "recovered": bool(fault and fault_detected and vlm.normal_successes >= 1 and alive_before_stop),
        "next_normal_request_success": bool(fault and vlm.normal_successes >= 1),
        "duplicate_suppressed": metrics.get("duplicate_suppressed", 0), "error": error or "",
    }
    row.update({"e2e_" + key: value for key, value in lat.items() if key not in ("at_or_below_1000", "over_1000", "compliance_rate")})
    row["at_or_below_1000"] = lat["at_or_below_1000"]
    row["over_1000"] = lat["over_1000"]
    row["compliance_rate"] = lat["compliance_rate"]
    evidence = {
        "row": row, "production_metrics": metrics,
        "scene": {"vehicle_color": scene_color, "target_color": target_color},
        "queue_samples": [{"frame": a, "candidate": b, "result": c} for a, b, c in queue_rows],
        "yolo_latency_ms": [round(v, 3) for v in adapter.latencies_ms],
        "e2e_latency_samples": observation.latency_rows,
    }
    _write_json(evidence_dir / "result.json", evidence)
    for latency_row in observation.latency_rows:
        latency_row.update({"run_id": run_id, "scenario": scenario, "repetition": repetition, "fault": fault or ""})
    return row, observation.latency_rows


def _aggregate(rows, np):
    output = []
    for scenario in ("target", "non_target"):
        selected = [row for row in rows if row["scenario"] == scenario]
        if not selected:
            continue
        samples = []
        for row in selected:
            result_path = HERE / "evidence" / "runs" / row["run_id"] / "result.json"
            data = json.loads(result_path.read_text(encoding="utf-8"))
            samples.extend(item["latency_ms"] for item in data["e2e_latency_samples"])
        lat = latency_summary(samples, np)
        output.append({
            "scenario": scenario, "repetitions": len(selected),
            "successes": sum(bool(row["scenario_success"]) for row in selected),
            "success_rate": round(sum(bool(row["scenario_success"]) for row in selected) / float(len(selected)), 6),
            "input_frames": sum(row["input_frames"] for row in selected),
            "yolo_detections": sum(row["yolo_detections"] for row in selected),
            "unique_tracks": sum(row["unique_tracks"] for row in selected),
            "confirmed_tracks": sum(row["confirmed_tracks"] for row in selected),
            "vlm_requests": sum(row["vlm_requests"] for row in selected),
            "target_events": sum(row["target_events"] for row in selected),
            "max_queue_depth": max(row["max_queue_depth"] for row in selected),
            "drops": sum(row["dropped_frames"] + row["dropped_events"] for row in selected),
            **lat,
        })
    return output


def _aggregate_faults(rows):
    output = []
    for fault in ("delay", "timeout", "error", "malformed"):
        selected = [row for row in rows if row["scenario"] == "fault" and row["fault"] == fault]
        if not selected:
            continue
        output.append({
            "fault": fault,
            "repetitions": len(selected),
            "injected": sum(row["fault_injected"] for row in selected),
            "detected": sum(bool(row["fault_detected"]) for row in selected),
            "recovered": sum(bool(row["recovered"]) for row in selected),
            "pipeline_crashes": sum(bool(row["pipeline_crash"]) for row in selected),
            "next_normal_request_successes": sum(bool(row["next_normal_request_success"]) for row in selected),
            "max_queue_depth": max(row["max_queue_depth"] for row in selected),
            "dropped_frames": sum(row["dropped_frames"] for row in selected),
            "dropped_events": sum(row["dropped_events"] for row in selected),
        })
    return output


def _write_outputs(rows, latency_rows, environment, np):
    HERE.mkdir(parents=True, exist_ok=True)
    _write_csv(HERE / "raw_results.csv", RAW_FIELDS, rows)
    latency_fields = ["run_id", "scenario", "repetition", "fault", "sample_index", "source_frame_timestamp", "accepted_monotonic", "decision_timestamp", "decision_monotonic", "boundary", "terminal", "track_id", "latency_ms"]
    _write_csv(HERE / "latency_samples.csv", latency_fields, latency_rows)
    summary = _aggregate(rows, np)
    summary_fields = ["scenario", "repetitions", "successes", "success_rate", "sample_count", "mean_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms", "at_or_below_1000", "over_1000", "compliance_rate", "input_frames", "yolo_detections", "unique_tracks", "confirmed_tracks", "vlm_requests", "target_events", "max_queue_depth", "drops"]
    _write_csv(HERE / "scenario_summary.csv", summary_fields, summary)
    latency_fields_summary = ["scenario", "sample_count", "mean_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms", "at_or_below_1000", "over_1000", "compliance_rate"]
    _write_csv(HERE / "latency_summary.csv", latency_fields_summary, summary)
    fault_rows = _aggregate_faults(rows)
    fault_fields = ["fault", "repetitions", "injected", "detected", "recovered", "pipeline_crashes", "next_normal_request_successes", "max_queue_depth", "dropped_frames", "dropped_events"]
    _write_csv(HERE / "fault_summary.csv", fault_fields, fault_rows)
    _write_json(HERE / "evidence" / "environment.json", environment)
    environment_lines = [
        "# Measured host environment", "",
        "This file is generated only after connecting to the host CARLA server.", "",
        "| Item | Measured value |", "|---|---|",
    ]
    environment_lines.extend("| `{0}` | `{1}` |".format(key, value) for key, value in environment.items())
    environment_lines.extend([
        "", "Required disclosure: **Post-project CARLA validation used a newly obtained pretrained YOLOv8s weight because the original research weight was unavailable.**",
        "", "No system Python package, NVIDIA driver, or system CUDA toolkit is changed by this runner.", "",
    ])
    (HERE / "environment.md").write_text("\n".join(environment_lines), encoding="utf-8")
    report = [
        "# Real CARLA pipeline validation report", "",
        "Status: host repetitions complete" if len(rows) == environment["planned_repetitions"] and all(row["status"] == "COMPLETE" for row in rows) else "Status: measured host run in progress",
        "", "This report describes actual CARLA simulation input with Real YOLO and deterministic Fake VLM/Fake Alert. It is not real-road or real-vehicle validation.", "",
        "| Scenario | Repetitions | Success | 1s Compliance | Mean E2E | p95 | Max | YOLO Detections | Unique Tracks | Confirmed | VLM Requests | Max Queue | Drops |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary:
        report.append("| {scenario} | {repetitions} | {successes}/{repetitions} | {compliance_rate} | {mean_ms} ms | {p95_ms} ms | {max_ms} ms | {yolo_detections} | {unique_tracks} | {confirmed_tracks} | {vlm_requests} | {max_queue_depth} | {drops} |".format(**item))
    report.extend(["", "## Fake VLM fault injection", "", "| Fault | Repetitions | Injected | Detected | Recovered | Crashes | Next normal success | Max queue | Drops |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for item in fault_rows:
        report.append("| {fault} | {repetitions} | {injected} | {detected} | {recovered} | {pipeline_crashes} | {next_normal_request_successes} | {max_queue_depth} | {drops} |".format(drops=item["dropped_frames"] + item["dropped_events"], **item))
    report.extend([
        "", "E2E samples use the triggering CARLA frame's successful input-queue insertion timestamp through the final target-colour rejection or AlertPolicy allow decision. YOLO-only latency is not included as a separate E2E sample.",
        "", "Historical 46,372 / 28,736 / 3,298 / 53 values are not compared because their units are not established as identical.", "",
    ])
    (HERE / "validation_report.md").write_text("\n".join(report), encoding="utf-8")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--run-timeout", type=float, default=45.0)
    parser.add_argument("--weight", type=Path, default=DEFAULT_WEIGHT)
    parser.add_argument("--target-repetitions", type=int, default=10)
    parser.add_argument("--non-target-repetitions", type=int, default=10)
    parser.add_argument("--fault-repetitions", type=int, default=5)
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--model-warmup", type=int, default=10)
    parser.add_argument("--fault-delay", type=float, default=1.2)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    log_path = HERE / "evidence" / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(str(log_path), mode="w", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    if str(HARNESS_DIR) not in sys.path:
        sys.path.insert(0, str(HARNESS_DIR))
    try:
        import carla
        import cv2
        import numpy as np
        import torch
        import torchvision
        import ultralytics
        from ultralytics import YOLO
        from core import mission as mission_mod
        from core import pipeline as pipeline_mod
        from perception.yolo_detector import Detection

        if not args.weight.is_file():
            raise FileNotFoundError("YOLO weight not found: {0}".format(args.weight))
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable")
        client = carla.Client(args.host, args.port)
        client.set_timeout(args.timeout)
        client_version = str(client.get_client_version())
        server_version = str(client.get_server_version())
        if client_version != EXPECTED_CARLA_VERSION or server_version != EXPECTED_CARLA_VERSION:
            raise RuntimeError("CARLA mismatch: client={0}, server={1}".format(client_version, server_version))
        world = client.get_world()
        model = YOLO(str(args.weight.resolve()))
        if args.model_warmup < 5:
            raise ValueError("--model-warmup must be at least 5")
        warmup_frame = np.zeros((600, 800, 3), dtype=np.uint8)
        warmup_latencies = []
        for index in range(args.model_warmup):
            torch.cuda.synchronize()
            warmup_started = time.perf_counter()
            model(warmup_frame, conf=0.40, iou=0.45, device=0, verbose=False)
            torch.cuda.synchronize()
            warmup_latencies.append(round((time.perf_counter() - warmup_started) * 1000.0, 3))
            logging.info("Excluded model warm-up %s/%s: %.3f ms", index + 1, args.model_warmup, warmup_latencies[-1])
        environment = {
            "captured_at_utc": utc_now(), "python": sys.version.split()[0],
            "carla_client": client_version, "carla_server": server_version,
            "map": str(world.get_map().name), "torch": torch.__version__,
            "torchvision": torchvision.__version__, "torch_cuda": str(torch.version.cuda),
            "cuda_available": True, "gpu": torch.cuda.get_device_name(0),
            "ultralytics": ultralytics.__version__, "opencv": cv2.__version__,
            "numpy": np.__version__, "weight": args.weight.name,
            "weight_sha256": sha256_file(args.weight),
            "weight_source": "Post-project pretrained YOLOv8s; original research weight unavailable",
            "model_warmup_count_excluded": args.model_warmup,
            "model_warmup_latencies_ms": warmup_latencies,
            "planned_repetitions": args.target_repetitions + args.non_target_repetitions + 4 * args.fault_repetitions,
        }
        context = {
            "carla": carla, "cv2": cv2, "np": np, "torch": torch,
            "pipeline_mod": pipeline_mod, "mission_mod": mission_mod,
            "Detection": Detection, "model": model, "world": world,
            "frames": args.frames, "fault_delay": args.fault_delay,
            "run_timeout": args.run_timeout,
        }
        rows = []
        latency_rows = []
        plan = (
            [("target", i, None) for i in range(1, args.target_repetitions + 1)]
            + [("non_target", i, None) for i in range(1, args.non_target_repetitions + 1)]
            + [("fault", i, fault) for fault in ("delay", "timeout", "error", "malformed") for i in range(1, args.fault_repetitions + 1)]
        )
        for scenario, repetition, fault in plan:
            logging.info("Running %s repetition=%s fault=%s", scenario, repetition, fault or "none")
            row, samples = run_repetition(context, scenario, repetition, fault)
            logging.info("Finished %s status=%s success=%s", row["run_id"], row["status"], row["scenario_success"])
            rows.append(row)
            latency_rows.extend(samples)
            _write_outputs(rows, latency_rows, environment, np)
        return 0 if all(row["status"] == "COMPLETE" for row in rows) else 1
    except Exception as exc:
        HERE.mkdir(parents=True, exist_ok=True)
        failure = {"status": "BLOCKED", "error": "{0}: {1}".format(type(exc).__name__, exc), "traceback": traceback.format_exc()}
        _write_json(HERE / "evidence" / "runner_failure.json", failure)
        print(failure["traceback"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

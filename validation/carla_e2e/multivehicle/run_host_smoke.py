#!/usr/bin/env python3
"""Host-only Real CARLA/YOLO dynamic multi-vehicle smoke validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import queue
import subprocess
import sys
import threading
import time
import traceback
from contextlib import ExitStack
from pathlib import Path


HERE = Path(__file__).resolve().parent
CARLA_E2E_DIR = HERE.parent
REPOSITORY_ROOT = CARLA_E2E_DIR.parents[1]
HARNESS_DIR = REPOSITORY_ROOT / "harness"
DEFAULT_WEIGHT = CARLA_E2E_DIR / "weights" / "yolov8s.pt"
EVIDENCE_DIR = HERE / "evidence" / "smoke"
EXPECTED_CARLA_VERSION = "0.9.13"
TARGET_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

sys.path.insert(0, str(HERE))
from instrumentation import (  # noqa: E402
    InstrumentedDetector, Observation, evaluate_smoke_gate, frame_retention,
    make_production_wrappers, project_actor_bbox,
)
from scene import (  # noqa: E402
    actor_locations, cleanup_owned_actors, movement_summary, plan_scene,
    spawn_planned_vehicles, start_probe, synchronous_mode, transform_from_dict,
)
from scene_manifest import (  # noqa: E402
    build_non_target_manifest, validate_manifest_parity, write_manifest,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--tm-port", type=int, default=8000)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--sensor-timeout", type=float, default=2.0)
    parser.add_argument("--camera-ready-ticks", type=int, default=10)
    parser.add_argument("--drain-timeout", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--background-vehicles", type=int, default=15)
    parser.add_argument("--probe-vehicles", type=int, default=1)
    parser.add_argument("--pre-roll-seconds", type=float, default=5.0)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=600)
    parser.add_argument("--fov", type=float, default=90.0)
    parser.add_argument("--model-warmup", type=int, default=10)
    parser.add_argument("--weight", type=Path, default=DEFAULT_WEIGHT)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    return parser.parse_args(argv)


def validate_args(args):
    if args.frames != 100:
        raise ValueError("multi-vehicle smoke requires exactly 100 frames")
    if args.background_vehicles != 15:
        raise ValueError("multi-vehicle smoke requires exactly 15 background vehicles")
    if args.probe_vehicles != 1:
        raise ValueError("multi-vehicle smoke requires exactly one probe vehicle")
    if args.seed != 42:
        raise ValueError("multi-vehicle smoke requires fixed seed 42")
    if (args.width, args.height, args.fov) != (800, 600, 90.0):
        raise ValueError("multi-vehicle smoke requires 800x600 and FOV 90")
    if args.pre_roll_seconds != 5.0:
        raise ValueError("multi-vehicle smoke requires a 5 second pre-roll")
    return args


def validate_carla_versions(client_version, server_version):
    if client_version != server_version:
        raise RuntimeError(
            "CARLA client/server version mismatch: {0} != {1}".format(client_version, server_version)
        )
    if client_version != EXPECTED_CARLA_VERSION:
        raise RuntimeError("CARLA version must be 0.9.13, got {0}".format(client_version))


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_manifest_pair(planned_scene):
    target = {
        "schema_version": 1,
        "scenario": "target",
        "planned_scene": planned_scene,
        "actual_spawned_scene": {"vehicles": []},
    }
    non_target = build_non_target_manifest(target, "255,0,0")
    validate_manifest_parity(target, non_target)
    target["parity_validation"] = {
        "status": "PASS", "allowed_difference": "planned probe color only",
        "non_target_probe_color": "255,0,0",
    }
    non_target["parity_validation"] = dict(target["parity_validation"])
    return target, non_target


def write_failure_evidence(evidence_dir, error, partial=None):
    value = dict(partial or {})
    value.update({
        "status": "FAIL",
        "error": "{0}: {1}".format(type(error).__name__, error),
    })
    _write_json(Path(evidence_dir) / "result.json", value)


def _setup_logging(evidence_dir):
    evidence_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("multivehicle-smoke")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers[:] = []
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(str(evidence_dir / "run.log"), mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers[:] = [file_handler, stream_handler]
    return logger


def _image_to_bgr(image, numpy_module):
    return numpy_module.frombuffer(image.raw_data, dtype=numpy_module.uint8).reshape(
        (image.height, image.width, 4)
    )[:, :, :3].copy()


class SensorFrameTimeout(RuntimeError):
    def __init__(self, expected_frame, received_frames):
        self.expected_frame = int(expected_frame)
        self.received_frames = list(received_frames)
        super().__init__(
            "sensor frame timeout: expected={0}, received={1}".format(
                self.expected_frame, self.received_frames
            )
        )


class CameraNotReadyError(RuntimeError):
    def __init__(self, attempts, timeout_evidence):
        self.attempts = int(attempts)
        self.timeout_evidence = list(timeout_evidence)
        super().__init__("CAMERA_NOT_READY after {0} synchronous ticks".format(attempts))


class SynchronousSensorStream:
    """Match sensor callbacks to explicit synchronous world ticks."""

    def __init__(self, sensor):
        self.sensor = sensor
        self.queue = queue.Queue()
        self.active = threading.Event()
        self.received_frames = []
        self.stale_frames = []
        self.future_frames = {}
        self.timeout_evidence = []

    def start(self):
        self.active.set()

        def callback(image):
            if not self.active.is_set():
                return
            frame_id = int(image.frame)
            self.received_frames.append(frame_id)
            self.queue.put_nowait(image)

        self.sensor.listen(callback)

    def close(self):
        self.active.clear()
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def wait_for_frame(self, expected_frame, timeout):
        expected_frame = int(expected_frame)
        if expected_frame in self.future_frames:
            return self.future_frames.pop(expected_frame)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                evidence = {
                    "expected_frame": expected_frame,
                    "received_frames": list(self.received_frames),
                }
                self.timeout_evidence.append(evidence)
                raise SensorFrameTimeout(expected_frame, self.received_frames)
            try:
                image = self.queue.get(timeout=remaining)
            except queue.Empty:
                evidence = {
                    "expected_frame": expected_frame,
                    "received_frames": list(self.received_frames),
                }
                self.timeout_evidence.append(evidence)
                raise SensorFrameTimeout(expected_frame, self.received_frames)
            frame_id = int(image.frame)
            if frame_id < expected_frame:
                self.stale_frames.append(frame_id)
                continue
            if frame_id == expected_frame:
                return image
            self.future_frames[frame_id] = image

    def tick_and_wait(self, world, tick_timeout, sensor_timeout):
        expected_frame = int(world.tick(tick_timeout))
        return expected_frame, self.wait_for_frame(expected_frame, sensor_timeout)

    def wait_until_ready(self, world, tick_timeout, sensor_timeout, max_ticks):
        for _ in range(max_ticks):
            try:
                return self.tick_and_wait(world, tick_timeout, sensor_timeout)
            except SensorFrameTimeout:
                continue
        raise CameraNotReadyError(max_ticks, self.timeout_evidence)


def stop_camera_stream(stream, camera):
    if stream is not None:
        stream.close()
    if camera is not None:
        try:
            camera.stop()
        except Exception:
            pass


def shutdown_scene_resources(stream, camera, owned_actors):
    stop_camera_stream(stream, camera)
    return cleanup_owned_actors(owned_actors)


class RealYoloDetector:
    def __init__(self, model, torch_module, detection_type, cv2_module, evidence_dir):
        self.model = model
        self.torch = torch_module
        self.detection_type = detection_type
        self.cv2 = cv2_module
        self.evidence_dir = Path(evidence_dir)
        self.latencies_ms = []
        self.max_boxes = -1

    def __call__(self, frame):
        if self.torch.cuda.is_available():
            self.torch.cuda.synchronize()
        started = time.perf_counter()
        results = self.model(frame, conf=0.40, iou=0.45, device=0, verbose=False)
        if self.torch.cuda.is_available():
            self.torch.cuda.synchronize()
        self.latencies_ms.append((time.perf_counter() - started) * 1000.0)
        detections = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                class_id = int(box.cls[0])
                if class_id not in TARGET_CLASSES:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(self.detection_type(
                    bbox=[int(x1), int(y1), int(x2), int(y2)],
                    class_id=class_id,
                    class_name=TARGET_CLASSES[class_id],
                    confidence=float(box.conf[0]),
                ))
        if len(detections) > self.max_boxes:
            self.max_boxes = len(detections)
            annotated = frame.copy()
            for detection in detections:
                x1, y1, x2, y2 = detection.bbox
                self.cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                self.cv2.putText(
                    annotated,
                    "{0} {1:.2f}".format(detection.class_name, detection.confidence),
                    (x1, max(15, y1 - 5)), self.cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 0), 1,
                )
            self.cv2.imwrite(str(self.evidence_dir / "max_detections_annotated.png"), annotated)
        return detections


class FakeVLM:
    def __init__(self, observation):
        self.observation = observation
        self.calls = 0
        self.images = 0

    def __call__(self, command, **kwargs):
        self.calls += 1
        prompt = kwargs.get("input", b"")
        if isinstance(prompt, bytes):
            prompt = prompt.decode("utf-8", errors="replace")
        for line in str(prompt).splitlines():
            if line.startswith("Analyze the image at "):
                path = Path(line[len("Analyze the image at "):].rstrip("."))
                if path.is_file():
                    self.images += 1
                    self.observation.record_vlm_image()
                break
        payload = {
            "visible_vehicle": True, "color": "blue", "color_match": True,
            "body_type": "car", "body_type_match": True,
            "confidence": "high", "confirmed": True,
            "reason": "deterministic multi-vehicle smoke response",
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload).encode("utf-8"), stderr=b"")


class FakeAlert:
    def __init__(self):
        self.events = []

    def __call__(self, agent_id, event):
        self.events.append(event)
        return True


def _queue_monitor(pipeline, stop_event, samples):
    while not stop_event.wait(0.01):
        samples.append({
            "input": pipeline.frame_queue.qsize(),
            "candidate": pipeline._candidate_queue.qsize(),
            "result": pipeline._result_queue.qsize(),
        })


def _ground_truth(actors, probe_actor, camera_transform, args, np):
    boxes = {}
    for actor in actors:
        if not actor.is_alive:
            continue
        bbox = project_actor_bbox(actor, camera_transform, args.width, args.height, args.fov, np)
        if bbox is not None:
            boxes[str(actor.id)] = bbox
    return {"actor_boxes": boxes, "probe_bbox": boxes.get(str(probe_actor.id))}


def _vehicle_counts(world):
    actors = list(world.get_actors().filter("vehicle.*"))
    controlled = 0
    for actor in actors:
        try:
            role = actor.attributes.get("role_name", "")
        except Exception:
            role = ""
        controlled += int(role.startswith("uropclaw_validation_"))
    return {
        "world_vehicle_count": len(actors),
        "preexisting_validation_actor_count": controlled,
        "uncontrolled_world_vehicle_count": len(actors) - controlled,
    }


def _drain_pipeline(pipeline, accepted_count, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        queues_empty = (
            pipeline.frame_queue.empty()
            and pipeline._candidate_queue.empty()
            and pipeline._result_queue.empty()
        )
        processed = pipeline._metrics.get("frames_processed", 0) >= accepted_count
        if queues_empty and processed:
            time.sleep(0.25)
            if pipeline.frame_queue.empty() and pipeline._candidate_queue.empty() and pipeline._result_queue.empty():
                return True
        time.sleep(0.05)
    return False


def run_smoke(args):
    evidence_dir = Path(args.evidence_dir)
    logger = _setup_logging(evidence_dir)
    partial = {"phase": "initializing", "status": "RUNNING"}
    owned_actors = []
    pipeline = None
    camera = None
    camera_stream = None
    monitor_stop = threading.Event()
    monitor_thread = None
    monitor_samples = []
    originals = None
    manifest = None
    caught_error = None
    cleanup = {
        "attempted": 0, "destroyed": 0, "failed_actor_ids": [],
        "skipped_duplicate_actor_ids": [],
    }
    cleanup_complete = False

    def cleanup_scene():
        nonlocal cleanup, cleanup_complete, pipeline
        if cleanup_complete:
            return
        monitor_stop.set()
        if monitor_thread is not None:
            monitor_thread.join(timeout=1.0)
        if pipeline is not None:
            try:
                pipeline.stop()
            except Exception:
                pass
            pipeline = None
        cleanup = shutdown_scene_resources(camera_stream, camera, owned_actors)
        cleanup_complete = True

    try:
        validate_args(args)
        if not args.weight.is_file():
            raise RuntimeError("YOLO weight not found: {0}".format(args.weight))

        import carla
        import cv2
        import numpy as np
        import torch
        import ultralytics
        from ultralytics import YOLO

        sys.path.insert(0, str(HARNESS_DIR))
        import core.mission as mission_mod
        import core.pipeline as pipeline_mod
        from perception.yolo_detector import Detection

        client = carla.Client(args.host, args.port)
        client.set_timeout(args.timeout)
        client_version = client.get_client_version()
        server_version = client.get_server_version()
        validate_carla_versions(client_version, server_version)
        world = client.get_world()
        tm = client.get_trafficmanager(args.tm_port)
        partial.update({
            "phase": "connected", "client_version": client_version,
            "server_version": server_version, "map": world.get_map().name,
            "actor_counts_before": _vehicle_counts(world),
        })
        if partial["actor_counts_before"]["preexisting_validation_actor_count"]:
            raise RuntimeError("pre-existing UROPCLAW validation actors found; refusing to delete or reuse them")

        model = YOLO(str(args.weight))
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable; Real YOLO smoke requires RTX 3060 GPU inference")
        model.to("cuda:0")
        environment = {
            "carla_client_version": client_version,
            "carla_server_version": server_version,
            "map": world.get_map().name,
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "cuda_available": bool(torch.cuda.is_available()),
            "gpu": torch.cuda.get_device_name(0),
            "ultralytics": ultralytics.__version__,
            "opencv": cv2.__version__,
            "yolo_weight": args.weight.name,
            "yolo_weight_sha256": _sha256_file(args.weight),
            "yolo_weight_source": "post-project pretrained YOLOv8s weight",
        }
        partial["environment"] = environment
        _write_json(evidence_dir / "environment.json", environment)
        observation = Observation("blue")
        base_detector = RealYoloDetector(model, torch, Detection, cv2, evidence_dir)
        detector = InstrumentedDetector(base_detector, observation)
        vlm = FakeVLM(observation)
        alert = FakeAlert()

        with ExitStack() as scene_stack:
            scene_stack.enter_context(synchronous_mode(world, tm, args.seed, 0.1))
            scene_stack.callback(cleanup_scene)
            planned = plan_scene(carla, world, args.seed, args.background_vehicles)
            planned["traffic_manager"]["port"] = args.tm_port
            target_manifest, non_target_manifest = make_manifest_pair(planned)
            manifest = target_manifest
            write_manifest(evidence_dir / "non_target_scene_manifest.json", non_target_manifest)

            controlled, actual = spawn_planned_vehicles(carla, world, tm, planned, args.tm_port)
            owned_actors.extend(controlled)
            manifest["actual_spawned_scene"] = actual
            probe_actor = controlled[-1]
            probe_plan = planned["vehicles"][-1]
            try:
                probe_actor.apply_control(carla.VehicleControl(hand_brake=True))
            except Exception:
                logger.warning("Probe hand brake could not be set; autopilot remains disabled during pre-roll")

            camera_bp = world.get_blueprint_library().find("sensor.camera.rgb")
            camera_bp.set_attribute("image_size_x", str(args.width))
            camera_bp.set_attribute("image_size_y", str(args.height))
            camera_bp.set_attribute("fov", str(args.fov))
            camera_bp.set_attribute("sensor_tick", "0.1")
            camera_transform = transform_from_dict(carla, planned["camera"]["transform"])
            camera = world.spawn_actor(camera_bp, camera_transform)
            owned_actors.append(camera)
            actual["camera"] = {"actor_id": int(camera.id), **planned["camera"]}
            actual["actor_counts_before"] = partial["actor_counts_before"]
            actual["actor_counts_after_spawn"] = _vehicle_counts(world)
            write_manifest(evidence_dir / "scene_manifest.json", manifest)

            camera_stream = SynchronousSensorStream(camera)
            camera_stream.start()
            partial["phase"] = "camera_readiness"
            ready_expected, ready_image = camera_stream.wait_until_ready(
                world, args.timeout, args.sensor_timeout, args.camera_ready_ticks
            )
            partial["camera_readiness"] = {
                "status": "PASS",
                "tick_frame": ready_expected,
                "sensor_frame": int(ready_image.frame),
                "ticks_attempted": len(camera_stream.timeout_evidence) + 1,
            }
            background_before = actor_locations(controlled[:-1])
            pre_roll_ticks = int(round(args.pre_roll_seconds / 0.1))
            partial["phase"] = "pre_roll"
            for tick_index in range(pre_roll_ticks):
                partial["pre_roll_tick_index"] = tick_index
                expected_frame, image = camera_stream.tick_and_wait(
                    world, args.timeout, args.sensor_timeout
                )
                frame = _image_to_bgr(image, np)
                if tick_index < args.model_warmup:
                    base_detector(frame)
                if tick_index == pre_roll_ticks - 1:
                    cv2.imwrite(str(evidence_dir / "scene_preroll.png"), frame)
            base_detector.max_boxes = -1
            background_after = actor_locations(controlled[:-1])
            movement = movement_summary(background_before, background_after, 1.0)

            workspace = evidence_dir / "workspace"
            mission_path = workspace / "uropclaw1" / "state" / "mission.json"
            mission_path.parent.mkdir(parents=True, exist_ok=True)
            mission_path.write_text(json.dumps({
                "active": True, "mission_id": "multivehicle-smoke",
                "target_color": "blue", "target_body_type": None,
                "discord_channel_id": "fake-only",
            }), encoding="utf-8")
            originals = (
                pipeline_mod.IoUTracker, pipeline_mod.TemporalConfirm,
                pipeline_mod.classify_color, pipeline_mod.WORKSPACE_BASE,
                pipeline_mod._METRICS_PATH, mission_mod._MISSION_PATH,
            )
            Tracker, Temporal, classifier = make_production_wrappers(
                pipeline_mod.IoUTracker, pipeline_mod.TemporalConfirm,
                pipeline_mod.classify_color, observation,
            )
            pipeline_mod.IoUTracker = Tracker
            pipeline_mod.TemporalConfirm = Temporal
            pipeline_mod.classify_color = classifier
            pipeline_mod.WORKSPACE_BASE = workspace
            pipeline_mod._METRICS_PATH = workspace / "uropclaw1" / "state" / "metrics.json"
            pipeline_mod._METRICS_INTERVAL = 0.1
            mission_mod._MISSION_PATH = mission_path
            pipeline = pipeline_mod.Pipeline(
                world=None, detector=detector, vlm_runner=vlm,
                alert_sender=alert, baseline_mode="proposed",
            )
            pipeline.start()
            monitor_thread = threading.Thread(
                target=_queue_monitor, args=(pipeline, monitor_stop, monitor_samples), daemon=True
            )
            monitor_thread.start()
            try:
                probe_actor.apply_control(carla.VehicleControl(hand_brake=False))
            except Exception:
                pass
            start_probe(carla, probe_actor, probe_plan, tm, args.tm_port)

            accepted = 0
            callback_drops = 0
            measurement_ticks = 0
            partial["phase"] = "measurement"
            while accepted < args.frames:
                measurement_ticks += 1
                partial["measurement_tick_index"] = measurement_ticks
                if measurement_ticks > args.frames * 3:
                    raise RuntimeError("could not accept 100 frames within 300 synchronous ticks")
                expected_frame, image = camera_stream.tick_and_wait(
                    world, args.timeout, args.sensor_timeout
                )
                frame = _image_to_bgr(image, np)
                ground_truth = _ground_truth(controlled, probe_actor, camera_transform, args, np)
                wall_timestamp = time.time()
                if pipeline.frame_queue.full():
                    callback_drops += 1
                    continue
                observation.accept_frame(frame, accepted, wall_timestamp, ground_truth)
                item = {
                    "camera_id": "multivehicle_fixed_cctv", "agent_id": "uropclaw1",
                    "frame": frame, "timestamp": wall_timestamp,
                    "cam_location": planned["camera"]["transform"]["location"],
                    "cam_rotation": planned["camera"]["transform"]["rotation"],
                }
                try:
                    pipeline.frame_queue.put_nowait(item)
                    accepted += 1
                except queue.Full:
                    callback_drops += 1
                    observation.frame_meta.pop(id(frame), None)
                    observation.timestamp_to_frame.pop(wall_timestamp, None)

            drained = _drain_pipeline(pipeline, accepted, args.drain_timeout)
            if not drained:
                raise RuntimeError("pipeline queues did not drain before timeout")
            production_metrics = pipeline.metrics_summary()
            pipeline_alive = all(thread.is_alive() for thread in pipeline._threads)
            pipeline.stop()
            pipeline = None

            metrics = observation.metrics()
            queue_samples = monitor_samples or [{"input": 0, "candidate": 0, "result": 0}]
            result = {
                **partial,
                **metrics,
                "phase": "cleanup",
                "actual_controlled_vehicle_count": actual["controlled_vehicle_count"],
                "background_movement": movement,
                "max_yolo_vehicle_boxes_per_frame": max(observation.detections_per_frame.values() or [0]),
                "mean_yolo_vehicle_boxes_per_frame": (
                    sum(observation.detections_per_frame.values()) / float(len(observation.detections_per_frame))
                    if observation.detections_per_frame else 0.0
                ),
                "probe_fov_enter_frame": observation.probe_fov_enter_frame,
                "probe_fov_exit_frame": observation.probe_fov_exit_frame,
                "probe_yolo_detected": observation.probe_yolo_detected,
                "probe_hsv_passed": observation.probe_hsv_passed,
                "target_track_created": observation.target_track_created,
                "target_temporal_confirmed": observation.target_temporal_confirmed,
                "fake_vlm_requests": vlm.calls,
                "fake_alert_events": len(alert.events),
                "pipeline_alive": pipeline_alive,
                "callback_dropped_frames": callback_drops,
                "camera_sync": {
                    "readiness": partial["camera_readiness"],
                    "received_frame_count": len(camera_stream.received_frames),
                    "first_received_frame": min(camera_stream.received_frames),
                    "last_received_frame": max(camera_stream.received_frames),
                    "stale_frames": list(camera_stream.stale_frames),
                    "timeout_evidence": list(camera_stream.timeout_evidence),
                },
                "production_metrics": production_metrics,
                "frame_retention": frame_retention(metrics),
                "tracking": observation.tracking_diagnostics(),
                "visible_vehicle_count_by_frame": observation.visible_vehicles_per_frame,
                "detections_per_frame": observation.detections_per_frame,
                "yolo_latency_ms": [round(value, 3) for value in base_detector.latencies_ms[args.model_warmup:]],
                "queue": {
                    "max_input_depth": max(item["input"] for item in queue_samples),
                    "max_candidate_depth": max(item["candidate"] for item in queue_samples),
                    "max_result_depth": max(item["result"] for item in queue_samples),
                    "ending_depth": 0,
                    "samples": queue_samples,
                },
            }
            partial = result
    except Exception as error:
        caught_error = error
        if isinstance(error, CameraNotReadyError):
            partial["phase"] = "CAMERA_NOT_READY"
            partial["camera_sync_error"] = {
                "attempts": error.attempts,
                "timeout_evidence": error.timeout_evidence,
            }
        elif isinstance(error, SensorFrameTimeout):
            partial["phase"] = "SENSOR_FRAME_TIMEOUT"
            partial["camera_sync_error"] = {
                "expected_frame": error.expected_frame,
                "received_frames": error.received_frames,
            }
        partial["traceback"] = traceback.format_exc()
        logger.exception("Multi-vehicle smoke failed")
    finally:
        cleanup_scene()
        if originals is not None:
            (
                pipeline_mod.IoUTracker, pipeline_mod.TemporalConfirm,
                pipeline_mod.classify_color, pipeline_mod.WORKSPACE_BASE,
                pipeline_mod._METRICS_PATH, mission_mod._MISSION_PATH,
            ) = originals

    if caught_error is not None:
        partial["cleanup"] = cleanup
        write_failure_evidence(evidence_dir, caught_error, partial)
        if manifest is not None:
            manifest["actual_spawned_scene"]["cleanup"] = cleanup
            write_manifest(evidence_dir / "scene_manifest.json", manifest)
            write_manifest(HERE / "scene_manifest.json", manifest)
        return 1

    partial["cleanup"] = cleanup
    evaluation = evaluate_smoke_gate(partial)
    partial.update(evaluation)
    partial["phase"] = "complete"
    _write_json(evidence_dir / "result.json", partial)
    if manifest is not None:
        manifest["actual_spawned_scene"]["cleanup"] = cleanup
        write_manifest(evidence_dir / "scene_manifest.json", manifest)
        write_manifest(HERE / "scene_manifest.json", manifest)
    logger.info("Multi-vehicle smoke status: %s", partial["status"])
    if partial["failed_gates"]:
        logger.error("Failed gates: %s", ", ".join(partial["failed_gates"]))
    return 0 if partial["status"] == "PASS" else 1


def main(argv=None):
    args = parse_args(argv)
    return run_smoke(args)


if __name__ == "__main__":
    raise SystemExit(main())

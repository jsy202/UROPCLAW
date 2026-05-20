#!/usr/bin/env python3
"""Warm-up/steady-state CUDA YOLO and positive-detection host gate."""

from __future__ import annotations

import argparse
import csv
import json
import queue
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from run_host_yolo_smoke import (  # noqa: E402
    CONFIDENCE_THRESHOLD,
    EXPECTED_CARLA_VERSION,
    IOU_THRESHOLD,
    POST_PROJECT_DISCLOSURE,
    POST_PROJECT_WEIGHT_SOURCE,
    close_logger,
    contract_is_compatible,
    convert_results,
    detection_class,
    make_logger,
    sha256_file,
    utc_now,
    write_json,
)


DEFAULT_EVIDENCE_DIR = MODULE_DIR / "evidence" / "yolo_gate"
DEFAULT_WEIGHT_PATH = MODULE_DIR / "weights" / "yolov8s.pt"
VEHICLE_BLUEPRINT = "vehicle.tesla.model3"
CAMERA_DISTANCE_METERS = 8.0
CAMERA_HEIGHT_METERS = 1.8
CAMERA_PITCH_DEGREES = -7.0


def summarize_latencies(samples, numpy_module):
    values = numpy_module.asarray(samples, dtype=float)
    return {
        "sample_count": int(values.size),
        "mean": round(float(values.mean()), 3),
        "p50": round(float(numpy_module.percentile(values, 50)), 3),
        "p95": round(float(numpy_module.percentile(values, 95)), 3),
        "max": round(float(values.max()), 3),
    }


def transform_dict(transform):
    return {
        "location": {
            "x": float(transform.location.x),
            "y": float(transform.location.y),
            "z": float(transform.location.z),
        },
        "rotation": {
            "pitch": float(transform.rotation.pitch),
            "yaw": float(transform.rotation.yaw),
            "roll": float(transform.rotation.roll),
        },
    }


def spawn_positive_scene(carla_module, world):
    blueprint_library = world.get_blueprint_library()
    vehicle_blueprint = blueprint_library.find(VEHICLE_BLUEPRINT)
    if vehicle_blueprint.has_attribute("role_name"):
        vehicle_blueprint.set_attribute("role_name", "uropclaw_validation_target")
    if vehicle_blueprint.has_attribute("color"):
        vehicle_blueprint.set_attribute("color", "0,0,255")

    target_vehicle = None
    target_transform = None
    for spawn_transform in world.get_map().get_spawn_points():
        target_vehicle = world.try_spawn_actor(vehicle_blueprint, spawn_transform)
        if target_vehicle is not None:
            target_transform = spawn_transform
            break
    if target_vehicle is None or target_transform is None:
        raise RuntimeError("No free map spawn point for positive-detection vehicle")
    target_vehicle.set_simulate_physics(False)

    forward = target_transform.get_forward_vector()
    camera_location = carla_module.Location(
        x=target_transform.location.x + forward.x * CAMERA_DISTANCE_METERS,
        y=target_transform.location.y + forward.y * CAMERA_DISTANCE_METERS,
        z=target_transform.location.z + CAMERA_HEIGHT_METERS,
    )
    camera_rotation = carla_module.Rotation(
        pitch=CAMERA_PITCH_DEGREES,
        yaw=target_transform.rotation.yaw + 180.0,
        roll=0.0,
    )
    camera_transform = carla_module.Transform(camera_location, camera_rotation)

    camera_blueprint = blueprint_library.find("sensor.camera.rgb")
    camera_blueprint.set_attribute("image_size_x", "800")
    camera_blueprint.set_attribute("image_size_y", "600")
    camera_blueprint.set_attribute("fov", "90")
    camera_blueprint.set_attribute("sensor_tick", "0.1")
    sensor = world.spawn_actor(camera_blueprint, camera_transform)
    return target_vehicle, sensor, target_transform, camera_transform


def write_latency_csv(path, rows):
    fieldnames = [
        "phase",
        "sample_index",
        "frame_id",
        "carla_timestamp",
        "latency_ms",
        "raw_boxes",
        "vehicle_detections",
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_gate(
    carla_module,
    torch_module,
    torchvision_module,
    ultralytics_module,
    cv2_module,
    numpy_module,
    yolo_factory,
    weight_path,
    weight_source,
    evidence_dir,
    host,
    port,
    timeout_seconds,
    warmup_count,
    steady_count,
):
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "environment": evidence_dir / "environment.json",
        "result": evidence_dir / "result.json",
        "input": evidence_dir / "input_frame.png",
        "annotated": evidence_dir / "annotated_frame.png",
        "warmup": evidence_dir / "warmup_latencies_ms.json",
        "steady": evidence_dir / "steady_state_latencies_ms.json",
        "samples": evidence_dir / "latency_samples.csv",
        "log": evidence_dir / "run.log",
    }
    for stale in (paths["input"], paths["annotated"]):
        if stale.exists():
            stale.unlink()

    logger = make_logger(paths["log"])
    started_at = utc_now()
    weight_path = Path(weight_path).resolve()
    environment = {
        "captured_at_utc": started_at,
        "python_version": sys.version.split()[0],
        "client_version": None,
        "server_version": None,
        "map_name": None,
        "torch_version": str(getattr(torch_module, "__version__", "unknown")),
        "torchvision_version": str(getattr(torchvision_module, "__version__", "unknown")),
        "torch_cuda_version": str(getattr(torch_module.version, "cuda", None)),
        "cuda_available": bool(torch_module.cuda.is_available()),
        "gpu_name": None,
        "ultralytics_version": str(getattr(ultralytics_module, "__version__", "unknown")),
        "opencv_version": str(getattr(cv2_module, "__version__", "unknown")),
        "numpy_version": str(getattr(numpy_module, "__version__", "unknown")),
        "weight_filename": weight_path.name,
        "weight_path": str(weight_path),
        "weight_source": weight_source,
        "weight_sha256": None,
        "weight_size_bytes": None,
        "weight_disclosure": POST_PROJECT_DISCLOSURE if weight_source == POST_PROJECT_WEIGHT_SOURCE else None,
        "system_python_modified": False,
        "system_cuda_or_driver_modified": False,
    }
    result = {
        "status": "FAIL",
        "started_at_utc": started_at,
        "finished_at_utc": None,
        "warmup_sample_count": 0,
        "steady_state_sample_count": 0,
        "warmup_latencies_excluded_from_summary": True,
        "steady_state_latency_ms": None,
        "cuda_synchronized_per_inference": True,
        "model_load_count": 0,
        "model_load_ms": None,
        "inference_device": None,
        "camera_frames_received": 0,
        "camera_frames_dropped": 0,
        "unique_frame_count": 0,
        "raw_box_count": 0,
        "positive_detection_count": 0,
        "positive_frame_count": 0,
        "detected_vehicle_classes": [],
        "positive_detection": None,
        "pipeline_detection_contract_compatible": True,
        "target_vehicle_blueprint": VEHICLE_BLUEPRINT,
        "target_vehicle_transform": None,
        "camera_transform": None,
        "input_frame_saved": False,
        "annotated_frame_saved": False,
        "sensor_stopped": False,
        "sensor_destroyed": False,
        "target_vehicle_destroyed": False,
        "error": None,
    }
    target_vehicle = None
    sensor = None
    warmup_latencies = []
    steady_latencies = []
    sample_rows = []
    measured_frame_ids = set()
    callback_counts = {"received": 0, "dropped": 0}
    first_frame_bgr = None
    last_annotated = None

    try:
        if warmup_count < 5:
            raise ValueError("warmup_count must be at least 5")
        if steady_count < 50:
            raise ValueError("steady_count must be at least 50")
        if not weight_path.is_file():
            raise FileNotFoundError("YOLO weight not found: {0}".format(weight_path))
        environment["weight_sha256"] = sha256_file(weight_path)
        environment["weight_size_bytes"] = weight_path.stat().st_size
        if not environment["cuda_available"]:
            raise RuntimeError("CUDA is unavailable; GPU YOLO gate is required")
        environment["gpu_name"] = str(torch_module.cuda.get_device_name(0))

        client = carla_module.Client(host, port)
        client.set_timeout(timeout_seconds)
        environment["client_version"] = str(client.get_client_version())
        environment["server_version"] = str(client.get_server_version())
        if (
            environment["client_version"] != EXPECTED_CARLA_VERSION
            or environment["server_version"] != EXPECTED_CARLA_VERSION
        ):
            raise RuntimeError(
                "CARLA version mismatch: client={0} server={1}".format(
                    environment["client_version"], environment["server_version"]
                )
            )
        world = client.get_world()
        environment["map_name"] = str(world.get_map().name)

        target_vehicle, sensor, target_transform, camera_transform = spawn_positive_scene(
            carla_module, world
        )
        result["target_vehicle_blueprint"] = str(target_vehicle.type_id)
        result["target_vehicle_transform"] = transform_dict(target_transform)
        result["camera_transform"] = transform_dict(camera_transform)
        logger.info(
            "Positive scene: vehicle=%s distance=%.1fm vehicle_transform=%s camera_transform=%s",
            result["target_vehicle_blueprint"],
            CAMERA_DISTANCE_METERS,
            result["target_vehicle_transform"],
            result["camera_transform"],
        )

        total_samples = warmup_count + steady_count
        frame_queue = queue.Queue(maxsize=max(100, total_samples))

        def on_frame(image):
            callback_counts["received"] += 1
            try:
                bgra = numpy_module.frombuffer(image.raw_data, dtype=numpy_module.uint8)
                bgra = bgra.reshape((image.height, image.width, 4))
                frame_bgr = bgra[:, :, :3].copy()
                frame_queue.put_nowait((image, frame_bgr))
            except queue.Full:
                callback_counts["dropped"] += 1

        sensor.listen(on_frame)

        load_started = time.perf_counter()
        model = yolo_factory(str(weight_path))
        result["model_load_ms"] = round((time.perf_counter() - load_started) * 1000.0, 3)
        result["model_load_count"] = 1
        detection_type = detection_class()
        detected_classes = set()

        for sample_index in range(total_samples):
            image, frame_bgr = frame_queue.get(timeout=timeout_seconds)
            measured_frame_ids.add(int(image.frame))
            if first_frame_bgr is None:
                first_frame_bgr = frame_bgr.copy()

            torch_module.cuda.synchronize()
            inference_started = time.perf_counter()
            inference_results = model(
                frame_bgr,
                conf=CONFIDENCE_THRESHOLD,
                iou=IOU_THRESHOLD,
                device=0,
                verbose=False,
            )
            torch_module.cuda.synchronize()
            latency_ms = round((time.perf_counter() - inference_started) * 1000.0, 3)
            result["inference_device"] = str(next(model.model.parameters()).device)

            detections, raw_boxes = convert_results(inference_results, detection_type)
            compatible = contract_is_compatible(detections, detection_type)
            result["pipeline_detection_contract_compatible"] = (
                result["pipeline_detection_contract_compatible"] and compatible
            )
            result["raw_box_count"] += raw_boxes
            result["positive_detection_count"] += len(detections)
            if detections:
                result["positive_frame_count"] += 1
                detected_classes.update(detection.class_name for detection in detections)
                if result["positive_detection"] is None:
                    result["positive_detection"] = asdict(detections[0])
                    result["input_frame_saved"] = bool(
                        cv2_module.imwrite(str(paths["input"]), frame_bgr)
                    )
                    plotted = inference_results[0].plot()
                    result["annotated_frame_saved"] = bool(
                        cv2_module.imwrite(str(paths["annotated"]), plotted)
                    )

            last_annotated = inference_results[0].plot() if inference_results else frame_bgr
            phase = "warmup" if sample_index < warmup_count else "steady_state"
            phase_index = sample_index if phase == "warmup" else sample_index - warmup_count
            if phase == "warmup":
                warmup_latencies.append(latency_ms)
            else:
                steady_latencies.append(latency_ms)
            sample_rows.append(
                {
                    "phase": phase,
                    "sample_index": phase_index,
                    "frame_id": int(image.frame),
                    "carla_timestamp": float(image.timestamp),
                    "latency_ms": latency_ms,
                    "raw_boxes": raw_boxes,
                    "vehicle_detections": len(detections),
                }
            )
            logger.info(
                "Inference phase=%s index=%s frame=%s latency_ms=%.3f raw_boxes=%s vehicle_detections=%s",
                phase,
                phase_index,
                image.frame,
                latency_ms,
                raw_boxes,
                len(detections),
            )

        if not result["input_frame_saved"] and first_frame_bgr is not None:
            result["input_frame_saved"] = bool(
                cv2_module.imwrite(str(paths["input"]), first_frame_bgr)
            )
        if not result["annotated_frame_saved"] and last_annotated is not None:
            result["annotated_frame_saved"] = bool(
                cv2_module.imwrite(str(paths["annotated"]), last_annotated)
            )

        result["warmup_sample_count"] = len(warmup_latencies)
        result["steady_state_sample_count"] = len(steady_latencies)
        result["steady_state_latency_ms"] = summarize_latencies(
            steady_latencies, numpy_module
        )
        result["detected_vehicle_classes"] = sorted(detected_classes)
        result["camera_frames_received"] = callback_counts["received"]
        result["camera_frames_dropped"] = callback_counts["dropped"]
        result["unique_frame_count"] = len(measured_frame_ids)
        result["input_frame_saved"] = (
            result["input_frame_saved"]
            and paths["input"].is_file()
            and paths["input"].stat().st_size > 0
        )
        result["annotated_frame_saved"] = (
            result["annotated_frame_saved"]
            and paths["annotated"].is_file()
            and paths["annotated"].stat().st_size > 0
        )
        result["status"] = "PASS" if (
            result["warmup_sample_count"] >= 5
            and result["steady_state_sample_count"] >= 50
            and result["unique_frame_count"] == total_samples
            and result["model_load_count"] == 1
            and result["inference_device"] is not None
            and result["inference_device"].startswith("cuda")
            and result["positive_detection_count"] > 0
            and result["positive_frame_count"] > 0
            and result["pipeline_detection_contract_compatible"]
            and result["input_frame_saved"]
            and result["annotated_frame_saved"]
        ) else "FAIL"
    except Exception as exc:
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        logger.exception("Host YOLO gate failed")
    finally:
        if sensor is not None:
            try:
                sensor.stop()
                result["sensor_stopped"] = True
            except Exception:
                logger.exception("Failed to stop validation camera")
            try:
                sensor.destroy()
                result["sensor_destroyed"] = True
            except Exception:
                logger.exception("Failed to destroy validation camera")
        if target_vehicle is not None:
            try:
                target_vehicle.destroy()
                result["target_vehicle_destroyed"] = True
            except Exception:
                logger.exception("Failed to destroy validation target vehicle")

        if result["status"] == "PASS" and not (
            result["sensor_stopped"]
            and result["sensor_destroyed"]
            and result["target_vehicle_destroyed"]
        ):
            result["status"] = "FAIL"
            result["error"] = {
                "type": "ActorCleanupError",
                "message": "Validation camera or target vehicle cleanup was incomplete",
                "traceback": None,
            }

        result["finished_at_utc"] = utc_now()
        write_json(paths["environment"], environment)
        write_json(paths["warmup"], warmup_latencies)
        write_json(paths["steady"], steady_latencies)
        write_latency_csv(paths["samples"], sample_rows)
        write_json(paths["result"], result)
        logger.info(
            "Gate result=%s warmup=%s steady=%s positive_detections=%s",
            result["status"],
            result["warmup_sample_count"],
            result["steady_state_sample_count"],
            result["positive_detection_count"],
        )
        close_logger(logger)

    return 0 if result["status"] == "PASS" else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=30.0, dest="timeout_seconds")
    parser.add_argument("--warmup", type=int, default=10, dest="warmup_count")
    parser.add_argument("--steady", type=int, default=50, dest="steady_count")
    parser.add_argument("--weight", type=Path, default=DEFAULT_WEIGHT_PATH)
    parser.add_argument("--weight-source", default=POST_PROJECT_WEIGHT_SOURCE)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        import carla
        import cv2
        import numpy as np
        import torch
        import torchvision
        import ultralytics
        from ultralytics import YOLO
    except Exception as exc:
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(args.evidence_dir / "result.json", {"status": "FAIL", "error": error})
        (args.evidence_dir / "run.log").write_text(error["traceback"], encoding="utf-8")
        print("Dependency import failed: {0}".format(exc), file=sys.stderr)
        return 1

    return run_gate(
        carla_module=carla,
        torch_module=torch,
        torchvision_module=torchvision,
        ultralytics_module=ultralytics,
        cv2_module=cv2,
        numpy_module=np,
        yolo_factory=YOLO,
        weight_path=args.weight,
        weight_source=args.weight_source,
        evidence_dir=args.evidence_dir,
        host=args.host,
        port=args.port,
        timeout_seconds=args.timeout_seconds,
        warmup_count=args.warmup_count,
        steady_count=args.steady_count,
    )


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Run one real-CARLA-frame, CUDA YOLOv8 smoke test on the host."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import queue
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_CARLA_VERSION = "0.9.13"
TARGET_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
CONFIDENCE_THRESHOLD = 0.40
IOU_THRESHOLD = 0.45
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence" / "yolo_smoke"
DEFAULT_WEIGHT_PATH = Path(__file__).resolve().parent / "weights" / "yolov8s.pt"
POST_PROJECT_WEIGHT_SOURCE = "Ultralytics pretrained YOLOv8s asset obtained after the original project"
POST_PROJECT_DISCLOSURE = (
    "Post-project CARLA validation used a newly obtained pretrained YOLOv8s "
    "weight because the original research weight was unavailable."
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def make_logger(path):
    logger = logging.getLogger("uropclaw.host_yolo_smoke.{0}".format(time.time_ns()))
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.FileHandler(str(path), mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def close_logger(logger):
    for handler in list(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)


def detection_class():
    harness_path = str(ROOT / "harness")
    if harness_path not in sys.path:
        sys.path.insert(0, harness_path)
    from perception.yolo_detector import Detection

    return Detection


def convert_results(results, detection_type):
    """Convert Ultralytics boxes to the existing UROP Detection contract."""
    converted = []
    raw_box_count = 0
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        raw_box_count += len(boxes)
        for box in boxes:
            class_id = int(box.cls[0])
            if class_id not in TARGET_CLASSES:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            converted.append(
                detection_type(
                    bbox=[int(x1), int(y1), int(x2), int(y2)],
                    class_id=class_id,
                    class_name=TARGET_CLASSES[class_id],
                    confidence=float(box.conf[0]),
                )
            )
    return converted, raw_box_count


def contract_is_compatible(detections, detection_type):
    if not isinstance(detections, list):
        return False
    for detection in detections:
        if not isinstance(detection, detection_type):
            return False
        if not isinstance(detection.bbox, list) or len(detection.bbox) != 4:
            return False
        if not all(isinstance(value, int) for value in detection.bbox):
            return False
        if not isinstance(detection.class_id, int):
            return False
        if not isinstance(detection.class_name, str):
            return False
        if not isinstance(detection.confidence, float):
            return False
    return True


def run_yolo_smoke(
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
):
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    input_path = evidence_dir / "input_frame.png"
    annotated_path = evidence_dir / "annotated_frame.png"
    result_path = evidence_dir / "result.json"
    environment_path = evidence_dir / "environment.json"
    log_path = evidence_dir / "run.log"
    for stale_path in (input_path, annotated_path):
        if stale_path.exists():
            stale_path.unlink()

    logger = make_logger(log_path)
    weight_path = Path(weight_path).resolve()
    started_at = utc_now()
    environment = {
        "captured_at_utc": started_at,
        "python_version": sys.version.split()[0],
        "carla_module_version": str(getattr(carla_module, "__version__", "not_exposed")),
        "client_version": None,
        "server_version": None,
        "map_name": None,
        "torch_version": str(getattr(torch_module, "__version__", "unknown")),
        "torchvision_version": str(getattr(torchvision_module, "__version__", "unknown")),
        "cuda_available": bool(torch_module.cuda.is_available()),
        "torch_cuda_version": str(getattr(torch_module.version, "cuda", None)),
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
        "actual_carla_frame": False,
        "frame": None,
        "input_frame_saved": False,
        "annotated_frame_saved": False,
        "model_loaded": False,
        "model_load_ms": None,
        "inference_succeeded": False,
        "inference_latency_ms": None,
        "inference_device": None,
        "raw_model_boxes": None,
        "vehicle_detections": None,
        "detections": [],
        "detection_output_type": "list[perception.yolo_detector.Detection]",
        "pipeline_detection_contract_compatible": False,
        "sensor_stopped": False,
        "sensor_destroyed": False,
        "error": None,
    }
    sensor = None

    try:
        if not weight_path.is_file():
            raise FileNotFoundError("YOLO weight not found: {0}".format(weight_path))
        environment["weight_sha256"] = sha256_file(weight_path)
        environment["weight_size_bytes"] = weight_path.stat().st_size
        logger.info(
            "Weight: %s sha256=%s source=%s",
            weight_path,
            environment["weight_sha256"],
            weight_source,
        )

        if not environment["cuda_available"]:
            raise RuntimeError("CUDA is unavailable; GPU YOLO smoke is required")
        environment["gpu_name"] = str(torch_module.cuda.get_device_name(0))
        logger.info(
            "CUDA available: torch=%s torch_cuda=%s gpu=%s",
            environment["torch_version"],
            environment["torch_cuda_version"],
            environment["gpu_name"],
        )

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
        logger.info(
            "Connected to CARLA: client=%s server=%s map=%s",
            environment["client_version"],
            environment["server_version"],
            environment["map_name"],
        )

        blueprint = world.get_blueprint_library().find("sensor.camera.rgb")
        blueprint.set_attribute("image_size_x", "800")
        blueprint.set_attribute("image_size_y", "600")
        blueprint.set_attribute("sensor_tick", "0.1")
        sensor = world.spawn_actor(blueprint, world.get_spectator().get_transform())

        frame_queue = queue.Queue(maxsize=1)

        def on_frame(image):
            try:
                bgra = numpy_module.frombuffer(image.raw_data, dtype=numpy_module.uint8)
                bgra = bgra.reshape((image.height, image.width, 4))
                frame_bgr = bgra[:, :, :3].copy()
                frame_queue.put_nowait((image, frame_bgr))
            except queue.Full:
                return

        sensor.listen(on_frame)
        image, frame_bgr = frame_queue.get(timeout=timeout_seconds)
        result["actual_carla_frame"] = True
        result["frame"] = {
            "frame_id": int(image.frame),
            "timestamp": float(image.timestamp),
            "width": int(image.width),
            "height": int(image.height),
            "shape_bgr": list(frame_bgr.shape),
        }
        result["input_frame_saved"] = bool(cv2_module.imwrite(str(input_path), frame_bgr))
        result["input_frame_saved"] = (
            result["input_frame_saved"] and input_path.is_file() and input_path.stat().st_size > 0
        )
        logger.info(
            "CARLA RGB frame: id=%s timestamp=%.6f shape=%s",
            result["frame"]["frame_id"],
            result["frame"]["timestamp"],
            result["frame"]["shape_bgr"],
        )

        load_started = time.perf_counter()
        model = yolo_factory(str(weight_path))
        result["model_load_ms"] = round((time.perf_counter() - load_started) * 1000.0, 3)
        result["model_loaded"] = True
        logger.info("YOLO model loaded in %.3f ms", result["model_load_ms"])

        torch_module.cuda.synchronize()
        inference_started = time.perf_counter()
        results = model(
            frame_bgr,
            conf=CONFIDENCE_THRESHOLD,
            iou=IOU_THRESHOLD,
            device=0,
            verbose=False,
        )
        torch_module.cuda.synchronize()
        result["inference_latency_ms"] = round(
            (time.perf_counter() - inference_started) * 1000.0, 3
        )
        result["inference_device"] = str(next(model.model.parameters()).device)
        result["inference_succeeded"] = True

        detection_type = detection_class()
        detections, raw_box_count = convert_results(results, detection_type)
        result["raw_model_boxes"] = raw_box_count
        result["vehicle_detections"] = len(detections)
        result["detections"] = [asdict(detection) for detection in detections]
        result["pipeline_detection_contract_compatible"] = contract_is_compatible(
            detections, detection_type
        )

        annotated = results[0].plot() if results else frame_bgr
        result["annotated_frame_saved"] = bool(
            cv2_module.imwrite(str(annotated_path), annotated)
        )
        result["annotated_frame_saved"] = (
            result["annotated_frame_saved"]
            and annotated_path.is_file()
            and annotated_path.stat().st_size > 0
        )
        logger.info(
            "Inference: device=%s latency_ms=%.3f raw_boxes=%s vehicle_detections=%s contract=%s",
            result["inference_device"],
            result["inference_latency_ms"],
            result["raw_model_boxes"],
            result["vehicle_detections"],
            result["pipeline_detection_contract_compatible"],
        )

        result["status"] = "PASS" if (
            result["actual_carla_frame"]
            and result["input_frame_saved"]
            and result["annotated_frame_saved"]
            and result["model_loaded"]
            and result["inference_succeeded"]
            and result["inference_device"].startswith("cuda")
            and result["pipeline_detection_contract_compatible"]
        ) else "FAIL"
    except Exception as exc:
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        logger.exception("Host YOLO smoke failed")
    finally:
        if sensor is not None:
            try:
                sensor.stop()
                result["sensor_stopped"] = True
                logger.info("Stopped RGB camera sensor")
            except Exception:
                logger.exception("Failed to stop RGB camera sensor")
            try:
                sensor.destroy()
                result["sensor_destroyed"] = True
                logger.info("Destroyed RGB camera sensor")
            except Exception:
                logger.exception("Failed to destroy RGB camera sensor")
        if result["status"] == "PASS" and (
            not result["sensor_stopped"] or not result["sensor_destroyed"]
        ):
            result["status"] = "FAIL"
            result["error"] = {
                "type": "SensorCleanupError",
                "message": "RGB sensor cleanup was incomplete",
                "traceback": None,
            }

        result["finished_at_utc"] = utc_now()
        write_json(environment_path, environment)
        write_json(result_path, result)
        logger.info("YOLO smoke result=%s", result["status"])
        logger.info("Wrote environment evidence to %s", environment_path)
        logger.info("Wrote result evidence to %s", result_path)
        close_logger(logger)

    return 0 if result["status"] == "PASS" else 1


def write_bootstrap_failure(evidence_dir, exc):
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    error = {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }
    now = utc_now()
    write_json(
        evidence_dir / "environment.json",
        {"captured_at_utc": now, "python_version": sys.version.split()[0], "error": error},
    )
    write_json(
        evidence_dir / "result.json",
        {"status": "FAIL", "started_at_utc": now, "finished_at_utc": now, "error": error},
    )
    (evidence_dir / "run.log").write_text(
        "Dependency import failed: {0}: {1}\n{2}".format(
            type(exc).__name__, exc, error["traceback"]
        ),
        encoding="utf-8",
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=30.0, dest="timeout_seconds")
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
        write_bootstrap_failure(args.evidence_dir, exc)
        print("Dependency import failed: {0}".format(exc), file=sys.stderr)
        return 1

    return run_yolo_smoke(
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
    )


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Host-side CARLA 0.9.13 RGB camera smoke test.

This runner is intentionally separate from the UROPCLAW production pipeline. It
must be run from a normal host terminal that can reach the already-running
CARLA server.
"""

import argparse
import json
import logging
import queue
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_CARLA_VERSION = "0.9.13"
DEFAULT_EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence" / "host_smoke"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def make_logger(log_path):
    logger = logging.getLogger("uropclaw.carla_host_smoke.{0}".format(time.time_ns()))
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def write_result(path, result):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_smoke(carla_module, evidence_dir, host, port, timeout_seconds, requested_frames):
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    result_path = evidence_dir / "result.json"
    frame_path = evidence_dir / "frame.png"
    log_path = evidence_dir / "run.log"
    if frame_path.exists():
        frame_path.unlink()

    logger = make_logger(log_path)
    result = {
        "status": "FAIL",
        "expected_carla_version": EXPECTED_CARLA_VERSION,
        "host": host,
        "port": port,
        "timeout_seconds": timeout_seconds,
        "requested_frames": requested_frames,
        "started_at_utc": utc_now(),
        "finished_at_utc": None,
        "client_version": None,
        "server_version": None,
        "versions_match_expected": False,
        "world_query_succeeded": False,
        "map_name": None,
        "synchronous_mode": None,
        "camera_blueprint": "sensor.camera.rgb",
        "camera_spawned": False,
        "frames_received": 0,
        "frames": [],
        "frame_evidence_path": str(frame_path),
        "frame_evidence_saved": False,
        "callback_errors": [],
        "sensor_stopped": False,
        "sensor_destroyed": False,
        "error": None,
    }
    sensor = None
    callback_queue = queue.Queue()
    first_frame_lock = threading.Lock()
    first_frame_claimed = [False]

    def on_frame(image):
        metadata = {
            "frame_id": int(image.frame),
            "width": int(image.width),
            "height": int(image.height),
            "timestamp": float(image.timestamp),
        }
        should_save = False
        with first_frame_lock:
            if not first_frame_claimed[0]:
                first_frame_claimed[0] = True
                should_save = True
        if should_save:
            try:
                image.save_to_disk(str(frame_path))
                logger.info("Saved first RGB frame to %s", frame_path)
            except Exception as exc:  # callback failures must survive in evidence
                result["callback_errors"].append(
                    {"type": type(exc).__name__, "message": str(exc)}
                )
                logger.exception("Failed to save first RGB frame")
        callback_queue.put(metadata)

    try:
        if requested_frames < 1:
            raise ValueError("requested_frames must be at least 1")

        logger.info("Connecting CARLA client to %s:%s", host, port)
        client = carla_module.Client(host, port)
        client.set_timeout(timeout_seconds)

        result["client_version"] = str(client.get_client_version())
        result["server_version"] = str(client.get_server_version())
        result["versions_match_expected"] = (
            result["client_version"] == EXPECTED_CARLA_VERSION
            and result["server_version"] == EXPECTED_CARLA_VERSION
        )
        logger.info(
            "CARLA versions: client=%s server=%s",
            result["client_version"],
            result["server_version"],
        )

        world = client.get_world()
        result["map_name"] = str(world.get_map().name)
        result["world_query_succeeded"] = True
        settings = world.get_settings()
        result["synchronous_mode"] = bool(settings.synchronous_mode)
        logger.info(
            "World query succeeded: map=%s synchronous_mode=%s",
            result["map_name"],
            result["synchronous_mode"],
        )

        blueprint = world.get_blueprint_library().find("sensor.camera.rgb")
        blueprint.set_attribute("image_size_x", "800")
        blueprint.set_attribute("image_size_y", "600")
        blueprint.set_attribute("sensor_tick", "0.1")
        camera_transform = world.get_spectator().get_transform()
        sensor = world.spawn_actor(blueprint, camera_transform)
        result["camera_spawned"] = True
        logger.info("Spawned RGB camera at the current spectator transform")
        sensor.listen(on_frame)

        deadline = time.monotonic() + timeout_seconds
        while len(result["frames"]) < requested_frames:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if result["synchronous_mode"]:
                world.tick(min(remaining, timeout_seconds))
            try:
                metadata = callback_queue.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            result["frames"].append(metadata)
            logger.info(
                "RGB frame received: id=%s timestamp=%.6f size=%sx%s",
                metadata["frame_id"],
                metadata["timestamp"],
                metadata["width"],
                metadata["height"],
            )

        result["frames_received"] = len(result["frames"])
        result["frame_evidence_saved"] = (
            frame_path.is_file() and frame_path.stat().st_size > 0
        )
        result["status"] = "PASS" if (
            result["versions_match_expected"]
            and result["world_query_succeeded"]
            and result["camera_spawned"]
            and result["frames_received"] >= 1
            and result["frame_evidence_saved"]
        ) else "FAIL"
        logger.info(
            "Smoke result=%s frames_received=%s frame_saved=%s",
            result["status"],
            result["frames_received"],
            result["frame_evidence_saved"],
        )
    except Exception as exc:
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        logger.exception("Host smoke test failed")
    finally:
        if sensor is not None:
            try:
                sensor.stop()
                result["sensor_stopped"] = True
                logger.info("Stopped RGB camera sensor")
            except Exception as exc:
                logger.exception("Failed to stop RGB camera sensor")
                result["callback_errors"].append(
                    {"type": type(exc).__name__, "message": "sensor.stop: {0}".format(exc)}
                )
            try:
                sensor.destroy()
                result["sensor_destroyed"] = True
                logger.info("Destroyed RGB camera sensor")
            except Exception as exc:
                logger.exception("Failed to destroy RGB camera sensor")
                result["callback_errors"].append(
                    {"type": type(exc).__name__, "message": "sensor.destroy: {0}".format(exc)}
                )

        if result["status"] == "PASS" and (
            not result["sensor_stopped"] or not result["sensor_destroyed"]
        ):
            result["status"] = "FAIL"
            logger.error("Smoke result changed to FAIL because sensor cleanup was incomplete")

        result["finished_at_utc"] = utc_now()
        write_result(result_path, result)
        logger.info("Wrote result evidence to %s", result_path)
        for handler in list(logger.handlers):
            handler.flush()
            handler.close()
            logger.removeHandler(handler)

    return 0 if result["status"] == "PASS" else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=20.0, dest="timeout_seconds")
    parser.add_argument("--frames", type=int, default=10, dest="requested_frames")
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        import carla
    except Exception as exc:
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "status": "FAIL",
            "started_at_utc": utc_now(),
            "finished_at_utc": utc_now(),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        }
        write_result(args.evidence_dir / "result.json", result)
        (args.evidence_dir / "run.log").write_text(
            "Failed to import CARLA Python API: {0}: {1}\n".format(
                type(exc).__name__, exc
            ),
            encoding="utf-8",
        )
        print("Failed to import CARLA Python API: {0}".format(exc), file=sys.stderr)
        return 1

    return run_smoke(
        carla_module=carla,
        evidence_dir=args.evidence_dir,
        host=args.host,
        port=args.port,
        timeout_seconds=args.timeout_seconds,
        requested_frames=args.requested_frames,
    )


if __name__ == "__main__":
    sys.exit(main())

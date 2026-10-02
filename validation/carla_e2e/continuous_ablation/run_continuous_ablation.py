#!/usr/bin/env python3
"""Experiment B: continuous CARLA traffic with a 4-way shadow ablation.

One synchronous CARLA run (default 600 s simulation time at 10 Hz). Every
camera frame is run through Real YOLO exactly once; the same frame, detections
and HSV colours are fanned out to four independent shadow branches (Full,
No HSV, No Temporal, No Dedup; see branches.py). VLM requests are recorded as
triggers only; no VLM is called. CARLA ground truth (projected boxes,
line-of-sight, actor colour) is evidence only and never reaches a branch.
"""

from __future__ import annotations

import argparse
import collections
import csv
import faulthandler
import json
import logging
import math
import os
import sys
import time
import traceback
from contextlib import ExitStack
from pathlib import Path


HERE = Path(__file__).resolve().parent
CARLA_E2E_DIR = HERE.parent
REPOSITORY_ROOT = CARLA_E2E_DIR.parents[1]
MULTIVEHICLE_DIR = CARLA_E2E_DIR / "multivehicle"
DEFAULT_WEIGHT = CARLA_E2E_DIR / "weights" / "yolov8s.pt"
DEFAULT_CAMERA_MANIFEST = MULTIVEHICLE_DIR / "evidence" / "benchmark" / "target_scene_manifest.json"
TARGET_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
TARGET_COLOR = "blue"
TARGET_RGB = "0,0,255"
# Deterministic paint palette; blue is one of eight colours. The number of
# blue actors that actually enter the camera view is not controlled.
PALETTE = (
    "0,0,255", "255,0,0", "255,255,255", "10,10,10",
    "150,150,150", "0,200,0", "255,255,0", "255,140,0",
)
ROLE_PREFIX = "uropclaw_validation_cont_"
MIN_VISIBLE_HEIGHT_PX = 12
MAX_VISIBLE_DISTANCE_M = 80.0

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(MULTIVEHICLE_DIR))
from branches import BRANCH_CONFIGS, SimClock, make_branches  # noqa: E402
from scene import (  # noqa: E402
    _sorted_spawn_points, deterministic_assignments, synchronous_mode, transform_from_dict,
)
from run_host_smoke import (  # noqa: E402
    SensorFrameTimeout, SynchronousSensorStream, cleanup_stale_validation_actors,
    shutdown_scene_resources, validate_carla_versions,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--tm-port", type=int, default=8000)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--sensor-timeout", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--vehicles", type=int, default=70)
    parser.add_argument("--duration-seconds", type=float, default=600.0)
    parser.add_argument("--pre-roll-seconds", type=float, default=5.0)
    parser.add_argument("--model-warmup", type=int, default=10)
    parser.add_argument("--sample-interval-seconds", type=float, default=60.0)
    parser.add_argument("--weight", type=Path, default=DEFAULT_WEIGHT)
    parser.add_argument("--camera-manifest", type=Path, default=DEFAULT_CAMERA_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=HERE)
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument("--label", default="full_10min")
    parser.add_argument("--cleanup-stale-validation-actors", action="store_true")
    return parser.parse_args(argv)


# ---------------------------------------------------------------- utilities

def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q / 100.0
    lower, upper = int(math.floor(position)), int(math.ceil(position))
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bbox_iou(left, right):
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = (left[2] - left[0]) * (left[3] - left[1]) + (right[2] - right[0]) * (right[3] - right[1]) - inter
    return inter / float(union) if union > 0 else 0.0


def best_actor(bbox, actor_boxes, threshold=0.30):
    best_id, best_iou = None, threshold
    for actor_id, box in actor_boxes.items():
        value = bbox_iou(bbox, box)
        if value >= best_iou:
            best_id, best_iou = actor_id, value
    return best_id


def rss_mb():
    try:
        with open("/proc/self/status", encoding="utf-8") as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024.0, 1)
    except OSError:
        pass
    return None


def write_csv(path, fieldnames, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def setup_logging(paths):
    logger = logging.getLogger("continuous-ablation")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers[:] = []
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    for path in paths:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(str(path), mode="w", encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    return logger


# ---------------------------------------------------------------- ground truth

class GroundTruth:
    """Evidence-only projection of CARLA vehicles into the fixed camera."""

    def __init__(self, carla_module, world, camera_transform, width, height, fov, np):
        self.carla = carla_module
        self.world = world
        self.np = np
        self.inverse = np.asarray(camera_transform.get_inverse_matrix(), dtype=float)
        self.camera_location = camera_transform.location
        self.width, self.height = width, height
        self.focal = width / (2.0 * math.tan(math.radians(fov) / 2.0))
        self.raycasts = 0

    def project(self, actor, transform):
        vertices = actor.bounding_box.get_world_vertices(transform)
        points = self.np.asarray([[v.x, v.y, v.z, 1.0] for v in vertices], dtype=float)
        sensor = points.dot(self.inverse.T)
        depth, right, down = sensor[:, 0], sensor[:, 1], -sensor[:, 2]
        front = depth > 0.1
        if not front.any():
            return None, None
        u = self.focal * right[front] / depth[front] + self.width / 2.0
        v = self.focal * down[front] / depth[front] + self.height / 2.0
        x1, y1, x2, y2 = u.min(), v.min(), u.max(), v.max()
        if x2 < 0 or y2 < 0 or x1 >= self.width or y1 >= self.height:
            return None, None
        box = [max(0, int(x1)), max(0, int(y1)), min(self.width - 1, int(x2)), min(self.height - 1, int(y2))]
        if box[2] <= box[0] or box[3] <= box[1]:
            return None, None
        centre = points[:, :3].mean(axis=0)
        return box, centre

    def line_of_sight(self, centre, extent):
        target = self.carla.Location(x=float(centre[0]), y=float(centre[1]), z=float(centre[2]))
        distance = self.camera_location.distance(target)
        self.raycasts += 1
        for hit in self.world.cast_ray(self.camera_location, target):
            if self.camera_location.distance(hit.location) < distance - extent - 0.5:
                return False
        return True

    def frame(self, actors, snapshot):
        projected, visible = {}, {}
        for actor in actors:
            state = snapshot.find(actor.id)
            if state is None:
                continue
            box, centre = self.project(actor, state.get_transform())
            if box is None or box[3] - box[1] < MIN_VISIBLE_HEIGHT_PX:
                continue
            projected[actor.id] = box
            target = self.carla.Location(x=float(centre[0]), y=float(centre[1]), z=float(centre[2]))
            if self.camera_location.distance(target) > MAX_VISIBLE_DISTANCE_M:
                continue
            extent = actor.bounding_box.extent
            if self.line_of_sight(centre, max(extent.x, extent.y)):
                visible[actor.id] = box
        return projected, visible


# ---------------------------------------------------------------- scene

def spawn_traffic(carla_module, world, tm, args, logger):
    library = world.get_blueprint_library()
    blueprints = [
        bp for bp in library.filter("vehicle.*")
        if bp.has_attribute("number_of_wheels") and bp.get_attribute("number_of_wheels").as_int() == 4
        and bp.has_attribute("color")
    ]
    assignments = deterministic_assignments([bp.id for bp in blueprints], PALETTE, args.vehicles, args.seed)
    import random
    spawn_points = _sorted_spawn_points(world.get_map())
    random.Random(args.seed).shuffle(spawn_points)
    actors, plan, failures = [], [], []
    for index, (blueprint_id, color) in enumerate(assignments):
        if index >= len(spawn_points):
            failures.append({"slot": index, "reason": "no spawn point"})
            continue
        blueprint = library.find(blueprint_id)
        blueprint.set_attribute("color", color)
        if blueprint.has_attribute("role_name"):
            blueprint.set_attribute("role_name", "{0}{1:03d}".format(ROLE_PREFIX, index))
        actor = world.try_spawn_actor(blueprint, spawn_points[index])
        if actor is None:
            failures.append({"slot": index, "blueprint": blueprint_id, "reason": "try_spawn_actor returned None"})
            continue
        actor.set_autopilot(True, args.tm_port)
        actors.append(actor)
        plan.append({
            "slot": index, "actor_id": int(actor.id), "blueprint": blueprint_id, "color": color,
            "is_target_color": color == TARGET_RGB,
        })
    logger.info("Spawned %d/%d traffic vehicles (%d failures)", len(actors), args.vehicles, len(failures))
    return actors, plan, failures


# ---------------------------------------------------------------- main run

def run(args):
    output_dir = Path(args.output_dir)
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else output_dir / "evidence"
    samples_dir = evidence_dir / "samples"
    logger = setup_logging([output_dir / "run.log"])
    faulthandler.enable(all_threads=True)

    import carla
    import cv2
    import numpy as np
    import torch
    import ultralytics
    from ultralytics import YOLO

    sys.path.insert(0, str(REPOSITORY_ROOT / "harness"))
    import perception.iou_tracker as iou_tracker_mod
    from perception.color_filter import classify_color
    from perception.deduplicator import Deduplicator
    from perception.temporal_confirm import TemporalConfirm
    from perception.yolo_detector import Detection

    clock = SimClock()
    iou_tracker_mod.time = clock  # tracker reconnect window on simulation time
    branches = make_branches(iou_tracker_mod.IoUTracker, TemporalConfirm, Deduplicator, TARGET_COLOR)

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    validate_carla_versions(client.get_client_version(), client.get_server_version())
    world = client.get_world()
    tm = client.get_trafficmanager(args.tm_port)
    camera_manifest = json.loads(Path(args.camera_manifest).read_text(encoding="utf-8"))
    if camera_manifest["planned_scene"]["map"] != world.get_map().name:
        raise RuntimeError("camera manifest map {0} != world map {1}".format(
            camera_manifest["planned_scene"]["map"], world.get_map().name))
    stale = cleanup_stale_validation_actors(
        list(world.get_actors().filter("vehicle.*")), enabled=args.cleanup_stale_validation_actors)
    foreign = list(world.get_actors().filter("vehicle.*"))
    if foreign:
        raise RuntimeError("world has {0} vehicles not created by this validation".format(len(foreign)))

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    model = YOLO(str(args.weight))
    model.to("cuda:0")
    environment = {
        "experiment": "B: continuous monitoring / pipeline efficiency ablation",
        "label": args.label,
        "carla_client_version": client.get_client_version(),
        "carla_server_version": client.get_server_version(),
        "map": world.get_map().name,
        "python": sys.version.split()[0],
        "torch": torch.__version__, "torch_cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "ultralytics": ultralytics.__version__, "opencv": cv2.__version__,
        "yolo_weight": args.weight.name,
        "yolo_confidence": 0.40, "yolo_iou": 0.45,
        "yolo_weight_source": "post-project pretrained YOLOv8s weight",
        "seed": args.seed, "requested_vehicles": args.vehicles,
        "fixed_delta_seconds": 0.1, "camera": {"width": 800, "height": 600, "fov": 90, "sensor_tick": 0.0},
        "camera_manifest": str(Path(args.camera_manifest).relative_to(REPOSITORY_ROOT)),
        "duration_seconds_requested": args.duration_seconds,
        "pre_roll_seconds": args.pre_roll_seconds,
        "target_color": TARGET_COLOR, "palette": list(PALETTE),
        "branches": {name: flags for name, flags in BRANCH_CONFIGS},
        "time_basis": "simulation time for temporal, dedup and tracker reconnect windows",
        "stale_validation_cleanup": stale,
    }

    def detect(frame):
        torch.cuda.synchronize()
        started = time.perf_counter()
        results = model(frame, conf=0.40, iou=0.45, device=0, verbose=False)
        torch.cuda.synchronize()
        elapsed = (time.perf_counter() - started) * 1000.0
        detections = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                class_id = int(box.cls[0])
                if class_id not in TARGET_CLASSES:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(Detection(
                    bbox=[int(x1), int(y1), int(x2), int(y2)], class_id=class_id,
                    class_name=TARGET_CLASSES[class_id], confidence=float(box.conf[0]),
                ))
        return detections, elapsed

    owned, camera, stream = [], None, None
    frame_rows, trigger_rows = [], []
    candidate_assoc = {name: collections.Counter() for name, _ in BRANCH_CONFIGS}
    trigger_tracks = {name: set() for name, _ in BRANCH_CONFIGS}
    trigger_actors = {name: set() for name, _ in BRANCH_CONFIGS}
    target_candidate_actors = {name: set() for name, _ in BRANCH_CONFIGS}
    actor_stats = {}
    minute_stats = collections.defaultdict(lambda: {
        "visible_actors": set(), "target_actors": set(), "yolo_detections": 0, "frames": 0,
        "visible_sum": 0, "triggers": collections.Counter(), "frames_with_detection": 0,
    })
    minute_positions = {}
    memory_samples = []
    dropped_frames = []
    branch_exceptions = []
    yolo_latency = []
    status, error, cleanup = "RUNNING", None, None
    traffic_plan, spawn_failures = [], []
    t0 = None
    gt = None
    try:
        with ExitStack() as stack:
            stack.enter_context(synchronous_mode(world, tm, args.seed, 0.1))

            def _cleanup():
                nonlocal cleanup
                cleanup = shutdown_scene_resources(stream, camera, owned, world, args.tm_port, args.timeout)
                logger.info("Cleanup result: %s", json.dumps(cleanup, sort_keys=True))
            stack.callback(_cleanup)

            traffic, traffic_plan, spawn_failures = spawn_traffic(carla, world, tm, args, logger)
            owned.extend(traffic)
            plan_by_id = {item["actor_id"]: item for item in traffic_plan}
            camera_bp = world.get_blueprint_library().find("sensor.camera.rgb")
            camera_bp.set_attribute("image_size_x", "800")
            camera_bp.set_attribute("image_size_y", "600")
            camera_bp.set_attribute("fov", "90")
            camera_bp.set_attribute("sensor_tick", "0.0")
            camera_transform = transform_from_dict(carla, camera_manifest["planned_scene"]["camera"]["transform"])
            camera = world.spawn_actor(camera_bp, camera_transform)
            owned.append(camera)
            gt = GroundTruth(carla, world, camera_transform, 800, 600, 90.0, np)
            stream = SynchronousSensorStream(camera)
            stream.start()
            stream.wait_until_ready(world, args.timeout, args.sensor_timeout, 10)

            logger.info("Phase: pre_roll (%d ticks)", int(round(args.pre_roll_seconds / 0.1)))
            for tick in range(int(round(args.pre_roll_seconds / 0.1))):
                _, image = stream.tick_and_wait(world, args.timeout, args.sensor_timeout)
                if tick < args.model_warmup:
                    frame = np.frombuffer(image.raw_data, dtype=np.uint8).reshape((600, 800, 4))[:, :, :3].copy()
                    detect(frame)

            total_frames = int(round(args.duration_seconds / 0.1))
            next_sample = 0.0
            logger.info("Phase: measurement (%d frames, %d branches)", total_frames, len(branches))
            wall_started = time.time()
            for index in range(total_frames):
                try:
                    carla_frame, image = stream.tick_and_wait(world, args.timeout, args.sensor_timeout)
                except SensorFrameTimeout as timeout_error:
                    dropped_frames.append({"index": index, "expected_frame": timeout_error.expected_frame})
                    logger.warning("Dropped frame %d: %s", index, timeout_error)
                    continue
                snapshot = world.get_snapshot()
                sim_time = snapshot.timestamp.elapsed_seconds
                if t0 is None:
                    t0 = sim_time
                rel = round(sim_time - t0, 3)
                minute = int(rel // 60)
                clock.now = sim_time
                frame = np.frombuffer(image.raw_data, dtype=np.uint8).reshape((600, 800, 4))[:, :, :3].copy()
                detections, yolo_ms = detect(frame)
                yolo_latency.append(yolo_ms)
                colors = [classify_color(frame, det.bbox) for det in detections]

                projected, visible = gt.frame(traffic, snapshot)
                row = {
                    "frame_index": index, "carla_frame": carla_frame, "sim_time_s": rel,
                    "yolo_detections": len(detections), "yolo_ms": round(yolo_ms, 3),
                    "hsv_blue_detections": sum(1 for color in colors if color == TARGET_COLOR),
                    "projected_vehicles": len(projected), "visible_vehicles": len(visible),
                    "visible_target_vehicles": sum(1 for a in visible if plan_by_id[a]["is_target_color"]),
                }
                matched = set()
                for det in detections:
                    actor_id = best_actor(det.bbox, projected)
                    if actor_id is not None:
                        matched.add(actor_id)
                for actor_id in set(visible) | matched:
                    stats = actor_stats.setdefault(actor_id, {
                        "frames_visible": 0, "frames_yolo_matched": 0, "first_visible_s": None,
                        "last_visible_s": None,
                    })
                    if actor_id in visible:
                        stats["frames_visible"] += 1
                        if stats["first_visible_s"] is None:
                            stats["first_visible_s"] = rel
                        stats["last_visible_s"] = rel
                    if actor_id in matched:
                        stats["frames_yolo_matched"] += 1
                minute_entry = minute_stats[minute]
                minute_entry["frames"] += 1
                minute_entry["visible_actors"].update(visible)
                minute_entry["target_actors"].update(a for a in visible if plan_by_id[a]["is_target_color"])
                minute_entry["yolo_detections"] += len(detections)
                minute_entry["frames_with_detection"] += int(bool(detections))
                minute_entry["visible_sum"] += len(visible)
                if minute not in minute_positions:
                    minute_positions[minute] = {
                        actor.id: snapshot.find(actor.id).get_transform().location for actor in traffic
                        if snapshot.find(actor.id) is not None
                    }

                for branch in branches:
                    try:
                        events = branch.process(detections, colors, sim_time)
                    except Exception:
                        branch.counters["exceptions"] += 1
                        branch_exceptions.append({"branch": branch.name, "frame_index": index,
                                                  "traceback": traceback.format_exc()})
                        continue
                    triggers = 0
                    for event in events:
                        actor_id = best_actor(event["bbox"], projected)
                        if actor_id is None:
                            association = "unassociated"
                        elif plan_by_id[actor_id]["is_target_color"]:
                            association = "target_actor"
                        else:
                            association = "non_target_actor"
                        candidate_assoc[branch.name][association] += 1
                        if actor_id is not None and plan_by_id[actor_id]["is_target_color"]:
                            target_candidate_actors[branch.name].add(actor_id)
                        if event["kind"] != "vlm_trigger":
                            continue
                        triggers += 1
                        trigger_tracks[branch.name].add(event["track_id"])
                        if actor_id is not None:
                            trigger_actors[branch.name].add(actor_id)
                        candidate_assoc[branch.name]["trigger_" + association] += 1
                        x1, y1, x2, y2 = event["bbox"]
                        crop_name = "{0}/f{1:04d}_t{2}.jpg".format(branch.name, index, event["track_id"])
                        crop_path = evidence_dir / "trigger_crops" / crop_name
                        crop_path.parent.mkdir(parents=True, exist_ok=True)
                        pad = 10
                        crop = frame[max(0, y1 - pad):min(600, y2 + pad), max(0, x1 - pad):min(800, x2 + pad)]
                        if crop.size:
                            cv2.imwrite(str(crop_path), crop, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                        trigger_rows.append({
                            "bbox": "{0} {1} {2} {3}".format(x1, y1, x2, y2), "crop": crop_name,
                            "branch": branch.name, "sim_time_s": rel, "frame_index": index,
                            "carla_frame": carla_frame, "track_id": event["track_id"],
                            "actor_id": actor_id if actor_id is not None else "",
                            "actor_blueprint": plan_by_id[actor_id]["blueprint"] if actor_id else "",
                            "actor_assigned_color": plan_by_id[actor_id]["color"] if actor_id else "",
                            "confirmed_color": event["confirmed_color"],
                            "target_color_state": association,
                            "trigger_reason": event["reason"],
                            "track_disappeared_frames": event["track_disappeared"],
                        })
                    row["triggers_" + branch.name] = triggers
                    minute_entry["triggers"][branch.name] += triggers
                frame_rows.append(row)

                if rel >= next_sample:
                    annotated = frame.copy()
                    for det, color in zip(detections, colors):
                        cv2.rectangle(annotated, tuple(det.bbox[:2]), tuple(det.bbox[2:]),
                                      (255, 0, 0) if color == TARGET_COLOR else (0, 255, 0), 2)
                    samples_dir.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(samples_dir / "t{0:04d}s.jpg".format(int(rel))), annotated,
                                [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                    next_sample += args.sample_interval_seconds
                if index % 600 == 0 or index == total_frames - 1:
                    sample = {
                        "frame_index": index, "sim_time_s": rel, "wall_elapsed_s": round(time.time() - wall_started, 1),
                        "rss_mb": rss_mb(), "cuda_allocated_mb": round(torch.cuda.memory_allocated() / 1048576.0, 1),
                        "triggers": {b.name: b.counters["vlm_triggers"] for b in branches},
                        "raycasts": gt.raycasts,
                    }
                    memory_samples.append(sample)
                    logger.info("Progress %s", json.dumps(sample, sort_keys=True))
            final_positions = {
                actor.id: world.get_snapshot().find(actor.id).get_transform().location for actor in traffic
            }
        status = "COMPLETE"
    except Exception as caught:
        status, error = "FAIL", "{0}: {1}\n{2}".format(type(caught).__name__, caught, traceback.format_exc())
        logger.error("Run failed: %s", error)
        final_positions = {}
    finally:
        iou_tracker_mod.time = time

    if status != "COMPLETE":
        write_json(evidence_dir / "result.json", {"status": status, "error": error, "cleanup": cleanup,
                                                 "frames_completed": len(frame_rows)})
        return 1

    # movement per minute (evidence that traffic kept moving)
    minutes = sorted(minute_stats)
    for minute in minutes:
        start = minute_positions.get(minute, {})
        end = minute_positions.get(minute + 1, final_positions)
        moved = sum(1 for actor_id, loc in start.items() if actor_id in end and loc.distance(end[actor_id]) > 5.0)
        minute_stats[minute]["moving_vehicles"] = moved
        minute_stats[minute]["tracked_vehicles"] = len(start)

    write_outputs(output_dir, evidence_dir, environment, args, branches, frame_rows, trigger_rows,
                  candidate_assoc, trigger_tracks, trigger_actors, target_candidate_actors, actor_stats, traffic_plan, spawn_failures,
                  minute_stats, memory_samples, dropped_frames, branch_exceptions, yolo_latency, cleanup, gt)
    logger.info("Experiment B complete: %d frames", len(frame_rows))
    return 0


# ---------------------------------------------------------------- outputs

BRANCH_TITLES = {"full": "Full", "no_hsv": "No HSV", "no_temporal": "No Temporal", "no_dedup": "No Dedup"}


def _ratio(numerator, denominator):
    return round(numerator / float(denominator), 6) if denominator else None


def longest_run(flags):
    best = current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        best = max(best, current)
    return best


def write_outputs(output_dir, evidence_dir, environment, args, branches, frame_rows, trigger_rows,
                  candidate_assoc, trigger_tracks, trigger_actors, target_candidate_actors, actor_stats, traffic_plan, spawn_failures,
                  minute_stats, memory_samples, dropped_frames, branch_exceptions, yolo_latency, cleanup, gt):
    plan_by_id = {item["actor_id"]: item for item in traffic_plan}
    detections_per_frame = [row["yolo_detections"] for row in frame_rows]
    duration = frame_rows[-1]["sim_time_s"] + 0.1 if frame_rows else 0.0
    entered = {a: s for a, s in actor_stats.items() if s["frames_visible"] > 0}
    entered_target = [a for a in entered if plan_by_id[a]["is_target_color"]]
    yolo_matched = [a for a, s in actor_stats.items() if s["frames_yolo_matched"] > 0]
    common = {
        "simulation_duration_s": round(duration, 3),
        "input_frames": len(frame_rows),
        "dropped_camera_frames": len(dropped_frames),
        "total_yolo_vehicle_detections": sum(detections_per_frame),
        "frames_with_vehicle_detection": sum(1 for n in detections_per_frame if n > 0),
        "mean_detections_per_frame": round(sum(detections_per_frame) / float(len(detections_per_frame)), 4),
        "p95_detections_per_frame": percentile(detections_per_frame, 95),
        "max_detections_per_frame": max(detections_per_frame),
        "spawned_vehicles": len(traffic_plan),
        "spawned_target_color_vehicles": sum(1 for p in traffic_plan if p["is_target_color"]),
        "unique_vehicles_entering_fov": len(entered),
        "unique_vehicles_entering_fov_3plus_frames": sum(1 for s in entered.values() if s["frames_visible"] >= 3),
        "target_color_vehicles_entering_fov": len(entered_target),
        "non_target_vehicles_entering_fov": len(entered) - len(entered_target),
        "unique_vehicles_matched_by_yolo": len(yolo_matched),
        "target_color_vehicles_matched_by_yolo": sum(1 for a in yolo_matched if plan_by_id[a]["is_target_color"]),
        "frames_with_no_visible_vehicle": sum(1 for row in frame_rows if row["visible_vehicles"] == 0),
        "frames_with_no_yolo_detection": sum(1 for n in detections_per_frame if n == 0),
        "yolo_latency_ms_mean": round(sum(yolo_latency) / len(yolo_latency), 3),
        "yolo_latency_ms_p95": round(percentile(yolo_latency, 95), 3),
        "raycasts": gt.raycasts,
        "longest_no_visible_vehicle_frames": longest_run(row["visible_vehicles"] == 0 for row in frame_rows),
        "longest_no_yolo_detection_frames": longest_run(row["yolo_detections"] == 0 for row in frame_rows),
        "ten_second_windows_with_visible_vehicle": len({
            int(row["sim_time_s"] // 10) for row in frame_rows if row["visible_vehicles"] > 0}),
        "ten_second_windows_total": int(math.ceil(len(frame_rows) / 100.0)),
    }

    full = next(b for b in branches if b.name == "full").counters
    ablation_rows = []
    for branch in branches:
        c = branch.counters
        assoc = candidate_assoc[branch.name]
        flags = dict(BRANCH_CONFIGS)[branch.name]
        row = dict(
            configuration=BRANCH_TITLES[branch.name], branch=branch.name,
            hsv=flags["use_hsv"], temporal=flags["use_temporal"], dedup=flags["use_dedup"],
            vlm_triggers=c["vlm_triggers"],
            vs_full_increase=c["vlm_triggers"] - full["vlm_triggers"],
            vs_full_ratio=_ratio(c["vlm_triggers"], full["vlm_triggers"]),
            frames_with_vlm_trigger=c["frames_with_vlm_trigger"],
            unique_tracks_triggering=len(trigger_tracks[branch.name]),
            unique_actors_triggering=len(trigger_actors[branch.name]),
            target_actors_with_candidate=len(target_candidate_actors[branch.name]),
            target_actors_with_vlm_trigger=len(
                [a for a in trigger_actors[branch.name] if plan_by_id[a]["is_target_color"]]),
            hsv_candidate_detections=c["hsv_candidate_detections"],
            frames_with_hsv_candidate=c["frames_with_hsv_candidate"],
            active_target_track_observations=c["active_target_track_observations"],
            frames_with_active_target_track=c["frames_with_active_target_track"],
            temporal_results=c["temporal_results"],
            temporal_confirmations_passing_gate=c["temporal_confirmations_passing_gate"],
            frames_triggering_confirmation=c["frames_triggering_confirmation"],
            candidates_raised=c["candidates_raised"],
            duplicate_suppressed=c["duplicate_suppressed"],
            candidates_target_actor=assoc["target_actor"],
            candidates_non_target_actor=assoc["non_target_actor"],
            candidates_unassociated=assoc["unassociated"],
            triggers_target_actor=assoc["trigger_target_actor"],
            triggers_non_target_actor=assoc["trigger_non_target_actor"],
            triggers_unassociated=assoc["trigger_unassociated"],
            candidates_from_disappeared_tracks=c["candidates_from_disappeared_tracks"],
            vlm_triggers_from_disappeared_tracks=c["vlm_triggers_from_disappeared_tracks"],
            max_candidates_in_one_frame=c["max_candidates_in_one_frame"],
            dropped_frames=len(dropped_frames),
            branch_exceptions=c["exceptions"],
        )
        ablation_rows.append(row)
    write_csv(output_dir / "ablation_summary.csv", list(ablation_rows[0].keys()), ablation_rows)

    funnel_stages = [
        ("input_frames", len(frame_rows)),
        ("frames_with_yolo_vehicle_detection", common["frames_with_vehicle_detection"]),
        ("frames_with_target_hsv_candidate", full["frames_with_hsv_candidate"]),
        ("frames_with_active_target_track", full["frames_with_active_target_track"]),
        ("frames_triggering_temporal_confirmation", full["frames_triggering_confirmation"]),
        ("frames_triggering_vlm", full["frames_with_vlm_trigger"]),
    ]
    funnel_rows, previous = [], None
    for stage, count in funnel_stages:
        funnel_rows.append({
            "stage": stage, "count": count,
            "previous_stage_retention": _ratio(count, previous) if previous is not None else None,
            "input_ratio": _ratio(count, len(frame_rows)),
        })
        previous = count
    write_csv(output_dir / "full_pipeline_funnel.csv", ["stage", "count", "previous_stage_retention", "input_ratio"],
              funnel_rows)

    minute_rows = []
    for minute in sorted(minute_stats):
        entry = minute_stats[minute]
        row = {
            "minute": minute, "frames": entry["frames"],
            "unique_vehicles": len(entry["visible_actors"]),
            "target_vehicles": len(entry["target_actors"]),
            "yolo_detections": entry["yolo_detections"],
            "frames_with_detection": entry["frames_with_detection"],
            "mean_visible_vehicles": round(entry["visible_sum"] / float(entry["frames"]), 3),
            "moving_vehicles": entry.get("moving_vehicles"),
            "tracked_vehicles": entry.get("tracked_vehicles"),
        }
        for name, _ in BRANCH_CONFIGS:
            row["vlm_triggers_" + name] = entry["triggers"][name]
        minute_rows.append(row)
    write_csv(output_dir / "per_minute_summary.csv", list(minute_rows[0].keys()), minute_rows)

    write_csv(output_dir / "vlm_trigger_events.csv", [
        "branch", "sim_time_s", "frame_index", "carla_frame", "track_id", "actor_id", "actor_blueprint",
        "actor_assigned_color", "confirmed_color", "target_color_state", "trigger_reason",
        "track_disappeared_frames", "bbox", "crop",
    ], trigger_rows)

    traffic_rows = []
    for item in traffic_plan:
        stats = actor_stats.get(item["actor_id"], {})
        traffic_rows.append(dict(
            item, frames_visible=stats.get("frames_visible", 0),
            frames_yolo_matched=stats.get("frames_yolo_matched", 0),
            entered_fov=stats.get("frames_visible", 0) > 0,
            first_visible_s=stats.get("first_visible_s"), last_visible_s=stats.get("last_visible_s"),
            full_vlm_triggers=0,
        ))
    full_trigger_counts = collections.Counter(
        row["actor_id"] for row in trigger_rows if row["branch"] == "full" and row["actor_id"] != "")
    for row in traffic_rows:
        row["full_vlm_triggers"] = full_trigger_counts.get(row["actor_id"], 0)
    write_csv(output_dir / "traffic_summary.csv", [
        "slot", "actor_id", "blueprint", "color", "is_target_color", "entered_fov", "frames_visible",
        "frames_yolo_matched", "first_visible_s", "last_visible_s", "full_vlm_triggers",
    ], traffic_rows)

    write_csv(evidence_dir / "frame_metrics.csv", list(frame_rows[0].keys()), frame_rows)
    environment = dict(environment, actual_simulation_duration_s=common["simulation_duration_s"],
                       spawned_vehicles=len(traffic_plan))
    write_json(output_dir / "environment.json", environment)
    result = {
        "status": "COMPLETE", "common": common,
        "branches": {b.name: b.counters for b in branches},
        "candidate_association": {k: dict(v) for k, v in candidate_assoc.items()},
        "memory_samples": memory_samples, "dropped_frames": dropped_frames,
        "branch_exceptions": branch_exceptions, "spawn_failures": spawn_failures, "cleanup": cleanup,
    }
    write_json(evidence_dir / "result.json", result)
    write_report(output_dir, environment, common, ablation_rows, funnel_rows, minute_rows, traffic_rows,
                 memory_samples, cleanup, branch_exceptions)


def _fmt(value):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return "{0:.4f}".format(value).rstrip("0").rstrip(".")
    return str(value)


def write_report(output_dir, environment, common, ablation_rows, funnel_rows, minute_rows, traffic_rows,
                 memory_samples, cleanup, branch_exceptions):
    by_name = {row["branch"]: row for row in ablation_rows}
    full = by_name["full"]
    color_counts = collections.Counter((row["color"], row["entered_fov"]) for row in traffic_rows)
    blueprint_counts = collections.Counter(row["blueprint"] for row in traffic_rows if row["entered_fov"])
    lines = [
        "# Experiment B: 10-minute continuous monitoring / pipeline efficiency ablation",
        "",
        "Run label: `{0}`. All numbers come from one continuous host CARLA run".format(environment["label"]),
        "(`evidence/result.json`, `evidence/frame_metrics.csv`). Experiment A",
        "(`../multivehicle/validation_report.md`, system integration / stability) is unchanged.",
        "",
        "Question: on the same {0:.1f} s of dynamic CARLA traffic, how much does the".format(
            common["simulation_duration_s"]),
        "VLM workload grow when HSV, Temporal Confirmation or Deduplication is removed?",
        "",
        "## Setup",
        "",
        "- CARLA {0} `{1}`, synchronous 0.1 s ticks, seed {2}; {3} TM-autopilot vehicles".format(
            environment["carla_server_version"], environment["map"], environment["seed"],
            environment["spawned_vehicles"]),
        "  (4-wheel blueprints with paintable colour, deterministic 8-colour palette incl. blue);",
        "  fixed CCTV 800x600 FOV 90 at 10 Hz (pose reused from Experiment A); {0} s pre-roll.".format(
            environment["pre_roll_seconds"]),
        "- Real YOLOv8s ({0}, conf 0.40) runs once per frame on the {1}. The identical frame,".format(
            environment["yolo_weight"], environment["gpu"]),
        "  detections and HSV colours are fanned out to four shadow branches with independent",
        "  production IoUTracker / TemporalConfirm / Deduplicator instances.",
        "- Branch logic replicates production YoloWorker + OpenClawWorker dedup; equivalence",
        "  with the production Pipeline is unit-tested (`tests/validation/test_continuous_ablation_branches.py`).",
        "- A VLM trigger is the point where production would call the VLM (after dedup). No VLM",
        "  is called; these are trigger counts, not Real VLM inferences.",
        "- Temporal, dedup and tracker-reconnect windows use simulation time (a real-time 10 Hz",
        "  camera's timestamps). Production dedup is per camera agent with a 30 s cooldown.",
        "",
        "## Ablation comparison (same traffic, same detections)",
        "",
        "| Configuration | VLM Triggers | vs Full increase | vs Full ratio |",
        "|---|---:|---:|---:|",
    ]
    for name in ("full", "no_hsv", "no_temporal", "no_dedup"):
        row = by_name[name]
        lines.append("| {0} | {1} | {2} | {3} |".format(
            row["configuration"], row["vlm_triggers"],
            "-" if name == "full" else "{0:+d}".format(row["vs_full_increase"]),
            "{0:.2f}x".format(row["vs_full_ratio"]) if row["vs_full_ratio"] is not None else "n/a"))
    lines += [
        "",
        "Stage contributions (ablation comparison on identical input, not a causal claim):",
        "",
    ]
    for name, stage in (("no_hsv", "HSV"), ("no_temporal", "Temporal Confirmation"), ("no_dedup", "Deduplication")):
        row = by_name[name]
        lines.append("- {0}: removing it changes VLM triggers {1} -> {2} ({3:+d}; {4}).".format(
            stage, full["vlm_triggers"], row["vlm_triggers"], row["vs_full_increase"],
            "{0:.2f}x".format(row["vs_full_ratio"]) if row["vs_full_ratio"] is not None else "ratio n/a"))
    lines += [
        "",
        "Because dedup is a 30 s per-camera cooldown, any branch that keeps dedup is bounded by",
        "roughly duration/30 s triggers; the dedup-free branch shows the candidate volume that",
        "dedup absorbs. Candidate counts below show what HSV and Temporal remove before dedup.",
        "",
        "## Per-branch metrics",
        "",
        "| Metric | Unit | Full | No HSV | No Temporal | No Dedup |",
        "|---|---|---:|---:|---:|---:|",
    ]
    metrics = (
        ("hsv_candidate_detections", "detections"), ("frames_with_hsv_candidate", "frames"),
        ("active_target_track_observations", "track-frames"), ("frames_with_active_target_track", "frames"),
        ("temporal_confirmations_passing_gate", "events"), ("frames_triggering_confirmation", "frames"),
        ("candidates_raised", "candidates"), ("duplicate_suppressed", "candidates"),
        ("vlm_triggers", "requests"), ("frames_with_vlm_trigger", "frames"),
        ("unique_tracks_triggering", "tracks"), ("unique_actors_triggering", "actors"),
        ("target_actors_with_candidate", "actors"), ("target_actors_with_vlm_trigger", "actors"),
        ("candidates_target_actor", "candidates"), ("candidates_non_target_actor", "candidates"),
        ("candidates_unassociated", "candidates"), ("triggers_target_actor", "requests"),
        ("triggers_non_target_actor", "requests"), ("triggers_unassociated", "requests"),
        ("candidates_from_disappeared_tracks", "candidates"),
        ("vlm_triggers_from_disappeared_tracks", "requests"),
        ("max_candidates_in_one_frame", "candidates"), ("dropped_frames", "frames"),
        ("branch_exceptions", "exceptions"),
    )
    for key, unit in metrics:
        lines.append("| {0} | {1} | {2} |".format(key, unit, " | ".join(
            _fmt(by_name[name][key]) for name in ("full", "no_hsv", "no_temporal", "no_dedup"))))
    lines += [
        "",
        "For No HSV, every detection/track is a candidate by construction (no colour gate).",
        "Actor association (IoU >= 0.30 with a projected CARLA box) is evidence only;",
        "`non_target_actor` candidates are false-target candidates, `unassociated` could not",
        "be matched to any projected vehicle (e.g. YOLO false positives, occlusion).",
        "The shadow branches are synchronous: no queue exists, so queue depth is reported as",
        "the maximum number of candidates produced in one frame; drops are camera frames lost.",
        "",
        "## Full pipeline frame funnel (frame units only)",
        "",
        "| Stage | Count | Previous-stage retention | Input ratio |",
        "|---|---:|---:|---:|",
    ]
    for row in funnel_rows:
        lines.append("| {0} | {1} | {2} | {3} |".format(
            row["stage"], row["count"], _fmt(row["previous_stage_retention"]), _fmt(row["input_ratio"])))
    lines += [
        "",
        "## Traffic",
        "",
        "| Item | Value |",
        "|---|---:|",
    ]
    for key in ("simulation_duration_s", "input_frames", "dropped_camera_frames", "spawned_vehicles",
                "spawned_target_color_vehicles", "unique_vehicles_entering_fov",
                "unique_vehicles_entering_fov_3plus_frames", "target_color_vehicles_entering_fov",
                "non_target_vehicles_entering_fov", "unique_vehicles_matched_by_yolo",
                "target_color_vehicles_matched_by_yolo", "total_yolo_vehicle_detections",
                "frames_with_vehicle_detection", "frames_with_no_yolo_detection",
                "frames_with_no_visible_vehicle", "mean_detections_per_frame", "p95_detections_per_frame",
                "max_detections_per_frame", "longest_no_visible_vehicle_frames",
                "longest_no_yolo_detection_frames", "ten_second_windows_with_visible_vehicle",
                "ten_second_windows_total", "yolo_latency_ms_mean", "yolo_latency_ms_p95"):
        lines.append("| {0} | {1} |".format(key, _fmt(common[key])))
    lines += [
        "",
        "FOV entry = projected box height >= {0} px, distance <= {1:.0f} m and clear centre".format(
            MIN_VISIBLE_HEIGHT_PX, MAX_VISIBLE_DISTANCE_M),
        "line of sight (`world.cast_ray`).",
        "",
        "Colour distribution (spawned / entered FOV):",
        "",
        "| Colour (RGB) | Spawned | Entered FOV |",
        "|---|---:|---:|",
    ]
    for color in PALETTE:
        spawned = color_counts[(color, True)] + color_counts[(color, False)]
        lines.append("| {0}{1} | {2} | {3} |".format(color, " (target blue)" if color == TARGET_RGB else "",
                                                     spawned, color_counts[(color, True)]))
    lines += [
        "",
        "Blueprints that entered the FOV: {0} distinct ({1}).".format(
            len(blueprint_counts), ", ".join("{0} x{1}".format(k, v) for k, v in sorted(blueprint_counts.items()))),
        "",
        "## Per-minute summary",
        "",
        "| Minute | Unique vehicles | Target vehicles | YOLO detections | Mean visible | Moving vehicles | Full | No HSV | No Temporal | No Dedup |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in minute_rows:
        lines.append("| {0} | {1} | {2} | {3} | {4} | {5}/{6} | {7} | {8} | {9} | {10} |".format(
            row["minute"], row["unique_vehicles"], row["target_vehicles"], row["yolo_detections"],
            row["mean_visible_vehicles"], row["moving_vehicles"], row["tracked_vehicles"],
            row["vlm_triggers_full"], row["vlm_triggers_no_hsv"], row["vlm_triggers_no_temporal"],
            row["vlm_triggers_no_dedup"]))
    lines += [
        "",
        "Moving vehicles: displaced > 5 m between the start of the minute and the next.",
        "",
        "## Stability",
        "",
        "- Memory (RSS MB / CUDA allocated MB) samples: {0}".format(", ".join(
            "{0}s: {1}/{2}".format(s["sim_time_s"], s["rss_mb"], s["cuda_allocated_mb"]) for s in memory_samples)),
        "- Branch exceptions: {0}; dropped camera frames: {1}.".format(
            len(branch_exceptions), common["dropped_camera_frames"]),
        "- Cleanup: {0}".format(json.dumps({k: cleanup.get(k) for k in ("attempted", "destroyed", "failed_actor_ids")}
                                           if cleanup else None)),
        "",
        "## Interpretation limits",
        "",
        "- One continuous run on one camera pose and one map; trigger counts are not",
        "  repeated-measure statistics and do not generalise to other traffic or scenes.",
        "- VLM triggers are counted, not executed; no Real VLM accuracy or latency is measured.",
        "- Input frames -> VLM triggers is not a single 'filtering effect': the stages are",
        "  separated above and dedup is a time-based cooldown.",
        "- Ground truth projection/line of sight is evidence only and approximate (centre ray).",
        "- Wall-clock processing in synchronous CARLA is not real-time road latency.",
        "- Historical 46,372 / 28,736 / 3,298 / 53 values are not compared (units not established).",
        "",
    ]
    (Path(output_dir) / "continuous_10min_report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

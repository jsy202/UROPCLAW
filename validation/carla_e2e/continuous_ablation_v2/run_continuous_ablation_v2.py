#!/usr/bin/env python3
"""Experiment B v2: continuous CARLA traffic, 4-way shadow ablation on FIXED production logic.

Scene, traffic, camera, YOLO and ground truth are identical to Experiment B v1
(imported from ../continuous_ablation/run_continuous_ablation.py). The shadow
branches (branches.py in this directory) mirror production after the
stale-track and per-target dedup fixes. Per-target-actor stage evidence uses
CARLA ground truth only for evaluation; no branch receives actor identity.
"""

from __future__ import annotations

import argparse
import collections
import faulthandler
import importlib.util
import json
import sys
import time
import traceback
from contextlib import ExitStack
from pathlib import Path


HERE = Path(__file__).resolve().parent
V1_DIR = HERE.parent / "continuous_ablation"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v1 = _load("continuous_ablation_v1_runner", V1_DIR / "run_continuous_ablation.py")
branches_v2 = _load("continuous_ablation_v2_branches", HERE / "branches.py")

STAGES = ("entered_fov", "yolo_detected", "hsv_passed", "tracked", "confirmed", "vlm_reached")
STAGE_FAILURE = {
    "entered_fov": "never entered FOV",
    "yolo_detected": "YOLO never detected",
    "hsv_passed": "HSV never classified blue",
    "tracked": "no blue matched track",
    "confirmed": "temporal confirmation never emitted",
}


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
    parser.add_argument("--weight", type=Path, default=v1.DEFAULT_WEIGHT)
    parser.add_argument("--camera-manifest", type=Path, default=v1.DEFAULT_CAMERA_MANIFEST)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--label", default="v2_run")
    parser.add_argument("--cleanup-stale-validation-actors", action="store_true")
    return parser.parse_args(argv)


def annotate(cv2, frame, boxes, title):
    image = frame.copy()
    for box, color, label in boxes:
        cv2.rectangle(image, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), color, 2)
        if label:
            cv2.putText(image, label, (int(box[0]), max(14, int(box[1]) - 4)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, color, 1)
    cv2.putText(image, title, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    return image


def run(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = v1.setup_logging([output_dir / "run.log"])
    faulthandler.enable(all_threads=True)

    import carla
    import cv2
    import numpy as np
    import torch
    import ultralytics
    from ultralytics import YOLO

    sys.path.insert(0, str(v1.REPOSITORY_ROOT / "harness"))
    import perception.iou_tracker as iou_tracker_mod
    from perception.color_filter import classify_color
    from perception.deduplicator import Deduplicator
    from perception.temporal_confirm import TemporalConfirm
    from perception.yolo_detector import Detection

    clock = branches_v2.SimClock()
    iou_tracker_mod.time = clock
    branches = branches_v2.make_branches(iou_tracker_mod.IoUTracker, TemporalConfirm, Deduplicator, v1.TARGET_COLOR)
    full_branch = branches[0]

    def jpg(path, image, quality=75):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    v1.validate_carla_versions(client.get_client_version(), client.get_server_version())
    world = client.get_world()
    tm = client.get_trafficmanager(args.tm_port)
    camera_manifest = json.loads(Path(args.camera_manifest).read_text(encoding="utf-8"))
    if camera_manifest["planned_scene"]["map"] != world.get_map().name:
        raise RuntimeError("camera manifest map mismatch")
    stale_cleanup = v1.cleanup_stale_validation_actors(
        list(world.get_actors().filter("vehicle.*")), enabled=args.cleanup_stale_validation_actors)
    if list(world.get_actors().filter("vehicle.*")):
        raise RuntimeError("world has vehicles not created by this validation")
    model = YOLO(str(args.weight))
    model.to("cuda:0")
    environment = {
        "experiment": "B v2: continuous ablation on fixed production logic (stale-track + per-target dedup)",
        "label": args.label,
        "carla_client_version": client.get_client_version(), "carla_server_version": client.get_server_version(),
        "map": world.get_map().name, "python": sys.version.split()[0], "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(0), "ultralytics": ultralytics.__version__, "opencv": cv2.__version__,
        "yolo_weight": args.weight.name, "yolo_confidence": 0.40, "yolo_iou": 0.45,
        "seed": args.seed, "requested_vehicles": args.vehicles, "fixed_delta_seconds": 0.1,
        "camera": {"width": 800, "height": 600, "fov": 90, "sensor_tick": 0.0},
        "duration_seconds_requested": args.duration_seconds, "pre_roll_seconds": args.pre_roll_seconds,
        "target_color": v1.TARGET_COLOR, "palette": list(v1.PALETTE),
        "branches": {name: flags for name, flags in branches_v2.BRANCH_CONFIGS},
        "time_basis": "simulation time for temporal, dedup and tracker reconnect windows",
        "stale_validation_cleanup": stale_cleanup,
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
                if class_id not in v1.TARGET_CLASSES:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(Detection(bbox=[int(x1), int(y1), int(x2), int(y2)], class_id=class_id,
                                            class_name=v1.TARGET_CLASSES[class_id], confidence=float(box.conf[0])))
        return detections, elapsed

    owned, camera, stream = [], None, None
    frame_rows, trigger_rows, suppressed_rows = [], [], []
    names = [name for name, _ in branches_v2.BRANCH_CONFIGS]
    candidate_assoc = {name: collections.Counter() for name in names}
    trigger_tracks = {name: set() for name in names}
    trigger_actors = {name: set() for name in names}
    target_owner = {name: {} for name in names}   # dedup target_key -> actor at creation
    actor_stats = {}
    funnel = {}
    minute_stats = collections.defaultdict(lambda: {
        "visible_actors": set(), "target_actors": set(), "yolo_detections": 0, "frames": 0,
        "visible_sum": 0, "triggers": collections.Counter(), "frames_with_detection": 0,
        "suppressed_full": 0,
    })
    minute_positions = {}
    memory_samples, dropped_frames, branch_exceptions, yolo_latency = [], [], [], []
    examples = collections.Counter()
    last_full_trigger = None
    status, error, cleanup = "RUNNING", None, None
    traffic_plan, spawn_failures, final_positions = [], [], {}
    t0 = None
    try:
        with ExitStack() as stack:
            stack.enter_context(v1.synchronous_mode(world, tm, args.seed, 0.1))

            def _cleanup():
                nonlocal cleanup
                cleanup = v1.shutdown_scene_resources(stream, camera, owned, world, args.tm_port, args.timeout)
                logger.info("Cleanup result: %s", json.dumps(cleanup, sort_keys=True))
            stack.callback(_cleanup)

            traffic, traffic_plan, spawn_failures = v1.spawn_traffic(carla, world, tm, args, logger)
            owned.extend(traffic)
            plan_by_id = {item["actor_id"]: item for item in traffic_plan}
            for item in traffic_plan:
                if item["is_target_color"]:
                    funnel[item["actor_id"]] = {stage: None for stage in STAGES}
                    funnel[item["actor_id"]].update(
                        candidates=0, triggers=0, suppressed=collections.Counter(), blocked_by=set())
            camera_bp = world.get_blueprint_library().find("sensor.camera.rgb")
            for key, value in (("image_size_x", "800"), ("image_size_y", "600"), ("fov", "90"), ("sensor_tick", "0.0")):
                camera_bp.set_attribute(key, value)
            camera_transform = v1.transform_from_dict(carla, camera_manifest["planned_scene"]["camera"]["transform"])
            camera = world.spawn_actor(camera_bp, camera_transform)
            owned.append(camera)
            gt = v1.GroundTruth(carla, world, camera_transform, 800, 600, 90.0, np)
            stream = v1.SynchronousSensorStream(camera)
            stream.start()
            stream.wait_until_ready(world, args.timeout, args.sensor_timeout, 10)
            for tick in range(int(round(args.pre_roll_seconds / 0.1))):
                _, image = stream.tick_and_wait(world, args.timeout, args.sensor_timeout)
                if tick < args.model_warmup:
                    detect(np.frombuffer(image.raw_data, dtype=np.uint8).reshape((600, 800, 4))[:, :, :3].copy())

            total_frames = int(round(args.duration_seconds / 0.1))
            logger.info("Phase: measurement (%d frames, %d branches)", total_frames, len(branches))
            wall_started = time.time()
            for index in range(total_frames):
                try:
                    carla_frame, image = stream.tick_and_wait(world, args.timeout, args.sensor_timeout)
                except v1.SensorFrameTimeout as timeout_error:
                    dropped_frames.append({"index": index, "expected_frame": timeout_error.expected_frame})
                    continue
                snapshot = world.get_snapshot()
                sim_time = snapshot.timestamp.elapsed_seconds
                t0 = sim_time if t0 is None else t0
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
                    "hsv_blue_detections": sum(1 for c in colors if c == v1.TARGET_COLOR),
                    "projected_vehicles": len(projected), "visible_vehicles": len(visible),
                    "visible_target_vehicles": sum(1 for a in visible if plan_by_id[a]["is_target_color"]),
                }
                det_actor = [v1.best_actor(det.bbox, projected) for det in detections]
                matched = {a for a in det_actor if a is not None}
                for actor_id in set(visible) | matched:
                    stats = actor_stats.setdefault(actor_id, {"frames_visible": 0, "frames_yolo_matched": 0,
                                                              "first_visible_s": None, "last_visible_s": None})
                    if actor_id in visible:
                        stats["frames_visible"] += 1
                        stats["first_visible_s"] = rel if stats["first_visible_s"] is None else stats["first_visible_s"]
                        stats["last_visible_s"] = rel
                    if actor_id in matched:
                        stats["frames_yolo_matched"] += 1

                def reach(actor_id, stage, box, color, title):
                    entry = funnel.get(actor_id)
                    if entry is None or entry[stage] is not None:
                        return
                    entry[stage] = rel
                    if stage != "entered_fov":
                        boxes = [(projected[actor_id], (255, 255, 255), "GT")] if actor_id in projected else []
                        boxes.append((box, color, stage))
                        jpg(output_dir / "evidence" / "stages" / "actor{0:03d}_{1}_{2}.jpg".format(
                            plan_by_id[actor_id]["slot"], STAGES.index(stage), stage),
                            annotate(cv2, frame, boxes, "t={0:.1f}s actor slot {1} {2}".format(
                                rel, plan_by_id[actor_id]["slot"], stage)))

                for actor_id in visible:
                    reach(actor_id, "entered_fov", visible[actor_id], None, "")
                for det, color, actor_id in zip(detections, colors, det_actor):
                    if actor_id is None:
                        continue
                    reach(actor_id, "yolo_detected", det.bbox, (0, 255, 0), "")
                    if color == v1.TARGET_COLOR:
                        reach(actor_id, "hsv_passed", det.bbox, (255, 0, 0), "")

                entry_minute = minute_stats[minute]
                entry_minute["frames"] += 1
                entry_minute["visible_actors"].update(visible)
                entry_minute["target_actors"].update(a for a in visible if plan_by_id[a]["is_target_color"])
                entry_minute["yolo_detections"] += len(detections)
                entry_minute["frames_with_detection"] += int(bool(detections))
                entry_minute["visible_sum"] += len(visible)
                if minute not in minute_positions:
                    minute_positions[minute] = {a.id: snapshot.find(a.id).get_transform().location for a in traffic
                                                if snapshot.find(a.id) is not None}

                current_boxes = [list(det.bbox) for det in detections]
                for branch in branches:
                    try:
                        events = branch.process(detections, colors, sim_time)
                    except Exception:
                        branch.counters["exceptions"] += 1
                        branch_exceptions.append({"branch": branch.name, "frame_index": index,
                                                  "traceback": traceback.format_exc()})
                        continue
                    if branch is full_branch:
                        for track in branch.matched_tracks:
                            if track["color"] != v1.TARGET_COLOR:
                                continue
                            actor_id = v1.best_actor(track["bbox"], projected)
                            if actor_id is not None:
                                reach(actor_id, "tracked", track["bbox"], (255, 0, 255), "")
                    triggers = 0
                    for event in events:
                        actor_id = v1.best_actor(event["bbox"], projected)
                        is_target_actor = actor_id is not None and plan_by_id[actor_id]["is_target_color"]
                        association = ("unassociated" if actor_id is None
                                       else "target_actor" if is_target_actor else "non_target_actor")
                        candidate_assoc[branch.name][association] += 1
                        target_key = event.get("target_key")
                        owner = target_owner[branch.name].get(tuple(target_key)) if target_key else None
                        if branch is full_branch and is_target_actor:
                            funnel[actor_id]["candidates"] += 1
                            reach(actor_id, "confirmed", event["bbox"], (0, 165, 255), "")
                        if event["kind"] == "suppressed":
                            if branch is full_branch:
                                entry_minute["suppressed_full"] += 1
                                if is_target_actor:
                                    funnel[actor_id]["suppressed"][event["reason"]] += 1
                                    if owner is not None and owner != actor_id:
                                        funnel[actor_id]["blocked_by"].add(owner)
                                key = event["reason"] + ("_other_actor" if owner not in (None, actor_id) else "")
                                if examples[key] < 3:
                                    examples[key] += 1
                                    jpg(output_dir / "evidence" / "dedup_suppressed" / "{0}_{1}_f{2:04d}.jpg".format(
                                        key, examples[key], index),
                                        annotate(cv2, frame, [(event["bbox"], (0, 0, 255), "suppressed: " + event["reason"])],
                                                 "t={0:.1f}s track {1} suppressed ({2}); owner actor {3}, this actor {4}".format(
                                                     rel, event["track_id"], event["reason"], owner, actor_id)))
                            suppressed_rows.append({
                                "branch": branch.name, "sim_time_s": rel, "frame_index": index,
                                "track_id": event["track_id"], "reason": event["reason"],
                                "actor_id": actor_id if actor_id is not None else "",
                                "actor_assigned_color": plan_by_id[actor_id]["color"] if actor_id else "",
                                "target_color_state": association,
                                "dedup_owner_actor_id": owner if owner is not None else "",
                                "same_actor_as_owner": (owner == actor_id) if owner is not None and actor_id is not None else "",
                                "bbox": " ".join(map(str, event["bbox"])),
                            })
                            continue
                        # VLM trigger
                        triggers += 1
                        if target_key and event.get("dedup_reason") == "new_target":
                            target_owner[branch.name][tuple(target_key)] = actor_id
                        trigger_tracks[branch.name].add(event["track_id"])
                        if actor_id is not None:
                            trigger_actors[branch.name].add(actor_id)
                        candidate_assoc[branch.name]["trigger_" + association] += 1
                        x1, y1, x2, y2 = event["bbox"]
                        crop_name = ""
                        if branch.name != "no_dedup" or candidate_assoc[branch.name]["triggers_saved"] < 60:
                            candidate_assoc[branch.name]["triggers_saved"] += 1
                            crop_name = "{0}/f{1:04d}_t{2}.jpg".format(branch.name, index, event["track_id"])
                            crop = frame[max(0, y1 - 10):min(600, y2 + 10), max(0, x1 - 10):min(800, x2 + 10)]
                            if crop.size:
                                jpg(output_dir / "evidence" / "trigger_crops" / crop_name, crop, 85)
                        if branch is full_branch:
                            if is_target_actor:
                                funnel[actor_id]["triggers"] += 1
                                reach(actor_id, "vlm_reached", event["bbox"], (0, 0, 255), "")
                            if (last_full_trigger is not None and rel - last_full_trigger[0] < 30.0
                                    and tuple(target_key or ()) != last_full_trigger[1]
                                    and examples["new_target_within_30s"] < 5):
                                examples["new_target_within_30s"] += 1
                                jpg(output_dir / "evidence" / "new_target_within_30s" / "f{0:04d}_t{1}.jpg".format(
                                    index, event["track_id"]),
                                    annotate(cv2, frame, [(event["bbox"], (0, 0, 255), "VLM trigger (new target)")],
                                             "t={0:.1f}s new target {1:.1f}s after previous trigger (actor {2})".format(
                                                 rel, rel - last_full_trigger[0], actor_id)))
                            last_full_trigger = (rel, tuple(target_key or ()))
                        trigger_rows.append({
                            "branch": branch.name, "sim_time_s": rel, "frame_index": index, "carla_frame": carla_frame,
                            "track_id": event["track_id"], "actor_id": actor_id if actor_id is not None else "",
                            "actor_blueprint": plan_by_id[actor_id]["blueprint"] if actor_id else "",
                            "actor_assigned_color": plan_by_id[actor_id]["color"] if actor_id else "",
                            "confirmed_color": event["confirmed_color"], "target_color_state": association,
                            "trigger_reason": event["reason"], "dedup_reason": event.get("dedup_reason", ""),
                            "track_disappeared_frames": event["track_disappeared"],
                            "bbox_is_current_detection": list(event["bbox"]) in current_boxes,
                            "bbox": " ".join(map(str, event["bbox"])), "crop": crop_name,
                        })
                    row["triggers_" + branch.name] = triggers
                    entry_minute["triggers"][branch.name] += triggers
                frame_rows.append(row)
                if index % 600 == 0 or index == total_frames - 1:
                    sample = {"frame_index": index, "sim_time_s": rel, "wall_elapsed_s": round(time.time() - wall_started, 1),
                              "rss_mb": v1.rss_mb(), "cuda_allocated_mb": round(torch.cuda.memory_allocated() / 1048576.0, 1),
                              "triggers": {b.name: b.counters["vlm_triggers"] for b in branches}}
                    memory_samples.append(sample)
                    logger.info("Progress %s", json.dumps(sample, sort_keys=True))
            final_snapshot = world.get_snapshot()
            final_positions = {a.id: final_snapshot.find(a.id).get_transform().location for a in traffic}
        status = "COMPLETE"
    except Exception as caught:
        status, error = "FAIL", "{0}: {1}\n{2}".format(type(caught).__name__, caught, traceback.format_exc())
        logger.error("Run failed: %s", error)
    finally:
        iou_tracker_mod.time = time

    if status != "COMPLETE":
        v1.write_json(output_dir / "result.json", {"status": status, "error": error, "cleanup": cleanup,
                                                  "frames_completed": len(frame_rows)})
        return 1

    for minute in sorted(minute_stats):
        start = minute_positions.get(minute, {})
        end = minute_positions.get(minute + 1, final_positions)
        minute_stats[minute]["moving_vehicles"] = sum(
            1 for a, loc in start.items() if a in end and loc.distance(end[a]) > 5.0)
        minute_stats[minute]["tracked_vehicles"] = len(start)

    detections_per_frame = [r["yolo_detections"] for r in frame_rows]
    entered = {a: s for a, s in actor_stats.items() if s["frames_visible"] > 0}
    common = {
        "simulation_duration_s": round(frame_rows[-1]["sim_time_s"] + 0.1, 3),
        "input_frames": len(frame_rows), "dropped_camera_frames": len(dropped_frames),
        "total_yolo_vehicle_detections": sum(detections_per_frame),
        "frames_with_vehicle_detection": sum(1 for n in detections_per_frame if n > 0),
        "mean_detections_per_frame": round(sum(detections_per_frame) / float(len(detections_per_frame)), 4),
        "p95_detections_per_frame": v1.percentile(detections_per_frame, 95),
        "max_detections_per_frame": max(detections_per_frame),
        "spawned_vehicles": len(traffic_plan),
        "unique_vehicles_entering_fov": len(entered),
        "target_color_vehicles_entering_fov": sum(1 for a in entered if plan_by_id[a]["is_target_color"]),
        "non_target_vehicles_entering_fov": sum(1 for a in entered if not plan_by_id[a]["is_target_color"]),
        "unique_vehicles_matched_by_yolo": sum(1 for s in actor_stats.values() if s["frames_yolo_matched"] > 0),
        "yolo_latency_ms_mean": round(sum(yolo_latency) / len(yolo_latency), 3),
        "yolo_latency_ms_p95": round(v1.percentile(yolo_latency, 95), 3),
    }
    funnel_rows = []
    for actor_id, entry in sorted(funnel.items(), key=lambda kv: plan_by_id[kv[0]]["slot"]):
        failure = ""
        for stage in STAGES[:-1]:
            if entry[stage] is None:
                failure = STAGE_FAILURE[stage]
                break
        if not failure and entry["vlm_reached"] is None:
            failure = "all {0} candidates dedup-suppressed ({1}){2}".format(
                entry["candidates"], ", ".join("{0} x{1}".format(k, v) for k, v in sorted(entry["suppressed"].items())),
                "; blocked by entry of actor(s) {0}".format(sorted(entry["blocked_by"])) if entry["blocked_by"] else "")
        funnel_rows.append(dict(
            actor_id=actor_id, slot=plan_by_id[actor_id]["slot"], blueprint=plan_by_id[actor_id]["blueprint"],
            **{stage: entry[stage] is not None for stage in STAGES},
            **{stage + "_first_s": entry[stage] for stage in STAGES},
            full_candidates=entry["candidates"], full_vlm_triggers=entry["triggers"],
            suppressed_same_target=entry["suppressed"]["same_target_cooldown"],
            suppressed_fragment=entry["suppressed"]["fragment_continuity"],
            blocked_by_other_actor=";".join(map(str, sorted(entry["blocked_by"]))),
            failure_reason=failure,
        ))
    result = {
        "status": "COMPLETE", "label": args.label, "common": common,
        "branches": {b.name: b.counters for b in branches},
        "candidate_association": {k: dict(v) for k, v in candidate_assoc.items()},
        "trigger_unique_tracks": {k: len(v) for k, v in trigger_tracks.items()},
        "trigger_unique_actors": {k: len(v) for k, v in trigger_actors.items()},
        "trigger_target_actors": {k: len([a for a in v if plan_by_id[a]["is_target_color"]]) for k, v in trigger_actors.items()},
        "examples_saved": dict(examples),
        "memory_samples": memory_samples, "dropped_frames": dropped_frames, "branch_exceptions": branch_exceptions,
        "spawn_failures": spawn_failures, "cleanup": cleanup,
    }
    v1.write_json(output_dir / "result.json", result)
    v1.write_json(output_dir / "environment.json", environment)
    v1.write_csv(output_dir / "frame_metrics.csv", list(frame_rows[0].keys()), frame_rows)
    v1.write_csv(output_dir / "vlm_trigger_events.csv", list(trigger_rows[0].keys()) if trigger_rows else ["branch"], trigger_rows)
    v1.write_csv(output_dir / "duplicate_suppressed_events.csv",
                 list(suppressed_rows[0].keys()) if suppressed_rows else ["branch"], suppressed_rows)
    v1.write_csv(output_dir / "target_actor_funnel.csv", list(funnel_rows[0].keys()), funnel_rows)
    minute_rows = []
    for minute in sorted(minute_stats):
        e = minute_stats[minute]
        minute_rows.append(dict(
            minute=minute, frames=e["frames"], unique_vehicles=len(e["visible_actors"]),
            target_vehicles=len(e["target_actors"]), yolo_detections=e["yolo_detections"],
            frames_with_detection=e["frames_with_detection"],
            mean_visible_vehicles=round(e["visible_sum"] / float(e["frames"]), 3),
            moving_vehicles=e.get("moving_vehicles"), tracked_vehicles=e.get("tracked_vehicles"),
            full_suppressed=e["suppressed_full"],
            **{"vlm_triggers_" + name: e["triggers"][name] for name in names}))
    v1.write_csv(output_dir / "per_minute_summary.csv", list(minute_rows[0].keys()), minute_rows)
    traffic_rows = []
    for item in traffic_plan:
        s = actor_stats.get(item["actor_id"], {})
        traffic_rows.append(dict(item, entered_fov=s.get("frames_visible", 0) > 0,
                                 frames_visible=s.get("frames_visible", 0),
                                 frames_yolo_matched=s.get("frames_yolo_matched", 0),
                                 first_visible_s=s.get("first_visible_s"), last_visible_s=s.get("last_visible_s")))
    v1.write_csv(output_dir / "traffic_summary.csv", list(traffic_rows[0].keys()), traffic_rows)
    logger.info("Experiment B v2 run complete: %d frames, full triggers %d", len(frame_rows),
                full_branch.counters["vlm_triggers"])
    return 0


def main(argv=None):
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

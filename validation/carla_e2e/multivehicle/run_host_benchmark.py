#!/usr/bin/env python3
"""Host-only repeated Target/Non-target dynamic multi-vehicle benchmark.

Plans the deterministic scene once, saves the Target manifest, then runs every
repetition as a separate ``run_host_smoke.py`` subprocess that replays that
manifest (Non-target changes only the probe colour). Repetitions alternate
Target/Non-target. Aggregates are computed only from per-run result.json files.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_host_smoke.py"
EVIDENCE_DIR = HERE / "evidence" / "benchmark"
SCENARIOS = ("target", "non_target")
IMAGE_NAMES = ("scene_preroll.png", "max_detections_annotated.png", "probe_first_detection_annotated.png")

sys.path.insert(0, str(HERE))
from scene import plan_scene  # noqa: E402
from scene_manifest import write_manifest  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--tm-port", type=int, default=8000)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--run-timeout", type=float, default=600.0)
    parser.add_argument("--keep-images-repetitions", type=int, default=1)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=HERE)
    parser.add_argument(
        "--aggregate-only", action="store_true",
        help="Re-aggregate existing evidence/benchmark/runs without running CARLA",
    )
    return parser.parse_args(argv)


def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q / 100.0
    lower, upper = int(math.floor(position)), int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def latency_summary(values):
    if not values:
        return {
            "sample_count": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None,
            "p99_ms": None, "max_ms": None, "at_or_below_1000": 0, "over_1000": 0,
            "compliance_rate": None,
        }
    below = sum(value <= 1000.0 for value in values)
    return {
        "sample_count": len(values),
        "mean_ms": round(sum(values) / float(len(values)), 3),
        "p50_ms": round(percentile(values, 50), 3),
        "p95_ms": round(percentile(values, 95), 3),
        "p99_ms": round(percentile(values, 99), 3),
        "max_ms": round(max(values), 3),
        "at_or_below_1000": below,
        "over_1000": len(values) - below,
        "compliance_rate": round(below / float(len(values)), 6),
    }


def _ratio(numerator, denominator):
    return round(numerator / float(denominator), 6) if denominator else None


def run_success(scenario, exit_code, result):
    """Target needs every smoke gate plus a target event; Non-target needs every non-target gate."""
    if exit_code != 0 or not result or result.get("status") != "PASS":
        return False
    if scenario == "target":
        return result.get("target_events", 0) > 0
    return result.get("target_events", 0) == 0 and result.get("fake_vlm_requests", 0) == 0


def false_target_events(scenario, result):
    if scenario == "non_target":
        return int(result.get("target_events", 0))
    probe_tracks = set(result.get("probe_track_ids", []))
    return sum(1 for track_id in result.get("alert_track_ids", []) if track_id not in probe_tracks)


def _write_csv(path, fieldnames, rows):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare_manifest(args, evidence_dir):
    import carla
    from run_host_smoke import cleanup_stale_validation_actors, make_manifest_pair, validate_carla_versions

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    validate_carla_versions(client.get_client_version(), client.get_server_version())
    world = client.get_world()
    stale = cleanup_stale_validation_actors(list(world.get_actors().filter("vehicle.*")), enabled=True)
    remaining = list(world.get_actors().filter("vehicle.*"))
    if remaining:
        raise RuntimeError(
            "world contains {0} vehicles not created by this validation; planning requires an empty world".format(
                len(remaining)
            )
        )
    planned = plan_scene(carla, world, 42)
    planned["traffic_manager"]["port"] = args.tm_port
    target, non_target = make_manifest_pair(planned)
    target_path = evidence_dir / "target_scene_manifest.json"
    write_manifest(target_path, target)
    write_manifest(evidence_dir / "non_target_scene_manifest.json", non_target)
    return target_path, {
        "carla_client_version": client.get_client_version(),
        "carla_server_version": client.get_server_version(),
        "map": world.get_map().name,
        "stale_validation_cleanup": stale,
    }


def run_one(args, scenario, repetition, manifest_path, runs_dir):
    run_id = "{0}-{1:02d}".format(scenario, repetition)
    run_dir = runs_dir / run_id
    if run_dir.exists():
        shutil.rmtree(str(run_dir))
    run_dir.mkdir(parents=True)
    command = [
        sys.executable, str(RUNNER), "--scenario", scenario,
        "--replay-manifest", str(manifest_path), "--evidence-dir", str(run_dir),
        "--host", args.host, "--port", str(args.port), "--tm-port", str(args.tm_port),
        "--cleanup-stale-validation-actors",
    ]
    started = time.time()
    with (run_dir / "stdout.log").open("w", encoding="utf-8") as log_stream:
        try:
            completed = subprocess.run(
                command, stdout=log_stream, stderr=subprocess.STDOUT, timeout=args.run_timeout,
            )
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            exit_code = "timeout"
    duration = round(time.time() - started, 3)
    result_path = run_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    if repetition > args.keep_images_repetitions:
        for name in IMAGE_NAMES:
            image = run_dir / name
            if image.exists():
                image.unlink()
    return {
        "run_id": run_id, "scenario": scenario, "repetition": repetition,
        "exit_code": exit_code, "duration_seconds": duration, "result": result,
    }


def build_rows(runs):
    object_rows, frame_rows, tracking_rows, latency_rows, run_rows = [], [], [], [], []
    for run in runs:
        result, scenario = run["result"], run["scenario"]
        success = run_success(scenario, run["exit_code"], result)
        production = result.get("production_metrics", {})
        queue_stats = result.get("queue", {})
        probe_tracks = set(result.get("probe_track_ids", []))
        base = {"run_id": run["run_id"], "scenario": scenario, "repetition": run["repetition"]}
        run_rows.append(dict(
            base, exit_code=run["exit_code"], status=result.get("status", "NO_RESULT"),
            success=success, failed_gates=";".join(result.get("failed_gates", [])),
            error=result.get("error", ""), duration_seconds=run["duration_seconds"],
            probe_fov_enter_frame=result.get("probe_fov_enter_frame"),
            probe_fov_exit_frame=result.get("probe_fov_exit_frame"),
            probe_first_detection_frame=result.get("probe_first_detection_frame"),
            probe_route_max_deviation_m=result.get("probe_route_max_deviation_m"),
            probe_track_ids=";".join(str(item) for item in sorted(probe_tracks)),
            probe_hsv_blue=result.get("probe_hsv_passed"),
            probe_temporal_confirmed_blue=result.get("probe_temporal_confirmed"),
            max_yolo_vehicle_boxes_per_frame=result.get("max_yolo_vehicle_boxes_per_frame"),
            background_moving=result.get("background_movement", {}).get("moving_count"),
            cleanup_destroyed=result.get("cleanup", {}).get("destroyed"),
            pipeline_alive=result.get("pipeline_alive"),
            max_input_queue=queue_stats.get("max_input_depth"),
            max_candidate_queue=queue_stats.get("max_candidate_depth"),
            ending_queue_depth=queue_stats.get("ending_depth"),
            dropped_frames=int(result.get("callback_dropped_frames", 0)) + int(production.get("frames_dropped", 0)),
            dropped_events=int(production.get("candidates_dropped", 0)) + int(production.get("alerts_failed", 0)),
        ))
        object_rows.append(dict(
            base, yolo_detections=result.get("yolo_detections"), unique_tracks=result.get("unique_tracks"),
            confirmed_tracks=result.get("confirmed_tracks"), vlm_requests=result.get("fake_vlm_requests"),
            target_events=result.get("target_events"),
            false_target_events=false_target_events(scenario, result) if result else None,
            duplicate_suppressed=production.get("duplicate_suppressed"),
        ))
        frame_rows.append(dict(base, **{key: result.get(key) for key in (
            "input_frames", "frames_with_yolo_detection", "frames_passing_hsv",
            "frames_with_active_track", "frames_triggering_confirmation", "images_sent_to_vlm",
        )}))
        tracking = result.get("tracking", {})
        lifetimes = list(tracking.get("track_lifetime_frames", {}).values())
        tracking_rows.append(dict(
            base, unique_tracks=result.get("unique_tracks"),
            mean_track_lifetime_frames=round(sum(lifetimes) / float(len(lifetimes)), 3) if lifetimes else None,
            max_track_lifetime_frames=max(lifetimes) if lifetimes else None,
            fragmented_actor_count=tracking.get("fragmented_actor_count"),
            possible_merged_track_count=tracking.get("possible_merged_track_count"),
            tracker_cleanup_observed=bool(result.get("tracker_removed_track_ids")),
        ))
        for row in result.get("latency_rows", []):
            latency_rows.append(dict(
                base, sample_index=row["sample_index"], source_frame_id=row["source_frame_id"],
                accepted_monotonic=row["accepted_monotonic"], decision_monotonic=row["decision_monotonic"],
                terminal=row["terminal"], track_id=row["track_id"],
                probe_track=row["track_id"] in probe_tracks, latency_ms=row["latency_ms"],
            ))
    return run_rows, object_rows, frame_rows, tracking_rows, latency_rows


def summarize(run_rows, object_rows, frame_rows, latency_rows):
    scenario_rows, frame_summary_rows, latency_summary_rows = [], [], []
    for scenario in SCENARIOS:
        runs = [row for row in run_rows if row["scenario"] == scenario]
        objects = [row for row in object_rows if row["scenario"] == scenario]
        frames = [row for row in frame_rows if row["scenario"] == scenario]
        if not runs:
            continue

        def total(rows, key):
            return sum(int(row.get(key) or 0) for row in rows)

        successes = sum(bool(row["success"]) for row in runs)
        scenario_rows.append({
            "scenario": scenario, "repetitions": len(runs), "successes": successes,
            "success_rate": _ratio(successes, len(runs)),
            "input_frames": total(frames, "input_frames"),
            "yolo_detections": total(objects, "yolo_detections"),
            "unique_tracks": total(objects, "unique_tracks"),
            "confirmed_tracks": total(objects, "confirmed_tracks"),
            "vlm_requests": total(objects, "vlm_requests"),
            "target_events": total(objects, "target_events"),
            "false_target_events": total(objects, "false_target_events"),
            "max_input_queue": max(int(row["max_input_queue"] or 0) for row in runs),
            "max_candidate_queue": max(int(row["max_candidate_queue"] or 0) for row in runs),
            "ending_queue_depth": max(int(row["ending_queue_depth"] or 0) for row in runs),
            "dropped_frames": total(runs, "dropped_frames"),
            "dropped_events": total(runs, "dropped_events"),
            "backlog_accumulation": sum(int(row["ending_queue_depth"] or 0) > 0 for row in runs),
            "pipeline_crashes": sum(
                row["exit_code"] not in (0, 1) or row["pipeline_alive"] is False for row in runs
            ),
        })
        counts = {key: total(frames, key) for key in (
            "input_frames", "frames_with_yolo_detection", "frames_passing_hsv",
            "frames_with_active_track", "frames_triggering_confirmation", "images_sent_to_vlm",
        )}
        frame_summary_rows.append(dict(
            scenario=scenario, repetitions=len(frames), **counts,
            yolo_positive_over_input=_ratio(counts["frames_with_yolo_detection"], counts["input_frames"]),
            hsv_pass_over_yolo_positive=_ratio(counts["frames_passing_hsv"], counts["frames_with_yolo_detection"]),
            tracking_over_hsv_pass=_ratio(counts["frames_with_active_track"], counts["frames_passing_hsv"]),
            confirmation_over_tracking=_ratio(
                counts["frames_triggering_confirmation"], counts["frames_with_active_track"]
            ),
            vlm_images_over_input=_ratio(counts["images_sent_to_vlm"], counts["input_frames"]),
        ))
        samples = [row for row in latency_rows if row["scenario"] == scenario]
        subsets = [("all_terminal_decisions", samples)]
        for terminal in ("alert_policy_allow", "target_color_reject"):
            subsets.append((terminal, [row for row in samples if row["terminal"] == terminal]))
        subsets.append(("probe_tracks", [row for row in samples if row["probe_track"]]))
        for subset, rows in subsets:
            latency_summary_rows.append(dict(
                scenario=scenario, subset=subset, **latency_summary([float(row["latency_ms"]) for row in rows])
            ))
    return scenario_rows, frame_summary_rows, latency_summary_rows


def _md_value(value):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return "{0:.3f}".format(value).rstrip("0").rstrip(".")
    return str(value)


DETERMINISM_KEYS = (
    "yolo_detections", "unique_tracks", "confirmed_tracks", "vlm_requests", "target_events",
    "duplicate_suppressed",
)


def determinism_lines(run_rows, object_rows):
    lines = []
    for scenario in SCENARIOS:
        objects = [row for row in object_rows if row["scenario"] == scenario]
        runs = [row for row in run_rows if row["scenario"] == scenario]
        if not objects:
            continue
        signature = {
            tuple(row.get(key) for key in DETERMINISM_KEYS) for row in objects
        } | set()
        probe = {
            (row["probe_fov_enter_frame"], row["probe_fov_exit_frame"], row["probe_track_ids"])
            for row in runs
        }
        identical = len(signature) == 1 and len(probe) == 1
        lines.append("- {0}: per-run object counts and probe entry/exit/tracks are {1} across {2} runs.".format(
            scenario, "identical" if identical else "NOT identical", len(objects),
        ))
    return lines


def write_report(output_dir, environment, run_rows, scenario_rows, frame_summary_rows, latency_summary_rows,
                 tracking_rows, object_rows):
    lines = [
        "# Real CARLA dynamic multi-vehicle validation report",
        "",
        "Status: host benchmark executed; every number below is aggregated from per-run",
        "`evidence/benchmark/runs/*/result.json` produced by real CARLA 0.9.13 frames,",
        "Real YOLOv8s on the RTX 3060, production HSV / IoU tracking / temporal",
        "confirmation / deduplication / AlertPolicy, and deterministic Fake VLM / Fake Alert.",
        "It is simulation validation, not real-road or real-vehicle validation.",
        "",
        "Scene: Town10HD_Opt, seed 42, 15 background vehicles + 1 probe (16 controlled),",
        "synchronous 0.1 s ticks, fixed CCTV 800x600 FOV 90, 5 s pre-roll, 100 measured frames",
        "per run. Every run replays the same saved Target manifest; Non-target changes only",
        "the probe colour (blue -> red). Repetitions alternate Target/Non-target in separate",
        "processes.",
        "",
        "## Scenario results",
        "",
        "| Scenario | Runs | Success | Input frames | YOLO dets | Unique tracks | Confirmed tracks | VLM requests | Target events | False target events | Max input queue | Max candidate queue | Dropped frames | Dropped events | Crashes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in scenario_rows:
        lines.append("| {scenario} | {repetitions} | {successes}/{repetitions} | {input_frames} | {yolo_detections} | {unique_tracks} | {confirmed_tracks} | {vlm_requests} | {target_events} | {false_target_events} | {max_input_queue} | {max_candidate_queue} | {dropped_frames} | {dropped_events} | {pipeline_crashes} |".format(**row))
    lines += [
        "",
        "Determinism (computed from the per-run rows):",
        "",
    ] + determinism_lines(run_rows, object_rows) + [
        "",
        "Identical counts mean the synchronous seed-42 scene and the GPU inference were",
        "reproducible run to run. The repetitions therefore establish stability and",
        "latency variation on one scene; they are not independent samples of",
        "detection accuracy and do not support generalisation claims.",
        "",
        "Success: Target = every Target smoke gate PASS and at least one target event;",
        "Non-target = every Non-target gate PASS (probe observed and tracked, no blue probe",
        "confirmation, zero Fake VLM requests, zero target events).",
        "",
        "## Event E2E latency",
        "",
        "Boundary: the triggering CARLA frame's input-queue insertion (perf_counter) to the",
        "final decision: production target-colour rejection at first temporal confirmation",
        "of a track, or AlertPolicy allow (Fake Alert delivery). Same definition as the",
        "single-vehicle validation. YOLO-only latency is not an E2E sample.",
        "",
        "| Scenario | Subset | Samples | Mean | p50 | p95 | p99 | Max | 1 s compliance rate |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in latency_summary_rows:
        lines.append("| {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} | {8} |".format(
            row["scenario"], row["subset"], row["sample_count"],
            *[(_md_value(row[key]) + " ms") if row[key] is not None else "n/a"
              for key in ("mean_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms")],
            _md_value(row["compliance_rate"]),
        ))
    lines += [
        "",
        "## Frame/image retention (frame units only)",
        "",
        "| Scenario | Input | YOLO+ | HSV blue | Active blue track | Blue confirmation | VLM images | YOLO+/Input | HSV/YOLO+ | Track/HSV | Confirm/Track | VLM/Input |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in frame_summary_rows:
        lines.append("| {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} | {8} | {9} | {10} | {11} |".format(
            row["scenario"], row["input_frames"], row["frames_with_yolo_detection"], row["frames_passing_hsv"],
            row["frames_with_active_track"], row["frames_triggering_confirmation"], row["images_sent_to_vlm"],
            *[_md_value(row[key]) for key in (
                "yolo_positive_over_input", "hsv_pass_over_yolo_positive", "tracking_over_hsv_pass",
                "confirmation_over_tracking", "vlm_images_over_input",
            )],
        ))
    lines += [
        "",
        "Object/track/event/request counts are reported separately above and are never",
        "combined with frame counts into one funnel.",
        "",
        "## Per-run gate outcomes",
        "",
        "| Run | Exit | Status | Failed gates | FOV enter/exit | Probe first YOLO frame | Probe tracks | Max boxes | Route dev (m) | Duplicates suppressed |",
        "|---|---:|---|---|---|---:|---|---:|---:|---:|",
    ]
    duplicates = {row["run_id"]: row.get("duplicate_suppressed") for row in object_rows}
    for row in run_rows:
        lines.append("| {0} | {1} | {2} | {3} | {4}/{5} | {6} | {7} | {8} | {9} | {10} |".format(
            row["run_id"], row["exit_code"], row["status"], row["failed_gates"] or "-",
            row["probe_fov_enter_frame"], row["probe_fov_exit_frame"], row["probe_first_detection_frame"],
            row["probe_track_ids"] or "-", row["max_yolo_vehicle_boxes_per_frame"],
            row["probe_route_max_deviation_m"], duplicates.get(row["run_id"]),
        ))
    fragmented = [row["fragmented_actor_count"] for row in tracking_rows if row["fragmented_actor_count"] is not None]
    lines += [
        "",
        "## Tracking diagnostics",
        "",
        "Ground-truth association (IoU >= 0.30 between a production track box and a projected",
        "CARLA actor box) is evidence only. Mean fragmented actors per run: {0}.".format(
            _md_value(sum(fragmented) / float(len(fragmented))) if fragmented else "n/a"
        ),
        "",
        "## Environment",
        "",
    ]
    for key in sorted(environment):
        if key != "stale_validation_cleanup":
            lines.append("- {0}: {1}".format(key, environment[key]))
    lines += [
        "",
        "Historical 46,372 / 28,736 / 3,298 / 53 values are not compared with these",
        "measurements because their units are not established as identical.",
        "",
    ]
    (Path(output_dir) / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")


def load_existing_runs(evidence_dir, runs_dir):
    """Rebuild run records from runs.csv (exit codes, durations) and per-run result.json."""
    runs = []
    with (evidence_dir / "runs.csv").open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            result_path = runs_dir / row["run_id"] / "result.json"
            exit_code = row["exit_code"]
            runs.append({
                "run_id": row["run_id"], "scenario": row["scenario"],
                "repetition": int(row["repetition"]),
                "exit_code": int(exit_code) if exit_code.lstrip("-").isdigit() else exit_code,
                "duration_seconds": float(row["duration_seconds"]),
                "result": json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {},
            })
    return runs


def main(argv=None):
    args = parse_args(argv)
    evidence_dir = Path(args.evidence_dir)
    runs_dir = evidence_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    if args.aggregate_only:
        runs = load_existing_runs(evidence_dir, runs_dir)
        environment = json.loads((evidence_dir / "environment.json").read_text(encoding="utf-8"))
    else:
        manifest_path, environment = prepare_manifest(args, evidence_dir)
        runs = []
        for repetition in range(1, args.repetitions + 1):
            for scenario in SCENARIOS:
                run = run_one(args, scenario, repetition, manifest_path, runs_dir)
                print("{0}: exit={1} status={2} failed={3}".format(
                    run["run_id"], run["exit_code"], run["result"].get("status", "NO_RESULT"),
                    run["result"].get("failed_gates", []),
                ), flush=True)
                runs.append(run)
        first = next((run["result"].get("environment") for run in runs if run["result"].get("environment")), {})
        environment.update(first or {})
    run_rows, object_rows, frame_rows, tracking_rows, latency_rows = build_rows(runs)
    scenario_rows, frame_summary_rows, latency_summary_rows = summarize(
        run_rows, object_rows, frame_rows, latency_rows
    )
    output_dir = Path(args.output_dir)
    _write_csv(output_dir / "scenario_summary.csv", [
        "scenario", "repetitions", "successes", "success_rate", "input_frames", "yolo_detections",
        "unique_tracks", "confirmed_tracks", "vlm_requests", "target_events", "false_target_events",
        "max_input_queue", "max_candidate_queue", "ending_queue_depth", "dropped_frames", "dropped_events",
        "backlog_accumulation", "pipeline_crashes",
    ], scenario_rows)
    _write_csv(output_dir / "object_metrics_raw.csv", [
        "run_id", "scenario", "repetition", "yolo_detections", "unique_tracks", "confirmed_tracks",
        "vlm_requests", "target_events", "false_target_events", "duplicate_suppressed",
    ], object_rows)
    _write_csv(output_dir / "frame_metrics_raw.csv", [
        "run_id", "scenario", "repetition", "input_frames", "frames_with_yolo_detection",
        "frames_passing_hsv", "frames_with_active_track", "frames_triggering_confirmation",
        "images_sent_to_vlm",
    ], frame_rows)
    _write_csv(output_dir / "frame_metrics_summary.csv", [
        "scenario", "repetitions", "input_frames", "frames_with_yolo_detection", "frames_passing_hsv",
        "frames_with_active_track", "frames_triggering_confirmation", "images_sent_to_vlm",
        "yolo_positive_over_input", "hsv_pass_over_yolo_positive", "tracking_over_hsv_pass",
        "confirmation_over_tracking", "vlm_images_over_input",
    ], frame_summary_rows)
    _write_csv(output_dir / "tracking_summary.csv", [
        "run_id", "scenario", "unique_tracks", "mean_track_lifetime_frames", "max_track_lifetime_frames",
        "fragmented_actor_count", "possible_merged_track_count", "tracker_cleanup_observed",
    ], tracking_rows)
    _write_csv(output_dir / "latency_samples.csv", [
        "run_id", "scenario", "repetition", "sample_index", "source_frame_id", "accepted_monotonic",
        "decision_monotonic", "terminal", "track_id", "probe_track", "latency_ms",
    ], latency_rows)
    _write_csv(output_dir / "latency_summary.csv", [
        "scenario", "subset", "sample_count", "mean_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms",
        "at_or_below_1000", "over_1000", "compliance_rate",
    ], latency_summary_rows)
    _write_csv(evidence_dir / "runs.csv", list(run_rows[0].keys()) if run_rows else ["run_id"], run_rows)
    _write_json(evidence_dir / "environment.json", environment)
    write_report(output_dir, environment, run_rows, scenario_rows, frame_summary_rows, latency_summary_rows,
                 tracking_rows, object_rows)
    all_success = all(row["success"] for row in run_rows)
    print("benchmark: {0}/{1} runs successful".format(sum(row["success"] for row in run_rows), len(run_rows)))
    return 0 if all_success else 1


if __name__ == "__main__":
    raise SystemExit(main())

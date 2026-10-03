#!/usr/bin/env python3
"""Aggregate Experiment B v2 runs and build the Before (v1) / After (v2) report.

Reads only saved outputs: v2 evidence/runs/run*/ and v1 ../continuous_ablation/.
"""

from __future__ import annotations

import collections
import csv
import json
import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
V1 = HERE.parent / "continuous_ablation"
RUNS_DIR = HERE / "evidence" / "runs"
BRANCHES = ("full", "no_hsv", "no_temporal", "no_dedup")
TITLES = {"full": "Full", "no_hsv": "No HSV", "no_temporal": "No Temporal", "no_dedup": "No Dedup"}
STAGES = ("entered_fov", "yolo_detected", "hsv_passed", "tracked", "confirmed", "vlm_reached")
STAGE_TITLES = {"entered_fov": "Entered FOV", "yolo_detected": "YOLO detected", "hsv_passed": "HSV passed",
                "tracked": "Tracked", "confirmed": "Confirmed", "vlm_reached": "VLM reached"}


def read_csv(path):
    with Path(path).open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows, fields=None):
    fields = fields or (list(rows[0].keys()) if rows else ["empty"])
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def ratio(a, b):
    return round(a / float(b), 4) if b else None


def load_runs():
    runs = []
    for run_dir in sorted(RUNS_DIR.glob("run*")):
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        if result.get("status") != "COMPLETE":
            raise RuntimeError("{0} is not COMPLETE: {1}".format(run_dir.name, result.get("error")))
        runs.append({
            "name": run_dir.name, "dir": run_dir, "result": result,
            "triggers": read_csv(run_dir / "vlm_trigger_events.csv"),
            "suppressed": read_csv(run_dir / "duplicate_suppressed_events.csv"),
            "funnel": read_csv(run_dir / "target_actor_funnel.csv"),
            "minutes": read_csv(run_dir / "per_minute_summary.csv"),
            "frames": read_csv(run_dir / "frame_metrics.csv"),
            "environment": json.loads((run_dir / "environment.json").read_text(encoding="utf-8")),
        })
    return runs


def duplicate_analysis(triggers):
    """Classify Full triggers on an actor that already had a Full trigger."""
    by_actor = collections.defaultdict(list)
    for row in triggers:
        if row["branch"] == "full" and row["actor_id"]:
            by_actor[row["actor_id"]].append(row)
    repeats = []
    for actor, rows in by_actor.items():
        rows.sort(key=lambda r: float(r["sim_time_s"]))
        for previous, current in zip(rows, rows[1:]):
            gap = float(current["sim_time_s"]) - float(previous["sim_time_s"])
            if gap < 30.0:
                kind = "fragment_leak_within_30s"
            elif current["track_id"] == previous["track_id"]:
                kind = "same_track_cooldown_expired"
            else:
                kind = "new_track_after_30s (revisit or re-track)"
            repeats.append({"actor_id": actor, "time_s": current["sim_time_s"], "gap_s": round(gap, 1),
                            "previous_track": previous["track_id"], "track": current["track_id"], "kind": kind,
                            "dedup_reason": current.get("dedup_reason", "")})
    return repeats


def ablation_rows(runs):
    rows = []
    for run in runs:
        result = run["result"]
        full = result["branches"]["full"]
        for branch in BRANCHES:
            c = result["branches"][branch]
            assoc = result["candidate_association"][branch]
            rows.append({
                "run": run["name"], "configuration": TITLES[branch], "branch": branch,
                "vlm_triggers": c["vlm_triggers"],
                "vs_full_increase": c["vlm_triggers"] - full["vlm_triggers"],
                "vs_full_ratio": ratio(c["vlm_triggers"], full["vlm_triggers"]),
                "candidates_before_dedup": c["candidates_raised"],
                "candidates_vs_full_ratio": ratio(c["candidates_raised"], full["candidates_raised"]),
                "duplicate_suppressed": c["duplicate_suppressed"],
                "suppressed_same_target_cooldown": c["suppressed_same_target_cooldown"],
                "suppressed_fragment_continuity": c["suppressed_fragment_continuity"],
                "unique_tracks_triggering": result["trigger_unique_tracks"][branch],
                "unique_actors_triggering": result["trigger_unique_actors"][branch],
                "unique_target_actors_triggering": result["trigger_target_actors"][branch],
                "triggers_target_actor": assoc.get("trigger_target_actor", 0),
                "triggers_non_target_actor": assoc.get("trigger_non_target_actor", 0),
                "triggers_unassociated": assoc.get("trigger_unassociated", 0),
                "candidates_from_disappeared_tracks": c["candidates_from_disappeared_tracks"],
                "vlm_triggers_from_disappeared_tracks": c["vlm_triggers_from_disappeared_tracks"],
                "frames_with_hsv_candidate": c["frames_with_hsv_candidate"],
                "frames_with_active_target_track": c["frames_with_active_target_track"],
                "frames_triggering_confirmation": c["frames_triggering_confirmation"],
                "frames_with_vlm_trigger": c["frames_with_vlm_trigger"],
                "max_candidates_in_one_frame": c["max_candidates_in_one_frame"],
                "dropped_frames": result["common"]["dropped_camera_frames"],
                "branch_exceptions": c["exceptions"],
            })
    return rows


def v1_before():
    """Before values from the preserved v1 outputs (runs 1-3)."""
    runs = {}
    for name, directory in (("run1", V1 / "evidence" / "runs" / "run1"), ("run2", V1 / "evidence" / "runs" / "run2"),
                            ("run3", V1)):
        ablation = {row["branch"]: row for row in read_csv(directory / "ablation_summary.csv")}
        result_path = directory / ("evidence/result.json" if name == "run3" else "result.json")
        common = json.loads(result_path.read_text(encoding="utf-8"))["common"]
        events = read_csv(directory / "vlm_trigger_events.csv")
        runs[name] = {
            "ablation": ablation, "common": common,
            "target_reached": len({e["actor_id"] for e in events
                                   if e["branch"] == "full" and e["target_color_state"] == "target_actor"}),
        }
    return runs


def span(values):
    values = list(values)
    if not values:
        return "n/a"
    return str(values[0]) if min(values) == max(values) else "{0}-{1}".format(min(values), max(values))


def main():
    runs = load_runs()
    before = v1_before()

    rows = ablation_rows(runs)
    write_csv(HERE / "ablation_summary.csv", rows)

    funnel_rows = []
    for run in runs:
        for row in run["funnel"]:
            funnel_rows.append(dict({"run": run["name"]}, **row))
    write_csv(HERE / "target_actor_funnel.csv", funnel_rows)

    frame_funnel = []
    for run in runs:
        common, full = run["result"]["common"], run["result"]["branches"]["full"]
        stages = [("input_frames", common["input_frames"]),
                  ("frames_with_yolo_vehicle_detection", common["frames_with_vehicle_detection"]),
                  ("frames_with_target_hsv_candidate", full["frames_with_hsv_candidate"]),
                  ("frames_with_active_target_track", full["frames_with_active_target_track"]),
                  ("frames_triggering_temporal_confirmation", full["frames_triggering_confirmation"]),
                  ("frames_triggering_vlm", full["frames_with_vlm_trigger"])]
        previous = None
        for stage, count in stages:
            frame_funnel.append({"run": run["name"], "stage": stage, "count": count,
                                 "previous_stage_retention": ratio(count, previous) if previous is not None else None,
                                 "input_ratio": ratio(count, common["input_frames"])})
            previous = count
    write_csv(HERE / "full_pipeline_funnel.csv", frame_funnel)

    write_csv(HERE / "vlm_trigger_events.csv", [dict({"run": r["name"]}, **e) for r in runs for e in r["triggers"]])
    write_csv(HERE / "duplicate_suppressed_events.csv",
              [dict({"run": r["name"]}, **e) for r in runs for e in r["suppressed"]])
    write_csv(HERE / "per_minute_summary.csv", [dict({"run": r["name"]}, **m) for r in runs for m in r["minutes"]])
    repeats = {r["name"]: duplicate_analysis(r["triggers"]) for r in runs}
    write_csv(HERE / "full_repeat_trigger_analysis.csv",
              [dict({"run": name}, **row) for name, items in repeats.items() for row in items],
              ["run", "actor_id", "time_s", "gap_s", "previous_track", "track", "kind", "dedup_reason"])

    environment = dict(runs[0]["environment"])
    environment["runs"] = [r["environment"]["label"] for r in runs]
    environment["production_changes"] = {
        "harness/core/pipeline.py": "YoloWorker: TemporalConfirm.update only for tracks matched in this frame; "
                                    "OpenClawWorker: per-target dedup via Deduplicator.should_verify_target",
        "harness/perception/deduplicator.py": "should_verify_target: per (camera, track) cooldown 30 s, "
                                              "fragment continuity (same colour, <= 2.0 s, centre within box diagonal)",
    }
    (HERE / "environment.json").write_text(json.dumps(environment, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (HERE / "run.log").open("w", encoding="utf-8") as log:
        for run in runs:
            log.write("===== {0} ({1}) =====\n".format(run["name"], run["environment"]["label"]))
            log.write((run["dir"] / "run.log").read_text(encoding="utf-8"))

    # Before/After
    v2 = {r["name"]: r for r in runs}
    by = {(row["run"], row["branch"]): row for row in rows}
    names = [r["name"] for r in runs]

    def after(branch, key):
        return span(by[(n, branch)][key] for n in names)

    def target_entered(run):
        return run["result"]["common"]["target_color_vehicles_entering_fov"]

    before_after = [
        {"metric": "stale (disappeared-track) Full candidates",
         "before": "{0} / {1} (run3; runs 1-2 not recorded)".format(
             before["run3"]["ablation"]["full"]["candidates_from_disappeared_tracks"],
             before["run3"]["ablation"]["full"]["candidates_raised"]),
         "after": " ; ".join("{0}: {1} / {2}".format(n, by[(n, 'full')]["candidates_from_disappeared_tracks"],
                                                     by[(n, 'full')]["candidates_before_dedup"]) for n in names)},
        {"metric": "stale (disappeared-track) Full VLM triggers",
         "before": "{0} / {1} (run3)".format(before["run3"]["ablation"]["full"]["vlm_triggers_from_disappeared_tracks"],
                                             before["run3"]["ablation"]["full"]["vlm_triggers"]),
         "after": " ; ".join("{0}: {1} / {2}".format(n, by[(n, 'full')]["vlm_triggers_from_disappeared_tracks"],
                                                     by[(n, 'full')]["vlm_triggers"]) for n in names)},
        {"metric": "target vehicles entering FOV",
         "before": "/".join(str(before[n]["common"]["target_color_vehicles_entering_fov"]) for n in ("run1", "run2", "run3")),
         "after": "/".join(str(target_entered(v2[n])) for n in names)},
        {"metric": "target vehicles reaching VLM (Full)",
         "before": ", ".join("{0}/{1}".format(before[n]["target_reached"], before[n]["common"]["target_color_vehicles_entering_fov"])
                            for n in ("run1", "run2", "run3")),
         "after": ", ".join("{0}/{1}".format(by[(n, 'full')]["unique_target_actors_triggering"], target_entered(v2[n]))
                           for n in names)},
    ]
    for branch in BRANCHES:
        before_after.append({
            "metric": "{0} VLM triggers".format(TITLES[branch]),
            "before": "/".join(before[n]["ablation"][branch]["vlm_triggers"] for n in ("run1", "run2", "run3")),
            "after": "/".join(str(by[(n, branch)]["vlm_triggers"]) for n in names)})
    before_after.append({
        "metric": "Full candidates before dedup",
        "before": "/".join(before[n]["ablation"]["full"]["candidates_raised"] for n in ("run1", "run2", "run3")),
        "after": "/".join(str(by[(n, 'full')]["candidates_before_dedup"]) for n in names)})
    write_csv(HERE / "before_after_summary.csv", before_after, ["metric", "before", "after"])

    # Before/After stale image evidence
    evidence = HERE / "evidence" / "before_after"
    evidence.mkdir(parents=True, exist_ok=True)
    shutil.copy(V1 / "evidence" / "runs" / "run2" / "trigger_crops" / "full" / "f1300_t77.jpg",
                evidence / "before_v1_run2_full_stale_trigger_f1300_t77.jpg")
    try:
        import cv2
        import numpy as np
        tiles = []
        for run in runs:
            for event in run["triggers"]:
                if event["branch"] == "full" and event["crop"]:
                    image = cv2.imread(str(run["dir"] / "evidence" / "trigger_crops" / event["crop"]))
                    if image is None:
                        continue
                    tile = cv2.resize(image, (160, 100))
                    cv2.putText(tile, "{0} t{1}".format(run["name"][-1], int(float(event["sim_time_s"]))), (3, 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)
                    tiles.append(tile)
        if tiles:
            per_row = 8
            while len(tiles) % per_row:
                tiles.append(np.zeros_like(tiles[0]))
            sheet = np.vstack([np.hstack(tiles[i:i + per_row]) for i in range(0, len(tiles), per_row)])
            cv2.imwrite(str(evidence / "after_v2_all_full_trigger_crops.jpg"), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    except ImportError:
        pass

    write_report(runs, rows, funnel_rows, frame_funnel, before_after, repeats, by, names)
    print((HERE / "validation_report.md").read_text(encoding="utf-8")[:6000])


def write_report(runs, rows, funnel_rows, frame_funnel, before_after, repeats, by, names):
    L = []
    L += ["# Experiment B v2: stale-track and per-target dedup fix, 10-minute continuous ablation", "",
          "Before = Experiment B v1 (`../continuous_ablation/`, preserved). After = this directory:",
          "{0} independent full 10-minute runs on the same scene/traffic configuration, with the".format(len(runs)),
          "fixed production logic. Within each run the four shadow branches share identical frames",
          "and YOLO output. Runs (and Before vs After) are not bit-identical, so per-run branch",
          "comparisons are primary and cross-run absolute numbers are context only.", "",
          "## Production changes", "",
          "1. `harness/core/pipeline.py` (YoloWorker): `TemporalConfirm.update` is called only for tracks",
          "   matched to a detection in the current frame (`track.disappeared == 0`). Unmatched tracks stay",
          "   in the tracker for association/reconnect but gain no temporal evidence, so no stale track can",
          "   be confirmed and every candidate bbox is the current detection bbox.",
          "2. `harness/core/pipeline.py` (OpenClawWorker) + `harness/perception/deduplicator.py`: VLM dedup",
          "   changed from one 30 s cooldown per camera agent to `should_verify_target(camera, track,",
          "   colour, bbox, now)`: a 30 s cooldown per target (track), plus fragment continuity - a new",
          "   track with the same confirmed colour, within 2.0 s (the tracker's RECONNECT_WINDOW) of the",
          "   target's last candidate and with its centre within one box diagonal, is the same target.",
          "   Only production information is used (camera, track id, colour, bbox, time); no CARLA IDs.",
          "", "Unit/regression tests: `tests/unit/test_dedup_and_stale_tracks.py`; v2 shadow equivalence with",
          "the production Pipeline: `tests/validation/test_continuous_ablation_v2.py`.", "",
          "## Before / After", "", "| Metric | Before (v1 runs 1/2/3) | After (v2 runs) |", "|---|---|---|"]
    for row in before_after:
        L.append("| {metric} | {before} | {after} |".format(**row))
    L += ["", "## Ablation (After)", "",
          "| Run | Configuration | VLM triggers | vs Full | Candidates before dedup | Candidates vs Full | Dedup-suppressed (same target / fragment) | Unique target vehicles reaching VLM |",
          "|---|---|---:|---:|---:|---:|---|---:|"]
    for row in rows:
        L.append("| {run} | {configuration} | {vlm_triggers} | {vs} | {candidates_before_dedup} | {cr} | {duplicate_suppressed} ({suppressed_same_target_cooldown} / {suppressed_fragment_continuity}) | {unique_target_actors_triggering} |".format(
            vs="1.00x" if row["branch"] == "full" else "{0:+d}, {1}x".format(row["vs_full_increase"], row["vs_full_ratio"]),
            cr="1.00x" if row["branch"] == "full" else "{0}x".format(row["candidates_vs_full_ratio"]), **row))
    L += ["", "What the triggers hit (actor association is evidence only):", "",
          "| Run | Configuration | Target / non-target / unassociated triggers | Triggers from disappeared tracks | Exceptions |",
          "|---|---|---|---:|---:|"]
    for row in rows:
        L.append("| {run} | {configuration} | {triggers_target_actor} / {triggers_non_target_actor} / {triggers_unassociated} | {vlm_triggers_from_disappeared_tracks} | {branch_exceptions} |".format(**row))

    L += ["", "## Target coverage (Full branch)", ""]
    for run in runs:
        actors = [r for r in funnel_rows if r["run"] == run["name"]]
        L += ["### {0}".format(run["name"]), "",
              "| Target actor (slot / blueprint) | FOV entry | YOLO | HSV | Track | Temporal | VLM Trigger | Failure reason |",
              "|---|---|---|---|---|---|---|---|"]
        for a in actors:
            def mark(stage):
                return "{0}s".format(a[stage + "_first_s"]) if a[stage] == "True" else "-"
            L.append("| {0} / {1} | {2} | {3} | {4} | {5} | {6} | {7} | {8} |".format(
                a["slot"], a["blueprint"], *[mark(s) for s in STAGES], a["failure_reason"] or "-"))
        L += ["", "| Stage | Unique target vehicles |", "|---|---:|"]
        for stage in STAGES:
            L.append("| {0} | {1} |".format(STAGE_TITLES[stage], sum(1 for a in actors if a[stage] == "True")))
        blocked = [a for a in actors if a["blocked_by_other_actor"]]
        L += ["", "Target vehicles with suppression owned by a different actor: {0}{1}.".format(
            len(blocked), " ({0})".format(", ".join("slot {0} by actor {1}".format(a["slot"], a["blocked_by_other_actor"])
                                                   for a in blocked)) if blocked else ""), ""]

    def series(branch, key):
        return "/".join(str(by[(n, branch)][key]) for n in names)

    def ratio_span(branch, key):
        values = [by[(n, branch)][key] / float(by[(n, "full")][key]) for n in names]
        return "{0:.2f}-{1:.2f}x".format(min(values), max(values))

    leaks = [sum(1 for r in repeats[n] if r["kind"] == "fragment_leak_within_30s") for n in names]
    blocked_total = sum(1 for r in funnel_rows if r["blocked_by_other_actor"])
    L += ["## Answers (per-run shadow comparison on identical input; not causal claims)", "",
          "1. HSV removed: VLM triggers {0} -> {1} ({2}).".format(
              series("full", "vlm_triggers"), series("no_hsv", "vlm_triggers"), ratio_span("no_hsv", "vlm_triggers")),
          "2. Temporal removed: candidates before dedup {0} -> {1} ({2}); VLM triggers {3} -> {4} ({5}).".format(
              series("full", "candidates_before_dedup"), series("no_temporal", "candidates_before_dedup"),
              ratio_span("no_temporal", "candidates_before_dedup"), series("full", "vlm_triggers"),
              series("no_temporal", "vlm_triggers"), ratio_span("no_temporal", "vlm_triggers")),
          "3. Dedup removed: VLM triggers {0} -> {1} ({2}).".format(
              series("full", "vlm_triggers"), series("no_dedup", "vlm_triggers"), ratio_span("no_dedup", "vlm_triggers")),
          "4. New dedup: unique target vehicles reaching VLM {0} of {1}; target vehicles whose".format(
              series("full", "unique_target_actors_triggering"),
              "/".join(str(r["result"]["common"]["target_color_vehicles_entering_fov"]) for r in runs)),
          "   candidates were suppressed by another vehicle's entry: {0}. Full suppressed {1} candidates".format(
              blocked_total, series("full", "duplicate_suppressed")),
          "   (same target {0}, fragment {1}); residual fragmentation leaks (<30 s repeat on the same".format(
              series("full", "suppressed_same_target_cooldown"), series("full", "suppressed_fragment_continuity")),
          "   vehicle) {0}.".format("/".join(map(str, leaks))),
          "5. Stale tracks: Full candidates from disappeared tracks {0}, VLM triggers {1}; triggers whose".format(
              series("full", "candidates_from_disappeared_tracks"), series("full", "vlm_triggers_from_disappeared_tracks")),
          "   bbox is not a current-frame detection: {0}.".format(sum(
              1 for r in runs for e in r["triggers"] if e["bbox_is_current_detection"] != "True")),
          "",
          "Ground-truth colour caveat (verified by crops): `vehicle.micro.microlino` renders a blue body",
          "regardless of the assigned `color` attribute, so the yellow-assigned Microlino is labelled",
          "non-target although it is visibly blue (e.g. `evidence/runs/run2/evidence/trigger_crops/full/f3381_t206.jpg`).",
          "All Full `non-target` triggers in these runs are that vehicle. The same artefact affects",
          "Experiment B v1's `non_target_actor` counts for the Microlino; v1 files are left unchanged.", ""]
    L += ["## Duplicate handling (Full)", "",
          "| Run | Total VLM triggers | Unique target vehicles reaching VLM | Same-target suppressed | Fragment suppressed | Repeat triggers on an already-triggered vehicle (<30 s leak / >=30 s) |",
          "|---|---:|---:|---:|---:|---|"]
    for name in names:
        row = by[(name, "full")]
        rep = repeats[name]
        leak = sum(1 for r in rep if r["kind"] == "fragment_leak_within_30s")
        L.append("| {0} | {1} | {2} | {3} | {4} | {5} / {6} |".format(
            name, row["vlm_triggers"], row["unique_target_actors_triggering"], row["suppressed_same_target_cooldown"],
            row["suppressed_fragment_continuity"], leak, len(rep) - leak))
    L += ["", "Repeat triggers are listed in `full_repeat_trigger_analysis.csv`. A <30 s repeat on the same",
          "vehicle is a fragmentation leak (new track ID not linked by the continuity rule, e.g. after the",
          "vehicle passes behind the street banner); >=30 s repeats are cooldown expiry or a later revisit,",
          "which production cannot distinguish without re-identification.", "",
          "## Full pipeline frame funnel (frame units)", "",
          "| Run | Stage | Count | Previous-stage retention | Input ratio |", "|---|---|---:|---:|---:|"]
    for row in frame_funnel:
        L.append("| {run} | {stage} | {count} | {previous_stage_retention} | {input_ratio} |".format(**row))
    L += ["", "## Runs", "", "| Run | Frames | Duration (s) | Unique vehicles in FOV | Target / non-target in FOV | YOLO detections | Dropped frames | Exceptions | Cleanup |",
          "|---|---:|---:|---:|---|---:|---:|---:|---|"]
    for run in runs:
        c, r = run["result"]["common"], run["result"]
        L.append("| {0} | {1} | {2} | {3} | {4} / {5} | {6} | {7} | {8} | {9}/{10} |".format(
            run["name"], c["input_frames"], c["simulation_duration_s"], c["unique_vehicles_entering_fov"],
            c["target_color_vehicles_entering_fov"], c["non_target_vehicles_entering_fov"],
            c["total_yolo_vehicle_detections"], c["dropped_camera_frames"],
            sum(b["exceptions"] for b in r["branches"].values()),
            r["cleanup"]["destroyed"], r["cleanup"]["attempted"]))
    L += ["", "## Evidence images", "",
          "- `evidence/runs/run*/evidence/stages/`: per target vehicle, first YOLO detection / HSV pass /",
          "  matched blue track / temporal confirmation / VLM trigger (white = projected CARLA box).",
          "- `evidence/runs/run*/evidence/dedup_suppressed/`: same-target and fragment suppressions.",
          "- `evidence/runs/run*/evidence/new_target_within_30s/`: a different target reaching VLM <30 s",
          "  after the previous trigger (blocked under the Before policy).",
          "- `evidence/before_after/`: Before stale trigger crop (empty road) and all After Full trigger crops.",
          "", "Limitations: `limitations.md`. VLM requests are counted triggers; no VLM is called.",
          "Historical 46,372 / 28,736 / 3,298 / 53 values are not compared.", ""]
    (HERE / "validation_report.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Render replay_benchmark.py JSON results as Markdown tables (mean over repeats, min-max in brackets).

    python3 tools/benchmark_table.py after.json                 # one result set
    python3 tools/benchmark_table.py before.json after.json     # Before / After per mode
Missing metrics (not present in that code version) are shown as "n/a".
"""

import json
import statistics
import sys

ROWS = [
    ("frames_pushed", "frames pushed"),
    ("frames_processed", "frames processed"),
    ("frames_dropped", "frames dropped"),
    ("candidates_dropped", "candidates dropped"),
    ("detections_total", "detections (FakeDetector)"),
    ("candidates_raised", "candidates raised"),
    ("duplicate_suppressed", "duplicates suppressed"),
    ("openclaw_calls", "VLM calls"),
    ("alerts_sent", "alerts attempted (alerts_sent)"),
    ("alerts_delivered", "alerts delivered"),
    ("max_depth_frame_queue", "max frame-queue depth"),
    ("max_depth_candidate_queue", "max candidate-queue depth"),
    ("max_depth_result_queue", "max result-queue depth"),
    ("detector_stage_ms_mean", "detector stage mean ms (FakeDetector)"),
    ("e2e_alert_ms_mean", "E2E push->alert mean ms"),
    ("e2e_alert_ms_max", "E2E push->alert max ms"),
    ("throughput_fps", "throughput frames/s"),
]


def agg(runs, key):
    vals = [r.get(key) for r in runs if r.get(key) is not None]
    if not vals:
        return "n/a"
    mean = statistics.mean(vals)
    def fmt(v):
        return f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}"
    return fmt(mean) if min(vals) == max(vals) else f"{fmt(mean)} [{fmt(min(vals))}–{fmt(max(vals))}]"


def by_mode(result):
    out = {}
    for r in result["runs"]:
        out.setdefault(r["mode"], []).append(r)
    return out


def main(paths):
    results = [json.load(open(p)) for p in paths]
    modes = list(by_mode(results[-1]))
    for mode in modes:
        cols = [by_mode(r).get(mode, []) for r in results]
        heads = [f"{'Before' if len(results) == 2 and i == 0 else 'After' if len(results) == 2 else 'Result'} ({r['code_commit']}, n={len(c)})"
                 for i, (r, c) in enumerate(zip(results, cols))]
        print(f"\n#### mode `{mode}`\n")
        print("| metric | " + " | ".join(heads) + " |")
        print("|---|" + "---|" * len(heads))
        for key, label in ROWS:
            print(f"| {label} | " + " | ".join(agg(c, key) for c in cols) + " |")


if __name__ == "__main__":
    main(sys.argv[1:])

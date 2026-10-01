#!/usr/bin/env python3
"""Replay benchmark for the UROPCLAW pipeline (system behaviour, not model accuracy).

Runs the real Pipeline (world=None) on deterministic synthetic scenes with the
test doubles from tests/fakes injected:

    detector  FakeDetector (box finder; NOT YOLOv8 -> YOLO latency is not measured)
    VLM       SuccessVLM with a fixed artificial delay (NOT a real model)
    alert     recording sender (no Discord)

Scene per run: agent uropclaw1 sees a moving BLUE box (mission target),
agent uropclaw2 sees a moving RED box (non-target). Frames are pushed through
Pipeline.push_frame() at a fixed interval, alternating agents.

Measured (only what the harness can observe):
    pipeline metrics (frames, detections, candidates, VLM calls, drops, alerts)
    max queue depth (frame / candidate / result), sampled every 5 ms
    detector-stage latency (FakeDetector) from yolo_latency_ms_list
    E2E latency = alert sender call time - frame push timestamp (per alert)
    throughput  = frames_processed / wall time of the replay

Usage:
    PYTHONPATH=<deps> python3 tools/replay_benchmark.py --modes A B C proposed --repeat 3 \
        --out validation/benchmark_results/current.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "harness"), str(ROOT / "tests")]

import core.mission as mission_mod  # noqa: E402
import core.pipeline as pipeline_mod  # noqa: E402
from fakes.components import FakeDetector, SuccessVLM  # noqa: E402
from replay.source import SyntheticSceneSource  # noqa: E402


def pct(values, p):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


class RecordingAlert:
    def __init__(self):
        self.latencies_ms = []
        self.count = 0
        self._lock = threading.Lock()

    def __call__(self, agent_id, event):
        now = time.time()
        with self._lock:
            self.count += 1
            self.latencies_ms.append((now - event["timestamp"]) * 1000.0)
        return True


def run_once(mode, frames, interval_s, vlm_delay_s, detector_delay_s):
    tmp = Path(tempfile.mkdtemp(prefix="uropclaw_bench_"))
    mission_mod._MISSION_PATH = tmp / "uropclaw1" / "state" / "mission.json"
    pipeline_mod.WORKSPACE_BASE = tmp
    pipeline_mod._METRICS_PATH = tmp / "uropclaw1" / "state" / "metrics.json"
    pipeline_mod._METRICS_INTERVAL = 0.5
    mission_mod.write_mission({"active": True, "target_color": "blue", "mission_id": "bench"})

    alert = RecordingAlert()
    vlm = SuccessVLM(delay_s=vlm_delay_s)
    p = pipeline_mod.Pipeline(world=None, baseline_mode=mode, detector=FakeDetector(delay_s=detector_delay_s),
                              vlm_runner=vlm, alert_sender=alert)
    depth = {"frame": 0, "candidate": 0, "result": 0}
    stop_sampler = threading.Event()

    def sampler():
        while not stop_sampler.is_set():
            depth["frame"] = max(depth["frame"], p.frame_queue.qsize())
            depth["candidate"] = max(depth["candidate"], p._candidate_queue.qsize())
            depth["result"] = max(depth["result"], p._result_queue.qsize())
            time.sleep(0.005)

    threading.Thread(target=sampler, daemon=True).start()
    p.start()
    blue = iter(SyntheticSceneSource(frames, colour="blue", agent_id="uropclaw1", step_px=1))
    red = iter(SyntheticSceneSource(frames, colour="red", agent_id="uropclaw2", step_px=1))
    t0 = time.time()
    pushed = 0
    for b, r in zip(blue, red):
        for rf in (b, r):
            p.push_frame(rf.camera_id, rf.agent_id, rf.frame, timestamp=time.time())
            pushed += 1
            time.sleep(interval_s)
    # drain: wait until all queues are empty and the VLM/alert stages are idle
    deadline = time.time() + 30
    while time.time() < deadline:
        if p.frame_queue.empty() and p._candidate_queue.empty() and p._result_queue.empty():
            time.sleep(max(0.5, vlm_delay_s * 2))
            if p.frame_queue.empty() and p._candidate_queue.empty() and p._result_queue.empty():
                break
        time.sleep(0.05)
    wall = time.time() - t0
    m = p.metrics_summary()
    stop_sampler.set()
    p.stop()

    det_lat = m.get("yolo_latency_ms_list", [])
    keys = ["frames_received", "frames_processed", "frames_dropped", "candidates_dropped", "detections_total",
            "color_filter_passed", "candidates_raised", "duplicate_suppressed", "openclaw_calls",
            "openclaw_confirmed", "openclaw_timeouts", "openclaw_errors", "openclaw_parse_failures",
            "alerts_sent", "alerts_delivered", "alerts_failed"]
    return {
        "mode": mode,
        "frames_pushed": pushed,
        **{k: m.get(k) for k in keys},
        "vlm_calls_observed": vlm.calls,
        "max_depth_frame_queue": depth["frame"],
        "max_depth_candidate_queue": depth["candidate"],
        "max_depth_result_queue": depth["result"],
        "detector_stage_ms_mean": statistics.mean(det_lat) if det_lat else None,
        "detector_stage_ms_p95": pct(det_lat, 95),
        "e2e_alert_ms_mean": statistics.mean(alert.latencies_ms) if alert.latencies_ms else None,
        "e2e_alert_ms_p95": pct(alert.latencies_ms, 95),
        "e2e_alert_ms_max": max(alert.latencies_ms) if alert.latencies_ms else None,
        "alerts_observed": alert.count,
        "throughput_fps": round(m["frames_processed"] / wall, 2) if wall else None,
        "wall_s": round(wall, 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="+", default=["A", "B", "C", "proposed"])
    ap.add_argument("--frames", type=int, default=150, help="frames per agent")
    ap.add_argument("--interval", type=float, default=0.02, help="seconds between pushed frames")
    ap.add_argument("--vlm-delay", type=float, default=0.2, help="artificial SuccessVLM latency (s)")
    ap.add_argument("--detector-delay", type=float, default=0.0)
    ap.add_argument("--baseline-n", type=int, default=None, help="override BASELINE_N (production 30)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.baseline_n:
        pipeline_mod.BASELINE_N = args.baseline_n

    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = "unknown"
    runs = []
    for mode in args.modes:
        for i in range(args.repeat):
            r = run_once(mode, args.frames, args.interval, args.vlm_delay, args.detector_delay)
            r["repeat"] = i + 1
            runs.append(r)
            print(json.dumps(r))
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "code_commit": commit,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "processor": platform.processor() or platform.machine()},
        "config": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "baseline_n": pipeline_mod.BASELINE_N,
        "not_measured": ["YOLOv8 inference latency (FakeDetector used)", "real VLM latency/accuracy",
                         "Discord delivery latency", "CARLA camera capture latency"],
        "runs": runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

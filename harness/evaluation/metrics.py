"""Metrics collection and evaluation reporting."""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import WORKSPACE_BASE

METRICS_PATH = WORKSPACE_BASE / "uropclaw1" / "state" / "metrics.json"
REPORT_PATH = WORKSPACE_BASE / "uropclaw1" / "state" / "eval_report.json"


@dataclass
class PipelineMetrics:
    # 기본 메트릭 (Phase 1부터)
    frames_received: int = 0
    frames_dropped: int = 0
    frames_processed: int = 0
    detections_total: int = 0
    color_filter_passed: int = 0
    candidates_raised: int = 0
    alerts_sent: int = 0
    duplicate_suppressed: int = 0

    # Phase 3 OpenClaw 메트릭
    openclaw_calls: int = 0
    openclaw_confirmed: int = 0
    openclaw_timeouts: int = 0
    openclaw_rejected: int = 0

    # 레이턴시 (ms 단위 리스트)
    yolo_latency_ms: list = field(default_factory=list)
    pipeline_latency_ms: list = field(default_factory=list)

    # 시작 시각
    start_time: float = field(default_factory=time.time)
    baseline_mode: str = "proposed"  # "A", "B", "C", "proposed"

    def openclaw_call_reduction_rate(self) -> float:
        """1 - (openclaw_calls / frames_processed). 핵심 평가 지표."""
        if self.frames_processed == 0:
            return 0.0
        return 1.0 - (self.openclaw_calls / self.frames_processed)

    def frame_drop_rate(self) -> float:
        total = self.frames_received
        return (self.frames_dropped / total) if total > 0 else 0.0

    def avg_yolo_latency_ms(self) -> float:
        return sum(self.yolo_latency_ms) / len(self.yolo_latency_ms) if self.yolo_latency_ms else 0.0

    def pipeline_fps(self) -> float:
        elapsed = time.time() - self.start_time
        return self.frames_processed / elapsed if elapsed > 0 else 0.0

    def summary(self) -> dict:
        return {
            "baseline_mode": self.baseline_mode,
            "frames_received": self.frames_received,
            "frames_dropped": self.frames_dropped,
            "frames_processed": self.frames_processed,
            "frame_drop_rate": round(self.frame_drop_rate(), 4),
            "pipeline_fps": round(self.pipeline_fps(), 2),
            "detections_total": self.detections_total,
            "color_filter_passed": self.color_filter_passed,
            "candidates_raised": self.candidates_raised,
            "alerts_sent": self.alerts_sent,
            "duplicate_suppressed": self.duplicate_suppressed,
            "openclaw_calls": self.openclaw_calls,
            "openclaw_confirmed": self.openclaw_confirmed,
            "openclaw_timeouts": self.openclaw_timeouts,
            "openclaw_call_reduction_rate": round(self.openclaw_call_reduction_rate(), 4),
            "avg_yolo_latency_ms": round(self.avg_yolo_latency_ms(), 2),
        }

    def save(self) -> None:
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        METRICS_PATH.write_text(
            json.dumps(self.summary(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls) -> Optional["PipelineMetrics"]:
        if not METRICS_PATH.exists():
            return None
        try:
            data = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
            m = cls()
            for k, v in data.items():
                if hasattr(m, k):
                    setattr(m, k, v)
            return m
        except Exception:
            return None


def generate_report(results: list[dict]) -> dict:
    """여러 baseline 결과를 비교하는 리포트 생성."""
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baselines": results,
        "comparison": {},
    }

    proposed = next((r for r in results if r.get("baseline_mode") == "proposed"), None)
    if proposed:
        for other in results:
            if other["baseline_mode"] == proposed["baseline_mode"]:
                continue
            label = other["baseline_mode"]
            report["comparison"][f"vs_baseline_{label}"] = {
                "openclaw_call_reduction_improvement": round(
                    proposed.get("openclaw_call_reduction_rate", 0)
                    - other.get("openclaw_call_reduction_rate", 0),
                    4,
                ),
                "alert_count_diff": proposed.get("alerts_sent", 0) - other.get("alerts_sent", 0),
            }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report

"""Baseline pipeline modes for evaluation comparison.

Baseline A: Every Nth frame sent to OpenClaw (no YOLO/color filter).
Baseline B: YOLO only — crops sent to OpenClaw without color filter or dedup.
Baseline C: YOLO + color filter, no OpenClaw.
Proposed:   Full pipeline (YOLO + color + tracker + temporal + dedup + OpenClaw).
"""
from enum import Enum


class BaselineMode(Enum):
    A = "A"                # Every Nth frame → OpenClaw
    B = "B"                # YOLO → OpenClaw (no color filter, no dedup)
    C = "C"                # YOLO + color filter (no OpenClaw)
    PROPOSED = "proposed"  # Full pipeline


BASELINE_N = 30  # Baseline A: every 30th frame


def should_send_to_openclaw_baseline_a(frame_count: int) -> bool:
    return frame_count % BASELINE_N == 0


def should_send_to_openclaw_baseline_b(detection_count: int) -> bool:
    """YOLO 감지만 있으면 모두 전송."""
    return detection_count > 0


def color_filter_enabled(mode: BaselineMode) -> bool:
    return mode in (BaselineMode.C, BaselineMode.PROPOSED)


def openclaw_enabled(mode: BaselineMode) -> bool:
    return mode in (BaselineMode.A, BaselineMode.B, BaselineMode.PROPOSED)


def dedup_enabled(mode: BaselineMode) -> bool:
    return mode == BaselineMode.PROPOSED

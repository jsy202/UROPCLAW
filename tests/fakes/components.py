"""Test doubles for UROPCLAW's external dependencies. Never used by the production path.

Detector : FakeDetector       - finds non-road boxes in synthetic frames (stands in for YOLOv8)
VLM      : SuccessVLM / RejectVLM / TimeoutVLM / ErrorVLM / MalformedResponseVLM
           - stand-ins for subprocess.run(["claude", "--print", ...]); the pipeline's real
             prompt building, JSON parsing and fail-open fallback still run
Alert    : FakeAlert          - records alerts instead of calling Discord; can fail
"""

from __future__ import annotations

import json
import subprocess
import threading
import time

import cv2
import numpy as np

from perception.yolo_detector import Detection
from replay.source import ROAD_BGR


class FakeDetector:
    def __init__(self, delay_s: float = 0.0, confidence: float = 0.9):
        self.calls = 0
        self.delay_s, self.confidence = delay_s, confidence

    def __call__(self, frame):
        self.calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        mask = np.any(frame != np.array(ROAD_BGR, np.uint8), axis=2).astype(np.uint8)  # raises on invalid frame, like YOLO would
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        dets = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if w * h >= 400:
                dets.append(Detection(bbox=[x, y, x + w, y + h], class_id=2, class_name="car", confidence=self.confidence))
        return dets


class EmptyDetector:
    def __init__(self):
        self.calls = 0

    def __call__(self, frame):
        self.calls += 1
        return []


class _VLMBase:
    def __init__(self):
        self.calls = 0
        self.prompts: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, cmd, input=None, capture_output=True, timeout=None, **kw):
        assert cmd[0] == "claude", cmd
        with self._lock:
            self.calls += 1
            self.prompts.append(input.decode() if isinstance(input, bytes) else str(input))
        return self.respond(cmd, timeout)

    @staticmethod
    def _done(cmd, stdout: str, rc: int = 0, stderr: str = ""):
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout.encode(), stderr=stderr.encode())


class SuccessVLM(_VLMBase):
    def __init__(self, confirmed=True, confidence="high", delay_s=0.0):
        super().__init__()
        self.confirmed, self.confidence, self.delay_s = confirmed, confidence, delay_s

    def respond(self, cmd, timeout):
        if self.delay_s:
            time.sleep(self.delay_s)
        body = {"visible_vehicle": True, "color": "blue", "color_match": self.confirmed, "body_type": "car",
                "body_type_match": True, "confidence": self.confidence, "confirmed": self.confirmed,
                "reason": "테스트 응답"}
        return self._done(cmd, "Here is the result:\n" + json.dumps(body))


def RejectVLM():
    return SuccessVLM(confirmed=False)


class TimeoutVLM(_VLMBase):
    def respond(self, cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)


class ErrorVLM(_VLMBase):
    """The `claude` CLI is missing / cannot start."""
    def respond(self, cmd, timeout):
        raise FileNotFoundError(2, "No such file or directory", "claude")


class MalformedResponseVLM(_VLMBase):
    def respond(self, cmd, timeout):
        return self._done(cmd, "I think it is probably a blue car, confidence high.")


class FakeAlert:
    """alert_sender(agent_id, event) -> bool. Records every attempt; can fail by return value or exception."""

    def __init__(self, fail: str | None = None):
        self.attempts: list[tuple[str, dict]] = []
        self.fail = fail  # None | "false" | "raise"
        self._lock = threading.Lock()

    def __call__(self, agent_id, event):
        with self._lock:
            self.attempts.append((agent_id, event))
        if self.fail == "raise":
            raise ConnectionError("discord unreachable (fake)")
        return self.fail != "false"

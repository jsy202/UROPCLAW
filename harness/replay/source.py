"""Replay input sources: feed recorded or synthetic frames into Pipeline.push_frame().

Production input is the CARLA camera (sensors/camera.py), which writes into
Pipeline.frame_queue. Replay sources use the same entry point (push_frame), so
everything downstream of the camera runs unchanged without CARLA.

    ReplayImageSource   - frames from image files on disk (sorted by name)
    SyntheticSceneSource - deterministic generated frames: a coloured box moving
                           over a grey road, for repeatable tests/benchmarks
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import cv2
import numpy as np


@dataclass
class ReplayFrame:
    frame_id: int
    camera_id: str
    agent_id: str
    frame: Optional[np.ndarray]


class ReplayImageSource:
    def __init__(self, directory: str | Path, agent_id: str = "uropclaw1", camera_id: str = "uropclaw1_front",
                 patterns=("*.jpg", "*.jpeg", "*.png")):
        self.files = sorted(f for p in patterns for f in Path(directory).glob(p))
        self.agent_id, self.camera_id = agent_id, camera_id

    def __iter__(self) -> Iterator[ReplayFrame]:
        for i, f in enumerate(self.files):
            yield ReplayFrame(i, self.camera_id, self.agent_id, cv2.imread(str(f)))


# BGR values verified to classify as the named colour with perception.color_filter
SCENE_COLOURS = {"blue": (170, 60, 20), "red": (30, 30, 190)}
ROAD_BGR = (90, 90, 90)


class SyntheticSceneSource:
    """`n_frames` frames of size 640x360; one box of `colour` moves `step_px` per frame."""

    def __init__(self, n_frames: int, colour: str = "blue", agent_id: str = "uropclaw1",
                 camera_id: Optional[str] = None, box=(200, 100, 340, 200), step_px: int = 4,
                 width: int = 640, height: int = 360):
        self.n_frames, self.colour, self.agent_id = n_frames, colour, agent_id
        self.camera_id = camera_id or f"{agent_id}_front"
        self.box, self.step_px, self.size = box, step_px, (height, width)

    def __iter__(self) -> Iterator[ReplayFrame]:
        x1, y1, x2, y2 = self.box
        for i in range(self.n_frames):
            frame = np.full((*self.size, 3), ROAD_BGR, np.uint8)
            dx = i * self.step_px
            if self.colour is not None:
                frame[y1:y2, x1 + dx:x2 + dx] = SCENE_COLOURS[self.colour]
            yield ReplayFrame(i, self.camera_id, self.agent_id, frame)


def replay(pipeline, source, interval_s: float = 0.05) -> int:
    """Push every frame of `source` into the pipeline at a fixed interval. Returns frames pushed."""
    n = 0
    for rf in source:
        pipeline.push_frame(rf.camera_id, rf.agent_id, rf.frame, timestamp=time.time())
        n += 1
        if interval_s:
            time.sleep(interval_s)
    return n

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from ultralytics import YOLO

_TARGET_CLASSES: set[int] = {2, 3, 5, 7}  # car, motorcycle, bus, truck
_CLASS_NAMES: dict[int, str] = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

_CONF = 0.40
_IOU = 0.45

_model: Optional[YOLO] = None


def _get_model() -> YOLO:
    global _model
    if _model is None:
        _model = YOLO("yolov8s.pt")
    return _model


@dataclass
class Detection:
    bbox: list[int]          # [x1, y1, x2, y2]
    class_id: int
    class_name: str
    confidence: float


def detect(frame_bgr: np.ndarray) -> list[Detection]:
    model = _get_model()
    results = model(frame_bgr, conf=_CONF, iou=_IOU, verbose=False)
    detections: list[Detection] = []

    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        for box in boxes:
            cid = int(box.cls[0])
            if cid not in _TARGET_CLASSES:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append(Detection(
                bbox=[int(x1), int(y1), int(x2), int(y2)],
                class_id=cid,
                class_name=_CLASS_NAMES[cid],
                confidence=float(box.conf[0]),
            ))

    return detections

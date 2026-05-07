from __future__ import annotations

import cv2
import numpy as np

# HSV ranges per color (OpenCV: H 0-179, S 0-255, V 0-255)
_COLOR_RANGES: dict[str, list[tuple[tuple[int, int, int], tuple[int, int, int]]]] = {
    "red":         [((0, 60, 40),   (10, 255, 220)),
                    ((165, 60, 40), (179, 255, 220))],
    "blue":        [((95, 60, 30),  (135, 255, 220))],
    "green":       [((35, 50, 30),  (85, 255, 210))],
    "yellow":      [((18, 80, 80),  (38, 255, 255))],
    "white":       [((0, 0, 160),   (179, 45, 255))],
    "black":       [((0, 0, 15),    (179, 255, 65))],
    "gray_silver": [((0, 0, 65),    (179, 45, 160))],
    "orange":      [((10, 100, 60), (20, 255, 230))],
}

_MIN_PIXEL_RATIO = 0.15


def classify_color(frame_bgr: np.ndarray, bbox: list[int]) -> str:
    x1, y1, x2, y2 = bbox
    h = y2 - y1
    w = x2 - x1

    if h <= 0 or w <= 0:
        return "unknown"

    # Crop central 60% vertically (remove top/bottom 20%) and 80% horizontally (remove L/R 10%)
    crop_y1 = y1 + int(h * 0.20)
    crop_y2 = y2 - int(h * 0.20)
    crop_x1 = x1 + int(w * 0.10)
    crop_x2 = x2 - int(w * 0.10)

    region = frame_bgr[crop_y1:crop_y2, crop_x1:crop_x2]
    if region.size == 0:
        return "unknown"

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    total_pixels = hsv.shape[0] * hsv.shape[1]

    best_color = "unknown"
    best_count = 0

    for color_name, ranges in _COLOR_RANGES.items():
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for (lo, hi) in ranges:
            mask |= cv2.inRange(hsv, np.array(lo), np.array(hi))
        count = int(np.count_nonzero(mask))
        if count > best_count:
            best_count = count
            best_color = color_name

    if best_count / total_pixels < _MIN_PIXEL_RATIO:
        return "unknown"

    return best_color

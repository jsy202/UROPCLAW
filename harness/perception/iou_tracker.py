from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

from perception.yolo_detector import Detection

_IOU_THRESHOLD = 0.30
_MAX_DISAPPEARED = 8
RECONNECT_WINDOW = 2.0   # seconds
RECONNECT_CENTER_DIST = 80  # pixels


@dataclass
class Track:
    track_id: int
    bbox: list[int]
    disappeared: int
    color_history: list[str]
    class_id: int
    frame_count: int


class IoUTracker:
    def __init__(self) -> None:
        self._tracks: dict[int, Track] = {}
        self._next_id: int = 0
        # 소멸 트랙 보관: {track_id: {bbox, color_history, class_id, died_at}}
        self.dead_tracks: dict[int, dict] = {}

    def update(
        self,
        detections: list[Detection],
        colors: list[str] | None = None,
    ) -> dict[int, Track]:
        if colors is None:
            colors = ["unknown"] * len(detections)

        now = time.time()

        for track in self._tracks.values():
            track.disappeared += 1

        if not detections:
            self._prune(now)
            return dict(self._tracks)

        track_ids = list(self._tracks.keys())
        unmatched_dets = list(range(len(detections)))

        if track_ids:
            matched_tracks: set[int] = set()
            matched_dets: set[int] = set()

            iou_matrix: list[list[float]] = []
            for tid in track_ids:
                row = [_iou(self._tracks[tid].bbox, detections[di].bbox) for di in range(len(detections))]
                iou_matrix.append(row)

            pairs: list[tuple[float, int, int]] = []
            for ti, tid in enumerate(track_ids):
                for di in range(len(detections)):
                    pairs.append((iou_matrix[ti][di], ti, di))
            pairs.sort(key=lambda x: x[0], reverse=True)

            for iou_val, ti, di in pairs:
                if iou_val < _IOU_THRESHOLD:
                    break
                tid = track_ids[ti]
                if tid in matched_tracks or di in matched_dets:
                    continue
                track = self._tracks[tid]
                track.bbox = detections[di].bbox
                track.disappeared = 0
                track.frame_count += 1
                track.color_history.append(colors[di])
                matched_tracks.add(tid)
                matched_dets.add(di)

            unmatched_dets = [di for di in range(len(detections)) if di not in matched_dets]

        # 미매칭 detection 처리: 재연결 우선 시도
        for di in unmatched_dets:
            det = detections[di]
            det_dict = {"bbox": det.bbox, "color": colors[di]}
            reconnect_tid = self._try_reconnect(det_dict, now)

            if reconnect_tid is not None:
                dead = self.dead_tracks.pop(reconnect_tid)
                track = Track(
                    track_id=reconnect_tid,
                    bbox=det.bbox,
                    disappeared=0,
                    color_history=dead["color_history"] + [colors[di]],
                    class_id=dead["class_id"],
                    frame_count=1,
                )
                self._tracks[reconnect_tid] = track
            else:
                track = Track(
                    track_id=self._next_id,
                    bbox=det.bbox,
                    disappeared=0,
                    color_history=[colors[di]],
                    class_id=det.class_id,
                    frame_count=1,
                )
                self._tracks[self._next_id] = track
                self._next_id += 1

        self._prune(now)
        return dict(self._tracks)

    def _try_reconnect(self, det: dict, now: float) -> int | None:
        cx = (det["bbox"][0] + det["bbox"][2]) / 2
        cy = (det["bbox"][1] + det["bbox"][3]) / 2
        best_tid: int | None = None
        best_dist = float("inf")

        for tid, dead in list(self.dead_tracks.items()):
            if now - dead["died_at"] > RECONNECT_WINDOW:
                del self.dead_tracks[tid]
                continue
            dx = (dead["bbox"][0] + dead["bbox"][2]) / 2 - cx
            dy = (dead["bbox"][1] + dead["bbox"][3]) / 2 - cy
            dist = (dx ** 2 + dy ** 2) ** 0.5

            dead_color = (
                Counter(dead["color_history"]).most_common(1)[0][0]
                if dead["color_history"]
                else "unknown"
            )
            det_color = det.get("color", "unknown")

            color_ok = (
                dead_color == det_color
                or dead_color == "unknown"
                or det_color == "unknown"
            )
            if dist < RECONNECT_CENTER_DIST and color_ok:
                if dist < best_dist:
                    best_dist = dist
                    best_tid = tid

        return best_tid

    def _prune(self, now: float | None = None) -> None:
        if now is None:
            now = time.time()
        dead = [tid for tid, t in self._tracks.items() if t.disappeared > _MAX_DISAPPEARED]
        for tid in dead:
            track = self._tracks.pop(tid)
            self.dead_tracks[tid] = {
                "bbox": track.bbox,
                "color_history": list(track.color_history),
                "class_id": track.class_id,
                "died_at": now,
            }


def _iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    inter_w = max(0, ix2 - ix1)
    inter_h = max(0, iy2 - iy1)
    inter = inter_w * inter_h

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter

    if union <= 0:
        return 0.0
    return inter / union

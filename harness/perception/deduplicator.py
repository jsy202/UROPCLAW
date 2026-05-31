from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

_OPENCLAW_COOLDOWN = 30.0
_DISCORD_COOLDOWN = 120.0
# Fragment continuity: a new track is treated as the same target when it has the
# same confirmed colour, appears within the tracker's reconnect window of the
# target's last candidate, and its centre is within one box diagonal of it.
_FRAGMENT_WINDOW = 2.0  # seconds; same value as iou_tracker.RECONNECT_WINDOW


@dataclass
class _Entry:
    last_verify: float = 0.0
    last_alert: float = 0.0


@dataclass
class _Target:
    color: str
    bbox: list
    last_seen: float
    last_verify: float


def _centre(bbox: list) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0


def _diagonal(bbox: list) -> float:
    return math.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1])


class Deduplicator:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        # Per-target VLM dedup state: target entries and track -> target aliases.
        self._targets: dict[tuple, _Target] = {}
        self._track_target: dict[tuple, tuple] = {}

    def should_verify_target(
        self, camera_id: str, track_id: int, color: str, bbox: list, now: float
    ) -> tuple[bool, str]:
        """Per-target VLM dedup. Returns (allow, reason).

        - same track (or a track aliased to it) within the cooldown -> suppress
        - new track continuing a recent same-colour target nearby -> suppress (fragment)
        - otherwise -> allow; a different target never inherits another's cooldown
        """
        with self._lock:
            track_key = (camera_id, track_id)
            target_key = self._track_target.get(track_key)
            if target_key is None:
                target_key = self._find_continuation(camera_id, color, bbox, now)
                if target_key is not None:
                    self._track_target[track_key] = target_key
                    target = self._targets[target_key]
                    target.bbox, target.last_seen = list(bbox), now
                    return False, "fragment_continuity"
                target_key = track_key
                self._track_target[track_key] = target_key
                self._targets[target_key] = _Target(color, list(bbox), now, now)
                return True, "new_target"
            target = self._targets[target_key]
            target.bbox, target.last_seen = list(bbox), now
            if now - target.last_verify >= _OPENCLAW_COOLDOWN:
                target.last_verify = now
                return True, "cooldown_expired"
            return False, "same_target_cooldown"

    def _find_continuation(self, camera_id, color, bbox, now):
        best_key, best_distance = None, None
        cx, cy = _centre(bbox)
        for key, target in self._targets.items():
            if key[0] != camera_id or target.color != color:
                continue
            if now - target.last_seen > _FRAGMENT_WINDOW:
                continue
            tx, ty = _centre(target.bbox)
            distance = math.hypot(cx - tx, cy - ty)
            if distance <= _diagonal(target.bbox) and (best_distance is None or distance < best_distance):
                best_key, best_distance = key, distance
        return best_key

    def _get_or_create(self, key: str) -> _Entry:
        if key not in self._entries:
            self._entries[key] = _Entry()
        return self._entries[key]

    def should_verify(self, key: str, now: float) -> bool:
        with self._lock:
            entry = self._get_or_create(key)
            if now - entry.last_verify >= _OPENCLAW_COOLDOWN:
                entry.last_verify = now
                return True
            return False

    def should_alert(self, key: str, now: float) -> bool:
        with self._lock:
            entry = self._get_or_create(key)
            if now - entry.last_alert >= _DISCORD_COOLDOWN:
                entry.last_alert = now
                return True
            return False

    def cleanup(self, now: float, ttl: float = 600.0) -> None:
        with self._lock:
            stale = [
                k for k, e in self._entries.items()
                if (now - e.last_verify > ttl) and (now - e.last_alert > ttl)
            ]
            for k in stale:
                del self._entries[k]
            stale_targets = {
                k for k, t in self._targets.items()
                if now - t.last_seen > ttl and now - t.last_verify > ttl
            }
            for k in stale_targets:
                del self._targets[k]
            for track_key in [tk for tk, k in self._track_target.items() if k in stale_targets]:
                del self._track_target[track_key]

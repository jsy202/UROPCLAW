from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

_CONFIRM_FRAMES = 3
_MAX_GAP_SECONDS = 1.0
_MAJORITY_RATIO = 0.6


@dataclass
class _Candidate:
    color_votes: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    timestamps: list[float] = field(default_factory=list)
    count: int = 0
    confirmed: bool = False


class TemporalConfirm:
    def __init__(self, confirm_frames: int = _CONFIRM_FRAMES) -> None:
        self.confirm_frames = confirm_frames
        self.pending: dict[int, _Candidate] = {}

    def update(
        self, track_id: int, color: str, timestamp: float
    ) -> Optional[dict]:
        if track_id not in self.pending:
            self.pending[track_id] = _Candidate()

        entry = self.pending[track_id]

        # Reset if gap is too large
        if entry.timestamps and (timestamp - entry.timestamps[-1]) > _MAX_GAP_SECONDS:
            entry.color_votes = defaultdict(int)
            entry.timestamps.clear()
            entry.count = 0
            entry.confirmed = False

        entry.color_votes[color] += 1
        entry.timestamps.append(timestamp)
        entry.count += 1

        if entry.confirmed:
            return None

        if entry.count >= self.confirm_frames:
            color_votes = entry.color_votes
            non_unknown = {c: v for c, v in color_votes.items() if c != "unknown"}

            if not non_unknown:
                # unknown만 있으면 승격 억제
                del self.pending[track_id]
                return None

            best_color, best_count = max(non_unknown.items(), key=lambda x: x[1])
            total_non_unknown = sum(non_unknown.values())

            if best_count / total_non_unknown < _MAJORITY_RATIO:
                del self.pending[track_id]
                return None

            del self.pending[track_id]
            return {"track_id": track_id, "color": best_color}

        return None

    def remove(self, track_id: int) -> None:
        self.pending.pop(track_id, None)

"""Validation-only shadow branches replicating the production candidate flow.

The production flow (harness/core/pipeline.py, YoloWorker + OpenClawWorker) is:

    detections -> classify_color per detection -> IoUTracker.update
    -> for every track: TemporalConfirm.update(track, latest colour, timestamp)
    -> confirmed colour must equal the mission target colour
    -> candidate -> Deduplicator.should_verify(agent_id, now) -> VLM call

Each ShadowBranch owns independent production IoUTracker, TemporalConfirm and
Deduplicator instances and can disable one stage:

- use_hsv=False: no colour classification and no target-colour gate. Every
  detection carries the constant label NO_HSV_LABEL so temporal majority voting
  still operates on track persistence alone.
- use_temporal=False: every track observed in the current frame
  (disappeared == 0) is confirmed immediately with its latest colour.
- use_dedup=False: every raised candidate becomes a VLM trigger.

No production code is modified; production classes are passed in.
"""

from __future__ import annotations

NO_HSV_LABEL = "vehicle"


class ShadowBranch:
    def __init__(self, name, tracker_cls, temporal_cls, dedup_cls, target_color="blue",
                 agent_id="uropclaw1", use_hsv=True, use_temporal=True, use_dedup=True):
        self.name = name
        self.tracker = tracker_cls()
        self.temporal = temporal_cls()
        self.dedup = dedup_cls()
        self.target_color = target_color
        self.agent_id = agent_id
        self.use_hsv = use_hsv
        self.use_temporal = use_temporal
        self.use_dedup = use_dedup
        self.counters = {
            "frames_processed": 0,
            "hsv_candidate_detections": 0,
            "frames_with_hsv_candidate": 0,
            "active_target_track_observations": 0,
            "frames_with_active_target_track": 0,
            "temporal_results": 0,
            "temporal_confirmations_passing_gate": 0,
            "frames_triggering_confirmation": 0,
            "candidates_raised": 0,
            "duplicate_suppressed": 0,
            "vlm_triggers": 0,
            "frames_with_vlm_trigger": 0,
            "max_candidates_in_one_frame": 0,
            # Production calls TemporalConfirm for every track, including tracks
            # not matched in this frame (disappeared > 0, bbox is stale).
            "candidates_from_disappeared_tracks": 0,
            "vlm_triggers_from_disappeared_tracks": 0,
            "exceptions": 0,
        }

    def _is_target(self, color):
        return (not self.use_hsv) or color == self.target_color

    def process(self, detections, colors, timestamp):
        """Process one frame. ``colors`` are HSV results (ignored when use_hsv=False).

        Returns a list of event dicts: {"kind": "candidate"|"vlm_trigger"|"suppressed", ...}.
        """
        counters = self.counters
        counters["frames_processed"] += 1
        events = []
        # Production: `if not detections: continue` before tracker/temporal.
        if not detections:
            return events
        labels = list(colors) if self.use_hsv else [NO_HSV_LABEL] * len(detections)
        hsv_hits = sum(1 for label in labels if self._is_target(label))
        counters["hsv_candidate_detections"] += hsv_hits
        counters["frames_with_hsv_candidate"] += int(hsv_hits > 0)

        tracks = self.tracker.update(detections, labels)
        active_target = 0
        confirmed_in_frame = False
        candidates = 0
        triggered = False
        for track_id, track in tracks.items():
            color = track.color_history[-1] if track.color_history else "unknown"
            if track.disappeared == 0 and self._is_target(color):
                active_target += 1
            if self.use_temporal:
                result = self.temporal.update(track_id, color, timestamp)
            elif track.disappeared == 0:
                result = {"track_id": track_id, "color": color}
            else:
                result = None
            if result is None:
                continue
            counters["temporal_results"] += 1
            if self.use_hsv and result["color"] != self.target_color:
                continue
            counters["temporal_confirmations_passing_gate"] += 1
            confirmed_in_frame = True
            candidates += 1
            counters["candidates_raised"] += 1
            event = {
                "track_id": int(track_id), "bbox": list(track.bbox),
                "confirmed_color": result["color"], "track_disappeared": int(track.disappeared),
            }
            stale = track.disappeared > 0
            counters["candidates_from_disappeared_tracks"] += int(stale)
            if self.use_dedup:
                self.dedup.cleanup(timestamp)
                if not self.dedup.should_verify(self.agent_id, timestamp):
                    counters["duplicate_suppressed"] += 1
                    events.append(dict(event, kind="suppressed"))
                    continue
            counters["vlm_triggers"] += 1
            counters["vlm_triggers_from_disappeared_tracks"] += int(stale)
            triggered = True
            events.append(dict(event, kind="vlm_trigger", reason=self.trigger_reason()))
        counters["active_target_track_observations"] += active_target
        counters["frames_with_active_target_track"] += int(active_target > 0)
        counters["frames_triggering_confirmation"] += int(confirmed_in_frame)
        counters["frames_with_vlm_trigger"] += int(triggered)
        counters["max_candidates_in_one_frame"] = max(counters["max_candidates_in_one_frame"], candidates)
        return events

    def trigger_reason(self):
        parts = [
            "temporal_confirmed" if self.use_temporal else "single_frame_observation",
            "target_colour_{0}".format(self.target_color) if self.use_hsv else "any_colour",
            "dedup_passed" if self.use_dedup else "dedup_disabled",
        ]
        return "+".join(parts)


BRANCH_CONFIGS = (
    ("full", dict(use_hsv=True, use_temporal=True, use_dedup=True)),
    ("no_hsv", dict(use_hsv=False, use_temporal=True, use_dedup=True)),
    ("no_temporal", dict(use_hsv=True, use_temporal=False, use_dedup=True)),
    ("no_dedup", dict(use_hsv=True, use_temporal=True, use_dedup=False)),
)


def make_branches(tracker_cls, temporal_cls, dedup_cls, target_color="blue"):
    return [
        ShadowBranch(name, tracker_cls, temporal_cls, dedup_cls, target_color=target_color, **flags)
        for name, flags in BRANCH_CONFIGS
    ]


class SimClock:
    """Stands in for the ``time`` module inside iou_tracker so its reconnect
    window runs on simulation time (as a real-time 10 Hz camera would)."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

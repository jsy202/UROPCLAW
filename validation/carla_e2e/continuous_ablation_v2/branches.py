"""Validation-only shadow branches replicating the FIXED production candidate flow.

Production (harness/core/pipeline.py YoloWorker + OpenClawWorker) after the
stale-track and per-target dedup fixes:

    detections -> classify_color -> IoUTracker.update
    -> for tracks matched in this frame (disappeared == 0):
         TemporalConfirm.update(track, latest colour, timestamp)
    -> confirmed colour == mission target colour
    -> candidate (bbox = current matched bbox)
    -> Deduplicator.should_verify_target(camera, track, colour, bbox, now) -> VLM

Ablation flags as in Experiment B v1:
- use_hsv=False: no colour classification / target gate (constant label).
- use_temporal=False: every matched track is confirmed immediately.
- use_dedup=False: every candidate is a VLM trigger.

Equivalence of the Full branch with the production Pipeline is unit-tested in
tests/validation/test_continuous_ablation_v2.py.
"""

from __future__ import annotations

NO_HSV_LABEL = "vehicle"
CAMERA_ID = "continuous_cctv"


class ShadowBranch:
    def __init__(self, name, tracker_cls, temporal_cls, dedup_cls, target_color="blue",
                 use_hsv=True, use_temporal=True, use_dedup=True):
        self.name = name
        self.tracker = tracker_cls()
        self.temporal = temporal_cls()
        self.dedup = dedup_cls()
        self.target_color = target_color
        self.use_hsv = use_hsv
        self.use_temporal = use_temporal
        self.use_dedup = use_dedup
        self.matched_tracks = []
        self.counters = {
            "frames_processed": 0,
            "hsv_candidate_detections": 0,
            "frames_with_hsv_candidate": 0,
            "active_target_track_observations": 0,
            "frames_with_active_target_track": 0,
            "temporal_updates_on_unmatched_tracks": 0,
            "temporal_results": 0,
            "temporal_confirmations_passing_gate": 0,
            "frames_triggering_confirmation": 0,
            "candidates_raised": 0,
            "candidates_from_disappeared_tracks": 0,
            "duplicate_suppressed": 0,
            "suppressed_same_target_cooldown": 0,
            "suppressed_fragment_continuity": 0,
            "vlm_triggers": 0,
            "vlm_triggers_from_disappeared_tracks": 0,
            "frames_with_vlm_trigger": 0,
            "max_candidates_in_one_frame": 0,
            "exceptions": 0,
        }

    def _is_target(self, color):
        return (not self.use_hsv) or color == self.target_color

    def process(self, detections, colors, timestamp):
        counters = self.counters
        counters["frames_processed"] += 1
        self.matched_tracks = []
        events = []
        if not detections:  # production: no tracker/temporal update on empty frames
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
            if track.disappeared != 0:  # fixed production: unmatched tracks add no evidence
                continue
            color = track.color_history[-1] if track.color_history else "unknown"
            self.matched_tracks.append({"track_id": int(track_id), "bbox": list(track.bbox), "color": color})
            if self._is_target(color):
                active_target += 1
            if self.use_temporal:
                result = self.temporal.update(track_id, color, timestamp)
            else:
                result = {"track_id": track_id, "color": color}
            if result is None:
                continue
            counters["temporal_results"] += 1
            if self.use_hsv and result["color"] != self.target_color:
                continue
            counters["temporal_confirmations_passing_gate"] += 1
            confirmed_in_frame = True
            candidates += 1
            counters["candidates_raised"] += 1
            counters["candidates_from_disappeared_tracks"] += int(track.disappeared > 0)
            event = {
                "track_id": int(track_id), "bbox": list(track.bbox),
                "confirmed_color": result["color"], "track_disappeared": int(track.disappeared),
            }
            if self.use_dedup:
                self.dedup.cleanup(timestamp)
                allowed, reason = self.dedup.should_verify_target(
                    CAMERA_ID, int(track_id), result["color"], list(track.bbox), timestamp)
                if not allowed:
                    counters["duplicate_suppressed"] += 1
                    counters["suppressed_" + reason] += 1
                    events.append(dict(event, kind="suppressed", reason=reason,
                                       target_key=self.dedup._track_target.get((CAMERA_ID, int(track_id)))))
                    continue
                event["dedup_reason"] = reason
                event["target_key"] = self.dedup._track_target.get((CAMERA_ID, int(track_id)))
            counters["vlm_triggers"] += 1
            counters["vlm_triggers_from_disappeared_tracks"] += int(track.disappeared > 0)
            triggered = True
            events.append(dict(event, kind="vlm_trigger", reason=self.trigger_reason(event.get("dedup_reason"))))
        counters["active_target_track_observations"] += active_target
        counters["frames_with_active_target_track"] += int(active_target > 0)
        counters["frames_triggering_confirmation"] += int(confirmed_in_frame)
        counters["frames_with_vlm_trigger"] += int(triggered)
        counters["max_candidates_in_one_frame"] = max(counters["max_candidates_in_one_frame"], candidates)
        return events

    def trigger_reason(self, dedup_reason=None):
        parts = [
            "temporal_confirmed" if self.use_temporal else "single_frame_observation",
            "target_colour_{0}".format(self.target_color) if self.use_hsv else "any_colour",
            "dedup_{0}".format(dedup_reason) if self.use_dedup else "dedup_disabled",
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
    """Replaces ``time`` inside iou_tracker so its reconnect window uses simulation time."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

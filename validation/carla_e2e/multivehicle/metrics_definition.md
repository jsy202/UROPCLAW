# Multi-vehicle metric definitions

Status: definitions fixed before host measurement.

## Frame/image units

- `input_frames`: real CARLA RGB frames successfully inserted into the
  production pipeline input queue. Pre-roll frames are excluded.
- `frames_with_yolo_detection`: accepted frames with at least one production
  vehicle-class YOLO detection.
- `frames_passing_hsv`: accepted frames with at least one detection classified
  as the mission target colour (`blue`) by the production HSV classifier.
- `frames_with_active_track`: accepted frames with at least one active
  (`disappeared == 0`) production track whose latest colour is `blue`.
- `frames_triggering_confirmation`: accepted frames where production temporal
  confirmation emits a `blue` candidate.
- `images_sent_to_vlm`: candidate images that actually reach the injected Fake
  VLM interface.

Retention rates use frame/image units only:

- YOLO-positive / Input
- HSV-pass / YOLO-positive
- Tracking / HSV-pass
- Confirmation / Tracking
- VLM images / Input

## Object, track, event, and request units

- `yolo_detections`: cumulative vehicle detection boxes over measured frames.
- `unique_tracks`: unique production IoU tracker IDs created during one run.
- `confirmed_tracks`: unique track IDs for which temporal confirmation emits a
  result, irrespective of the emitted colour.
- `vlm_requests`: Fake VLM interface invocations.
- `target_events`: final blue-target Fake Alert events.
- `false_target_events`: target events in a Non-target run.
- `duplicate_suppressed`: production deduplicator suppressions.

These units are not combined into a funnel percentage. Historical
46,372 / 28,736 / 3,298 / 53 values are retained only as historical results.

## Ground-truth diagnostics

CARLA actor projection establishes visible vehicle counts, probe entry/exit,
probe-to-detection evidence associations, fragmentation, and possible track
merges. It is not passed into any production perception decision.

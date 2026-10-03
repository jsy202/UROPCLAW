# Real CARLA pipeline metric definitions

These definitions apply only to measured runs using real CARLA simulation
frames and Real YOLO. Counts with different units are reported separately and
must not be presented as a single reduction funnel.

## Frame/image counters

These counters are the only values used for previous-stage retention rates:

| Metric | Unit | Definition |
|---|---|---|
| `input_frames` | frame | RGB frames successfully inserted into the pipeline input queue during one repetition. |
| `frames_with_yolo_detection` | frame | Processed frames for which Real YOLO returned at least one retained vehicle-class `Detection`. Multiple boxes still count as one frame. |
| `frames_passing_hsv` | frame | YOLO-positive frames in which the existing HSV classifier returned at least one supported colour rather than `unknown`. This is colour-classification validity, not mission target-colour equality. |
| `frames_with_active_track` | frame | YOLO-positive frames for which the existing `IoUTracker.update` result contained at least one track with `disappeared == 0`. |
| `frames_triggering_confirmation` | frame | Distinct source-frame timestamps on which the existing `TemporalConfirm.update` returned a confirmation. Repeated confirmation of one track on later frames counts as additional trigger frames. |
| `images_sent_to_vlm` | image | VLM interface calls whose generated prompt referenced a crop file that existed when the injected VLM interface received the call. A request without an image is not counted here. |

Retention is calculated only between adjacent values in this table:
`current frame/image count / previous frame/image count`. A zero denominator is
reported as `N/M`, never zero percent. Because the production code classifies
colour but does not discard `unknown` detections before tracking,
`frames_passing_hsv` and `frames_with_active_track` are independently observed
stages rather than an asserted strict subset. Any retention above 100% must be
reported as observed rather than normalized or hidden.

## Detection/track/event/request counters

| Metric | Unit | Definition |
|---|---|---|
| `yolo_detections` | detection box | Sum of vehicle-class `Detection` objects returned for all processed frames. The retained COCO classes are car (2), motorcycle (3), bus (5), and truck (7). Multiple boxes in one frame count separately. |
| `unique_tracks` | track | Number of distinct `(camera_id, track_id)` identities created by `IoUTracker` during one repetition. Re-observation of an existing or reconnected identity does not increment this count. |
| `confirmed_tracks` | confirmed track/event | Number of distinct temporal-confirmation outputs produced after the three-frame majority rule and before target-colour suppression. Repeated frames before or after confirmation do not increment this count. |
| `vlm_requests` | request | Calls that enter the configured VLM dependency. Retries, if any, count as separate calls; queue candidates suppressed by deduplication do not count. Fake and Real VLM requests are never combined in one summary row. |
| `target_events` | event | Final events for which the VLM result and `AlertPolicy` permit the target decision. Fake-alert delivery outcome is recorded separately and does not redefine the event count. In a non-target scenario, every such event is also a false target event. |

Additional operational metrics:

| Metric | Unit | Definition |
|---|---|---|
| `camera_frames` | frame | RGB sensor callbacks observed by the validation runner, including callbacks rejected at the pipeline input queue. |
| `hsv_target_passes` | detection box | YOLO detections whose existing HSV classifier output equals the active mission target colour. This is not interchangeable with `yolo_detections`. |
| `frame_drops` | frame | Camera frames rejected because the input queue is full plus accepted frames discarded by the existing stale-frame rule. Each frame is counted at most once. |
| `event_drops` | event | Confirmed candidates that cannot enter a downstream queue. This excludes intentional target-colour rejection and deduplication, which are recorded separately. |
| `max_queue_depth` | queued item | Maximum observed depth across the frame, candidate, and result queues. Per-queue maxima are also retained in raw evidence. |
| `scenario_success` | repetition | Target: at least one target event and successful fake-alert delivery before timeout. Non-target: the run completes with zero target events and zero VLM requests while the configured non-target vehicle is visible in evidence. |
| `pipeline_alive` | repetition | All pipeline worker threads remain alive until the planned shutdown point. |
| `recovery` | injected fault | After the injected VLM fault, the same pipeline instance processes the next normal eligible request to its expected terminal decision without a restart. |

Frame/image retention never uses `yolo_detections`, `unique_tracks`,
`confirmed_tracks`, `vlm_requests`, or `target_events` as a numerator or
denominator.

## One-second monitoring boundary

The fixed timing boundary for a decision-bearing event is:

`successful insertion into pipeline frame queue (host monotonic clock)`

to

`terminal pipeline decision for that frame on the same host monotonic clock`.

For the temporal-confirmation frame that creates a VLM candidate, the terminal point is the
`AlertPolicy` allow/suppress decision after the VLM response or handled VLM
failure. When temporal confirmation produces a non-target colour, the terminal
point is the existing target-colour rejection. Frames that are still building
the three-frame temporal window, frames with no vehicle detection, frames
dropped as stale, and frames rejected at queue insertion do not have a final
event decision and therefore have no E2E sample; their counts remain visible
in the raw and drop metrics.

Each confirmed event contributes at most one E2E sample. The source timestamp
is assigned from the host wall clock immediately before successful input-queue
insertion and is propagated unchanged by the production pipeline. Raw
evidence retains the source and terminal timestamps so mean,
p50, p95, p99, maximum, counts at or below 1,000 ms, counts above 1,000 ms,
and the compliance rate can be recalculated. The result therefore characterizes
decision-bearing event latency, not every accepted camera frame. `1초 감시 유지`
may be stated only with that scope, when measured samples exist and the
documented acceptance criterion is met; otherwise the result is failed or not
measured.

Queue accumulation means the queue depth has a sustained positive trend or
does not return to its pre-load level before the repetition timeout. A single
peak is not by itself reported as long-term accumulation.

## Historical-result separation

The historical values YOLO 46,372, HSV 28,736, Tracking 3,298, and VLM 53
remain historical context only. Their original units have not been proven
identical, so this validation will not calculate a reduction percentage or
direct numerical comparison from them.

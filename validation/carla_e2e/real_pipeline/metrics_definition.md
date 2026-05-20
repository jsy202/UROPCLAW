# Real CARLA pipeline metric definitions

These definitions apply only to measured runs using real CARLA simulation
frames and Real YOLO. Counts with different units are reported separately and
must not be presented as a single reduction funnel.

| Metric | Unit | Definition |
|---|---|---|
| `input_frames` | frame | RGB frames successfully inserted into the pipeline input queue during one repetition. Camera callbacks rejected because the queue is full are excluded here and counted as dropped frames. |
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

## One-second monitoring boundary

The fixed timing boundary is:

`successful insertion into pipeline frame queue (host monotonic clock)`

to

`terminal pipeline decision for that frame on the same host monotonic clock`.

For a frame that creates a VLM candidate, the terminal point is the
`AlertPolicy` allow/suppress decision after the VLM response or handled VLM
failure. For a processed frame that creates no VLM candidate, the terminal
point is completion of YOLO, HSV, tracking, temporal, and target filtering for
that frame. Frames dropped as stale or rejected at queue insertion have no
E2E latency sample and remain visible in the drop metrics.

Each accepted and processed frame contributes at most one E2E sample. Raw
evidence retains the acceptance and terminal monotonic timestamps so mean,
p50, p95, p99, maximum, counts at or below 1,000 ms, counts above 1,000 ms,
and the compliance rate can be recalculated. `1초 감시 유지` may be stated
only when measured samples exist and the documented acceptance criterion is
met; otherwise the result is failed or not measured.

Queue accumulation means the queue depth has a sustained positive trend or
does not return to its pre-load level before the repetition timeout. A single
peak is not by itself reported as long-term accumulation.

## Historical-result separation

The historical values YOLO 46,372, HSV 28,736, Tracking 3,298, and VLM 53
remain historical context only. Their original units have not been proven
identical, so this validation will not calculate a reduction percentage or
direct numerical comparison from them.

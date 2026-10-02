# Real CARLA pipeline validation report

Status: host repetitions complete

This report describes actual CARLA simulation input with Real YOLO and deterministic Fake VLM/Fake Alert. It is not real-road or real-vehicle validation.

| Scenario | Repetitions | Success | 1s Compliance | Mean E2E | p95 | Max | YOLO Detections | Unique Tracks | Confirmed | VLM Requests | Max Queue | Drops |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| target | 10 | 10/10 | 1.0 | 26.845 ms | 29.381 ms | 30.151 ms | 100 | 10 | 10 | 10 | 1 | 0 |
| non_target | 10 | 10/10 | 1.0 | 23.405 ms | 25.564 ms | 25.767 ms | 100 | 10 | 10 | 0 | 0 | 0 |

## Fake VLM fault injection

| Fault | Repetitions | Injected | Detected | Recovered | Crashes | Next normal success | Max queue | Drops |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| delay | 5 | 5 | 5 | 5 | 0 | 5 | 3 | 0 |
| timeout | 5 | 5 | 5 | 5 | 0 | 5 | 3 | 0 |
| error | 5 | 5 | 5 | 5 | 0 | 5 | 3 | 0 |
| malformed | 5 | 5 | 5 | 5 | 0 | 5 | 3 | 0 |

E2E samples use the triggering CARLA frame's successful input-queue insertion timestamp through the final target-colour rejection or AlertPolicy allow decision. YOLO-only latency is not included as a separate E2E sample.

Historical 46,372 / 28,736 / 3,298 / 53 values are not compared because their units are not established as identical.

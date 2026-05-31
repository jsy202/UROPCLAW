# Real CARLA dynamic multi-vehicle validation report

Status: host benchmark executed; every number below is aggregated from per-run
`evidence/benchmark/runs/*/result.json` produced by real CARLA 0.9.13 frames,
Real YOLOv8s on the RTX 3060, production HSV / IoU tracking / temporal
confirmation / deduplication / AlertPolicy, and deterministic Fake VLM / Fake Alert.
It is simulation validation, not real-road or real-vehicle validation.

Scene: Town10HD_Opt, seed 42, 15 background vehicles + 1 probe (16 controlled),
synchronous 0.1 s ticks, fixed CCTV 800x600 FOV 90, 5 s pre-roll, 100 measured frames
per run. Every run replays the same saved Target manifest; Non-target changes only
the probe colour (blue -> red). Repetitions alternate Target/Non-target in separate
processes.

## Scenario results

| Scenario | Runs | Success | Input frames | YOLO dets | Unique tracks | Confirmed tracks | VLM requests | Target events | False target events | Max input queue | Max candidate queue | Dropped frames | Dropped events | Crashes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| target | 10 | 10/10 | 1000 | 1550 | 150 | 150 | 10 | 10 | 0 | 2 | 1 | 0 | 0 | 0 |
| non_target | 10 | 10/10 | 1000 | 1660 | 150 | 150 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |

Determinism (computed from the per-run rows):

- target: per-run object counts and probe entry/exit/tracks are identical across 10 runs.
- non_target: per-run object counts and probe entry/exit/tracks are identical across 10 runs.

Identical counts mean the synchronous seed-42 scene and the GPU inference were
reproducible run to run. The repetitions therefore establish stability and
latency variation on one scene; they are not independent samples of
detection accuracy and do not support generalisation claims.

Success: Target = every Target smoke gate PASS and at least one target event;
Non-target = every Non-target gate PASS (probe observed and tracked, no blue probe
confirmation, zero Fake VLM requests, zero target events).

## Event E2E latency

Boundary: the triggering CARLA frame's input-queue insertion (perf_counter) to the
final decision: production target-colour rejection at first temporal confirmation
of a track, or AlertPolicy allow (Fake Alert delivery). Same definition as the
single-vehicle validation. YOLO-only latency is not an E2E sample.

| Scenario | Subset | Samples | Mean | p50 | p95 | p99 | Max | 1 s compliance rate |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| target | all_terminal_decisions | 140 | 27.055 ms | 22.035 ms | 42.755 ms | 54.711 ms | 56.133 ms | 1 |
| target | alert_policy_allow | 10 | 22.714 ms | 22.412 ms | 24.964 ms | 26.071 ms | 26.348 ms | 1 |
| target | target_color_reject | 130 | 27.389 ms | 20.387 ms | 43.115 ms | 54.721 ms | 56.133 ms | 1 |
| target | probe_tracks | 10 | 22.714 ms | 22.412 ms | 24.964 ms | 26.071 ms | 26.348 ms | 1 |
| non_target | all_terminal_decisions | 150 | 25.582 ms | 19.529 ms | 37.779 ms | 54.312 ms | 54.999 ms | 1 |
| non_target | alert_policy_allow | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| non_target | target_color_reject | 150 | 25.582 ms | 19.529 ms | 37.779 ms | 54.312 ms | 54.999 ms | 1 |
| non_target | probe_tracks | 20 | 18.501 ms | 18.458 ms | 19.205 ms | 19.74 ms | 19.874 ms | 1 |

## Frame/image retention (frame units only)

| Scenario | Input | YOLO+ | HSV blue | Active blue track | Blue confirmation | VLM images | YOLO+/Input | HSV/YOLO+ | Track/HSV | Confirm/Track | VLM/Input |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| target | 1000 | 1000 | 320 | 320 | 150 | 10 | 1 | 0.32 | 1 | 0.469 | 0.01 |
| non_target | 1000 | 1000 | 0 | 0 | 0 | 0 | 1 | 0 | n/a | n/a | 0 |

Object/track/event/request counts are reported separately above and are never
combined with frame counts into one funnel.

## Per-run gate outcomes

| Run | Exit | Status | Failed gates | FOV enter/exit | Probe first YOLO frame | Probe tracks | Max boxes | Route dev (m) | Duplicates suppressed |
|---|---:|---|---|---|---:|---|---:|---:|---:|
| target-01 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 14 |
| non_target-01 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 0 |
| target-02 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 14 |
| non_target-02 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 0 |
| target-03 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 14 |
| non_target-03 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 0 |
| target-04 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 14 |
| non_target-04 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 0 |
| target-05 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 14 |
| non_target-05 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 0 |
| target-06 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 14 |
| non_target-06 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 0 |
| target-07 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 14 |
| non_target-07 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 0 |
| target-08 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 14 |
| non_target-08 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 0 |
| target-09 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 14 |
| non_target-09 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 0 |
| target-10 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 14 |
| non_target-10 | 0 | PASS | - | 29/77 | 31 | 9;12 | 4 | 0.26 | 0 |

## Tracking diagnostics

Ground-truth association (IoU >= 0.30 between a production track box and a projected
CARLA actor box) is evidence only. Mean fragmented actors per run: 4.

## Environment

- carla_client_version: 0.9.13
- carla_server_version: 0.9.13
- cuda_available: True
- gpu: NVIDIA GeForce RTX 3060
- map: Carla/Maps/Town10HD_Opt
- opencv: 4.8.1
- python: 3.7.17
- torch: 1.13.1+cu117
- torch_cuda: 11.7
- ultralytics: 8.0.145
- yolo_weight: yolov8s.pt
- yolo_weight_sha256: 268e5bb54c640c96c3510224833bc2eeacab4135c6deb41502156e39986b562d
- yolo_weight_source: post-project pretrained YOLOv8s weight

## Related experiment

This report is Experiment A (system integration / stability validation). Experiment B,
a separate 10-minute continuous-traffic run with a 4-way shadow ablation of HSV,
Temporal Confirmation and Deduplication on identical YOLO output, is reported in
`../continuous_ablation/continuous_10min_report.md`. Its numbers are not merged with
the results above.

Historical 46,372 / 28,736 / 3,298 / 53 values are not compared with these
measurements because their units are not established as identical.

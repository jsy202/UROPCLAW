# CARLA E2E Simulation Validation Report

Status: **CARLA/Real YOLO gates PASS; full E2E host repetitions pending**

This interim report contains no full-pipeline CARLA E2E performance result. The camera smoke, CUDA YOLO contract smoke, and warm-up-separated positive gate passed against the independently running CARLA 0.9.13 server. The first 3,806.716 ms inference remains cold-start evidence only. The separate 50-frame detector distribution is not reported as E2E latency.

| Scenario | Environment | Repetitions | Success | Avg E2E | p95 | Max | VLM Calls | Max Queue | Drops |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Camera smoke | CARLA 0.9.13 host simulation | 1 | 1 | N/M | N/M | N/M | 0 | N/M | N/M |
| Real YOLO one-frame smoke | CARLA 0.9.13 + CUDA YOLOv8s | 1 | 1 | N/M | N/M | N/M | 0 | N/M | N/M |
| YOLO positive + steady-state gate | CARLA 0.9.13 + CUDA YOLOv8s | 1 | 1 | N/M | N/M | N/M | 0 | N/M | 0 |
| Target + Fake VLM | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| Non-target + Fake VLM | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| VLM faults | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| Real VLM | Not executed | 0 | BLOCKED | N/M | N/M | N/M | 0 | N/M | N/M |

`N/M` means not measured.

## Required disclosures

1. **Scope verified in CARLA:** host connection, matching client/server versions, `Town10HD_Opt` world query, RGB camera spawn, ten 800×600 frames, PNG evidence, and sensor cleanup.
2. **Real YOLO used:** yes. The controlled gate detected a vehicle in 60/60 CARLA frames; 50 steady-state inferences had p95 27.343 ms. This is detector-only, not E2E.
3. **Real VLM used:** no. Authentication and cost authorization were not established.
4. **Real Alert used:** no. No alert path ran.
5. **One-second monitoring cycle satisfied:** not measured; zero final-decision samples exist.
6. **New defects:** Python 3.7 annotation evaluation prevented production imports. The validation branch applies only the compatibility changes listed in `real_pipeline/defects.md`; regression tests pass.
7. **Synthetic-validation issues reproduced in CARLA:** none; no complete Real YOLO pipeline run has occurred.
8. **Résumé-ready measured numbers:** none. Environment inventory values are not pipeline performance results.
9. **Required limitations:** see `limitations.md`; most importantly, repeated full-pipeline E2E measurements are still pending.
10. **Final commit:** not yet applicable; validation remains in progress.

## Production-code impact

Production algorithms and dependency-injection behavior were not modified. Minimal postponed-annotation compatibility edits were made for Python 3.7; runners, instrumentation, documentation, and evidence are isolated under validation paths.

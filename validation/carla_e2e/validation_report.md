# CARLA E2E Simulation Validation Report

Status: **CARLA camera and one-frame CUDA YOLO smoke PASS; positive/steady-state gate pending**

This interim report contains no CARLA E2E performance result. The camera host smoke and one-frame CUDA YOLO smoke passed against the independently running CARLA 0.9.13 server. The first inference was a 3,806.716 ms cold start with zero raw boxes, so it is not treated as representative latency or positive-perception validation.

| Scenario | Environment | Repetitions | Success | Avg E2E | p95 | Max | VLM Calls | Max Queue | Drops |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Camera smoke | CARLA 0.9.13 host simulation | 1 | 1 | N/M | N/M | N/M | 0 | N/M | N/M |
| Real YOLO one-frame smoke | CARLA 0.9.13 + CUDA YOLOv8s | 1 | 1 | N/M | N/M | N/M | 0 | N/M | N/M |
| YOLO positive + steady-state gate | Not executed | 0 | PENDING | N/M | N/M | N/M | 0 | N/M | N/M |
| Target + Fake VLM | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| Non-target + Fake VLM | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| VLM faults | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| Real VLM | Not executed | 0 | BLOCKED | N/M | N/M | N/M | 0 | N/M | N/M |

`N/M` means not measured.

## Required disclosures

1. **Scope verified in CARLA:** host connection, matching client/server versions, `Town10HD_Opt` world query, RGB camera spawn, ten 800×600 frames, PNG evidence, and sensor cleanup.
2. **Real YOLO used:** yes for one CUDA cold-start inference, but no positive detection was produced and steady-state latency is not yet measured.
3. **Real VLM used:** no. The positive/steady-state YOLO gate is pending; authentication was not modified.
4. **Real Alert used:** no. No alert path ran.
5. **One-second monitoring cycle satisfied:** not measured; zero final-decision samples exist.
6. **New defects:** the existing production pipeline fails to import in the required Python 3.7 environment because `harness/config.py` evaluates `dict[...]` annotations unsupported at runtime on Python 3.7. Eight additional harness modules contain the same unpostponed annotation pattern. Production code has not been changed at this gate.
7. **Synthetic-validation issues reproduced in CARLA:** none; no complete Real YOLO pipeline run has occurred.
8. **Résumé-ready measured numbers:** none. Environment inventory values are not pipeline performance results.
9. **Required limitations:** see `limitations.md`; most importantly, no live CARLA frame reached Real YOLO.
10. **Final commit:** not yet applicable; validation remains in progress.

## Production-code impact

No production code was modified. The existing `Pipeline` dependency-injection structure is unchanged. Host smoke runners, validation documentation, tests, and evidence are isolated under validation paths.

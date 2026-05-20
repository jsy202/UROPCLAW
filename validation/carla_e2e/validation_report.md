# CARLA E2E Simulation Validation Report

Status: **CARLA camera smoke PASS; Real YOLO smoke pending**

This interim report contains no CARLA E2E performance result. The camera-only host smoke passed against the independently running CARLA 0.9.13 server. AI dependencies, CUDA inference, and the Real YOLO detector contract have not yet passed the host gate.

| Scenario | Environment | Repetitions | Success | Avg E2E | p95 | Max | VLM Calls | Max Queue | Drops |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Camera smoke | CARLA 0.9.13 host simulation | 1 | 1 | N/M | N/M | N/M | 0 | N/M | N/M |
| Real YOLO smoke | CARLA 0.9.13 + Real YOLO intended | 0 | PENDING | N/M | N/M | N/M | 0 | N/M | N/M |
| Target + Fake VLM | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| Non-target + Fake VLM | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| VLM faults | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| Real VLM | Not executed | 0 | BLOCKED | N/M | N/M | N/M | 0 | N/M | N/M |

`N/M` means not measured.

## Required disclosures

1. **Scope verified in CARLA:** host connection, matching client/server versions, `Town10HD_Opt` world query, RGB camera spawn, ten 800×600 frames, PNG evidence, and sensor cleanup.
2. **Real YOLO used:** not yet. The host YOLO smoke remains pending.
3. **Real VLM used:** no. The Real YOLO gate is pending; authentication was not modified.
4. **Real Alert used:** no. No alert path ran.
5. **One-second monitoring cycle satisfied:** not measured; zero final-decision samples exist.
6. **New defects:** none claimed from the camera-only smoke. Managed-environment network/process isolation remains an execution constraint, not a product defect.
7. **Synthetic-validation issues reproduced in CARLA:** none; no Real YOLO pipeline run has occurred.
8. **Résumé-ready measured numbers:** none. Environment inventory values are not pipeline performance results.
9. **Required limitations:** see `limitations.md`; most importantly, no live CARLA frame reached Real YOLO.
10. **Final commit:** not yet applicable; validation remains in progress.

## Production-code impact

No production code was modified. The existing `Pipeline` dependency-injection structure is unchanged. Host smoke runners, validation documentation, tests, and evidence are isolated under validation paths.

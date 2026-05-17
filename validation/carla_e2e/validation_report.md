# CARLA E2E Simulation Validation Report

Status: **BLOCKED at the prerequisite smoke gate**

This report contains no CARLA E2E performance result. The isolated CARLA 0.9.13 Python client was prepared, but AI dependencies could not be downloaded and the CARLA server did not remain running in the managed execution environment.

| Scenario | Environment | Repetitions | Success | Avg E2E | p95 | Max | VLM Calls | Max Queue | Drops |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Smoke | CARLA 0.9.13 + Real YOLO intended | 0 | BLOCKED | N/M | N/M | N/M | 0 | N/M | N/M |
| Target + Fake VLM | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| Non-target + Fake VLM | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| VLM faults | Not executed | 0 | N/M | N/M | N/M | N/M | 0 | N/M | N/M |
| Real VLM | Not executed | 0 | BLOCKED | N/M | N/M | N/M | 0 | N/M | N/M |

`N/M` means not measured.

## Required disclosures

1. **Scope verified in CARLA:** none. The server connection and camera-frame prerequisites were not reached.
2. **Real YOLO used:** no. PyTorch, Ultralytics, OpenCV, and weights were unavailable.
3. **Real VLM used:** no. The prerequisite smoke gate failed; authentication was not modified.
4. **Real Alert used:** no. No alert path ran.
5. **One-second monitoring cycle satisfied:** not measured; zero final-decision samples exist.
6. **New defects:** none claimed. Two environment blockers were identified, not product defects: package-index DNS failure and CARLA process exit in the managed sandbox.
7. **Synthetic-validation issues reproduced in CARLA:** none; no CARLA pipeline run occurred.
8. **Résumé-ready measured numbers:** none. Environment inventory values are not pipeline performance results.
9. **Required limitations:** see `limitations.md`; most importantly, no live CARLA frame reached Real YOLO.
10. **Final commit:** recorded after the blocked-evidence commit is created.

## Production-code impact

No production code was modified. The existing `Pipeline` dependency-injection structure is unchanged. Only design, plan, isolated-environment manifest, ignore rules, and blocked evidence/report files were added.

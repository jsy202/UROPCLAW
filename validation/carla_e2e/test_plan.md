# CARLA E2E Test Plan and Execution Status

The approved protocol is defined in `design.md`. Execution is gated in this order: exact client/server version match, RGB frame receipt, real CUDA YOLO inference, detector contract, then repeated scenarios.

| Phase | Planned repetitions | Status |
|---|---:|---|
| CARLA camera smoke | 1 | PASS — host evidence: matching 0.9.13 versions, world query, 10 RGB frames |
| Real YOLO one-frame smoke | 1 | PASS — CUDA inference and contract verified; zero boxes, cold-start 3,806.716 ms |
| Real YOLO positive + steady-state gate | 1 | PENDING — 10 warm-up, 50 measured frames, positive vehicle detection required |
| Target + fake VLM/alert | 10 | NOT RUN — Real YOLO gate pending |
| Non-target + fake VLM/alert | 10 | NOT RUN — Real YOLO gate pending |
| VLM delay | 5 | NOT RUN — Real YOLO gate pending |
| VLM timeout | 5 | NOT RUN — Real YOLO gate pending |
| VLM error | 5 | NOT RUN — Real YOLO gate pending |
| VLM malformed response | 5 | NOT RUN — Real YOLO gate pending |
| One-second final-decision cycle | derived from target cycles | NOT MEASURED |
| Real VLM + fake alert | 3–5 | NOT RUN — Real YOLO gate pending; no credential change attempted |

No synthetic result is substituted for a missing CARLA or Real YOLO result. The existing host CARLA server must remain running; the next action is to prepare `.venv-carla-e2e`, obtain and hash the post-project validation weight, and run the Real YOLO one-frame smoke. Scenario and fault repetitions remain gated on that result.

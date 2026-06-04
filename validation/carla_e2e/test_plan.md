# CARLA E2E Test Plan and Execution Status

The approved protocol is defined in `design.md`. Execution is gated in this order: exact client/server version match, RGB frame receipt, real CUDA YOLO inference, detector contract, then repeated scenarios.

| Phase | Planned repetitions | Status |
|---|---:|---|
| CARLA camera smoke | 1 | PASS — host evidence: matching 0.9.13 versions, world query, 10 RGB frames |
| Real YOLO one-frame smoke | 1 | PASS — CUDA inference and contract verified; zero boxes, cold-start 3,806.716 ms |
| Real YOLO positive + steady-state gate | 1 | PASS — 10 warm-up excluded, 50 measured, vehicle detection 60/60 frames |
| Target + fake VLM/alert | 10 | NOT RUN — host runner prepared |
| Non-target + fake VLM/alert | 10 | NOT RUN — host runner prepared |
| VLM delay | 5 | NOT RUN — host runner prepared |
| VLM timeout | 5 | NOT RUN — host runner prepared |
| VLM error | 5 | NOT RUN — host runner prepared |
| VLM malformed response | 5 | NOT RUN — host runner prepared |
| One-second final-decision cycle | derived from target cycles | NOT MEASURED |
| Real VLM + fake alert | 3–5 | BLOCKED — authentication/cost authorization not established |

No synthetic result is substituted for a missing CARLA or Real YOLO result. The existing host CARLA server must remain running. Scenario and fault repetitions are now ready for the normal host terminal using `real_pipeline/run_host_e2e.py`.

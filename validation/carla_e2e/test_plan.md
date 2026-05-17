# CARLA E2E Test Plan and Execution Status

The approved protocol is defined in `design.md`. Execution is gated in this order: exact client/server version match, RGB frame receipt, real CUDA YOLO inference, detector contract, then repeated scenarios.

| Phase | Planned repetitions | Status |
|---|---:|---|
| Smoke | 1 | BLOCKED before server connection and YOLO load |
| Target + fake VLM/alert | 10 | NOT RUN — smoke gate failed |
| Non-target + fake VLM/alert | 10 | NOT RUN — smoke gate failed |
| VLM delay | 3–5 | NOT RUN — smoke gate failed |
| VLM timeout | 3–5 | NOT RUN — smoke gate failed |
| VLM error | 3–5 | NOT RUN — smoke gate failed |
| VLM malformed response | 3–5 | NOT RUN — smoke gate failed |
| One-second final-decision cycle | derived from target cycles | NOT MEASURED |
| Real VLM + fake alert | up to 5 | BLOCKED — prerequisite smoke failed; no credential change attempted |

No synthetic result is substituted for a missing CARLA result. A future continuation must first install the pinned dependencies in `.venv-carla-e2e`, obtain and hash the post-project validation weight, start CARLA, and rerun the complete smoke gate.

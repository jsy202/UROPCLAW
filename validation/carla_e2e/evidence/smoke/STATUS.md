# Smoke Test Status

Status: **BLOCKED**

| Required check | Result |
|---|---|
| CARLA 0.9.13 server starts | BLOCKED — process exits status 1 |
| Python client 0.9.13 | PASS — isolated bundled wheel reports 0.9.13 |
| Client/server versions equal | NOT MEASURED — no server connection |
| World load | NOT MEASURED |
| RGB camera frame | NOT MEASURED |
| Real YOLO load | BLOCKED — dependencies and weight unavailable |
| RTX 3060 inference | NOT MEASURED |
| One-frame inference | NOT MEASURED |
| Existing `Detection` output compatibility | NOT MEASURED |

No performance, scenario-success, latency, queue, drop, or one-second-cycle result was produced.

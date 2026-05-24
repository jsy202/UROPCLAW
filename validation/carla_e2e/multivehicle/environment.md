# Multi-vehicle validation environment

Status: **AWAITING HOST SMOKE**.

No multi-vehicle CARLA measurement has been executed in the managed sandbox.
The host runner requires CARLA client/server 0.9.13 equality and CUDA-enabled
Real YOLO inference. It writes measured versions, map, GPU details, actor counts,
and weight information to `evidence/smoke/result.json` and `run.log`.

Required disclosure: **Post-project CARLA validation used a newly obtained
pretrained YOLOv8s weight because the original research weight was unavailable.**

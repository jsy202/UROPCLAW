# Multi-vehicle validation environment

Status: **host smoke PASS; host Target/Non-target benchmark executed**
(see `validation_report.md`).

Measured on the host (from `evidence/smoke/environment.json` and
`evidence/benchmark/environment.json`):

- CARLA client/server 0.9.13 / 0.9.13, map `Carla/Maps/Town10HD_Opt`, server
  started with `-RenderOffScreen -quality-level=Low`
- NVIDIA GeForce RTX 3060 (8 GB), driver 595.91.07, CUDA available
- Python 3.7.17, torch 1.13.1+cu117, ultralytics 8.0.145, OpenCV 4.8.1
- YOLO weight `yolov8s.pt`, SHA-256
  `268e5bb54c640c96c3510224833bc2eeacab4135c6deb41502156e39986b562d`

Required disclosure: **Post-project CARLA validation used a newly obtained
pretrained YOLOv8s weight because the original research weight was unavailable.**

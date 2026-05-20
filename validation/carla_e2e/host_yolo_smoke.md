# Host Real YOLO smoke

This phase uses the existing CARLA 0.9.13 host server and one newly captured
RGB frame. It does not start or stop the server. It does not modify system
Python, the NVIDIA driver, or the system CUDA toolkit.

No original UROP research weight was found under the repository, research
worktrees, home directory, or common local caches. This phase therefore uses
an ignored post-project validation weight and records this disclosure:

> Post-project CARLA validation used a newly obtained pretrained YOLOv8s
> weight because the original research weight was unavailable.

## 1. Prepare the isolated host environment

Run from a normal host terminal with internet and GPU access:

```bash
cd /home/jsy202/validation-work/UROPCLAW-carla-e2e
bash validation/carla_e2e/prepare_host_yolo_env.sh
```

The script pins these Python 3.7 packages in `.venv-carla-e2e` only:

- `torch==1.13.1+cu117`
- `torchvision==0.14.1+cu117`
- `ultralytics==8.0.145`
- `opencv-python==4.8.1.78`
- `numpy==1.21.6`
- `pytest==7.4.4`
- `requests==2.31.0`
- bundled CARLA client wheel `0.9.13`

It downloads `yolov8s.pt` only when the ignored file
`validation/carla_e2e/weights/yolov8s.pt` is absent. Installation and weight
details are written to
`validation/carla_e2e/evidence/yolo_smoke/environment_setup.log`.

## 2. Run one-frame host smoke

Keep the existing CARLA server running, then execute:

```bash
cd /home/jsy202/validation-work/UROPCLAW-carla-e2e
source .venv-carla-e2e/bin/activate
python validation/carla_e2e/run_host_yolo_smoke.py \
  --host 127.0.0.1 \
  --port 2000 \
  --timeout 30 \
  --weight validation/carla_e2e/weights/yolov8s.pt
```

The runner exits with status 0 only when it receives a real CARLA RGB frame,
runs the model on CUDA, returns a detection list compatible with
`perception.yolo_detector.Detection`, saves both images, and destroys the
camera sensor. Evidence is written to:

```text
validation/carla_e2e/evidence/yolo_smoke/environment.json
validation/carla_e2e/evidence/yolo_smoke/result.json
validation/carla_e2e/evidence/yolo_smoke/input_frame.png
validation/carla_e2e/evidence/yolo_smoke/annotated_frame.png
validation/carla_e2e/evidence/yolo_smoke/run.log
```

Do not begin scenario repetitions unless `result.json` reports
`"status": "PASS"`.

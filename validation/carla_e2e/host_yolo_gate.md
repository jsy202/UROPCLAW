# Host YOLO positive and steady-state gate

This gate follows the passed one-frame CUDA smoke. The observed first
inference latency of 3,806.716 ms is retained as cold-start evidence and is
not used as representative performance.

The runner loads the same ignored `yolov8s.pt` exactly once. It creates a
stationary `vehicle.tesla.model3` at a free CARLA map spawn point and places
an 800×600 RGB camera 8 m directly in front of the vehicle, facing it. All
validation actors are destroyed on exit.

For every inference, the runner calls `torch.cuda.synchronize()` immediately
before starting the host monotonic timer and immediately after the model call.
The elapsed latency therefore ends only after queued GPU work for that
inference has completed.

Run from a normal host terminal while the existing CARLA 0.9.13 server remains
running:

```bash
cd /home/jsy202/validation-work/UROPCLAW-carla-e2e
source .venv-carla-e2e/bin/activate
python validation/carla_e2e/run_host_yolo_gate.py \
  --host 127.0.0.1 \
  --port 2000 \
  --timeout 30 \
  --warmup 10 \
  --steady 50 \
  --weight validation/carla_e2e/weights/yolov8s.pt
```

Evidence is written separately from the one-frame smoke:

```text
validation/carla_e2e/evidence/yolo_gate/environment.json
validation/carla_e2e/evidence/yolo_gate/result.json
validation/carla_e2e/evidence/yolo_gate/warmup_latencies_ms.json
validation/carla_e2e/evidence/yolo_gate/steady_state_latencies_ms.json
validation/carla_e2e/evidence/yolo_gate/latency_samples.csv
validation/carla_e2e/evidence/yolo_gate/input_frame.png
validation/carla_e2e/evidence/yolo_gate/annotated_frame.png
validation/carla_e2e/evidence/yolo_gate/run.log
```

The steady-state summary uses only the 50 post-warm-up samples and reports
mean, p50, p95, and maximum latency using NumPy's linear percentile method.
Warm-up samples remain available in their own JSON file and in CSV rows marked
`warmup`.

PASS requires all of the following:

- matching CARLA client/server 0.9.13 versions;
- CUDA inference on a `cuda` device with one model load;
- at least 5 warm-up samples and at least 50 distinct steady-state CARLA
  frames;
- at least one raw model box and one retained vehicle-class detection;
- conversion to `perception.yolo_detector.Detection`;
- a saved positive input frame and annotated bounding-box image; and
- successful camera and target-vehicle cleanup.

Do not begin target/non-target E2E repetitions unless `result.json` reports
`"status": "PASS"`.

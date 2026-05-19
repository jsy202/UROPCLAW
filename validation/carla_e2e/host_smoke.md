# Host CARLA camera smoke test

Run this only from a normal host terminal that can reach the already-running
CARLA 0.9.13 server on `127.0.0.1:2000`. The command does not start or stop the
server and does not install packages.

```bash
cd /home/jsy202/validation-work/UROPCLAW-carla-e2e
source .venv-carla-e2e/bin/activate
python validation/carla_e2e/run_host_smoke.py \
  --host 127.0.0.1 \
  --port 2000 \
  --timeout 20 \
  --frames 10
```

The process exits with status 0 only when all smoke PASS conditions are met:

- client version is exactly `0.9.13`;
- server version is exactly `0.9.13`;
- the current world and map can be queried;
- an RGB camera can be spawned;
- at least one RGB frame is received; and
- the first frame is saved successfully.

Review these files after the command finishes:

```text
validation/carla_e2e/evidence/host_smoke/result.json
validation/carla_e2e/evidence/host_smoke/frame.png
validation/carla_e2e/evidence/host_smoke/run.log
```

Each run replaces the preceding smoke result, log, and first-frame image. The
camera is stopped and destroyed in a `finally` block. On failure, `result.json`
contains the exception type, message, and traceback when available.

Do not install Torch, Ultralytics, or download a YOLO weight until this smoke
test reports `"status": "PASS"`.

# Real CARLA pipeline host test plan

## Preconditions and gate

- Run only from the isolated `.venv-carla-e2e` in the normal host namespace.
- Connect to the already-running server at `127.0.0.1:2000`; never start or
  restart CARLA from this runner.
- Require client and server version `0.9.13`, CUDA availability, and the local
  ignored `yolov8s.pt` weight before creating a measured repetition.
- Load the model once. Run ten unmeasured initialization inferences, with CUDA
  synchronization before and after each inference, before scenario metrics.
- Use the post-project weight disclosure in every environment report.

## Controlled scenarios

The target definition comes from the repository's documented default example
(`start.py --target-color blue`) and the production mission/HSV support for
`blue`. Both scenes use a stationary `vehicle.tesla.model3` eight metres in
front of an 800x600 RGB camera, matching the positive YOLO gate geometry.

| Scenario | Vehicle | Mission | Repetitions | Expected terminal result |
|---|---|---|---:|---|
| target | blue Model 3 | blue vehicle | 10 | Temporal confirmation, deterministic Fake VLM, Fake Alert event |
| non-target | red Model 3 | blue vehicle | 10 | Existing target-colour rejection; no VLM request or alert |
| VLM delay | blue Model 3 | blue vehicle | 5 | delayed first request, then normal request on same pipeline |
| VLM timeout | blue Model 3 | blue vehicle | 5 | injected timeout/fail-open, then normal request |
| VLM error | blue Model 3 | blue vehicle | 5 | injected exception/fail-open, then normal request |
| malformed VLM | blue Model 3 | blue vehicle | 5 | parse failure/fail-open, then normal request |

The fault repetitions use two production tracker/temporal streams and two
agent IDs in one pipeline instance so deduplication does not suppress the
required second, normal recovery request. The production algorithms and
thresholds are unchanged.

## Acceptance

- Target success: at least one Real YOLO vehicle detection, Fake VLM request,
  and AlertPolicy-permitted Fake Alert while all workers remain alive.
- Non-target success: at least one Real YOLO vehicle detection, zero VLM
  requests, zero target events, and all workers alive.
- Fault recovery: the injected condition is observed by the relevant
  production metric, all workers remain alive, and the next eligible normal
  request reaches the deterministic VLM successfully without restart.
- Queue accumulation: failure if the combined ending depth is non-zero after
  the drain wait. Per-queue maxima and ending depth remain in raw evidence.
- A runner timeout or exception is retained as `TIMEOUT` or `ERROR`; it is not
  converted to a successful repetition.

Real VLM is outside this runner. It remains `BLOCKED` unless authentication and
cost authorization can be confirmed separately, and it must never be mixed
with these Fake VLM results.

## Frame-metrics-only rerun

After the completed E2E/fault run, `--frame-metrics-only` repeats the same ten
target and ten non-target controlled scenarios. It does not schedule fault
scenarios and writes only:

- `frame_metrics_raw.csv`
- `frame_metrics_summary.csv`
- `frame_metrics_report.md`
- `evidence/frame_metrics_environment.json`
- `evidence/frame_metrics_run.log`
- new per-run JSON/image evidence under `evidence/runs/`

The existing E2E latency, scenario, queue/drop, fault summary, and validation
report files are not overwritten by this mode. Detection/track/event/request
metrics remain in the frame-metrics raw rows for traceability but are never
used to calculate frame retention.

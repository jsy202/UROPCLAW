# CARLA E2E Simulation Validation Design

## Purpose

Run the existing UROPCLAW AI pipeline with live CARLA simulation camera input and preserve auditable system-level evidence. This is post-project simulation validation, not real-road, real-vehicle, production, or model-accuracy validation.

## Constraints

- Work only on `validation-carla-e2e`, based on `main` commit `fe781f5`.
- Keep the existing synthetic validation and dependency-injection behavior intact.
- Do not merge to `main`.
- Use only `.venv-carla-e2e`; do not change system Python, the NVIDIA driver, or the system CUDA toolkit.
- Use CARLA server 0.9.13 with Python client 0.9.13. Do not collect benchmark results unless `get_client_version()` equals `get_server_version()`.
- Pin a Python 3.7-compatible PyTorch, torchvision, Ultralytics, OpenCV, and NumPy set.
- Use the original research YOLO weight if found. Otherwise use a newly downloaded `yolov8s.pt`, keep it out of Git, record its SHA-256, and label it as a post-project validation weight.
- Keep actual CARLA results separate from synthetic/FakeDetector results.
- Keep Discord fake unless explicitly needed. If the real VLM cannot be used safely with existing authentication, mark that phase `BLOCKED`.

## Architecture

The validation runner imports the existing `Pipeline`, `CameraManager`, perception modules, and dependency-injection interfaces. It creates a controlled CARLA scene in which a stationary RGB camera observes either a blue target vehicle or a non-target vehicle. Fake VLM and alert implementations are deterministic; fault runners inject delay, timeout, process error, or malformed output without replacing CARLA, YOLO, HSV, tracking, or temporal confirmation.

Production behavior remains unchanged by default. Small additive counters in `Pipeline` expose HSV target matches, tracking observations, temporal confirmations, VLM latency, final-decision latency, and exact pipeline queue peaks. A validation-only queue sink records camera callbacks, accepted frames, and input-queue rejection. The runner writes one raw row per repetition and derives scenario and latency summaries from those rows.

## Measurement Boundaries

- `camera_frames`: RGB sensor callbacks received.
- `input_frames`: frames successfully accepted by `Pipeline.frame_queue`.
- `yolo_detections`: vehicle-class detections returned by the existing detector wrapper.
- `hsv_pass`: detections whose classified colour equals the active mission target.
- `tracking_candidates`: track observations emitted by `IoUTracker.update`.
- `temporal_confirmed`: non-`None` decisions emitted by `TemporalConfirm.update`, before target-colour suppression.
- `vlm_calls`: calls entering the VLM dependency.
- `vlm_latency_ms`: wall time from immediately before to immediately after the VLM dependency call/failure.
- Queue peaks: exact maximum queue sizes observed immediately after pipeline queue insertions, plus validation input-sink rejection counts.
- `frame_drops`: input queue rejection plus stale-frame drops. `event_drops`: candidate-queue rejection plus any result-queue rejection.
- Alert E2E: camera-frame acceptance timestamp to alert sender invocation for the frame that generated the alert.
- Final-decision cycle: camera-frame acceptance timestamp to AlertPolicy decision for a temporally confirmed target candidate, including VLM time. This is the fixed boundary for the one-second check.
- Scenario success, target case: at least one temporally confirmed target, VLM request, and delivered fake alert before timeout.
- Scenario success, non-target case: the scene completes without a VLM request or alert. YOLO detection is reported separately and is not required for success unless the vehicle is visible in captured evidence.

The one-second result reports mean, p95, maximum, and count over 1,000 ms for final-decision cycles. It may be called satisfied only if measured cycles exist and all are at most 1,000 ms; otherwise it is failed or not measured.

## Execution Phases

1. Create the isolated Python 3.7 environment and record exact package and GPU properties.
2. Start CARLA 0.9.13 and run the required one-frame smoke path. Stop if client/server versions differ, GPU inference is unavailable, or the existing detector output contract fails.
3. Run target and non-target scenarios at least ten times each with real CARLA/perception and deterministic fake VLM/alert.
4. Run VLM delay, timeout, error, and malformed-response scenarios three times each while retaining real CARLA/perception.
5. Calculate the fixed-boundary one-second cycle result from raw measured decision latencies.
6. Probe existing Claude CLI authentication without changing credentials. If usable, run up to five target repetitions with real VLM and fake alert; otherwise record `BLOCKED`.
7. Compare with another pipeline revision only if the input scene, dependencies, weight, hardware, and run protocol are identical.

## Evidence and Reporting

All committed evidence lives under `validation/carla_e2e/`: `environment.md`, `test_plan.md`, `raw_results.csv`, `scenario_results.csv`, `latency_summary.csv`, `validation_report.md`, `limitations.md`, and `evidence/`. Large models, virtual environments, generated crops, and transient CARLA artifacts are excluded from Git. Raw logs retain commands, timestamps, versions, failures, and scenario identifiers without credentials.

## Acceptance Criteria

- Existing tests remain green.
- Smoke evidence proves matching CARLA 0.9.13 client/server versions, at least one RGB frame, CUDA inference on the RTX 3060, one real YOLO inference, and compatibility with `list[Detection]`.
- Every reported numeric claim is derivable from committed raw CSV rows.
- Missing dependencies, authentication, or reproducibility are marked `BLOCKED` rather than estimated.
- The final report uses the requested scenario table and explicitly answers the ten requested disclosure questions.

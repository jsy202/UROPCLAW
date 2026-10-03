# CARLA E2E Simulation Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce reproducible, evidence-backed system validation of the existing UROPCLAW pipeline using live CARLA 0.9.13 RGB frames and real YOLO perception.

**Architecture:** A validation-only runner builds a controlled CARLA scene and injects deterministic VLM/alert dependencies through the existing `Pipeline` constructor. Small backward-compatible metrics additions expose otherwise invisible stage and timing boundaries; CSV aggregation and Markdown reports consume raw run rows.

**Tech Stack:** Python 3.7, CARLA 0.9.13, pinned CUDA-enabled PyTorch/torchvision, pinned Ultralytics YOLOv8, OpenCV, pytest, CSV/JSON/Markdown evidence.

**Spec:** `validation/carla_e2e/design.md`

## Global Constraints

- Branch from `main` commit `fe781f5`; never merge to `main`.
- Use `.venv-carla-e2e` only; no system Python, driver, CUDA toolkit, sudo, or system-wide package changes.
- CARLA client and server must both report 0.9.13 before measured runs.
- Preserve existing dependency injection and production defaults.
- Keep real CARLA evidence separate from synthetic validation.
- Never manufacture comparisons or unmeasured performance claims.
- Mark unavailable real-VLM execution `BLOCKED`.

## Review Focus

- Camera callback queue rejection must be counted without double-counting stale frames.
- A VLM exception must still yield a measured latency and a final fail-open decision.
- Non-target scenes must not be reported successful merely because the target was outside the camera view; visibility evidence is recorded separately.
- Cleanup must restore asynchronous CARLA mode and destroy validation actors after every repetition and interruption.
- Empty latency samples must produce `not_measured`, never zero latency or a one-second success claim.

---

### Task 1: Isolated environment manifest and branch hygiene

**Files:**
- Modify: `.gitignore`
- Create: `validation/carla_e2e/requirements-py37.txt`
- Create: `validation/carla_e2e/environment.md`

**Interfaces:**
- Produces: `.venv-carla-e2e` runtime with CARLA 0.9.13 and pinned AI dependencies; environment evidence used by all later tasks.

- [ ] Add `.venv-carla-e2e/`, validation weights, and transient run output to `.gitignore`.
- [ ] Record exact dependency pins compatible with Python 3.7 and CARLA 0.9.13.
- [ ] Create the venv, install the bundled CARLA wheel and pinned packages, and save installation logs.
- [ ] Verify imports and record Python, CARLA, torch, torchvision, CUDA, GPU, Ultralytics, and OpenCV versions.
- [ ] Search repository, research files, home directory, and caches for the original weight; only if absent obtain `yolov8s.pt`, calculate SHA-256, and label it as a post-project validation weight.
- [ ] Commit manifest, ignore rules, and environment evidence.

### Task 2: Passive pipeline instrumentation

**Files:**
- Modify: `harness/core/pipeline.py`
- Create: `tests/unit/test_carla_e2e_instrumentation.py`

**Interfaces:**
- Produces: metrics keys `hsv_target_passed`, `tracking_candidates`, `temporal_confirmed`, `vlm_latency_ms_list`, `final_decision_latency_ms_list`, and queue peak keys in `Pipeline.metrics_summary()`.

- [ ] Write failing unit/integration tests for stage counters, VLM success/failure latency, decision latency, queue peaks, and empty samples.
- [ ] Run the focused tests and verify failures identify missing metrics.
- [ ] Add counters and timestamps without changing default dependency selection, filtering, deduplication, fail-open, or alert policy behavior.
- [ ] Run focused tests and the existing full suite.
- [ ] Commit instrumentation and tests.

### Task 3: Validation runner and result aggregation

**Files:**
- Create: `tools/carla_e2e.py`
- Create: `tools/carla_e2e_report.py`
- Create: `tests/unit/test_carla_e2e_tools.py`
- Create: `validation/carla_e2e/test_plan.md`

**Interfaces:**
- Consumes: Task 2 metrics keys and the existing `Pipeline(detector, vlm_runner, alert_sender)` interface.
- Produces: commands `smoke`, `scenario`, and `summarize`; append-only `raw_results.csv`; derived `scenario_results.csv` and `latency_summary.csv`.

- [ ] Write failing tests for percentile calculation, success rules, empty samples, row schema, deterministic fake/fault VLMs, and report aggregation.
- [ ] Run focused tests and verify expected failures.
- [ ] Implement a validation-only controlled scene, camera queue sink, fake/fault VLMs, fake alert, cleanup, finite timeout, and CSV row writer.
- [ ] Implement aggregation directly from raw rows and document exact scenarios, repetitions, timeouts, and timing boundaries.
- [ ] Run focused tests and the full suite.
- [ ] Commit runner, aggregation, tests, and test plan.

### Task 4: Required smoke test

**Files:**
- Create: `validation/carla_e2e/evidence/smoke/` logs and metadata
- Update: `validation/carla_e2e/environment.md`

**Interfaces:**
- Consumes: Task 1 runtime and Task 3 `smoke` command.
- Produces: gate decision allowing or blocking measured scenarios.

- [ ] Start the installed CARLA 0.9.13 server without changing system components.
- [ ] Run smoke and capture client/server versions, map, one RGB frame, weight provenance/checksum, CUDA device, one inference, and `Detection` contract result.
- [ ] Stop immediately and record `BLOCKED` if versions differ, CUDA inference is unavailable, no frame arrives, or detector output is incompatible.
- [ ] Commit smoke evidence and environment update when the gate passes or is conclusively blocked.

### Task 5: CARLA scenario and fault repetitions

**Files:**
- Create/Update: `validation/carla_e2e/raw_results.csv`
- Create: `validation/carla_e2e/evidence/runs/` logs

**Interfaces:**
- Consumes: Task 4 passed smoke gate and Task 3 `scenario` command.
- Produces: at least 10 target rows, 10 non-target rows, and 3 rows each for delay, timeout, error, and malformed VLM conditions when executable.

- [ ] Execute target and non-target repetitions with real CARLA/YOLO/HSV/tracking/temporal stages and fake VLM/alert.
- [ ] Execute fault repetitions with the same scene and perception dependencies.
- [ ] Audit every row for scenario completion, visibility, stage counts, queue peaks, drops, VLM latency, E2E, and recovery/liveness.
- [ ] Commit raw CSV and non-sensitive logs.

### Task 6: One-second cycle and real VLM phase

**Files:**
- Update: `validation/carla_e2e/raw_results.csv`
- Create: `validation/carla_e2e/evidence/real_vlm/` logs or blocked record

**Interfaces:**
- Consumes: final-decision cycle boundary from Task 2 and real CARLA target scene from Task 3.
- Produces: measured one-second statistics and up to five real-VLM rows, or an explicit `BLOCKED` record.

- [ ] Calculate mean, p95, maximum, and over-1,000-ms count only from measured final-decision cycles.
- [ ] Probe existing Claude CLI authentication without adding credentials or exposing secrets.
- [ ] If safe and available, execute up to five real-VLM target repetitions with fake alert; otherwise record the exact blocker.
- [ ] Commit real-VLM evidence or blocked record.

### Task 7: Reports and final verification

**Files:**
- Create: `validation/carla_e2e/scenario_results.csv`
- Create: `validation/carla_e2e/latency_summary.csv`
- Create: `validation/carla_e2e/validation_report.md`
- Create: `validation/carla_e2e/limitations.md`

**Interfaces:**
- Consumes: committed raw CSV and environment/smoke evidence.
- Produces: requested final table, ten disclosures, and at most three defensible résumé numbers.

- [ ] Generate summaries only from raw rows and cross-check totals manually.
- [ ] Write the requested final scenario table and disclosure answers, clearly separating CARLA simulation from synthetic validation.
- [ ] Run forbidden-claim and placeholder scans, CSV schema checks, report-to-raw consistency checks, and the full test suite.
- [ ] Commit reports, then perform whole-branch review and one fix pass for critical/important findings.

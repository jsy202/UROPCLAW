# CARLA Multi-Vehicle Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a host-only, deterministic CARLA multi-vehicle smoke runner and validation instrumentation without changing production perception behavior.

**Architecture:** Validation modules create and replay a topology-derived scene manifest, instrument injected production components, and evaluate an explicit smoke gate. Host orchestration uses real CARLA and YOLO; unit/integration tests use complete fakes at the CARLA boundary.

**Tech Stack:** Python 3.7, CARLA 0.9.13 API, PyTorch/Ultralytics, OpenCV, pytest.

**Spec:** `validation/carla_e2e/multivehicle/scenario_design.md`

## Global Constraints

- Production perception algorithms and existing single-vehicle results are unchanged.
- Exactly 15 background actors and one probe are required; bounded spawn failure is fatal.
- Target and Non-target manifests differ only in probe colour.
- CARLA ground truth is evidence-only.
- Full benchmark code is deferred until actual host smoke PASS.

## Review Focus

- Occupied spawn points must exhaust bounded retries and fail rather than reduce the scene.
- World and Traffic Manager synchronous settings must be restored on every exit path.
- Partial exceptions must still write result/log/manifest evidence and clean created actors.
- Target/non-target parity must reject every difference except probe colour and actual actor IDs.
- Asynchronous camera callbacks must not count pre-roll frames or more than 100 accepted frames.

---

### Task 1: Manifest model and parity

**Files:**
- Create: `validation/carla_e2e/multivehicle/scene_manifest.py`
- Test: `tests/validation/test_multivehicle_manifest.py`

**Interfaces:**
- Produces: `build_non_target_manifest(target_manifest)`, `validate_manifest_parity(target, non_target)`, atomic JSON read/write.

- [ ] Write tests for colour-only parity, prohibited background/probe changes, and planned/actual separation.
- [ ] Run tests and observe missing-module failure.
- [ ] Implement the minimal manifest functions.
- [ ] Run tests and confirm PASS.

### Task 2: Scene planning and lifecycle

**Files:**
- Create: `validation/carla_e2e/multivehicle/scene.py`
- Test: `tests/validation/test_multivehicle_scene.py`

**Interfaces:**
- Consumes: manifest serialization from Task 1.
- Produces: deterministic spawn planning, exact-count spawn, sync settings context, owned-actor cleanup, movement/FOV helpers.

- [ ] Write tests for deterministic planning, sixteen-actor enforcement, settings restoration, movement threshold, and cleanup.
- [ ] Run tests and observe expected failures.
- [ ] Implement the minimal scene lifecycle against CARLA-like interfaces.
- [ ] Run tests and confirm PASS.

### Task 3: Production-path instrumentation and smoke gate

**Files:**
- Create: `validation/carla_e2e/multivehicle/instrumentation.py`
- Test: `tests/validation/test_multivehicle_instrumentation.py`

**Interfaces:**
- Produces: production wrappers, frame/object counters, queue samples, ground-truth association diagnostics, and `evaluate_smoke_gate(result)`.

- [ ] Write tests proving target-colour frame semantics, separated units, ground-truth non-interference, and all gate failures.
- [ ] Run tests and observe expected failures.
- [ ] Implement wrappers and evaluator without changing production modules.
- [ ] Run tests and confirm PASS.

### Task 4: Host smoke orchestration

**Files:**
- Create: `validation/carla_e2e/multivehicle/run_host_smoke.py`
- Test: `tests/validation/test_multivehicle_smoke_runner.py`

**Interfaces:**
- Consumes: Tasks 1-3 and existing injected `Pipeline` components.
- Produces: CLI, host run, evidence, non-zero exit on any gate failure.

- [ ] Write tests for defaults, frame bounds, failure evidence, cleanup, version gate, and no benchmark mode.
- [ ] Run tests and observe expected failures.
- [ ] Implement host orchestration and exact result schema.
- [ ] Run tests and confirm PASS.

### Task 5: Validation documentation and repository verification

**Files:**
- Create: `validation/carla_e2e/multivehicle/{environment.md,metrics_definition.md,test_plan.md,limitations.md}`
- Create: requested CSV headers and `evidence/.gitkeep`

- [ ] Document host command, measured-vs-planned status, definitions, and limitations.
- [ ] Run Python 3.7 compile/import checks and all tests.
- [ ] Verify existing single-vehicle result checksums and production source diff.
- [ ] Commit only validation additions and tests.

# Temporal Filter Study Implementation Plan — historical initial plan

Initial 180s/60-recording design retained for provenance. User first limited collection to40 and prohibited actualVLM, then requested40fresh600s/6000frame recordings at10Hz. Current scope and staged additions: [progressive protocol](../../../validation/carla_e2e/progressive_filter_study/PROTOCOL.ko.md). Do not execute this superseded collection count.

> **For agentic workers:** Execute inline with executing-plans; user authorized complete execution.

**Goal:** Produce measured temporal/filter tradeoffs with reproducible offscreen CARLA evidence.
**Architecture:** Validation-only capture archives share original YOLO/HSV outputs across independent replay branches. Ground truth is evaluation-only. Production stays unchanged.
**Tech Stack:** CARLA0.9.13, existing Python3.7/CUDA YOLO environment, pytest, matplotlib.
**Spec:** validation/carla_e2e/temporal_filter_study/protocol.md

## Global Constraints
- Two maps, three lighting/weather conditions, two traffic densities, 5 seeds, 180s at10Hz.
- Development seeds101,102; held-out seeds201,202,203. Freeze selection before held-out analysis.
- N=1,2,3,5,7,10 with dedup on/off; unknown-aware alternatives at N3; all eight HSV/temporal/dedup combinations; two alternative architectures.
- Cache original detection/color outputs and save every RGB frame as JPEG evidence. JPEG is not the pixel-exact detector input.
- Report request trigger metrics separately from real VLM performance. No external messages or alerts.

## Review Focus
- No ground truth reaches branches; ambiguous associations kept separate.
- Exposure/latency denominators do not silently discard misses.
- Unknown votes, gap resets and temporal initializations agree with production.
- No split leakage: disjoint recording seeds; paired uncertainty clusters by recording.
- No silent skipped/incomplete capture accepted as finished.

### Task 1: Validation rules and replay
- [ ] Write failing tests for unknown votes, full denominator, gap reset, sliding/batch, branch parity, episodes and misses.
- [ ] Implement study.py with configs, independent branch state, exposure metrics and controlled sequences.
- [ ] Run targeted tests; verify original branch equivalence.

### Task 2: Offscreen capture
- [ ] Implement capture.py using existing synchronous sensor/lifecycle and GT projection helpers.
- [ ] Calibrate two camera poses with pilot data only, inspect images, freeze protocol.
- [ ] Capture all60 recordings with manifest, timing, frame records, all JPEG frames; resume only completed records.

### Task 3: Analysis and delivery
- [ ] Replay all configs; save event/exposure/run/aggregate tables and paired CIs.
- [ ] Choose N on dev only using recall margin2pp and p95 confirmation delay .5s; validate on held-out without retuning.
- [ ] Stress short exposures, color errors, unknowns, gaps and distinct targets; distinguish synthetic results.
- [ ] Save charts, annotated case images, Korean report, limitations, and actual defect trail.
- [ ] Run complete pytest and independent review, resolve material findings.

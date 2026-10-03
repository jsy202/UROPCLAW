# Experiment B v2: stale-track and per-target dedup fix, 10-minute continuous ablation

Before = Experiment B v1 (`../continuous_ablation/`, preserved). After = this directory:
3 independent full 10-minute runs on the same scene/traffic configuration, with the
fixed production logic. Within each run the four shadow branches share identical frames
and YOLO output. Runs (and Before vs After) are not bit-identical, so per-run branch
comparisons are primary and cross-run absolute numbers are context only.

## Production changes

1. `harness/core/pipeline.py` (YoloWorker): `TemporalConfirm.update` is called only for tracks
   matched to a detection in the current frame (`track.disappeared == 0`). Unmatched tracks stay
   in the tracker for association/reconnect but gain no temporal evidence, so no stale track can
   be confirmed and every candidate bbox is the current detection bbox.
2. `harness/core/pipeline.py` (OpenClawWorker) + `harness/perception/deduplicator.py`: VLM dedup
   changed from one 30 s cooldown per camera agent to `should_verify_target(camera, track,
   colour, bbox, now)`: a 30 s cooldown per target (track), plus fragment continuity - a new
   track with the same confirmed colour, within 2.0 s (the tracker's RECONNECT_WINDOW) of the
   target's last candidate and with its centre within one box diagonal, is the same target.
   Only production information is used (camera, track id, colour, bbox, time); no CARLA IDs.

Unit/regression tests: `tests/unit/test_dedup_and_stale_tracks.py`; v2 shadow equivalence with
the production Pipeline: `tests/validation/test_continuous_ablation_v2.py`.

## Before / After

| Metric | Before (v1 runs 1/2/3) | After (v2 runs) |
|---|---|---|
| stale (disappeared-track) Full candidates | 88 / 215 (run3; runs 1-2 not recorded) | run1: 0 / 89 ; run2: 0 / 126 ; run3: 0 / 126 |
| stale (disappeared-track) Full VLM triggers | 4 / 11 (run3) | run1: 0 / 19 ; run2: 0 / 23 ; run3: 0 / 23 |
| target vehicles entering FOV | 9/9/9 | 9/9/9 |
| target vehicles reaching VLM (Full) | 6/9, 5/9, 6/9 | 9/9, 9/9, 9/9 |
| Full VLM triggers | 11/11/11 | 19/23/23 |
| No HSV VLM triggers | 19/19/20 | 142/156/155 |
| No Temporal VLM triggers | 11/11/11 | 22/29/29 |
| No Dedup VLM triggers | 186/222/215 | 89/126/126 |
| Full candidates before dedup | 186/222/215 | 89/126/126 |

## Ablation (After)

| Run | Configuration | VLM triggers | vs Full | Candidates before dedup | Candidates vs Full | Dedup-suppressed (same target / fragment) | Unique target vehicles reaching VLM |
|---|---|---:|---:|---:|---:|---|---:|
| run1 | Full | 19 | 1.00x | 89 | 1.00x | 70 (68 / 2) | 9 |
| run1 | No HSV | 142 | +123, 7.4737x | 1252 | 14.0674x | 1110 (1026 / 84) | 9 |
| run1 | No Temporal | 22 | +3, 1.1579x | 292 | 3.2809x | 270 (259 / 11) | 9 |
| run1 | No Dedup | 89 | +70, 4.6842x | 89 | 1.0x | 0 (0 / 0) | 9 |
| run2 | Full | 23 | 1.00x | 126 | 1.00x | 103 (101 / 2) | 9 |
| run2 | No HSV | 156 | +133, 6.7826x | 1229 | 9.754x | 1073 (1002 / 71) | 9 |
| run2 | No Temporal | 29 | +6, 1.2609x | 407 | 3.2302x | 378 (371 / 7) | 9 |
| run2 | No Dedup | 126 | +103, 5.4783x | 126 | 1.0x | 0 (0 / 0) | 9 |
| run3 | Full | 23 | 1.00x | 126 | 1.00x | 103 (101 / 2) | 9 |
| run3 | No HSV | 155 | +132, 6.7391x | 1230 | 9.7619x | 1075 (1003 / 72) | 9 |
| run3 | No Temporal | 29 | +6, 1.2609x | 406 | 3.2222x | 377 (370 / 7) | 9 |
| run3 | No Dedup | 126 | +103, 5.4783x | 126 | 1.0x | 0 (0 / 0) | 9 |

What the triggers hit (actor association is evidence only):

| Run | Configuration | Target / non-target / unassociated triggers | Triggers from disappeared tracks | Exceptions |
|---|---|---|---:|---:|
| run1 | Full | 16 / 3 / 0 | 0 | 0 |
| run1 | No HSV | 13 / 127 / 2 | 0 | 0 |
| run1 | No Temporal | 19 / 2 / 1 | 0 | 0 |
| run1 | No Dedup | 84 / 5 / 0 | 0 | 0 |
| run2 | Full | 20 / 3 / 0 | 0 | 0 |
| run2 | No HSV | 17 / 138 / 1 | 0 | 0 |
| run2 | No Temporal | 26 / 2 / 1 | 0 | 0 |
| run2 | No Dedup | 121 / 5 / 0 | 0 | 0 |
| run3 | Full | 20 / 3 / 0 | 0 | 0 |
| run3 | No HSV | 17 / 137 / 1 | 0 | 0 |
| run3 | No Temporal | 26 / 2 / 1 | 0 | 0 |
| run3 | No Dedup | 121 / 5 / 0 | 0 | 0 |

## Target coverage (Full branch)

### run1

| Target actor (slot / blueprint) | FOV entry | YOLO | HSV | Track | Temporal | VLM Trigger | Failure reason |
|---|---|---|---|---|---|---|---|
| 5 / vehicle.chevrolet.impala | 67.6s | 68.2s | 68.2s | 68.2s | 68.4s | 68.4s | - |
| 13 / vehicle.mini.cooper_s_2021 | 28.8s | 28.9s | 29.1s | 29.1s | 29.1s | 29.1s | - |
| 21 / vehicle.mini.cooper_s | 426.2s | 426.5s | 426.5s | 426.5s | 426.7s | 426.7s | - |
| 29 / vehicle.bmw.grandtourer | 103.2s | 103.3s | 103.4s | 103.4s | 103.5s | 103.5s | - |
| 37 / vehicle.carlamotors.firetruck | 204.5s | 204.7s | 205.0s | 205.0s | 205.2s | 205.2s | - |
| 45 / vehicle.lincoln.mkz_2020 | 154.7s | 155.0s | 155.2s | 155.2s | 155.2s | 155.2s | - |
| 53 / vehicle.volkswagen.t2 | 99.6s | 99.8s | 99.9s | 99.9s | 100.0s | 100.0s | - |
| 61 / vehicle.micro.microlino | 200.7s | 201.0s | 201.0s | 201.0s | 201.2s | 201.2s | - |
| 69 / vehicle.ford.crown | 92.5s | 92.7s | 92.9s | 92.9s | 93.2s | 93.2s | - |

| Stage | Unique target vehicles |
|---|---:|
| Entered FOV | 9 |
| YOLO detected | 9 |
| HSV passed | 9 |
| Tracked | 9 |
| Confirmed | 9 |
| VLM reached | 9 |

Target vehicles with suppression owned by a different actor: 0.

### run2

| Target actor (slot / blueprint) | FOV entry | YOLO | HSV | Track | Temporal | VLM Trigger | Failure reason |
|---|---|---|---|---|---|---|---|
| 5 / vehicle.chevrolet.impala | 67.6s | 68.2s | 68.2s | 68.2s | 68.4s | 68.4s | - |
| 13 / vehicle.mini.cooper_s_2021 | 28.8s | 28.9s | 29.1s | 29.1s | 29.1s | 29.1s | - |
| 21 / vehicle.mini.cooper_s | 367.9s | 368.2s | 368.2s | 368.2s | 368.5s | 368.5s | - |
| 29 / vehicle.bmw.grandtourer | 103.2s | 103.3s | 103.4s | 103.4s | 103.5s | 103.5s | - |
| 37 / vehicle.carlamotors.firetruck | 204.5s | 204.7s | 205.0s | 205.0s | 205.2s | 205.2s | - |
| 45 / vehicle.lincoln.mkz_2020 | 154.7s | 155.0s | 155.2s | 155.2s | 155.2s | 155.2s | - |
| 53 / vehicle.volkswagen.t2 | 99.6s | 99.8s | 99.9s | 99.9s | 100.0s | 100.0s | - |
| 61 / vehicle.micro.microlino | 200.7s | 201.0s | 201.0s | 201.0s | 201.2s | 201.2s | - |
| 69 / vehicle.ford.crown | 92.5s | 92.7s | 92.9s | 92.9s | 93.2s | 93.2s | - |

| Stage | Unique target vehicles |
|---|---:|
| Entered FOV | 9 |
| YOLO detected | 9 |
| HSV passed | 9 |
| Tracked | 9 |
| Confirmed | 9 |
| VLM reached | 9 |

Target vehicles with suppression owned by a different actor: 0.

### run3

| Target actor (slot / blueprint) | FOV entry | YOLO | HSV | Track | Temporal | VLM Trigger | Failure reason |
|---|---|---|---|---|---|---|---|
| 5 / vehicle.chevrolet.impala | 67.6s | 68.2s | 68.2s | 68.2s | 68.4s | 68.4s | - |
| 13 / vehicle.mini.cooper_s_2021 | 28.8s | 28.9s | 29.1s | 29.1s | 29.1s | 29.1s | - |
| 21 / vehicle.mini.cooper_s | 367.9s | 368.2s | 368.2s | 368.2s | 368.5s | 368.5s | - |
| 29 / vehicle.bmw.grandtourer | 103.2s | 103.3s | 103.4s | 103.4s | 103.5s | 103.5s | - |
| 37 / vehicle.carlamotors.firetruck | 204.5s | 204.7s | 205.0s | 205.0s | 205.2s | 205.2s | - |
| 45 / vehicle.lincoln.mkz_2020 | 154.7s | 155.0s | 155.2s | 155.2s | 155.2s | 155.2s | - |
| 53 / vehicle.volkswagen.t2 | 99.6s | 99.8s | 99.9s | 99.9s | 100.0s | 100.0s | - |
| 61 / vehicle.micro.microlino | 200.7s | 201.0s | 201.0s | 201.0s | 201.2s | 201.2s | - |
| 69 / vehicle.ford.crown | 92.5s | 92.7s | 92.9s | 92.9s | 93.2s | 93.2s | - |

| Stage | Unique target vehicles |
|---|---:|
| Entered FOV | 9 |
| YOLO detected | 9 |
| HSV passed | 9 |
| Tracked | 9 |
| Confirmed | 9 |
| VLM reached | 9 |

Target vehicles with suppression owned by a different actor: 0.

## Answers (per-run shadow comparison on identical input; not causal claims)

1. HSV removed: VLM triggers 19/23/23 -> 142/156/155 (6.74-7.47x).
2. Temporal removed: candidates before dedup 89/126/126 -> 292/407/406 (3.22-3.28x); VLM triggers 19/23/23 -> 22/29/29 (1.16-1.26x).
3. Dedup removed: VLM triggers 19/23/23 -> 89/126/126 (4.68-5.48x).
4. New dedup: unique target vehicles reaching VLM 9/9/9 of 9/9/9; target vehicles whose
   candidates were suppressed by another vehicle's entry: 0. Full suppressed 70/103/103 candidates
   (same target 68/101/101, fragment 2/2/2); residual fragmentation leaks (<30 s repeat on the same
   vehicle) 5/4/4.
5. Stale tracks: Full candidates from disappeared tracks 0/0/0, VLM triggers 0/0/0; triggers whose
   bbox is not a current-frame detection: 0.

Ground-truth colour caveat (verified by crops): `vehicle.micro.microlino` renders a blue body
regardless of the assigned `color` attribute, so the yellow-assigned Microlino is labelled
non-target although it is visibly blue (e.g. `evidence/runs/run2/evidence/trigger_crops/full/f3381_t206.jpg`).
All Full `non-target` triggers in these runs are that vehicle. The same artefact affects
Experiment B v1's `non_target_actor` counts for the Microlino; v1 files are left unchanged.

## Duplicate handling (Full)

| Run | Total VLM triggers | Unique target vehicles reaching VLM | Same-target suppressed | Fragment suppressed | Repeat triggers on an already-triggered vehicle (<30 s leak / >=30 s) |
|---|---:|---:|---:|---:|---|
| run1 | 19 | 9 | 68 | 2 | 5 / 4 |
| run2 | 23 | 9 | 101 | 2 | 4 / 9 |
| run3 | 23 | 9 | 101 | 2 | 4 / 9 |

Repeat triggers are listed in `full_repeat_trigger_analysis.csv`. A <30 s repeat on the same
vehicle is a fragmentation leak (new track ID not linked by the continuity rule, e.g. after the
vehicle passes behind the street banner); >=30 s repeats are cooldown expiry or a later revisit,
which production cannot distinguish without re-identification.

## Full pipeline frame funnel (frame units)

| Run | Stage | Count | Previous-stage retention | Input ratio |
|---|---|---:|---:|---:|
| run1 | input_frames | 6000 | None | 1.0 |
| run1 | frames_with_yolo_vehicle_detection | 2682 | 0.447 | 0.447 |
| run1 | frames_with_target_hsv_candidate | 285 | 0.1063 | 0.0475 |
| run1 | frames_with_active_target_track | 285 | 1.0 | 0.0475 |
| run1 | frames_triggering_temporal_confirmation | 89 | 0.3123 | 0.0148 |
| run1 | frames_triggering_vlm | 19 | 0.2135 | 0.0032 |
| run2 | input_frames | 6000 | None | 1.0 |
| run2 | frames_with_yolo_vehicle_detection | 2744 | 0.4573 | 0.4573 |
| run2 | frames_with_target_hsv_candidate | 398 | 0.145 | 0.0663 |
| run2 | frames_with_active_target_track | 398 | 1.0 | 0.0663 |
| run2 | frames_triggering_temporal_confirmation | 126 | 0.3166 | 0.021 |
| run2 | frames_triggering_vlm | 23 | 0.1825 | 0.0038 |
| run3 | input_frames | 6000 | None | 1.0 |
| run3 | frames_with_yolo_vehicle_detection | 2741 | 0.4568 | 0.4568 |
| run3 | frames_with_target_hsv_candidate | 397 | 0.1448 | 0.0662 |
| run3 | frames_with_active_target_track | 397 | 1.0 | 0.0662 |
| run3 | frames_triggering_temporal_confirmation | 126 | 0.3174 | 0.021 |
| run3 | frames_triggering_vlm | 23 | 0.1825 | 0.0038 |

## Runs

| Run | Frames | Duration (s) | Unique vehicles in FOV | Target / non-target in FOV | YOLO detections | Dropped frames | Exceptions | Cleanup |
|---|---:|---:|---:|---|---:|---:|---:|---|
| run1 | 6000 | 600.0 | 69 | 9 / 60 | 4174 | 0 | 0 | 71/71 |
| run2 | 6000 | 600.0 | 67 | 9 / 58 | 4114 | 0 | 0 | 71/71 |
| run3 | 6000 | 600.0 | 67 | 9 / 58 | 4112 | 0 | 0 | 71/71 |

## Evidence images

- `evidence/runs/run*/evidence/stages/`: per target vehicle, first YOLO detection / HSV pass /
  matched blue track / temporal confirmation / VLM trigger (white = projected CARLA box).
- `evidence/runs/run*/evidence/dedup_suppressed/`: same-target and fragment suppressions.
- `evidence/runs/run*/evidence/new_target_within_30s/`: a different target reaching VLM <30 s
  after the previous trigger (blocked under the Before policy).
- `evidence/before_after/`: Before stale trigger crop (empty road) and all After Full trigger crops.

Limitations: `limitations.md`. VLM requests are counted triggers; no VLM is called.
Historical 46,372 / 28,736 / 3,298 / 53 values are not compared.

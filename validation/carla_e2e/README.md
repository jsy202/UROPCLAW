# CARLA validation index

Post-project validation on a real CARLA 0.9.13 host (RTX 3060, Real YOLOv8s).
Every result below comes from committed run outputs in the linked directories.
VLM and alert services are deterministic fakes, or are counted as triggers only;
no Real VLM inference is measured. Back to the [project README](../../README.md).

| Experiment | Question | Directory | Main report |
|---|---|---|---|
| Single-vehicle E2E | Does the pipeline run end-to-end on real CARLA frames with Real YOLO, and recover from Fake VLM faults? | [`real_pipeline/`](real_pipeline/) | [validation_report.md](real_pipeline/validation_report.md) |
| A: Dynamic multi-vehicle | Is the pipeline stable with 16 moving vehicles (Target / Non-target x10)? | [`multivehicle/`](multivehicle/) | [validation_report.md](multivehicle/validation_report.md) |
| B v1 (Before) | 10-minute 4-way ablation on the original production logic | [`continuous_ablation/`](continuous_ablation/) | [continuous_10min_report.md](continuous_ablation/continuous_10min_report.md) |
| B v2 (After) | Same ablation after the stale-track and per-target dedup fixes | [`continuous_ablation_v2/`](continuous_ablation_v2/) | [validation_report.md](continuous_ablation_v2/validation_report.md) |

## Results at a glance

- Single-vehicle E2E: Target 10/10 and Non-target 10/10. Fake VLM faults (delay, timeout, error, malformed) were injected 20 times, and all 20 were detected and recovered from. See `real_pipeline/scenario_summary.csv` and `real_pipeline/fault_summary.csv`.
- Experiment A: Target 10/10 and Non-target 10/10. 0 false target events, 0 dropped frames, 0 crashes, and 17/17 actors cleaned up in every run. Nine validation-harness defects were found and fixed; see [DEF-MV-01-09](multivehicle/evidence/defects/DEF-MV-01-09.md).
- Experiment B v1 (Before): the Full branch reached only 6, 5 and 6 of the 9 target vehicles. In run 3, 88 of 215 Full candidates and 4 of 11 triggers came from stale (disappeared) tracks. These numbers are the Before reference; v1 files are kept unchanged.
- Experiment B v2 (After):
  - VLM triggers per run (Full / No HSV / No Temporal / No Dedup): 19/142/22/89, 23/156/29/126 and 23/155/29/126.
  - Target coverage was 9/9 in every run, with 0 stale-track triggers.
  - The before/after comparison is in [before_after_summary.csv](continuous_ablation_v2/before_after_summary.csv).

Results from different experiments are not merged. The historical 46,372 / 28,736 / 3,298 / 53 values are not compared with any of them.

## Production changes made during validation

Both changes are in commit `a25c6ae`:

- `harness/core/pipeline.py`: temporal confirmation is updated only for tracks matched in the current frame, and the VLM dedup call uses per-target dedup.
- `harness/perception/deduplicator.py`: adds `should_verify_target` (a 30 s cooldown per target, plus fragment continuity).

The regression tests are in `tests/unit/test_dedup_and_stale_tracks.py`, and the shadow-branch equivalence test is in `tests/validation/test_continuous_ablation_v2.py`.

## Re-running on a CARLA host

These commands need a running CARLA 0.9.13 server on `127.0.0.1:2000` and the `.venv-carla-e2e` environment. Never run two at once.

```bash
python validation/carla_e2e/multivehicle/run_host_smoke.py                     # Experiment A smoke
python validation/carla_e2e/multivehicle/run_host_benchmark.py --repetitions 10 # Experiment A benchmark
python validation/carla_e2e/continuous_ablation_v2/run_continuous_ablation_v2.py \
    --duration-seconds 600 --output-dir validation/carla_e2e/continuous_ablation_v2/evidence/runs/runN
python validation/carla_e2e/continuous_ablation_v2/aggregate_v2.py              # rebuild v2 report from runs
```

## Limitations

- [Experiment B v2](continuous_ablation_v2/limitations.md)
- [Experiment B v1](continuous_ablation/limitations.md)
- [Experiment A](multivehicle/limitations.md)
- [Single-vehicle](real_pipeline/limitations.md)

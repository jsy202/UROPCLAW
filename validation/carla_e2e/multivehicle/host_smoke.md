# Host smoke and benchmark execution

Run from a normal host terminal while the CARLA 0.9.13 server is already
listening on `127.0.0.1:2000` (do not start a second server):

```bash
cd /home/jsy202/validation-work/UROPCLAW-carla-e2e
source .venv-carla-e2e/bin/activate
python validation/carla_e2e/multivehicle/run_host_smoke.py
echo "exit_code=$?"
```

If a previous validation process aborted after spawning its role-tagged actors,
add `--cleanup-stale-validation-actors`. It destroys only actors whose
`role_name` starts with `uropclaw_validation_` and records their IDs.

The smoke exits `0` only for a complete PASS and writes to `evidence/smoke/`:
`result.json`, `run.log`, `scene_manifest.json`, `target_scene_manifest.json`,
`non_target_scene_manifest.json`, `environment.json`, `scene_preroll.png`,
`max_detections_annotated.png`, `probe_first_detection_annotated.png`.

Non-target replay of a saved Target manifest:

```bash
python validation/carla_e2e/multivehicle/run_host_smoke.py --scenario non_target \
  --replay-manifest validation/carla_e2e/multivehicle/evidence/smoke/target_scene_manifest.json \
  --evidence-dir /tmp/non_target_check
```

Repeated benchmark (10 Target + 10 Non-target, alternating, one subprocess per
run; writes the CSVs and `validation_report.md` in this directory and per-run
evidence under `evidence/benchmark/runs/`):

```bash
python validation/carla_e2e/multivehicle/run_host_benchmark.py --repetitions 10
echo "exit_code=$?"
```

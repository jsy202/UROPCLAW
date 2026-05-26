# Host smoke execution

Run from a normal host terminal while the CARLA 0.9.13 server is already
listening on `127.0.0.1:2000`:

```bash
cd /home/jsy202/validation-work/UROPCLAW-carla-e2e
source .venv-carla-e2e/bin/activate
python validation/carla_e2e/multivehicle/run_host_smoke.py
```

If a previous validation process aborted after spawning its role-tagged actors,
use the explicit recovery flag. It destroys only actors whose `role_name`
starts with `uropclaw_validation_` and records their IDs:

```bash
python validation/carla_e2e/multivehicle/run_host_smoke.py --cleanup-stale-validation-actors
```

Do not start a second CARLA server. The command exits `0` only for a complete
smoke PASS and writes:

- `evidence/smoke/result.json`
- `evidence/smoke/scene_manifest.json`
- `evidence/smoke/non_target_scene_manifest.json`
- `evidence/smoke/scene_preroll.png`
- `evidence/smoke/max_detections_annotated.png`
- `evidence/smoke/run.log`

After execution, preserve the command exit code:

```bash
echo "exit_code=$?"
```

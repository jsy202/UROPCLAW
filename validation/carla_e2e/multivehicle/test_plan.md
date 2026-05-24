# Dynamic multi-vehicle test plan

## Current gate: Target smoke only

1. Connect to the already-running host CARLA server without restarting it.
2. Require client/server version 0.9.13.
3. Enable synchronous 0.1-second ticks and Traffic Manager seed 42.
4. Plan and spawn exactly fifteen background actors plus one blue probe.
5. Spawn the fixed 800x600, 90-degree CCTV.
6. Run fifty pre-roll ticks; use ten real pre-roll frames for YOLO warm-up.
7. Start the probe route and accept exactly 100 measured frames.
8. Run the injected production pipeline with Real YOLO, existing HSV/tracker/
   temporal/deduplication, deterministic Fake VLM, and Fake Alert.
9. Drain queues, evaluate every smoke gate, destroy owned actors, and restore
   world/TM mode.

The runner exits zero only when every gate in `scenario_design.md` passes.
Failure evidence remains in `evidence/smoke/` with a non-zero exit code.

## Deferred work

The repeated Target/Non-target benchmark runner is intentionally not present.
It will be prepared only after reviewing an actual Target smoke PASS. Its
planned default is 100 frames/run with an explicit CLI option up to 200.

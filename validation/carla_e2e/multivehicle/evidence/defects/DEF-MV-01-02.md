# Multi-vehicle runner orchestration defects

Status: runner defects reproduced and patched; host smoke has not yet passed.

## DEF-MV-01: synchronous camera readiness timeout

Observed host evidence in `../smoke/run.log`:

```text
image = image_queue.get(timeout=args.timeout)
_queue.Empty
```

The original order was `camera.listen()` -> `world.tick()` -> blocking queue
read. It was not a queue read before the first tick. `max_detections_annotated.png`
shows that at least one camera frame arrived; the traceback line is inside the
pre-roll loop. The precise reason one later tick produced no queued image is not
established by the old runner because it recorded neither the tick frame ID nor
received sensor frame IDs. Its orchestration defect was treating an unlabelled
queue item as the current tick and, on a missing callback, blocking for 30
seconds without diagnostic frame correlation.

The patch introduces an explicit readiness gate that can advance up to ten
bounded synchronous ticks. After readiness, every pre-roll and measurement
step matches the frame ID returned by `world.tick()` to `image.frame`, discards
stale sensor frames explicitly, and records expected/received IDs on timeout.
The next host run is required to distinguish a transient startup condition from
a reproducible mid-pre-roll sensor delivery problem.

## DEF-MV-02: cleanup access after actor destruction

The old cleanup called `actor.destroy()` and then queried `actor.is_alive` on
the same CARLA proxy. CARLA 0.9.13 can reject operations on that destroyed
proxy, matching the observed native `std::runtime_error`.

The patch closes the callback gate, calls `camera.stop()`, destroys the camera,
then destroys controlled vehicles. Owned actor handles are deduplicated and no
actor property is read after `destroy()`.

## Evidence integrity note

The current `../smoke/result.json` still contains the earlier WorldSettings
copy failure because the native cleanup termination prevented the timeout run
from completing its atomic result rewrite. The contemporaneous timeout is in
`../smoke/run.log`; `scene_manifest.json` records the planned and actually
spawned scene for that run. These artifacts are preserved as failure evidence
and are not multi-vehicle validation results.

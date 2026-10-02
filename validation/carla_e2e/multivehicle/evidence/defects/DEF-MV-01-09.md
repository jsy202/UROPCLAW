# Multi-vehicle runner orchestration defects

Status: DEF-MV-01..09 reproduced on the host and fixed; host smoke PASS
(see DEF-MV-03 onward and `../smoke/result.json`).

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

## DEF-MV-03: native abort at Traffic Manager teardown (exit 134)

Reproduced on a clean server with `python -X faulthandler`:

```text
terminate called after throwing an instance of 'std::runtime_error'
  what():  trying to operate on a destroyed actor; ...
Fatal Python error: Aborted
  File ".../multivehicle/scene.py", line 289 in synchronous_mode   # tm.set_synchronous_mode(False)
```

`set_autopilot(True, tm_port)` hands Traffic Manager the same client-side actor
proxy. Cleanup destroyed that proxy while the vehicles were still registered;
switching TM out of synchronous mode then let TM's native thread call into a
destroyed actor, and the C++ exception escaped a non-Python thread. A clean
server does not help because the runner itself creates the condition.

Fix (`shutdown_scene_resources`): stop camera -> `set_autopilot(False)` for every
owned vehicle -> `world.tick()` -> destroy -> `world.tick()`, all while still
synchronous; only then leave TM/world synchronous mode. The spawn-failure path
also unregisters before destroying. `faulthandler` is enabled in `main()`.

The abort had masked the earlier Python failure below; no artifact after
`scene_manifest.json` had been written.

## DEF-MV-04: synchronous sensor frame skipped (`sensor_tick == fixed_delta`)

After DEF-MV-03 the masked error surfaced:
`SensorFrameTimeout: expected=58082, received=[58081]`. With
`sensor_tick=0.1` equal to `fixed_delta_seconds=0.1`, the camera can skip a
synchronous tick through float accumulation. The single-vehicle runner was
asynchronous, so it never hit this. Fix: `sensor_tick=0.0` (capture every tick);
the effective period is exactly 0.1 s (10 Hz), recorded in the manifest.

## DEF-MV-05: frame identity collision in instrumentation (`input_frames=24`)

`Observation` keyed frames by `id(frame)`. Once production released a processed
array, CPython reused its address for a later frame, overwriting metadata
(100 accepted frames -> 24 keys) and attributing ground truth to the wrong
frame. Fix: hold a reference to each accepted frame for the run. The main
thread also no longer writes `current_frame`, which the YOLO worker reads.

## DEF-MV-06: probe wedged by TM `set_path`

Probe diagnostics (collision sensor, control, nearest actors) showed TM
`set_path` with 2 m route points steering the probe off-lane into static
geometry (`static.static` collisions, throttle 0.85, steer -0.8, 0.05 m/s).
Plain autopilot followed the same lane without collision. Fix: autopilot only,
probe `auto_lane_change=False`, and per-frame measured route adherence
(`probe_route_deviation_m`, gate <= 3.5 m while inside the corridor).

## DEF-MV-07: corridor geometry prevented observable entry/exit

Measured on the host: (a) the probe started already clipped into the FOV edge
(entry frame 0); (b) on a curved corridor the probe drove parallel to the
frustum edge (bbox stuck at x=794..799 px for 15 frames, no exit); (c) a junction
made TM yield to cross traffic for ~2 s. Fix: require a straight (heading spread
<= 10 deg), junction-free 80 m corridor, and extend backwards along the lane
until the probe footprint projects fully outside the image.

## DEF-MV-08: CCTV placed inside static geometry

The planned camera landed inside an elevated rail structure (YOLO 0 boxes in
all frames, `scene_preroll.png` shows the deck). Fix: candidate corridors are
accepted only with two-way `world.cast_ray` line of sight from the camera to the
observation point and >= 80% of corridor points at 1 m height; the right side
is tried first, then the left.

## DEF-MV-09: target gates satisfied by a non-probe blue object

A blue confirmation occurred while the probe was not near the view (a parked
blue motorcycle prop, not a CARLA actor). Gates now require the confirmed track
to overlap the probe's projected box (IoU >= 0.30); other blue confirmations
are recorded as `non_probe_target_confirmed_track_ids`. The deviation metric is
also not evaluated beyond the corridor's end (a 3.70 m value at frame 99 was the
distance to the route endpoint after the probe left the corridor).

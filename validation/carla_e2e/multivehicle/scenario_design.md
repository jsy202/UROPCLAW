# Dynamic multi-vehicle CARLA validation design

Status: approved design, revised after host smoke diagnosis (DEF-MV-03..09);
host smoke PASS.

## Scope

This validation exercises the unchanged production perception path with real
CARLA RGB frames and Real YOLO. Scene construction, measurement, Fake VLM, and
Fake Alert are validation-only. CARLA actor identity and projected bounding
boxes are evidence inputs only and must never affect detector, tracker,
confirmation, deduplication, or alert decisions.

The existing static single-vehicle results remain a separate
`Real CARLA based deterministic single-candidate system integration validation`.
This directory is reserved for `Real CARLA dynamic multi-vehicle traffic
validation` and does not overwrite those results.

## Fixed scenario contract

- CARLA synchronous mode with `fixed_delta_seconds=0.1`.
- Traffic Manager synchronous mode, port 8000, random seed 42.
- Fifteen background four-wheel vehicles and one probe: exactly sixteen
  controlled vehicles. A bounded spawn retry may choose another planned slot;
  fewer than sixteen actual actors is a smoke failure.
- A topology-derived deterministic road corridor and fixed world-space CCTV.
- RGB camera: 800x600, 90 degree FOV, `sensor_tick=0.0` (one frame per 0.1 s
  synchronous tick, i.e. 10 Hz; `sensor_tick=0.1` skipped ticks, DEF-MV-04).
- Five seconds (50 ticks) of pre-roll, excluded from measured frame metrics.
- Smoke measurement: exactly 100 accepted frames.
- Target probe is blue. Non-target replays the saved Target manifest and changes
  only the probe colour to red; its blueprint, transform, route, and Traffic
  Manager settings remain identical.
- Target manifest is written with separate `planned_scene` and
  `actual_spawned_scene` sections.
- Only actors created by this validation are destroyed.

## Deterministic corridor and traffic

Spawn points are sorted by rounded world coordinates and rotation before any
seeded choice. Candidate probe routes are built by walking driving-lane
waypoints forward at two-metre intervals. The selected candidate must provide
an 80 m route that is straight (yaw spread <= 10 degrees) and junction-free
(DEF-MV-07). The camera is placed 18 m beside and 8 m above the observation
waypoint (route[20]) and aimed at it; the candidate is accepted only if
`world.cast_ray` shows two-way line of sight to the observation point and to at
least 80% of the corridor points within +/-20 m at 1 m height (right side
first, then left; DEF-MV-08). The probe start is extended backwards along the
lane until its conservative footprint projects fully outside the image.

The probe is held during pre-roll. At measurement start it is enabled for
autopilot with `auto_lane_change=False`; no TM `set_path` is used (DEF-MV-06).
Route adherence is measured every frame while the probe is inside the
corridor. Background vehicles use
autopilot throughout pre-roll and measurement. Planned background spawns favor
the selected corridor and nearby lanes, then use the remaining deterministically
ordered spawn points.

No route is declared successful from geometry alone. Ground-truth projection is
used after the production result solely to establish visible actor counts and
the probe's FOV entry/exit frames. The smoke fails if entry and exit are not both
observed inside the 100 measured frames.

## Smoke gate

PASS requires all of the following measured facts:

1. All sixteen controlled actors spawned.
2. At least twelve of the fifteen background vehicles moved at least one metre
   during pre-roll.
3. At least one measured frame has two or more Real YOLO vehicle boxes.
4. Probe FOV entry and exit are observed.
5. A production-format YOLO box is associated with the projected probe box for
   evidence only.
6. A blue HSV classification occurs for the associated probe observation.
7. The unchanged IoU tracker creates a blue active track overlapping the
   projected probe box (IoU >= 0.30).
8. The unchanged temporal confirmer emits a blue result for such a probe track
   (a blue confirmation of any other object does not satisfy this gate).
9. The unchanged candidate/dedup path calls Fake VLM with an image.
10. Every validation-created camera and vehicle is destroyed.
11. Exactly 100 frames enter the production input queue.
12. The probe stays within 3.5 m of the planned corridor while inside it.

Non-target runs (`--scenario non_target --replay-manifest <target manifest>`)
share gates 1-5 and 10-12 and additionally require: a production track overlaps
the red probe, no blue probe confirmation, zero Fake VLM requests and zero
target events.

Failure evidence is saved without silently lowering actor count, extending the
measurement window, or treating an unobserved gate as success.

## Measurement units

Frame/image counters are kept separate from object, track, event, and request
counters. Frame retention is computed only for Input->YOLO, YOLO->HSV,
HSV->Tracking, Tracking->Confirmation, and VLM images/Input. Historical
46,372 / 28,736 / 3,298 / 53 values are not compared with these measurements.

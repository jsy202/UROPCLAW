# Dynamic multi-vehicle CARLA validation design

Status: approved design, host smoke not yet executed.

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
- RGB camera: 800x600, 90 degree FOV, sensor tick 0.1 seconds.
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
enough route length on both sides of its observation point and nearby vehicle
spawn capacity. The camera is placed above and beside the observation waypoint
and aimed at the road corridor.

The probe is held during pre-roll. At measurement start it is enabled for
autopilot and receives its saved Traffic Manager path. Background vehicles use
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
7. The unchanged IoU tracker creates a target-colour active track.
8. The unchanged temporal confirmer emits a blue result.
9. The unchanged candidate/dedup path calls Fake VLM with an image.
10. Every validation-created camera and vehicle is destroyed.

Failure evidence is saved without silently lowering actor count, extending the
measurement window, or treating an unobserved gate as success.

## Measurement units

Frame/image counters are kept separate from object, track, event, and request
counters. Frame retention is computed only for Input->YOLO, YOLO->HSV,
HSV->Tracking, Tracking->Confirmation, and VLM images/Input. Historical
46,372 / 28,736 / 3,298 / 53 values are not compared with these measurements.

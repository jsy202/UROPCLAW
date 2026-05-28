"""Validation-only deterministic CARLA scene construction and lifecycle."""

from __future__ import annotations

import copy
import math
import random
from contextlib import contextmanager


BACKGROUND_COUNT = 15
PROBE_COUNT = 1
CONTROLLED_COUNT = BACKGROUND_COUNT + PROBE_COUNT
BACKGROUND_COLORS = (
    "255,0,0", "255,255,255", "10,10,10", "150,150,150",
    "0,200,0", "255,255,0", "255,140,0",
)


class SceneBuildError(RuntimeError):
    pass


def transform_to_dict(transform):
    return {
        "location": {
            "x": float(transform.location.x),
            "y": float(transform.location.y),
            "z": float(transform.location.z),
        },
        "rotation": {
            "pitch": float(transform.rotation.pitch),
            "yaw": float(transform.rotation.yaw),
            "roll": float(transform.rotation.roll),
        },
    }


def transform_from_dict(carla_module, value):
    location = value["location"]
    rotation = value["rotation"]
    return carla_module.Transform(
        carla_module.Location(x=location["x"], y=location["y"], z=location["z"]),
        carla_module.Rotation(
            pitch=rotation["pitch"], yaw=rotation["yaw"], roll=rotation["roll"]
        ),
    )


def deterministic_assignments(blueprint_ids, colors, count, seed):
    blueprint_ids = sorted(set(blueprint_ids))
    colors = sorted(set(colors))
    if not blueprint_ids or not colors:
        raise SceneBuildError("vehicle blueprints and colours are required")
    rng = random.Random(seed)
    blueprint_order = list(blueprint_ids)
    color_order = list(colors)
    rng.shuffle(blueprint_order)
    rng.shuffle(color_order)
    return [
        (blueprint_order[index % len(blueprint_order)], color_order[index % len(color_order)])
        for index in range(count)
    ]


def _location_dict(location):
    return {"x": float(location.x), "y": float(location.y), "z": float(location.z)}


def _distance_locations(left, right):
    return math.sqrt((left.x - right.x) ** 2 + (left.y - right.y) ** 2 + (left.z - right.z) ** 2)


def _sorted_spawn_points(carla_map):
    return sorted(
        carla_map.get_spawn_points(),
        key=lambda item: (
            round(item.location.x, 3), round(item.location.y, 3), round(item.location.z, 3),
            round(item.rotation.yaw, 3),
        ),
    )


def _walk_route(start_waypoint, distance=2.0, points=41):
    route = [start_waypoint]
    current = start_waypoint
    for _ in range(points - 1):
        candidates = current.next(distance)
        if not candidates:
            return []
        current = sorted(
            candidates,
            key=lambda item: (
                int(getattr(item, "road_id", 0)), int(getattr(item, "lane_id", 0)),
                round(item.transform.location.x, 3), round(item.transform.location.y, 3),
            ),
        )[0]
        route.append(current)
    return route


def _heading_spread_degrees(route):
    """Largest yaw difference from the first waypoint along a route."""
    start = route[0].transform.rotation.yaw
    spread = 0.0
    for waypoint in route[1:]:
        delta = (waypoint.transform.rotation.yaw - start + 180.0) % 360.0 - 180.0
        spread = max(spread, abs(delta))
    return spread


MAX_CORRIDOR_HEADING_SPREAD_DEGREES = 10.0


def _camera_transform(carla_module, observation_transform, side=1.0):
    target = observation_transform.location
    yaw_radians = math.radians(observation_transform.rotation.yaw)
    right_x, right_y = -math.sin(yaw_radians), math.cos(yaw_radians)
    camera_location = carla_module.Location(
        x=target.x + side * right_x * 18.0,
        y=target.y + side * right_y * 18.0,
        z=target.z + 8.0,
    )
    dx, dy, dz = target.x - camera_location.x, target.y - camera_location.y, target.z - camera_location.z
    horizontal = math.sqrt(dx * dx + dy * dy)
    return carla_module.Transform(
        camera_location,
        carla_module.Rotation(
            pitch=math.degrees(math.atan2(dz, horizontal)),
            yaw=math.degrees(math.atan2(dy, dx)),
            roll=0.0,
        ),
    )


def project_point(camera_transform, location, width=800, height=600, fov=90.0):
    """Pinhole projection of a world point; returns (u, v) or None if behind."""
    pitch = math.radians(camera_transform.rotation.pitch)
    yaw = math.radians(camera_transform.rotation.yaw)
    dx = location.x - camera_transform.location.x
    dy = location.y - camera_transform.location.y
    dz = location.z - camera_transform.location.z
    forward = (math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch))
    right = (-math.sin(yaw), math.cos(yaw), 0.0)
    up = (-math.sin(pitch) * math.cos(yaw), -math.sin(pitch) * math.sin(yaw), math.cos(pitch))
    depth = dx * forward[0] + dy * forward[1] + dz * forward[2]
    if depth <= 0.1:
        return None
    focal = width / (2.0 * math.tan(math.radians(fov) / 2.0))
    lateral = dx * right[0] + dy * right[1]
    vertical = dx * up[0] + dy * up[1] + dz * up[2]
    return (width / 2.0 + focal * lateral / depth, height / 2.0 - focal * vertical / depth)


def footprint_in_image(carla_module, camera_transform, location, width=800, height=600, fov=90.0, half_extent=3.0):
    """True if any corner of a conservative vehicle box around location projects into the image."""
    for ox in (-half_extent, half_extent):
        for oy in (-half_extent, half_extent):
            for oz in (0.0, 2.0):
                corner = carla_module.Location(x=location.x + ox, y=location.y + oy, z=location.z + oz)
                point = project_point(camera_transform, corner, width, height, fov)
                if point is not None and 0 <= point[0] < width and 0 <= point[1] < height:
                    return True
    return False


def _walk_back_outside_view(carla_module, start_waypoint, camera_transform, distance=2.0, max_points=20, margin_points=0):
    """Walk backwards along the lane until the probe footprint is fully outside the camera view."""
    lead_in = []
    current = start_waypoint
    outside = 0
    while outside <= margin_points:
        if not footprint_in_image(carla_module, camera_transform, current.transform.location):
            outside += 1
            if outside > margin_points:
                break
        else:
            outside = 0
        if len(lead_in) >= max_points:
            return None
        candidates = current.previous(distance)
        if not candidates:
            return None
        current = sorted(
            candidates,
            key=lambda item: (
                int(getattr(item, "road_id", 0)), int(getattr(item, "lane_id", 0)),
                round(item.transform.location.x, 3), round(item.transform.location.y, 3),
            ),
        )[0]
        lead_in.insert(0, current)
    return lead_in


def _ray_clear(world, start, end, endpoint_tolerance=1.5):
    """True if no static geometry is hit before the ray reaches the endpoint region."""
    for hit in world.cast_ray(start, end):
        location = hit.location
        if _distance_locations(location, end) > endpoint_tolerance:
            return False
    return True


MIN_CORRIDOR_VISIBLE_FRACTION = 0.8


def corridor_visibility(carla_module, world, camera_transform, route, centre_index=20, half_window=10):
    """Fraction of corridor points (vehicle height) with two-way line of sight from the camera."""
    camera = camera_transform.location
    samples = route[max(0, centre_index - half_window):centre_index + half_window + 1]
    clear = 0
    centre_clear = False
    for index, waypoint in enumerate(samples):
        location = waypoint.transform.location
        target = carla_module.Location(x=location.x, y=location.y, z=location.z + 1.0)
        visible = _ray_clear(world, camera, target) and _ray_clear(world, target, camera)
        clear += int(visible)
        if waypoint is route[centre_index]:
            centre_clear = visible
    fraction = clear / float(len(samples)) if samples else 0.0
    return {"visible_fraction": round(fraction, 3), "centre_visible": centre_clear, "samples": len(samples)}


def plan_scene(carla_module, world, seed=42, background_count=BACKGROUND_COUNT):
    """Create a deterministic plan from the current map without spawning actors."""
    if background_count != BACKGROUND_COUNT:
        raise SceneBuildError("smoke requires exactly 15 background vehicles")
    carla_map = world.get_map()
    spawn_points = _sorted_spawn_points(carla_map)
    if len(spawn_points) < CONTROLLED_COUNT:
        raise SceneBuildError("map has fewer than 16 spawn points")

    rng = random.Random(seed)
    candidates = list(spawn_points)
    rng.shuffle(candidates)
    route = []
    probe_spawn = None
    camera_transform = None
    visibility = None
    rejected_occluded = 0
    for candidate in candidates:
        waypoint = carla_map.get_waypoint(candidate.location)
        candidate_route = _walk_route(waypoint)
        # A curved corridor can run parallel to the frustum edge, so the probe
        # never cleanly exits the view; a junction makes TM yield to cross
        # traffic. Require a straight, junction-free 80 m corridor.
        if (
            len(candidate_route) == 41
            and _heading_spread_degrees(candidate_route) <= MAX_CORRIDOR_HEADING_SPREAD_DEGREES
            and not any(bool(getattr(waypoint, "is_junction", False)) for waypoint in candidate_route)
        ):
            # The fixed CCTV must actually see the corridor: try the right-hand
            # side, then the left, and require two-way line of sight.
            for side in (1.0, -1.0):
                candidate_camera = _camera_transform(carla_module, candidate_route[20].transform, side)
                candidate_visibility = corridor_visibility(carla_module, world, candidate_camera, candidate_route)
                if (
                    candidate_visibility["centre_visible"]
                    and candidate_visibility["visible_fraction"] >= MIN_CORRIDOR_VISIBLE_FRACTION
                ):
                    route = candidate_route
                    probe_spawn = candidate
                    camera_transform = candidate_camera
                    visibility = dict(candidate_visibility, camera_side="right" if side > 0 else "left")
                    break
                rejected_occluded += 1
            if route:
                break
    if not route or probe_spawn is None:
        raise SceneBuildError("no deterministic straight junction-free 80 metre driving corridor found")

    observation = route[20].transform
    # The probe must start fully outside the frustum so FOV entry is observed
    # inside the measurement window. Extend the corridor backwards along the lane.
    lead_in = _walk_back_outside_view(carla_module, route[0], camera_transform)
    if lead_in is None:
        raise SceneBuildError("no lead-in found that starts the probe outside the camera view")
    route = lead_in + route
    probe_start = route[0].transform
    probe_spawn_transform = carla_module.Transform(
        carla_module.Location(
            x=probe_start.location.x, y=probe_start.location.y, z=probe_start.location.z + 0.6,
        ),
        probe_start.rotation,
    )
    remaining = [item for item in spawn_points if _distance_locations(item.location, probe_spawn.location) > 1.0]
    remaining.sort(key=lambda item: (_distance_locations(item.location, observation.location), round(item.location.x, 3), round(item.location.y, 3)))
    if len(remaining) < BACKGROUND_COUNT + CONTROLLED_COUNT:
        retry_pool = remaining[BACKGROUND_COUNT:]
    else:
        retry_pool = remaining[BACKGROUND_COUNT:BACKGROUND_COUNT + CONTROLLED_COUNT]

    library = world.get_blueprint_library()
    vehicle_bps = [
        blueprint for blueprint in library.filter("vehicle.*")
        if blueprint.has_attribute("number_of_wheels")
        and blueprint.get_attribute("number_of_wheels").as_int() == 4
        and blueprint.has_attribute("color")
    ]
    assignments = deterministic_assignments([bp.id for bp in vehicle_bps], BACKGROUND_COLORS, BACKGROUND_COUNT, seed)
    vehicles = []
    for index in range(BACKGROUND_COUNT):
        primary = remaining[index]
        retries = retry_pool[index:index + 1]
        blueprint, color = assignments[index]
        vehicles.append({
            "slot": "background-{0:02d}".format(index), "kind": "background",
            "blueprint": blueprint, "color": color,
            "spawn_transform": transform_to_dict(primary),
            "retry_transforms": [transform_to_dict(item) for item in retries],
            "route": [],
            "tm": {"speed_difference": 0.0, "ignore_lights": 0.0, "distance_to_leading_vehicle": 2.0},
        })
    available_ids = sorted(bp.id for bp in vehicle_bps)
    probe_blueprint = "vehicle.tesla.model3" if "vehicle.tesla.model3" in available_ids else available_ids[0]
    vehicles.append({
        "slot": "probe", "kind": "probe", "blueprint": probe_blueprint,
        "color": "0,0,255", "spawn_transform": transform_to_dict(probe_spawn_transform),
        "retry_transforms": [transform_to_dict(probe_spawn)],
        "route": [_location_dict(waypoint.transform.location) for waypoint in route],
        "lead_in_points": len(lead_in),
        # Keep the probe on the planned lane; adherence is still measured.
        "tm": {
            "speed_difference": -20.0, "ignore_lights": 100.0,
            "distance_to_leading_vehicle": 1.0, "auto_lane_change": False,
        },
    })
    return {
        "seed": seed,
        "map": carla_map.name,
        "planned_background_vehicle_count": BACKGROUND_COUNT,
        "planned_probe_vehicle_count": PROBE_COUNT,
        "planned_controlled_vehicle_count": CONTROLLED_COUNT,
        "traffic_manager": {
            "port": 8000, "synchronous_mode": True,
            "fixed_delta_seconds": 0.1, "random_seed": seed,
        },
        "camera": {
            "transform": transform_to_dict(camera_transform),
            "width": 800, "height": 600, "fov": 90, "sensor_tick": 0.0,
            "effective_frame_period_seconds": 0.1,
        },
        "corridor": {
            "camera_visibility": visibility,
            "min_visible_fraction": MIN_CORRIDOR_VISIBLE_FRACTION,
            "rejected_occluded_camera_candidates": rejected_occluded,
            "heading_spread_degrees": round(_heading_spread_degrees(route), 3),
            "junction_free": not any(bool(getattr(waypoint, "is_junction", False)) for waypoint in route),
            "max_heading_spread_degrees": MAX_CORRIDOR_HEADING_SPREAD_DEGREES,
            "probe_route": [_location_dict(waypoint.transform.location) for waypoint in route],
            "observation_transform": transform_to_dict(observation),
        },
        "vehicles": vehicles,
    }


def _configure_tm(tm, actor, config):
    tm.vehicle_percentage_speed_difference(actor, float(config.get("speed_difference", 0.0)))
    tm.ignore_lights_percentage(actor, float(config.get("ignore_lights", 0.0)))
    tm.distance_to_leading_vehicle(actor, float(config.get("distance_to_leading_vehicle", 2.0)))
    if "auto_lane_change" in config:
        tm.auto_lane_change(actor, bool(config["auto_lane_change"]))


def spawn_planned_vehicles(carla_module, world, tm, planned_scene, tm_port):
    plans = planned_scene.get("vehicles", [])
    if len(plans) != CONTROLLED_COUNT:
        raise SceneBuildError("planned controlled vehicle count must be exactly 16")
    actors = []
    actual = {"vehicles": [], "controlled_vehicle_count": 0}
    library = world.get_blueprint_library()
    try:
        for plan in plans:
            blueprint = library.find(plan["blueprint"])
            if blueprint.has_attribute("color"):
                blueprint.set_attribute("color", plan["color"])
            if blueprint.has_attribute("role_name"):
                blueprint.set_attribute("role_name", "uropclaw_validation_{0}".format(plan["slot"]))
            actor = None
            selected = None
            attempt = 0
            transforms = [plan["spawn_transform"]] + list(plan.get("retry_transforms", []))
            for attempt, transform_value in enumerate(transforms, 1):
                selected = transform_from_dict(carla_module, transform_value)
                actor = world.try_spawn_actor(blueprint, selected)
                if actor is not None:
                    break
            if actor is None:
                raise SceneBuildError("failed to spawn {0} after {1} attempts".format(plan["slot"], len(transforms)))
            actors.append(actor)
            _configure_tm(tm, actor, plan.get("tm", {}))
            actor.set_autopilot(plan["kind"] == "background", tm_port)
            actual["vehicles"].append({
                "slot": plan["slot"], "kind": plan["kind"], "actor_id": int(actor.id),
                "blueprint": plan["blueprint"], "color": plan["color"],
                "spawn_attempt": attempt, "spawn_transform": transform_to_dict(selected),
                "route": copy.deepcopy(plan.get("route", [])), "tm": copy.deepcopy(plan.get("tm", {})),
            })
        actual["controlled_vehicle_count"] = len(actors)
        if len(actors) != CONTROLLED_COUNT:
            raise SceneBuildError("actual controlled vehicle count is not 16")
        return actors, actual
    except Exception:
        release_from_traffic_manager(actors, tm_port)
        cleanup_owned_actors(actors)
        raise


def start_probe(carla_module, probe_actor, probe_plan, tm, tm_port):
    # TM set_path in CARLA 0.9.13 steered the probe off-lane into static
    # geometry with 2 m route points; plain autopilot follows the planned lane.
    # Adherence is measured per frame (route_deviation_m) instead of assumed.
    probe_actor.set_autopilot(True, tm_port)


def route_deviation_m(location, route):
    """Distance from (x, y) to the nearest planned route segment.

    Returns None when the probe is before the corridor start or past its end,
    where distance to an endpoint is not a lane-adherence measurement.
    """
    best = None
    best_raw_t = None
    best_index = None
    x, y = location[0], location[1]
    segments = list(zip(route, route[1:]))
    for index, (left, right) in enumerate(segments):
        sx, sy = right["x"] - left["x"], right["y"] - left["y"]
        length = sx * sx + sy * sy
        raw_t = 0.0 if not length else ((x - left["x"]) * sx + (y - left["y"]) * sy) / length
        t = max(0.0, min(1.0, raw_t))
        px, py = left["x"] + t * sx, left["y"] + t * sy
        distance = math.hypot(x - px, y - py)
        if best is None or distance < best:
            best, best_raw_t, best_index = distance, raw_t, index
    if best is None:
        return None
    if (best_index == 0 and best_raw_t < 0.0) or (best_index == len(segments) - 1 and best_raw_t > 1.0):
        return None
    return best


@contextmanager
def synchronous_mode(world, tm, seed=42, fixed_delta_seconds=0.1):
    settings = world.get_settings()
    original = {
        "synchronous_mode": bool(settings.synchronous_mode),
        "fixed_delta_seconds": settings.fixed_delta_seconds,
        "no_rendering_mode": bool(settings.no_rendering_mode),
    }
    try:
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = fixed_delta_seconds
        world.apply_settings(settings)
        tm.set_synchronous_mode(True)
        tm.set_random_device_seed(seed)
        yield
    finally:
        try:
            tm.set_synchronous_mode(False)
        finally:
            restore = world.get_settings()
            restore.synchronous_mode = original["synchronous_mode"]
            restore.fixed_delta_seconds = original["fixed_delta_seconds"]
            restore.no_rendering_mode = original["no_rendering_mode"]
            world.apply_settings(restore)


def actor_locations(actors):
    return {
        int(actor.id): _location_dict(actor.get_transform().location)
        for actor in actors
    }


def movement_summary(before, after, minimum_distance=1.0):
    distances = {}
    for actor_id, start in before.items():
        end = after.get(actor_id, start)
        distances[actor_id] = math.sqrt(
            (end["x"] - start["x"]) ** 2
            + (end["y"] - start["y"]) ** 2
            + (end["z"] - start["z"]) ** 2
        )
    moving = sum(distance >= minimum_distance for distance in distances.values())
    total = len(distances)
    required = int(math.ceil(total * 0.8)) if total else 0
    return {
        "total_count": total, "moving_count": moving,
        "required_moving_count": required,
        "most_background_moving": bool(total and moving >= required),
        "distance_by_actor": {str(key): round(value, 3) for key, value in distances.items()},
    }


def release_from_traffic_manager(actors, tm_port):
    """Unregister vehicles from TM before destroy.

    TM keeps the same client-side actor proxy passed to ``set_autopilot``.
    Destroying that proxy while still registered makes TM's native thread
    call into a destroyed actor and abort the process.
    """
    released = []
    failed = []
    for actor in actors:
        if not hasattr(actor, "set_autopilot"):
            continue
        actor_id = int(getattr(actor, "id", -1))
        try:
            actor.set_autopilot(False, tm_port)
            released.append(actor_id)
        except Exception:
            failed.append(actor_id)
    return {"released_actor_ids": released, "failed_actor_ids": failed}


def cleanup_owned_actors(actors):
    failed = []
    skipped = []
    destroyed = 0
    attempted = 0
    seen = set()
    for actor in reversed(list(actors)):
        actor_id = int(getattr(actor, "id", -1))
        identity = id(actor)
        if identity in seen:
            skipped.append(actor_id)
            continue
        seen.add(identity)
        attempted += 1
        try:
            result = actor.destroy()
            if result is False:
                failed.append(actor_id)
            else:
                destroyed += 1
        except Exception:
            failed.append(actor_id)
    return {
        "attempted": attempted,
        "destroyed": destroyed,
        "failed_actor_ids": failed,
        "skipped_duplicate_actor_ids": skipped,
    }

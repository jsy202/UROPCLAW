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


def _camera_transform(carla_module, observation_transform):
    target = observation_transform.location
    yaw_radians = math.radians(observation_transform.rotation.yaw)
    right_x, right_y = -math.sin(yaw_radians), math.cos(yaw_radians)
    camera_location = carla_module.Location(
        x=target.x + right_x * 18.0,
        y=target.y + right_y * 18.0,
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
    for candidate in candidates:
        waypoint = carla_map.get_waypoint(candidate.location)
        candidate_route = _walk_route(waypoint)
        if len(candidate_route) == 41:
            route = candidate_route
            probe_spawn = candidate
            break
    if not route or probe_spawn is None:
        raise SceneBuildError("no deterministic 80 metre driving corridor found")

    observation = route[20].transform
    camera_transform = _camera_transform(carla_module, observation)
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
        "color": "0,0,255", "spawn_transform": transform_to_dict(probe_spawn),
        "retry_transforms": [transform_to_dict(probe_spawn)],
        "route": [_location_dict(waypoint.transform.location) for waypoint in route],
        "tm": {"speed_difference": -20.0, "ignore_lights": 100.0, "distance_to_leading_vehicle": 1.0},
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
            "width": 800, "height": 600, "fov": 90, "sensor_tick": 0.1,
        },
        "corridor": {
            "probe_route": [_location_dict(waypoint.transform.location) for waypoint in route],
            "observation_transform": transform_to_dict(observation),
        },
        "vehicles": vehicles,
    }


def _configure_tm(tm, actor, config):
    tm.vehicle_percentage_speed_difference(actor, float(config.get("speed_difference", 0.0)))
    tm.ignore_lights_percentage(actor, float(config.get("ignore_lights", 0.0)))
    tm.distance_to_leading_vehicle(actor, float(config.get("distance_to_leading_vehicle", 2.0)))


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
        cleanup_owned_actors(actors)
        raise


def start_probe(carla_module, probe_actor, probe_plan, tm, tm_port):
    probe_actor.set_autopilot(True, tm_port)
    locations = [
        carla_module.Location(x=item["x"], y=item["y"], z=item["z"])
        for item in probe_plan["route"]
    ]
    tm.set_path(probe_actor, locations)


@contextmanager
def synchronous_mode(world, tm, seed=42, fixed_delta_seconds=0.1):
    original = copy.copy(world.get_settings())
    updated = copy.copy(original)
    updated.synchronous_mode = True
    updated.fixed_delta_seconds = fixed_delta_seconds
    world.apply_settings(updated)
    tm.set_synchronous_mode(True)
    tm.set_random_device_seed(seed)
    try:
        yield
    finally:
        tm.set_synchronous_mode(False)
        world.apply_settings(original)


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


def cleanup_owned_actors(actors):
    failed = []
    destroyed = 0
    for actor in reversed(list(actors)):
        actor_id = int(getattr(actor, "id", -1))
        try:
            result = actor.destroy()
            alive = bool(getattr(actor, "is_alive", False))
            if result is False or alive:
                failed.append(actor_id)
            else:
                destroyed += 1
        except Exception:
            failed.append(actor_id)
    return {"attempted": len(actors), "destroyed": destroyed, "failed_actor_ids": failed}

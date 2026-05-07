import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import carla
import math
import logging
from core.envelope import VehicleObservation

log = logging.getLogger(__name__)


def _traffic_light_state(vehicle: carla.Vehicle) -> str:
    mapping = {
        carla.TrafficLightState.Green:  "green",
        carla.TrafficLightState.Red:    "red",
        carla.TrafficLightState.Yellow: "yellow",
    }
    return mapping.get(vehicle.get_traffic_light_state(), "unknown")


def _lane_available(world: carla.World, vehicle: carla.Vehicle, side: str) -> bool:
    wp = world.get_map().get_waypoint(vehicle.get_location(), project_to_road=True)
    if wp is None:
        return False
    neighbor = wp.get_left_lane() if side == "left" else wp.get_right_lane()
    return neighbor is not None and neighbor.lane_type == carla.LaneType.Driving


def read(
    world: carla.World,
    agent_id: str,
    vehicle: carla.Vehicle,
    capture_path: str | None = None,
) -> VehicleObservation:
    transform = vehicle.get_transform()
    velocity  = vehicle.get_velocity()
    speed_kmh = math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2) * 3.6

    loc = transform.location
    wp  = world.get_map().get_waypoint(loc, project_to_road=True)

    # 앞차 탐지 (같은 방향 50m 이내)
    heading = math.radians(transform.rotation.yaw)
    fwd_x, fwd_y = math.cos(heading), math.sin(heading)
    front_id, front_dist = None, 999.0
    lane_width = wp.lane_width if wp else 3.5

    for other in world.get_actors().filter("vehicle.*"):
        if other.id == vehicle.id:
            continue
        diff  = other.get_location() - loc
        dot   = diff.x * fwd_x + diff.y * fwd_y
        if dot <= 0:
            continue
        dist    = math.sqrt(diff.x**2 + diff.y**2)
        lateral = abs(-diff.x * fwd_y + diff.y * fwd_x)
        if dist < front_dist and dist < 50.0 and lateral < lane_width * 0.6:
            front_dist = dist
            front_id   = str(other.id)

    return VehicleObservation(
        vehicle_id=agent_id,
        speed_kmh=round(speed_kmh, 2),
        position={"x": round(loc.x, 2), "y": round(loc.y, 2), "z": round(loc.z, 2)},
        heading_deg=round(transform.rotation.yaw, 2),
        lane_id=wp.lane_id if wp else 0,
        lane_width=round(lane_width, 2),
        front_vehicle_id=front_id,
        front_vehicle_dist_m=round(front_dist, 2),
        left_lane_available=_lane_available(world, vehicle, "left"),
        right_lane_available=_lane_available(world, vehicle, "right"),
        traffic_light_state=_traffic_light_state(vehicle),
        capture_path=capture_path,
    )

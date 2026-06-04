import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "validation" / "carla_e2e" / "multivehicle" / "scene.py"


def load_module():
    spec = importlib.util.spec_from_file_location("multivehicle_scene", str(MODULE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Location:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z


class Rotation:
    def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
        self.pitch, self.yaw, self.roll = pitch, yaw, roll


class Transform:
    def __init__(self, location=None, rotation=None):
        self.location = location or Location()
        self.rotation = rotation or Rotation()


class Carla:
    Location = Location
    Rotation = Rotation
    Transform = Transform


class Attribute:
    def __init__(self, value):
        self.value = value

    def as_int(self):
        return int(self.value)


class Blueprint:
    def __init__(self, identifier):
        self.id = identifier
        self.values = {"number_of_wheels": "4", "color": "", "role_name": ""}

    def has_attribute(self, name):
        return name in self.values

    def get_attribute(self, name):
        return Attribute(self.values[name])

    def set_attribute(self, name, value):
        self.values[name] = value


class Library:
    def __init__(self):
        self.blueprints = {"vehicle.test.{0}".format(i): Blueprint("vehicle.test.{0}".format(i)) for i in range(4)}

    def filter(self, pattern):
        return list(self.blueprints.values())

    def find(self, identifier):
        return self.blueprints[identifier]


class Actor:
    next_id = 100

    def __init__(self, transform):
        self.id = Actor.next_id
        Actor.next_id += 1
        self._transform = transform
        self.is_alive = True
        self.autopilot = []
        self.destroy_calls = 0

    def set_autopilot(self, enabled, port):
        self.autopilot.append((enabled, port))

    def get_transform(self):
        return self._transform

    def destroy(self):
        self.destroy_calls += 1
        if self.destroy_calls > 1:
            raise RuntimeError("double destroy")
        self.is_alive = False
        return True


class Settings:
    def __init__(self, synchronous_mode=False, fixed_delta_seconds=None, no_rendering_mode=False):
        self.synchronous_mode = synchronous_mode
        self.fixed_delta_seconds = fixed_delta_seconds
        self.no_rendering_mode = no_rendering_mode


class NonCopyableSettings(Settings):
    def __reduce_ex__(self, protocol):
        raise RuntimeError('Pickling of "carla.libcarla.WorldSettings" instances is not enabled')


class World:
    def __init__(self, failure_slots=None, settings=None):
        self.library = Library()
        self.settings = settings or Settings(False, None)
        self.applied = []
        self.failure_slots = set(failure_slots or [])
        self.spawn_calls = 0

    def get_blueprint_library(self):
        return self.library

    def try_spawn_actor(self, blueprint, transform):
        call = self.spawn_calls
        self.spawn_calls += 1
        if call in self.failure_slots:
            return None
        return Actor(transform)

    def get_settings(self):
        return self.settings

    def apply_settings(self, settings):
        self.settings = settings
        self.applied.append((settings.synchronous_mode, settings.fixed_delta_seconds))


class TrafficManager:
    def __init__(self):
        self.sync = []
        self.seed = []
        self.paths = []

    def set_synchronous_mode(self, value):
        self.sync.append(value)

    def set_random_device_seed(self, value):
        self.seed.append(value)

    def vehicle_percentage_speed_difference(self, actor, value):
        pass

    def ignore_lights_percentage(self, actor, value):
        pass

    def distance_to_leading_vehicle(self, actor, value):
        pass

    def set_path(self, actor, locations):
        self.paths.append((actor.id, locations))

    def auto_lane_change(self, actor, value):
        pass


def transform_dict(x):
    return {"location": {"x": float(x), "y": 0.0, "z": 0.5}, "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}}


def planned_scene(count=16):
    vehicles = []
    for index in range(count):
        kind = "probe" if index == count - 1 else "background"
        vehicles.append({
            "slot": "probe" if kind == "probe" else "background-{0:02d}".format(index),
            "kind": kind,
            "blueprint": "vehicle.test.{0}".format(index % 4),
            "color": "0,0,255" if kind == "probe" else "10,10,10",
            "spawn_transform": transform_dict(index),
            "retry_transforms": [transform_dict(index + 100)],
            "route": [{"x": float(index), "y": 0.0, "z": 0.5}, {"x": float(index + 20), "y": 0.0, "z": 0.5}],
            "tm": {"speed_difference": -20.0, "ignore_lights": 100.0, "distance_to_leading_vehicle": 2.0},
        })
    return {"seed": 42, "traffic_manager": {"port": 8000}, "vehicles": vehicles}


def test_deterministic_vehicle_choice_is_reproducible_and_varied():
    module = load_module()
    blueprint_ids = ["vehicle.test.{0}".format(i) for i in range(8)]
    colors = ["255,0,0", "255,255,255", "10,10,10"]

    first = module.deterministic_assignments(blueprint_ids, colors, 15, 42)
    second = module.deterministic_assignments(list(reversed(blueprint_ids)), list(reversed(colors)), 15, 42)

    assert first == second
    assert len(set(item[0] for item in first)) > 1
    assert len(set(item[1] for item in first)) > 1


def test_spawn_requires_all_sixteen_and_records_actual_scene():
    module = load_module()
    world = World()
    tm = TrafficManager()

    actors, actual = module.spawn_planned_vehicles(Carla, world, tm, planned_scene(), 8000)

    assert len(actors) == 16
    assert len(actual["vehicles"]) == 16
    assert actual["controlled_vehicle_count"] == 16
    assert actual["vehicles"][-1]["slot"] == "probe"
    assert actors[-1].autopilot[-1] == (False, 8000)


def test_spawn_uses_bounded_retry_but_never_silently_reduces_actor_count():
    module = load_module()
    retry_world = World(failure_slots={0})
    actors, actual = module.spawn_planned_vehicles(Carla, retry_world, TrafficManager(), planned_scene(), 8000)
    assert len(actors) == 16
    assert actual["vehicles"][0]["spawn_attempt"] == 2

    failing_world = World(failure_slots={0, 1})
    with pytest.raises(module.SceneBuildError, match="background-00"):
        module.spawn_planned_vehicles(Carla, failing_world, TrafficManager(), planned_scene(), 8000)


def test_synchronous_mode_restores_world_and_disables_tm_on_exit():
    module = load_module()
    world = World()
    tm = TrafficManager()

    with module.synchronous_mode(world, tm, seed=42, fixed_delta_seconds=0.1):
        assert world.settings.synchronous_mode is True
        assert world.settings.fixed_delta_seconds == 0.1
        assert tm.seed == [42]

    assert world.settings.synchronous_mode is False
    assert world.settings.fixed_delta_seconds is None
    assert tm.sync == [True, False]


def test_synchronous_mode_does_not_copy_world_settings_and_restores_after_exception():
    module = load_module()
    settings = NonCopyableSettings(
        synchronous_mode=False,
        fixed_delta_seconds=0.05,
        no_rendering_mode=True,
    )
    world = World(settings=settings)
    tm = TrafficManager()

    with pytest.raises(ValueError, match="injected body failure"):
        with module.synchronous_mode(world, tm, seed=42, fixed_delta_seconds=0.1):
            assert world.settings is settings
            assert world.settings.synchronous_mode is True
            assert world.settings.fixed_delta_seconds == 0.1
            assert world.settings.no_rendering_mode is True
            raise ValueError("injected body failure")

    assert world.settings is settings
    assert world.settings.synchronous_mode is False
    assert world.settings.fixed_delta_seconds == 0.05
    assert world.settings.no_rendering_mode is True
    assert tm.sync == [True, False]


def test_cleanup_destroys_only_owned_actors_and_reports_result():
    module = load_module()
    owned = [Actor(Transform()), Actor(Transform())]
    uncontrolled = Actor(Transform())

    result = module.cleanup_owned_actors(owned)

    assert result == {
        "attempted": 2, "destroyed": 2, "failed_actor_ids": [],
        "skipped_duplicate_actor_ids": [],
    }
    assert all(not actor.is_alive for actor in owned)
    assert uncontrolled.is_alive


def test_cleanup_deduplicates_actor_handles_and_never_reads_after_destroy():
    module = load_module()
    actor = Actor(Transform())

    result = module.cleanup_owned_actors([actor, actor])

    assert actor.destroy_calls == 1
    assert result["attempted"] == 1
    assert result["destroyed"] == 1
    assert result["skipped_duplicate_actor_ids"] == [actor.id]


def test_movement_summary_requires_twelve_of_fifteen_backgrounds():
    module = load_module()
    before = {index: {"x": 0.0, "y": 0.0, "z": 0.0} for index in range(15)}
    after = {index: {"x": 2.0 if index < 12 else 0.5, "y": 0.0, "z": 0.0} for index in range(15)}

    summary = module.movement_summary(before, after, minimum_distance=1.0)

    assert summary["moving_count"] == 12
    assert summary["total_count"] == 15
    assert summary["most_background_moving"] is True


def test_project_point_centre_and_behind_camera():
    module = load_module()
    camera = Transform(Location(0.0, 0.0, 0.0), Rotation(0.0, 0.0, 0.0))
    assert module.project_point(camera, Location(10.0, 0.0, 0.0)) == (400.0, 300.0)
    right = module.project_point(camera, Location(10.0, 5.0, 0.0))
    assert right[0] > 400.0
    assert module.project_point(camera, Location(-10.0, 0.0, 0.0)) is None


def test_footprint_outside_horizontal_fov_is_not_in_image():
    module = load_module()
    camera = Transform(Location(0.0, 0.0, 0.0), Rotation(0.0, 0.0, 0.0))
    assert module.footprint_in_image(Carla, camera, Location(20.0, 0.0, 0.0)) is True
    assert module.footprint_in_image(Carla, camera, Location(10.0, 40.0, 0.0)) is False


def test_route_deviation_measures_distance_to_nearest_segment():
    module = load_module()
    route = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 10.0, "y": 10.0}]
    assert module.route_deviation_m([5.0, 2.0], route) == 2.0
    assert module.route_deviation_m([12.0, 5.0], route) == 2.0


def test_ray_clear_ignores_endpoint_hits_but_rejects_occluders():
    module = load_module()

    class Hit:
        def __init__(self, location):
            self.location = location

    class RayWorld:
        def __init__(self, hits):
            self.hits = hits

        def cast_ray(self, start, end):
            return self.hits

    end = Location(10.0, 0.0, 1.0)
    assert module._ray_clear(RayWorld([Hit(Location(10.0, 0.0, 0.0))]), Location(), end) is True
    assert module._ray_clear(RayWorld([Hit(Location(5.0, 0.0, 1.0))]), Location(), end) is False


def test_route_deviation_is_not_measured_outside_corridor_extent():
    module = load_module()
    route = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 20.0, "y": 0.0}]
    assert module.route_deviation_m([25.0, 3.0], route) is None
    assert module.route_deviation_m([-5.0, 0.0], route) is None
    assert module.route_deviation_m([15.0, 3.0], route) == 3.0

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "validation" / "carla_e2e" / "multivehicle" / "run_host_smoke.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("multivehicle_run_host_smoke", str(RUNNER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_defaults_are_the_approved_smoke_contract():
    runner = load_runner()
    args = runner.parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 2000
    assert args.tm_port == 8000
    assert args.seed == 42
    assert args.background_vehicles == 15
    assert args.probe_vehicles == 1
    assert args.pre_roll_seconds == 5.0
    assert args.frames == 100
    assert args.width == 800
    assert args.height == 600
    assert args.fov == 90.0
    assert not hasattr(args, "repetitions")


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--frames", "99"], "100 frames"),
        (["--background-vehicles", "14"], "15 background"),
        (["--probe-vehicles", "2"], "one probe"),
        (["--seed", "7"], "seed 42"),
    ],
)
def test_smoke_contract_rejects_silent_scope_reduction(argv, message):
    runner = load_runner()
    with pytest.raises(ValueError, match=message):
        runner.validate_args(runner.parse_args(argv))


def test_carla_version_gate_requires_exact_0913_pair():
    runner = load_runner()
    runner.validate_carla_versions("0.9.13", "0.9.13")
    with pytest.raises(RuntimeError, match="client/server version mismatch"):
        runner.validate_carla_versions("0.9.13", "0.9.15")


def test_target_manifest_creation_also_verifies_non_target_colour_only_parity():
    runner = load_runner()
    planned = {
        "seed": 42, "camera": {"width": 800, "height": 600, "fov": 90},
        "vehicles": [
            {"slot": "background-00", "kind": "background", "blueprint": "vehicle.a", "color": "10,10,10", "spawn_transform": {}, "route": [], "tm": {}},
            {"slot": "probe", "kind": "probe", "blueprint": "vehicle.b", "color": "0,0,255", "spawn_transform": {}, "route": [], "tm": {}},
        ],
    }
    target, non_target = runner.make_manifest_pair(planned)
    assert target["planned_scene"]["vehicles"][-1]["color"] == "0,0,255"
    assert non_target["planned_scene"]["vehicles"][-1]["color"] == "255,0,0"
    assert target["parity_validation"]["status"] == "PASS"
    assert non_target["actual_spawned_scene"] == {"vehicles": []}


def test_failure_evidence_is_atomic_and_never_claims_pass(tmp_path):
    runner = load_runner()
    error = RuntimeError("spawned 15/16")

    runner.write_failure_evidence(tmp_path, error, {"phase": "spawn"})

    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "FAIL"
    assert result["error"] == "RuntimeError: spawned 15/16"
    assert result["phase"] == "spawn"
    assert not (tmp_path / "result.json.tmp").exists()


class SensorImage:
    def __init__(self, frame):
        self.frame = frame


class Sensor:
    def __init__(self):
        self.callback = None
        self.events = []

    def listen(self, callback):
        self.callback = callback
        self.events.append("listen")

    def emit(self, frame):
        self.callback(SensorImage(frame))

    def stop(self):
        self.events.append("stop")


class TickWorld:
    def __init__(self, sensor, emissions):
        self.sensor = sensor
        self.emissions = list(emissions)
        self.ticks = []

    def tick(self, timeout):
        frame_id, emit = self.emissions.pop(0)
        self.ticks.append(frame_id)
        if emit:
            self.sensor.emit(frame_id)
        return frame_id


def test_camera_readiness_keeps_ticking_when_first_sensor_frame_is_not_ready():
    runner = load_runner()
    sensor = Sensor()
    stream = runner.SynchronousSensorStream(sensor)
    stream.start()
    world = TickWorld(sensor, [(100, False), (101, True)])

    expected, image = stream.wait_until_ready(
        world, tick_timeout=1.0, sensor_timeout=0.001, max_ticks=3
    )

    assert world.ticks == [100, 101]
    assert expected == 101
    assert image.frame == 101
    assert stream.timeout_evidence[0]["expected_frame"] == 100
    assert stream.timeout_evidence[0]["received_frames"] == []


def test_tick_and_wait_discards_stale_sensor_frames_and_matches_tick_frame():
    runner = load_runner()
    sensor = Sensor()
    stream = runner.SynchronousSensorStream(sensor)
    stream.start()
    sensor.emit(199)
    world = TickWorld(sensor, [(200, True)])

    expected, image = stream.tick_and_wait(world, 1.0, 0.01)

    assert expected == 200
    assert image.frame == 200
    assert stream.stale_frames == [199]


def test_camera_timeout_records_expected_and_received_frame_ids():
    runner = load_runner()
    sensor = Sensor()
    stream = runner.SynchronousSensorStream(sensor)
    stream.start()
    world = TickWorld(sensor, [(300, False)])

    with pytest.raises(runner.SensorFrameTimeout) as caught:
        stream.tick_and_wait(world, 1.0, 0.001)

    assert caught.value.expected_frame == 300
    assert caught.value.received_frames == []


def test_camera_shutdown_disables_callback_before_sensor_stop():
    runner = load_runner()
    sensor = Sensor()
    stream = runner.SynchronousSensorStream(sensor)
    stream.start()
    stream.close()
    sensor.emit(400)
    runner.stop_camera_stream(stream, sensor)

    assert stream.received_frames == []
    assert sensor.events == ["listen", "stop"]


def test_sensor_timeout_cleanup_stops_camera_before_destroying_owned_actors():
    runner = load_runner()
    events = []

    class OrderedSensor(Sensor):
        id = 2

        def stop(self):
            events.append("camera_stop")

        def destroy(self):
            events.append("camera_destroy")
            return True

    class OrderedVehicle:
        id = 1

        def destroy(self):
            events.append("vehicle_destroy")
            return True

    camera = OrderedSensor()
    vehicle = OrderedVehicle()
    stream = runner.SynchronousSensorStream(camera)
    stream.start()
    world = TickWorld(camera, [(500, False)])

    with pytest.raises(runner.SensorFrameTimeout):
        try:
            stream.tick_and_wait(world, 1.0, 0.001)
        finally:
            result = runner.shutdown_scene_resources(stream, camera, [vehicle, camera])

    assert result["destroyed"] == 2
    assert events == ["camera_stop", "camera_destroy", "vehicle_destroy"]

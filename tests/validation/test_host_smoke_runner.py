import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "validation" / "carla_e2e" / "run_host_smoke.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("run_host_smoke", str(RUNNER_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeFrame:
    def __init__(self, frame_id):
        self.frame = frame_id
        self.width = 800
        self.height = 600
        self.timestamp = frame_id / 10.0

    def save_to_disk(self, path):
        Path(path).write_bytes(b"fake-png")


class FakeSensor:
    def __init__(self):
        self.stopped = False
        self.destroyed = False

    def listen(self, callback):
        for frame_id in range(1, 11):
            callback(FakeFrame(frame_id))

    def stop(self):
        self.stopped = True

    def destroy(self):
        self.destroyed = True


class FakeBlueprint:
    id = "sensor.camera.rgb"

    def __init__(self):
        self.attributes = {}

    def set_attribute(self, name, value):
        self.attributes[name] = value


class FakeBlueprintLibrary:
    def __init__(self):
        self.blueprint = FakeBlueprint()

    def find(self, blueprint_id):
        assert blueprint_id == "sensor.camera.rgb"
        return self.blueprint


class FakeMap:
    name = "Carla/Maps/Town03"


class FakeSpectator:
    def get_transform(self):
        return "spectator-transform"


class FakeSettings:
    synchronous_mode = False


class FakeWorld:
    def __init__(self, sensor):
        self.sensor = sensor
        self.blueprints = FakeBlueprintLibrary()

    def get_map(self):
        return FakeMap()

    def get_spectator(self):
        return FakeSpectator()

    def get_blueprint_library(self):
        return self.blueprints

    def get_settings(self):
        return FakeSettings()

    def spawn_actor(self, blueprint, transform):
        assert blueprint is self.blueprints.blueprint
        assert transform == "spectator-transform"
        return self.sensor


class FakeClient:
    def __init__(self, world):
        self.world = world
        self.timeout = None

    def set_timeout(self, timeout):
        self.timeout = timeout

    def get_client_version(self):
        return "0.9.13"

    def get_server_version(self):
        return "0.9.13"

    def get_world(self):
        return self.world


class FakeCarla:
    def __init__(self):
        self.sensor = FakeSensor()
        self.client = FakeClient(FakeWorld(self.sensor))

    def Client(self, host, port):
        assert (host, port) == ("127.0.0.1", 2000)
        return self.client


def test_success_writes_evidence_and_destroys_sensor(tmp_path):
    runner = load_runner()
    fake_carla = FakeCarla()

    exit_code = runner.run_smoke(
        carla_module=fake_carla,
        evidence_dir=tmp_path,
        host="127.0.0.1",
        port=2000,
        timeout_seconds=2.0,
        requested_frames=10,
    )

    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert result["status"] == "PASS"
    assert result["client_version"] == result["server_version"] == "0.9.13"
    assert result["map_name"] == "Carla/Maps/Town03"
    assert result["frames_received"] == 10
    assert result["frames"][0] == {
        "frame_id": 1,
        "height": 600,
        "timestamp": 0.1,
        "width": 800,
    }
    assert result["frame_evidence_saved"] is True
    assert (tmp_path / "frame.png").read_bytes() == b"fake-png"
    assert (tmp_path / "run.log").is_file()
    assert fake_carla.sensor.stopped is True
    assert fake_carla.sensor.destroyed is True


def test_connection_failure_still_writes_result_and_log(tmp_path):
    runner = load_runner()

    class FailingCarla:
        @staticmethod
        def Client(host, port):
            raise RuntimeError("simulator unavailable")

    exit_code = runner.run_smoke(
        carla_module=FailingCarla(),
        evidence_dir=tmp_path,
        host="127.0.0.1",
        port=2000,
        timeout_seconds=2.0,
        requested_frames=10,
    )

    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert result["error"]["type"] == "RuntimeError"
    assert result["error"]["message"] == "simulator unavailable"
    assert "RuntimeError: simulator unavailable" in result["error"]["traceback"]
    assert (tmp_path / "run.log").is_file()

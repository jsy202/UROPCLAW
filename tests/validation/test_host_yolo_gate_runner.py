import csv
import importlib.util
import json
from pathlib import Path

import numpy as np

from test_host_yolo_smoke_runner import (
    FakeBox,
    FakeCv2,
    FakeResult,
    FakeTorch,
    FakeTorchvision,
    FakeUltralytics,
)


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "validation" / "carla_e2e" / "run_host_yolo_gate.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("run_host_yolo_gate", str(RUNNER_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SequenceImage:
    width = 800
    height = 600

    def __init__(self, frame_id):
        self.frame = frame_id
        self.timestamp = frame_id / 10.0
        bgra = np.zeros((self.height, self.width, 4), dtype=np.uint8)
        bgra[:, :, 0] = 200
        bgra[:, :, 3] = 255
        self.raw_data = bgra.tobytes()


class SequenceSensor:
    def __init__(self, frame_count):
        self.frame_count = frame_count
        self.stopped = False
        self.destroyed = False

    def listen(self, callback):
        for frame_id in range(1, self.frame_count + 1):
            callback(SequenceImage(frame_id))

    def stop(self):
        self.stopped = True

    def destroy(self):
        self.destroyed = True


class FakeAttribute:
    recommended_values = ["0,0,255"]


class GateBlueprint:
    def __init__(self, blueprint_id):
        self.id = blueprint_id
        self.attributes = {}

    def has_attribute(self, name):
        return name in {"color", "role_name"}

    def get_attribute(self, name):
        return FakeAttribute()

    def set_attribute(self, name, value):
        self.attributes[name] = value


class GateBlueprintLibrary:
    def __init__(self):
        self.camera = GateBlueprint("sensor.camera.rgb")
        self.vehicle = GateBlueprint("vehicle.tesla.model3")

    def find(self, blueprint_id):
        if blueprint_id == "sensor.camera.rgb":
            return self.camera
        if blueprint_id == "vehicle.tesla.model3":
            return self.vehicle
        raise KeyError(blueprint_id)


class FakeLocation:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z


class FakeRotation:
    def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
        self.pitch = pitch
        self.yaw = yaw
        self.roll = roll


class FakeVector:
    def __init__(self, x=1.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z


class FakeTransform:
    def __init__(self, location=None, rotation=None):
        self.location = location or FakeLocation(10.0, 20.0, 0.5)
        self.rotation = rotation or FakeRotation(yaw=90.0)

    @staticmethod
    def get_forward_vector():
        return FakeVector(0.0, 1.0, 0.0)


class GateMap:
    name = "Carla/Maps/Town10HD_Opt"

    @staticmethod
    def get_spawn_points():
        return [FakeTransform()]


class FakeVehicle:
    type_id = "vehicle.tesla.model3"

    def __init__(self, transform):
        self.transform = transform
        self.physics_values = []
        self.destroyed = False

    def set_simulate_physics(self, value):
        self.physics_values.append(value)

    def destroy(self):
        self.destroyed = True


class GateWorld:
    def __init__(self, sensor):
        self.sensor = sensor
        self.blueprints = GateBlueprintLibrary()
        self.vehicle = None
        self.camera_transform = None

    @staticmethod
    def get_map():
        return GateMap()

    def get_blueprint_library(self):
        return self.blueprints

    def try_spawn_actor(self, blueprint, transform):
        assert blueprint is self.blueprints.vehicle
        self.vehicle = FakeVehicle(transform)
        return self.vehicle

    def spawn_actor(self, blueprint, transform):
        assert blueprint is self.blueprints.camera
        self.camera_transform = transform
        return self.sensor


class GateClient:
    def __init__(self, world):
        self.world = world

    @staticmethod
    def get_client_version():
        return "0.9.13"

    @staticmethod
    def get_server_version():
        return "0.9.13"

    def set_timeout(self, timeout):
        self.timeout = timeout

    def get_world(self):
        return self.world


class GateCarla:
    __version__ = "0.9.13"
    Location = FakeLocation
    Rotation = FakeRotation
    Transform = FakeTransform

    def __init__(self, frame_count):
        self.sensor = SequenceSensor(frame_count)
        self.world = GateWorld(self.sensor)
        self.client = GateClient(self.world)

    def Client(self, host, port):
        assert (host, port) == ("127.0.0.1", 2000)
        return self.client


class FakeParameter:
    device = "cuda:0"


class FakeInnerModel:
    @staticmethod
    def parameters():
        return iter([FakeParameter()])


class GateModel:
    def __init__(self, positive=True):
        self.model = FakeInnerModel()
        self.positive = positive
        self.calls = 0

    def __call__(self, frame, **kwargs):
        self.calls += 1
        result = FakeResult()
        if not self.positive:
            result.boxes = [FakeBox(0, 0.88, [1.0, 1.0, 3.0, 2.0])]
        return [result]


def run_gate(tmp_path, positive=True):
    runner = load_runner()
    warmup_count = 5
    steady_count = 50
    fake_carla = GateCarla(warmup_count + steady_count)
    fake_torch = FakeTorch()
    fake_model = GateModel(positive=positive)
    factory_calls = []
    weight_path = tmp_path / "yolov8s.pt"
    weight_path.write_bytes(b"post-project-weight")

    def factory(path):
        factory_calls.append(path)
        return fake_model

    exit_code = runner.run_gate(
        carla_module=fake_carla,
        torch_module=fake_torch,
        torchvision_module=FakeTorchvision(),
        ultralytics_module=FakeUltralytics(),
        cv2_module=FakeCv2(),
        numpy_module=np,
        yolo_factory=factory,
        weight_path=weight_path,
        weight_source=runner.POST_PROJECT_WEIGHT_SOURCE,
        evidence_dir=tmp_path / "evidence",
        host="127.0.0.1",
        port=2000,
        timeout_seconds=2.0,
        warmup_count=warmup_count,
        steady_count=steady_count,
    )
    return runner, exit_code, fake_carla, fake_torch, fake_model, factory_calls


def test_gate_separates_warmup_and_steady_samples_and_proves_positive_contract(tmp_path):
    runner, exit_code, fake_carla, fake_torch, fake_model, factory_calls = run_gate(tmp_path)
    evidence = tmp_path / "evidence"
    result = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
    warmup = json.loads((evidence / "warmup_latencies_ms.json").read_text(encoding="utf-8"))
    steady = json.loads((evidence / "steady_state_latencies_ms.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((evidence / "latency_samples.csv").open(encoding="utf-8")))

    assert exit_code == 0
    assert result["status"] == "PASS"
    assert result["model_load_count"] == 1
    assert result["warmup_sample_count"] == 5
    assert result["steady_state_sample_count"] == 50
    assert result["unique_frame_count"] == 55
    assert len(warmup) == 5
    assert len(steady) == 50
    assert len(rows) == 55
    assert len({row["frame_id"] for row in rows}) == 55
    assert [row["phase"] for row in rows[:5]] == ["warmup"] * 5
    assert [row["phase"] for row in rows[5:]] == ["steady_state"] * 50
    assert result["steady_state_latency_ms"]["sample_count"] == 50
    assert set(result["steady_state_latency_ms"]) == {"sample_count", "mean", "p50", "p95", "max"}
    assert result["cuda_synchronized_per_inference"] is True
    assert result["positive_detection_count"] == 55
    assert result["positive_frame_count"] == 55
    assert result["detected_vehicle_classes"] == ["car"]
    assert result["pipeline_detection_contract_compatible"] is True
    assert result["positive_detection"]["class_name"] == "car"
    assert len(result["positive_detection"]["bbox"]) == 4
    assert (evidence / "input_frame.png").is_file()
    assert (evidence / "annotated_frame.png").is_file()

    assert len(factory_calls) == 1
    assert fake_model.calls == 55
    assert fake_torch.cuda.synchronize_calls == 110
    assert fake_carla.sensor.stopped is True
    assert fake_carla.sensor.destroyed is True
    assert fake_carla.world.vehicle.physics_values == [False]
    assert fake_carla.world.vehicle.destroyed is True
    assert fake_carla.world.camera_transform.location.x == 10.0
    assert fake_carla.world.camera_transform.location.y == 28.0
    assert fake_carla.world.camera_transform.rotation.yaw == 270.0


def test_gate_fails_when_only_non_vehicle_boxes_are_returned(tmp_path):
    _, exit_code, _, _, _, _ = run_gate(tmp_path, positive=False)
    evidence = tmp_path / "evidence"
    result = json.loads((evidence / "result.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert result["steady_state_sample_count"] == 50
    assert result["raw_box_count"] == 55
    assert result["positive_detection_count"] == 0
    assert result["positive_frame_count"] == 0
    assert result["pipeline_detection_contract_compatible"] is True
    assert (evidence / "annotated_frame.png").is_file()


def test_latency_summary_uses_linear_percentiles_without_warmup_samples():
    runner = load_runner()
    summary = runner.summarize_latencies([10.0, 20.0, 30.0, 40.0, 50.0], np)
    assert summary == {
        "sample_count": 5,
        "mean": 30.0,
        "p50": 30.0,
        "p95": 48.0,
        "max": 50.0,
    }

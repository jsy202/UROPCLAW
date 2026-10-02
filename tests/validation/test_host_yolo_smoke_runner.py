import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "validation" / "carla_e2e" / "run_host_yolo_smoke.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("run_host_yolo_smoke", str(RUNNER_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeImage:
    frame = 321
    width = 4
    height = 3
    timestamp = 12.5

    def __init__(self):
        bgra = np.zeros((self.height, self.width, 4), dtype=np.uint8)
        bgra[:, :, 0] = 10
        bgra[:, :, 1] = 20
        bgra[:, :, 2] = 30
        bgra[:, :, 3] = 255
        self.raw_data = bgra.tobytes()


class FakeSensor:
    def __init__(self):
        self.stopped = False
        self.destroyed = False

    def listen(self, callback):
        callback(FakeImage())

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
    name = "Carla/Maps/Town10HD_Opt"


class FakeSpectator:
    def get_transform(self):
        return "spectator-transform"


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
    __version__ = "0.9.13"

    def __init__(self):
        self.sensor = FakeSensor()
        self.client = FakeClient(FakeWorld(self.sensor))

    def Client(self, host, port):
        assert (host, port) == ("127.0.0.1", 2000)
        return self.client


class FakeCuda:
    def __init__(self, available=True):
        self.available = available
        self.synchronize_calls = 0

    def is_available(self):
        return self.available

    def get_device_name(self, index):
        assert index == 0
        return "NVIDIA GeForce RTX 3060"

    def synchronize(self):
        self.synchronize_calls += 1


class FakeTorchVersion:
    cuda = "11.7"


class FakeTorch:
    __version__ = "1.13.1+cu117"
    version = FakeTorchVersion()

    def __init__(self, cuda_available=True):
        self.cuda = FakeCuda(cuda_available)


class FakeTorchvision:
    __version__ = "0.14.1+cu117"


class FakeCv2:
    __version__ = "4.8.1"

    @staticmethod
    def imwrite(path, image):
        assert image.shape[2] == 3
        Path(path).write_bytes(b"fake-png")
        return True


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, index):
        value = self.values[index]
        if isinstance(value, list):
            return FakeTensor(value)
        return value

    def tolist(self):
        return list(self.values)


class FakeBox:
    def __init__(self, class_id, confidence, bbox):
        self.cls = FakeTensor([class_id])
        self.conf = FakeTensor([confidence])
        self.xyxy = FakeTensor([bbox])


class FakeResult:
    def __init__(self):
        self.boxes = [
            FakeBox(2, 0.91, [1.0, 1.0, 3.0, 2.0]),
            FakeBox(0, 0.88, [0.0, 0.0, 1.0, 2.0]),
        ]

    @staticmethod
    def plot():
        return np.zeros((3, 4, 3), dtype=np.uint8)


class FakeParameter:
    device = "cuda:0"


class FakeInnerModel:
    @staticmethod
    def parameters():
        return iter([FakeParameter()])


class FakeModel:
    def __init__(self):
        self.model = FakeInnerModel()
        self.calls = []

    def __call__(self, frame, **kwargs):
        self.calls.append((frame.copy(), kwargs))
        return [FakeResult()]


class FakeUltralytics:
    __version__ = "8.0.145"


def test_real_yolo_contract_smoke_writes_complete_evidence(tmp_path):
    runner = load_runner()
    fake_carla = FakeCarla()
    fake_torch = FakeTorch()
    fake_model = FakeModel()
    weight_path = tmp_path / "yolov8s.pt"
    weight_path.write_bytes(b"post-project-weight")

    exit_code = runner.run_yolo_smoke(
        carla_module=fake_carla,
        torch_module=fake_torch,
        torchvision_module=FakeTorchvision(),
        ultralytics_module=FakeUltralytics(),
        cv2_module=FakeCv2(),
        numpy_module=np,
        yolo_factory=lambda path: fake_model,
        weight_path=weight_path,
        weight_source=runner.POST_PROJECT_WEIGHT_SOURCE,
        evidence_dir=tmp_path / "evidence",
        host="127.0.0.1",
        port=2000,
        timeout_seconds=2.0,
    )

    evidence = tmp_path / "evidence"
    environment = json.loads((evidence / "environment.json").read_text(encoding="utf-8"))
    result = json.loads((evidence / "result.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert result["status"] == "PASS"
    assert result["actual_carla_frame"] is True
    assert result["frame"] == {
        "frame_id": 321,
        "height": 3,
        "shape_bgr": [3, 4, 3],
        "timestamp": 12.5,
        "width": 4,
    }
    assert result["raw_model_boxes"] == 2
    assert result["vehicle_detections"] == 1
    assert result["detections"] == [{
        "bbox": [1, 1, 3, 2],
        "class_id": 2,
        "class_name": "car",
        "confidence": 0.91,
    }]
    assert result["pipeline_detection_contract_compatible"] is True
    assert result["inference_device"] == "cuda:0"
    assert result["model_loaded"] is True
    assert result["inference_succeeded"] is True
    assert (evidence / "input_frame.png").read_bytes() == b"fake-png"
    assert (evidence / "annotated_frame.png").read_bytes() == b"fake-png"
    assert (evidence / "run.log").is_file()

    assert environment["client_version"] == environment["server_version"] == "0.9.13"
    assert environment["torch_version"] == "1.13.1+cu117"
    assert environment["torchvision_version"] == "0.14.1+cu117"
    assert environment["torch_cuda_version"] == "11.7"
    assert environment["cuda_available"] is True
    assert environment["gpu_name"] == "NVIDIA GeForce RTX 3060"
    assert environment["ultralytics_version"] == "8.0.145"
    assert environment["opencv_version"] == "4.8.1"
    assert environment["weight_sha256"] == hashlib.sha256(b"post-project-weight").hexdigest()
    assert environment["weight_source"] == runner.POST_PROJECT_WEIGHT_SOURCE
    assert runner.POST_PROJECT_DISCLOSURE in environment["weight_disclosure"]

    assert fake_carla.sensor.stopped is True
    assert fake_carla.sensor.destroyed is True
    assert fake_torch.cuda.synchronize_calls == 2
    assert len(fake_model.calls) == 1
    _, model_kwargs = fake_model.calls[0]
    assert model_kwargs == {"conf": 0.40, "device": 0, "iou": 0.45, "verbose": False}


def test_cuda_unavailable_fails_before_model_load_and_keeps_evidence(tmp_path):
    runner = load_runner()
    factory_calls = []
    weight_path = tmp_path / "yolov8s.pt"
    weight_path.write_bytes(b"weight")

    exit_code = runner.run_yolo_smoke(
        carla_module=FakeCarla(),
        torch_module=FakeTorch(cuda_available=False),
        torchvision_module=FakeTorchvision(),
        ultralytics_module=FakeUltralytics(),
        cv2_module=FakeCv2(),
        numpy_module=np,
        yolo_factory=lambda path: factory_calls.append(path),
        weight_path=weight_path,
        weight_source=runner.POST_PROJECT_WEIGHT_SOURCE,
        evidence_dir=tmp_path / "evidence",
        host="127.0.0.1",
        port=2000,
        timeout_seconds=2.0,
    )

    evidence = tmp_path / "evidence"
    environment = json.loads((evidence / "environment.json").read_text(encoding="utf-8"))
    result = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
    assert exit_code == 1
    assert result["status"] == "FAIL"
    assert result["error"]["type"] == "RuntimeError"
    assert result["error"]["message"] == "CUDA is unavailable; GPU YOLO smoke is required"
    assert environment["cuda_available"] is False
    assert factory_calls == []
    assert (evidence / "run.log").is_file()

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

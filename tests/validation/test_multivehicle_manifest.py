import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "validation" / "carla_e2e" / "multivehicle" / "scene_manifest.py"


def load_module():
    spec = importlib.util.spec_from_file_location("multivehicle_scene_manifest", str(MODULE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def target_manifest():
    return {
        "schema_version": 1,
        "scenario": "target",
        "planned_scene": {
            "seed": 42,
            "traffic_manager": {"port": 8000, "synchronous_mode": True},
            "camera": {"width": 800, "height": 600, "fov": 90},
            "vehicles": [
                {
                    "slot": "background-00", "kind": "background",
                    "blueprint": "vehicle.audi.a2", "color": "10,10,10",
                    "spawn_transform": {"location": {"x": 1.0, "y": 2.0, "z": 0.5}, "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}},
                    "route": [{"x": 1.0, "y": 2.0, "z": 0.5}],
                    "tm": {"speed_difference": 0.0, "ignore_lights": 0.0},
                },
                {
                    "slot": "probe", "kind": "probe",
                    "blueprint": "vehicle.tesla.model3", "color": "0,0,255",
                    "spawn_transform": {"location": {"x": 3.0, "y": 4.0, "z": 0.5}, "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}},
                    "route": [{"x": 3.0, "y": 4.0, "z": 0.5}, {"x": 30.0, "y": 4.0, "z": 0.5}],
                    "tm": {"speed_difference": -20.0, "ignore_lights": 100.0},
                },
            ],
        },
        "actual_spawned_scene": {
            "vehicles": [
                {"slot": "background-00", "actor_id": 101, "color": "10,10,10"},
                {"slot": "probe", "actor_id": 102, "color": "0,0,255"},
            ]
        },
    }


def test_non_target_manifest_changes_only_probe_colour_and_clears_actual_scene():
    module = load_module()
    target = target_manifest()

    non_target = module.build_non_target_manifest(target, "255,0,0")

    assert non_target["scenario"] == "non_target"
    assert non_target["actual_spawned_scene"] == {"vehicles": []}
    assert non_target["planned_scene"]["vehicles"][0] == target["planned_scene"]["vehicles"][0]
    assert non_target["planned_scene"]["vehicles"][1]["color"] == "255,0,0"
    module.validate_manifest_parity(target, non_target)


@pytest.mark.parametrize("mutation", ["background_color", "probe_route", "camera", "seed"])
def test_parity_rejects_every_change_except_probe_colour(mutation):
    module = load_module()
    target = target_manifest()
    non_target = module.build_non_target_manifest(target, "255,0,0")
    if mutation == "background_color":
        non_target["planned_scene"]["vehicles"][0]["color"] = "255,255,255"
    elif mutation == "probe_route":
        non_target["planned_scene"]["vehicles"][1]["route"][1]["x"] = 31.0
    elif mutation == "camera":
        non_target["planned_scene"]["camera"]["fov"] = 100
    else:
        non_target["planned_scene"]["seed"] = 7

    with pytest.raises(ValueError, match="manifest parity"):
        module.validate_manifest_parity(target, non_target)


def test_manifest_write_is_atomic_and_preserves_planned_actual_sections(tmp_path):
    module = load_module()
    path = tmp_path / "scene_manifest.json"
    value = target_manifest()

    module.write_manifest(path, value)

    assert json.loads(path.read_text(encoding="utf-8")) == value
    assert not path.with_suffix(".json.tmp").exists()
    assert set(module.read_manifest(path)) >= {"planned_scene", "actual_spawned_scene"}

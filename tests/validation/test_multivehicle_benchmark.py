import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "validation" / "carla_e2e" / "multivehicle" / "run_host_benchmark.py"


def load_module():
    sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("multivehicle_benchmark", str(MODULE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_success_requires_exit_zero_pass_and_scenario_outcome():
    module = load_module()
    passing = {"status": "PASS", "target_events": 1, "fake_vlm_requests": 1}
    assert module.run_success("target", 0, passing) is True
    assert module.run_success("target", 1, passing) is False
    assert module.run_success("target", 0, dict(passing, target_events=0)) is False
    assert module.run_success("target", 0, dict(passing, status="FAIL")) is False
    assert module.run_success("non_target", 0, {"status": "PASS", "target_events": 0, "fake_vlm_requests": 0}) is True
    assert module.run_success("non_target", 0, {"status": "PASS", "target_events": 1, "fake_vlm_requests": 0}) is False
    assert module.run_success("non_target", "timeout", {}) is False


def test_false_target_events_count_non_probe_alerts_in_target_runs():
    module = load_module()
    assert module.false_target_events("target", {"probe_track_ids": [9, 12], "alert_track_ids": [9, 3]}) == 1
    assert module.false_target_events("non_target", {"target_events": 2}) == 2


def test_latency_summary_does_not_invent_values_for_empty_sets():
    module = load_module()
    empty = module.latency_summary([])
    assert empty["sample_count"] == 0 and empty["p95_ms"] is None and empty["compliance_rate"] is None
    summary = module.latency_summary([10.0, 20.0, 30.0, 2000.0])
    assert summary["p50_ms"] == 25.0
    assert summary["over_1000"] == 1
    assert summary["compliance_rate"] == 0.75

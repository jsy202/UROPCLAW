import importlib.util
import subprocess
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "validation" / "carla_e2e" / "real_pipeline" / "run_host_e2e.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("run_host_e2e", str(RUNNER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_latency_summary_reports_one_second_compliance():
    runner = load_runner()
    summary = runner.latency_summary([100.0, 200.0, 300.0, 1100.0], np)
    assert summary == {
        "sample_count": 4,
        "mean_ms": 425.0,
        "p50_ms": 250.0,
        "p95_ms": 980.0,
        "p99_ms": 1076.0,
        "max_ms": 1100.0,
        "at_or_below_1000": 3,
        "over_1000": 1,
        "compliance_rate": 0.75,
    }


def test_latency_summary_does_not_claim_empty_samples_are_fast():
    runner = load_runner()
    summary = runner.latency_summary([], np)
    assert summary["sample_count"] == 0
    assert summary["mean_ms"] is None
    assert summary["compliance_rate"] is None


def test_scenario_success_keeps_target_and_non_target_rules_distinct():
    runner = load_runner()
    assert runner.scenario_success("target", 1, 1, 1, True) is True
    assert runner.scenario_success("target", 1, 0, 1, True) is False
    assert runner.scenario_success("non_target", 0, 0, 1, True) is True
    assert runner.scenario_success("non_target", 1, 0, 1, True) is False


def test_fault_summary_keeps_fault_types_separate():
    runner = load_runner()
    template = {
        "scenario": "fault", "fault_injected": 1, "fault_detected": True,
        "recovered": True, "pipeline_crash": False,
        "next_normal_request_success": True, "max_queue_depth": 2,
        "dropped_frames": 0, "dropped_events": 0,
    }
    rows = [dict(template, fault="delay"), dict(template, fault="timeout", max_queue_depth=3)]
    result = runner._aggregate_faults(rows)
    assert [row["fault"] for row in result] == ["delay", "timeout"]
    assert result[1]["max_queue_depth"] == 3


@pytest.mark.parametrize("fault", ["delay", "timeout", "error", "malformed"])
def test_fault_vlm_injects_once_then_recovers_with_normal_response(fault):
    runner = load_runner()
    vlm = runner.FaultThenSuccessVLM(fault, delay_seconds=0.0)
    command = ["claude", "--print"]

    if fault == "timeout":
        with pytest.raises(subprocess.TimeoutExpired):
            vlm(command, input=b"prompt", timeout=25)
    elif fault == "error":
        with pytest.raises(RuntimeError):
            vlm(command, input=b"prompt", timeout=25)
    else:
        first = vlm(command, input=b"prompt", timeout=25)
        if fault == "malformed":
            assert b"{" not in first.stdout
        else:
            assert first.returncode == 0

    second = vlm(command, input=b"prompt", timeout=25)
    assert b'"confirmed": true' in second.stdout
    assert vlm.calls == 2
    assert vlm.injected == 1
    assert vlm.normal_successes == 1

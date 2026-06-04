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


def test_frame_retention_uses_only_frame_and_image_units():
    runner = load_runner()
    summary = runner.frame_metric_summary({
        "input_frames": 10,
        "frames_with_yolo_detection": 8,
        "frames_passing_hsv": 6,
        "frames_with_active_track": 6,
        "frames_triggering_confirmation": 2,
        "images_sent_to_vlm": 1,
    })
    assert summary["input_to_yolo_retention"] == 0.8
    assert summary["yolo_to_hsv_retention"] == 0.75
    assert summary["hsv_to_tracking_retention"] == 1.0
    assert summary["tracking_to_confirmation_retention"] == pytest.approx(1 / 3)
    assert summary["confirmation_to_vlm_retention"] == 0.5


def test_frame_retention_is_not_fabricated_for_zero_denominator():
    runner = load_runner()
    summary = runner.frame_metric_summary({
        "input_frames": 10,
        "frames_with_yolo_detection": 0,
        "frames_passing_hsv": 0,
        "frames_with_active_track": 0,
        "frames_triggering_confirmation": 0,
        "images_sent_to_vlm": 0,
    })
    assert summary["input_to_yolo_retention"] == 0.0
    assert summary["yolo_to_hsv_retention"] is None
    assert summary["confirmation_to_vlm_retention"] is None


def test_counting_tracker_records_hsv_and_active_track_frames_once():
    runner = load_runner()
    observation = runner.Observation("blue")

    class Track:
        disappeared = 0

    class BaseTracker:
        def update(self, detections, colors=None):
            return {7: Track()}

    class BaseTemporal:
        def update(self, track_id, color, timestamp):
            return None

    class PipelineModule:
        IoUTracker = BaseTracker
        TemporalConfirm = BaseTemporal
        classify_color = staticmethod(lambda frame, bbox: "blue")

    CountingTracker, _, _ = runner._make_counting_classes(PipelineModule, observation)
    tracker = CountingTracker()
    tracker.update([object()], ["blue"])
    tracker.update([object()], ["unknown"])

    assert observation.frames_passing_hsv == 1
    assert observation.frames_with_active_track == 2


def test_temporal_counter_counts_trigger_frames_not_unique_tracks():
    runner = load_runner()
    observation = runner.Observation("blue")

    class BaseTracker:
        pass

    class BaseTemporal:
        def update(self, track_id, color, timestamp):
            return {"track_id": track_id, "color": color}

    class PipelineModule:
        IoUTracker = BaseTracker
        TemporalConfirm = BaseTemporal
        classify_color = staticmethod(lambda frame, bbox: "blue")

    _, CountingTemporal, _ = runner._make_counting_classes(PipelineModule, observation)
    confirmer = CountingTemporal()
    confirmer.update(3, "blue", 1.0)
    confirmer.update(3, "blue", 2.0)

    assert observation.frames_triggering_confirmation == 2
    assert len(observation.confirmed_tracks) == 1


def test_fake_vlm_distinguishes_requests_from_images(tmp_path):
    runner = load_runner()
    image_path = tmp_path / "crop.jpg"
    image_path.write_bytes(b"image")
    vlm = runner.DeterministicVLM()

    vlm(["claude"], input=("Analyze the image at {0}.\n".format(image_path)).encode())
    vlm(["claude"], input=b"No image available")

    assert vlm.calls == 2
    assert vlm.images_received == 1


def test_frame_metric_aggregation_keeps_scenarios_separate():
    runner = load_runner()
    rows = [
        {
            "scenario": "target", "input_frames": 10,
            "frames_with_yolo_detection": 9, "frames_passing_hsv": 8,
            "frames_with_active_track": 8, "frames_triggering_confirmation": 3,
            "images_sent_to_vlm": 1,
        },
        {
            "scenario": "target", "input_frames": 10,
            "frames_with_yolo_detection": 10, "frames_passing_hsv": 10,
            "frames_with_active_track": 10, "frames_triggering_confirmation": 3,
            "images_sent_to_vlm": 1,
        },
        {
            "scenario": "non_target", "input_frames": 10,
            "frames_with_yolo_detection": 10, "frames_passing_hsv": 10,
            "frames_with_active_track": 10, "frames_triggering_confirmation": 3,
            "images_sent_to_vlm": 0,
        },
    ]

    result = runner._aggregate_frame_metrics(rows)

    assert result[0]["scenario"] == "target"
    assert result[0]["repetitions"] == 2
    assert result[0]["input_frames"] == 20
    assert result[0]["frames_with_yolo_detection"] == 19
    assert result[0]["input_to_yolo_retention"] == 0.95
    assert result[1]["scenario"] == "non_target"
    assert result[1]["images_sent_to_vlm"] == 0


def test_frame_metrics_only_cli_is_explicit():
    runner = load_runner()
    args = runner.parse_args(["--frame-metrics-only"])
    assert args.frame_metrics_only is True


def test_frame_metric_writer_does_not_overwrite_existing_e2e_results(tmp_path):
    runner = load_runner()
    runner.HERE = tmp_path
    protected = [
        "raw_results.csv", "latency_samples.csv", "scenario_summary.csv",
        "latency_summary.csv", "fault_summary.csv", "validation_report.md",
    ]
    for filename in protected:
        (tmp_path / filename).write_text("existing-result\n", encoding="utf-8")
    row = {
        "run_id": "target-01", "scenario": "target", "repetition": 1,
        "status": "COMPLETE", "scenario_success": True, "input_frames": 10,
        "frames_with_yolo_detection": 10, "frames_passing_hsv": 10,
        "frames_with_active_track": 10, "frames_triggering_confirmation": 3,
        "images_sent_to_vlm": 1, "yolo_detections": 10, "unique_tracks": 1,
        "confirmed_tracks": 1, "vlm_requests": 1, "target_events": 1,
        "max_queue_depth": 0, "ending_queue_depth": 0, "dropped_frames": 0,
        "dropped_events": 0, "pipeline_alive": True, "error": "",
    }

    runner._write_frame_metric_outputs([row], {"mode": "test"})

    for filename in protected:
        assert (tmp_path / filename).read_text(encoding="utf-8") == "existing-result\n"
    assert (tmp_path / "frame_metrics_raw.csv").is_file()
    assert (tmp_path / "frame_metrics_summary.csv").is_file()
    assert (tmp_path / "frame_metrics_report.md").is_file()


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

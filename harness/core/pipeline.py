from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Optional

import cv2
import numpy as np

from perception.yolo_detector import detect, Detection
from perception.color_filter import classify_color
from perception.iou_tracker import IoUTracker
from perception.temporal_confirm import TemporalConfirm
from perception.deduplicator import Deduplicator
from core.mission import is_active, get_target_color, read_mission
from policy.alert_policy import AlertPolicy
from evaluation.baseline import BaselineMode, color_filter_enabled, dedup_enabled, BASELINE_N
from config import WORKSPACE_BASE

log = logging.getLogger(__name__)

_METRICS_PATH = WORKSPACE_BASE / "uropclaw1" / "state" / "metrics.json"
_METRICS_INTERVAL = 5.0  # seconds

VERIFICATION_REQUEST_PATH = WORKSPACE_BASE / "uropclaw1" / "state" / "verification_request.json"
VERIFICATION_RESPONSE_PATH = WORKSPACE_BASE / "uropclaw1" / "state" / "verification_response.json"
OPENCLAW_TIMEOUT_S = 30.0
OPENCLAW_POLL_INTERVAL_S = 0.5


def _state_dir(agent_id: str) -> Path:
    n = agent_id.replace("uropclaw", "")
    return WORKSPACE_BASE / f"uropclaw{n}" / "state"


def _crops_dir(agent_id: str) -> Path:
    return _state_dir(agent_id) / "crops"


# ── Thread-1: CARLA tick ──────────────────────────────────────────────────────

class CarlaTickThread(threading.Thread):
    def __init__(self, world, stop_event: threading.Event) -> None:
        super().__init__(name="carla-tick", daemon=True)
        self.world = world
        self.stop_event = stop_event

    def run(self) -> None:
        log.info("CarlaTickThread started")
        while not self.stop_event.is_set():
            try:
                self.world.tick(60.0)
            except Exception as e:
                log.warning(f"world.tick() error: {e}")
                time.sleep(1.0)
            except BaseException as e:
                log.error(f"world.tick() fatal error (retrying): {e}")
                time.sleep(2.0)


# ── Thread-2: YOLO Worker ─────────────────────────────────────────────────────

class YoloWorker(threading.Thread):
    def __init__(
        self,
        stop_event: threading.Event,
        frame_queue: Queue,
        candidate_queue: Queue,
        metrics: dict,
        baseline_mode: str = "proposed",
    ) -> None:
        super().__init__(name="yolo-worker", daemon=True)
        self.stop_event = stop_event
        self._frame_queue = frame_queue
        self._candidate_queue = candidate_queue
        self._metrics = metrics
        self._baseline_mode = baseline_mode
        self._trackers: dict[str, IoUTracker] = {}
        self._confirmer: dict[str, TemporalConfirm] = {}
        self._frame_count: int = 0

    def _get_tracker(self, camera_id: str) -> IoUTracker:
        if camera_id not in self._trackers:
            self._trackers[camera_id] = IoUTracker()
        return self._trackers[camera_id]

    def _get_confirmer(self, camera_id: str) -> TemporalConfirm:
        if camera_id not in self._confirmer:
            self._confirmer[camera_id] = TemporalConfirm()
        return self._confirmer[camera_id]

    def run(self) -> None:
        log.info(f"YoloWorker started (baseline_mode={self._baseline_mode})")
        mode = BaselineMode(self._baseline_mode)

        while not self.stop_event.is_set():
            try:
                item = self._frame_queue.get(timeout=0.5)
            except Empty:
                continue

            self._metrics["frames_received"] += 1
            self._frame_count += 1

            camera_id: str = item["camera_id"]
            agent_id: str = item["agent_id"]
            frame: np.ndarray = item["frame"]
            timestamp: float = item.get("timestamp", time.time())

            if not is_active():
                continue

            # Baseline A: YOLO/color 없이 매 N번째 프레임만 candidate_queue 전달
            if mode == BaselineMode.A:
                if self._frame_count % BASELINE_N == 0:
                    self._metrics["candidates_raised"] += 1
                    self._candidate_queue.put({
                        "camera_id": camera_id,
                        "agent_id": agent_id,
                        "track_id": -1,
                        "color": "unknown",
                        "color_score": 0.0,
                        "bbox": [0, 0, 0, 0],
                        "frame": frame,
                        "timestamp": timestamp,
                        "yolo_class": "car",
                        "yolo_confidence": 0.0,
                        "class_id": -1,
                    })
                self._metrics["frames_processed"] = self._frame_count
                continue

            try:
                t_yolo_start = time.time()
                detections: list[Detection] = detect(frame)
                yolo_elapsed_ms = (time.time() - t_yolo_start) * 1000.0
                self._metrics.setdefault("yolo_latency_ms_list", []).append(round(yolo_elapsed_ms, 2))

                self._metrics["detections_total"] += len(detections)
                self._metrics["frames_processed"] = self._frame_count

                if not detections:
                    continue

                # Baseline B: YOLO → OpenClaw, color filter/dedup 없음
                if mode == BaselineMode.B:
                    for det in detections:
                        self._metrics["candidates_raised"] += 1
                        self._candidate_queue.put({
                            "camera_id": camera_id,
                            "agent_id": agent_id,
                            "track_id": -1,
                            "color": "unknown",
                            "color_score": 0.0,
                            "bbox": det.bbox,
                            "frame": frame,
                            "timestamp": timestamp,
                            "yolo_class": det.class_name,
                            "yolo_confidence": det.confidence,
                            "class_id": -1,
                        })
                    continue

                # Baseline C / Proposed: color filter 적용
                use_color_filter = color_filter_enabled(mode)
                colors: list[str] = []
                for det in detections:
                    if use_color_filter:
                        c = classify_color(frame, det.bbox)
                        self._metrics["color_filter_passed"] = (
                            self._metrics.get("color_filter_passed", 0) + 1
                        )
                    else:
                        c = "unknown"
                    colors.append(c)

                tracker = self._get_tracker(camera_id)
                tracks = tracker.update(detections, colors)

                confirmer = self._get_confirmer(camera_id)
                use_dedup = dedup_enabled(mode)

                for tid, track in tracks.items():
                    color = track.color_history[-1] if track.color_history else "unknown"
                    result = confirmer.update(tid, color, timestamp)
                    if result is None:
                        continue

                    confirmed_color = result["color"]
                    target = get_target_color()
                    if target and confirmed_color != target:
                        continue

                    # Baseline C: OpenClaw 없이 종료 (candidate_queue 넣지 않음)
                    if mode == BaselineMode.C:
                        self._metrics["candidates_raised"] += 1
                        continue

                    matched_det: Optional[Detection] = None
                    for det in detections:
                        if det.bbox == track.bbox:
                            matched_det = det
                            break

                    self._metrics["candidates_raised"] += 1
                    self._candidate_queue.put({
                        "camera_id": camera_id,
                        "agent_id": agent_id,
                        "track_id": tid,
                        "color": confirmed_color,
                        "color_score": _dominant_ratio(track.color_history, confirmed_color),
                        "bbox": track.bbox,
                        "frame": frame,
                        "timestamp": timestamp,
                        "yolo_class": matched_det.class_name if matched_det else "car",
                        "yolo_confidence": matched_det.confidence if matched_det else 0.0,
                        "class_id": track.class_id,
                        "dedup_enabled": use_dedup,
                    })

            except Exception as e:
                log.error(f"YoloWorker error: {e}", exc_info=True)


def _dominant_ratio(history: list[str], color: str) -> float:
    if not history:
        return 0.0
    return history.count(color) / len(history)


# ── Thread-3: OpenClaw Worker (Phase 3 실연동) ────────────────────────────────

class OpenClawWorker(threading.Thread):
    def __init__(
        self,
        stop_event: threading.Event,
        candidate_queue: Queue,
        result_queue: Queue,
        metrics: dict,
    ) -> None:
        super().__init__(name="openclaw-worker", daemon=True)
        self.stop_event = stop_event
        self._candidate_queue = candidate_queue
        self._result_queue = result_queue
        self._metrics = metrics
        self._dedup = Deduplicator()

    def run(self) -> None:
        log.info("OpenClawWorker started (Phase 3 실연동)")
        while not self.stop_event.is_set():
            try:
                item = self._candidate_queue.get(timeout=0.5)
            except Empty:
                continue

            now = time.time()
            key = f"{item['camera_id']}::{item['track_id']}"

            self._dedup.cleanup(now)

            # dedup_enabled 플래그가 False이면 dedup 체크 건너뜀 (Baseline B)
            if item.get("dedup_enabled", True):
                if not self._dedup.should_verify(key, now):
                    self._metrics["duplicate_suppressed"] = (
                        self._metrics.get("duplicate_suppressed", 0) + 1
                    )
                    continue

            mission = read_mission()
            mission_id = mission.get("mission_id", "") if mission else ""
            candidate = {**item, "mission_id": mission_id}

            target_body_type = mission.get("target_body_type") if mission else None

            if not target_body_type:
                # body_type 미지정 미션: OpenClaw 검증 없이 바로 통과
                candidate["openclaw_result"] = {
                    "confirmed": True,
                    "confidence": "n/a",
                    "vehicle_body_type": "unknown",
                    "target_body_type_match": True,
                    "reason": "body_type not specified — skipped verification",
                }
                self._result_queue.put(candidate)
                continue

            # body_type 지정 미션: OpenClaw 검증 요청
            self._metrics["openclaw_calls"] = self._metrics.get("openclaw_calls", 0) + 1
            result = self._request_verification(candidate, mission)
            candidate["openclaw_result"] = result

            if result.get("confirmed", False):
                self._metrics["openclaw_confirmed"] = self._metrics.get("openclaw_confirmed", 0) + 1

            self._result_queue.put(candidate)

    def _request_verification(self, candidate: dict, mission: dict) -> dict:
        request_id = str(uuid.uuid4())

        # Create crop for uropclaw1 to attach when messaging uropclaw2
        crop_path = None
        frame = candidate.get("frame")
        bbox = candidate.get("bbox")
        if frame is not None and bbox:
            agent_id = candidate.get("agent_id", "uropclaw2")
            crops_dir = _crops_dir(agent_id)
            crops_dir.mkdir(parents=True, exist_ok=True)
            crop_filename = f"vreq_{request_id[:8]}.jpg"
            crop_path_obj = crops_dir / crop_filename
            x1, y1, x2, y2 = bbox
            crop = frame[max(0, y1):y2, max(0, x1):x2]
            if crop.size > 0:
                import cv2
                cv2.imwrite(str(crop_path_obj), crop)
                crop_path = str(crop_path_obj)

        request = {
            "request_id": request_id,
            "mission_id": candidate.get("mission_id"),
            "crop_path": crop_path,
            "target_color": mission.get("target_color"),
            "target_body_type": mission.get("target_body_type"),
            "yolo_class": candidate.get("yolo_class"),
            "yolo_confidence": candidate.get("yolo_confidence"),
            "color_score": candidate.get("color_score"),
            "camera_id": candidate.get("camera_id"),
            "timestamp": candidate.get("timestamp"),
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }

        # 기존 응답 파일 삭제 (이전 응답이 남아있지 않도록)
        VERIFICATION_RESPONSE_PATH.unlink(missing_ok=True)

        # 요청 파일 작성
        VERIFICATION_REQUEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        VERIFICATION_REQUEST_PATH.write_text(
            json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info(
            f"[openclaw] verification requested: request_id={request_id} "
            f"mission_id={candidate.get('mission_id')} "
            f"target_body_type={mission.get('target_body_type')}"
        )

        # 응답 polling (최대 OPENCLAW_TIMEOUT_S초)
        deadline = time.time() + OPENCLAW_TIMEOUT_S
        while time.time() < deadline:
            if VERIFICATION_RESPONSE_PATH.exists():
                try:
                    raw = VERIFICATION_RESPONSE_PATH.read_text(encoding="utf-8")
                    response = json.loads(raw)
                    if response.get("request_id") == request_id:
                        VERIFICATION_RESPONSE_PATH.unlink(missing_ok=True)
                        log.info(
                            f"[openclaw] response received: request_id={request_id} "
                            f"confirmed={response.get('confirmed')} "
                            f"confidence={response.get('confidence')}"
                        )
                        return response
                except (json.JSONDecodeError, KeyError):
                    log.warning("Invalid verification response JSON — retrying")
            time.sleep(OPENCLAW_POLL_INTERVAL_S)

        # timeout
        log.warning(f"[openclaw] verification timeout: request_id={request_id}")
        self._metrics["openclaw_timeouts"] = self._metrics.get("openclaw_timeouts", 0) + 1
        return {
            "request_id": request_id,
            "confirmed": False,
            "confidence": "low",
            "vehicle_body_type": "unknown",
            "target_body_type_match": False,
            "reason": "OpenClaw 응답 시간 초과",
        }


# ── Thread-4: Alert Worker ────────────────────────────────────────────────────

class AlertWorker(threading.Thread):
    def __init__(
        self,
        stop_event: threading.Event,
        result_queue: Queue,
        metrics: dict,
    ) -> None:
        super().__init__(name="alert-worker", daemon=True)
        self.stop_event = stop_event
        self._result_queue = result_queue
        self._metrics = metrics
        self._alert_policy = AlertPolicy()

    def run(self) -> None:
        log.info("AlertWorker started")
        while not self.stop_event.is_set():
            try:
                item = self._result_queue.get(timeout=0.5)
            except Empty:
                continue

            try:
                mission = read_mission()
                openclaw_result = item.get("openclaw_result")
                if not self._alert_policy.should_alert(item, mission, openclaw_result):
                    log.debug(
                        f"[{item.get('agent_id')}] alert suppressed: "
                        f"track={item.get('track_id')} color={item.get('color')} "
                        f"score={item.get('color_score', 0):.3f} "
                        f"openclaw_confirmed={openclaw_result.get('confirmed') if openclaw_result else 'n/a'}"
                    )
                    continue
                self._metrics["alerts_sent"] += 1
                self._write_event(item)
            except Exception as e:
                log.error(f"AlertWorker error: {e}", exc_info=True)

    def _write_event(self, item: dict) -> None:
        agent_id: str = item["agent_id"]
        camera_id: str = item["camera_id"]
        track_id: int = item["track_id"]
        timestamp: float = item["timestamp"]
        color: str = item["color"]
        color_score: float = item.get("color_score", 0.0)
        yolo_class: str = item.get("yolo_class", "car")
        yolo_confidence: float = item.get("yolo_confidence", 0.0)
        bbox: list[int] = item["bbox"]
        frame: np.ndarray = item["frame"]
        mission_id: str = item.get("mission_id", "")

        event_id = str(uuid.uuid4())
        crops_dir = _crops_dir(agent_id)
        crops_dir.mkdir(parents=True, exist_ok=True)
        crop_filename = f"evt_{event_id[:8]}.jpg"
        crop_path = crops_dir / crop_filename

        x1, y1, x2, y2 = bbox
        crop = frame[max(0, y1):y2, max(0, x1):x2]
        if crop.size > 0:
            cv2.imwrite(str(crop_path), crop)

        event = {
            "event_id": event_id,
            "camera_id": camera_id,
            "agent_id": agent_id,
            "track_id": track_id,
            "timestamp": timestamp,
            "color": color,
            "color_score": round(color_score, 4),
            "yolo_class": yolo_class,
            "yolo_confidence": round(yolo_confidence, 4),
            "bbox": bbox,
            "mission_id": mission_id,
            "crop_path": str(crop_path),
            "openclaw_result": item.get("openclaw_result"),
        }

        state_dir = _state_dir(agent_id)
        state_dir.mkdir(parents=True, exist_ok=True)
        event_path = state_dir / "detection_event.json"
        event_path.write_text(json.dumps(event, indent=2), encoding="utf-8")
        log.info(f"[{agent_id}] detection event written: track={track_id} color={color}")


# ── Thread-5: Metrics Writer ──────────────────────────────────────────────────

class MetricsWriter(threading.Thread):
    def __init__(self, stop_event: threading.Event, metrics: dict) -> None:
        super().__init__(name="metrics-writer", daemon=True)
        self.stop_event = stop_event
        self._metrics = metrics

    def run(self) -> None:
        log.info("MetricsWriter started")
        while not self.stop_event.is_set():
            time.sleep(_METRICS_INTERVAL)
            try:
                snapshot = dict(self._metrics)
                snapshot["uptime_seconds"] = round(
                    time.time() - snapshot.get("pipeline_start_time", time.time()), 1
                )
                _METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
                _METRICS_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            except Exception as e:
                log.warning(f"MetricsWriter error: {e}")


# ── Pipeline controller ───────────────────────────────────────────────────────

class Pipeline:
    def __init__(self, world, manager=None, camera=None, baseline_mode: str = "proposed") -> None:
        self._world = world
        self._manager = manager
        self._camera = camera
        self._baseline_mode = baseline_mode
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

        self.frame_queue: Queue = Queue(maxsize=4)
        self._candidate_queue: Queue = Queue(maxsize=20)
        self._result_queue: Queue = Queue(maxsize=20)

        self._metrics: dict = {
            "baseline_mode": baseline_mode,
            "frames_received": 0,
            "frames_dropped": 0,
            "frames_processed": 0,
            "detections_total": 0,
            "color_filter_passed": 0,
            "candidates_raised": 0,
            "alerts_sent": 0,
            "duplicate_suppressed": 0,
            "openclaw_calls": 0,
            "openclaw_confirmed": 0,
            "openclaw_timeouts": 0,
            "pipeline_start_time": time.time(),
        }

    def start(self) -> None:
        self._stop.clear()
        self._metrics["pipeline_start_time"] = time.time()
        self._threads = [
            CarlaTickThread(self._world, self._stop),
            YoloWorker(self._stop, self.frame_queue, self._candidate_queue, self._metrics,
                       baseline_mode=self._baseline_mode),
            OpenClawWorker(self._stop, self._candidate_queue, self._result_queue, self._metrics),
            AlertWorker(self._stop, self._result_queue, self._metrics),
            MetricsWriter(self._stop, self._metrics),
        ]
        for t in self._threads:
            t.start()
        log.info("Pipeline started (5 threads)")

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5.0)
        log.info("Pipeline stopped")

    def join(self) -> None:
        """메인 스레드가 파이프라인 종료를 대기."""
        self._stop.wait()

    def metrics_summary(self) -> dict:
        """현재 메트릭 스냅샷 반환 (종료 시 출력용)."""
        snapshot = dict(self._metrics)
        start = snapshot.pop("pipeline_start_time", time.time())
        elapsed = time.time() - start
        snapshot["uptime_seconds"] = round(elapsed, 1)
        frames_processed = snapshot.get("frames_processed", 0)
        if frames_processed > 0:
            openclaw_calls = snapshot.get("openclaw_calls", 0)
            snapshot["openclaw_call_reduction_rate"] = round(
                1.0 - (openclaw_calls / frames_processed), 4
            )
        else:
            snapshot["openclaw_call_reduction_rate"] = 0.0
        if elapsed > 0:
            snapshot["pipeline_fps"] = round(frames_processed / elapsed, 2)
        else:
            snapshot["pipeline_fps"] = 0.0
        return snapshot

    def push_frame(
        self,
        camera_id: str,
        agent_id: str,
        frame: np.ndarray,
        timestamp: Optional[float] = None,
    ) -> None:
        try:
            self.frame_queue.put_nowait({
                "camera_id": camera_id,
                "agent_id": agent_id,
                "frame": frame,
                "timestamp": timestamp or time.time(),
            })
        except Exception:
            self._metrics["frames_dropped"] += 1

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
import uuid
import logging
from config import AGENT_IDS, STATE_INTERVAL_S
from sensors.manager import CarlaManager
from sensors.camera import CameraManager
from sensors.sensor import read as read_sensor
from sensors.controller import apply as apply_control
from core.envelope import HarnessEnvelope, AgentDecision
from core.policy import check as policy_check
from core.state import write_observation, read_decision
from core.session_store import (
    create_session, tick_session, save_checkpoint,
    load_latest_checkpoint, resume_session, log_event,
)
from agent.messenger import send
from agent.parser import read as read_agent_decision, DEFAULT
from obs.logger import log_tick
from gateway import proxy as proxy_store

log = logging.getLogger(__name__)

CHECKPOINT_EVERY = 10   # N tick마다 checkpoint
DECISION_TIMEOUT_S = 8  # agent 응답 대기 최대 시간
DECISION_POLL_S = 0.2   # polling 간격


class Orchestrator:
    def __init__(self, manager: CarlaManager, camera: CameraManager):
        self.manager  = manager
        self.camera   = camera
        self.running  = False
        self._sessions: dict[str, str] = {}   # agent_id → session_id
        self._ticks:    dict[str, int] = {}   # agent_id → tick count

    # ── 시작 ──────────────────────────────────────────────

    def run(self) -> None:
        self._init_sessions()
        self.running = True
        log.info("Orchestrator started")
        try:
            while self.running:
                self._tick_all()
                time.sleep(STATE_INTERVAL_S)
        except KeyboardInterrupt:
            log.info("Stopped by user")
        finally:
            self.running = False
            self._close_sessions()

    def _init_sessions(self) -> None:
        for agent_id in self.manager.vehicles:
            # 이전 세션 재개 시도
            prev = resume_session(agent_id)
            if prev:
                sid = prev["session_id"]
                ckpt = load_latest_checkpoint(sid)
                if ckpt:
                    log.info(f"[{agent_id}] resumed session {sid} from tick {ckpt['tick']}")
                else:
                    log.info(f"[{agent_id}] resumed session {sid} (no checkpoint)")
            else:
                sid = str(uuid.uuid4())
                create_session(sid, agent_id)
                log.info(f"[{agent_id}] new session {sid}")

            self._sessions[agent_id] = sid
            self._ticks[agent_id] = 0

    def _close_sessions(self) -> None:
        from core.session_store import close_session
        for sid in self._sessions.values():
            close_session(sid)

    # ── 메인 루프 ──────────────────────────────────────────

    def _tick_all(self) -> None:
        saved = self.camera.tick()

        for agent_id, vehicle in self.manager.vehicles.items():
            sid = self._sessions[agent_id]

            # 1. 센서 읽기
            obs = read_sensor(
                self.manager.world, agent_id, vehicle,
                capture_path=saved.get(agent_id),
            )

            # 2. Envelope 생성 + 파일 전달 + Proxy 주입
            envelope = HarnessEnvelope(session_id=sid, observation=obs)
            write_observation(agent_id, envelope)
            send(agent_id, envelope)
            proxy_store.push_observation(agent_id, obs.model_dump())

            # 3. Agent 결정 읽기 (timeout 포함)
            tick = tick_session(sid)
            self._ticks[agent_id] = tick
            decision = self._wait_for_decision(agent_id, sid, tick)

            # 4. Policy 검증
            policy_result = policy_check(decision, obs)
            if policy_result.action in ("override", "deny"):
                log.info(f"[{agent_id}] policy {policy_result.action}: {policy_result.reason}")
                log_event(sid, tick, "policy_override", {
                    "reason": policy_result.reason,
                    "original_maneuver": decision.maneuver,
                })
                if policy_result.override_decision:
                    decision = policy_result.override_decision

            # 5. 승인 필요 기동 플래그
            if policy_result.action == "approve_required":
                self._flag_approval(agent_id, decision)

            # 6. 제어 적용
            apply_control(vehicle, decision, obs.speed_kmh)

            # 7. 이벤트 기록 (파일 + DB)
            log_tick(agent_id, obs, decision, policy_result)
            log_event(sid, tick, "tick", {
                "speed_kmh":  obs.speed_kmh,
                "front_dist": obs.front_vehicle_dist_m,
                "maneuver":   decision.maneuver,
                "policy":     policy_result.action,
            })

            # 8. Checkpoint (N tick마다)
            if tick % CHECKPOINT_EVERY == 0:
                save_checkpoint(sid, tick, {
                    "speed_kmh":  obs.speed_kmh,
                    "position":   obs.position,
                    "lane_id":    obs.lane_id,
                    "maneuver":   decision.maneuver,
                })
                log.debug(f"[{agent_id}] checkpoint saved at tick {tick}")

    # ── 결정 대기 (Timeout + Retry) ────────────────────────

    def _wait_for_decision(
        self, agent_id: str, sid: str, tick: int
    ) -> AgentDecision:
        deadline = time.time() + DECISION_TIMEOUT_S
        while time.time() < deadline:
            decision = read_agent_decision(agent_id)
            if decision is not DEFAULT:
                return decision
            time.sleep(DECISION_POLL_S)

        log.warning(f"[{agent_id}] decision timeout at tick {tick} — using DEFAULT")
        log_event(sid, tick, "decision_timeout", {"tick": tick})
        return DEFAULT

    # ── 승인 플래그 ────────────────────────────────────────

    def _flag_approval(self, agent_id: str, decision: AgentDecision) -> None:
        import json
        from config import WORKSPACE_BASE
        from datetime import datetime, timezone
        path = WORKSPACE_BASE / agent_id / "state" / "approval_required.json"
        path.write_text(json.dumps({
            "maneuver":         decision.maneuver,
            "target_speed_kmh": decision.target_speed_kmh,
            "flagged_at":       datetime.now(timezone.utc).isoformat(),
            "instructions":     "Write approved.json in same dir to proceed.",
        }, indent=2), encoding="utf-8")
        log.warning(f"[{agent_id}] approval required: {decision.maneuver}")

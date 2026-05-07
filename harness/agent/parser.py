import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import logging
from config import WORKSPACE_BASE
from core.envelope import AgentDecision

log = logging.getLogger(__name__)

DEFAULT = AgentDecision(maneuver="keep_lane", target_speed_kmh=30.0)


def read(agent_id: str) -> AgentDecision:
    """
    agent가 workspaces/{agent_id}/state/decision.json 에 결정을 기록하면 읽어 반환.
    읽은 후 파일 삭제 (중복 적용 방지).
    파일 없으면 DEFAULT 반환.
    """
    path = WORKSPACE_BASE / agent_id / "state" / "decision.json"
    if not path.exists():
        return DEFAULT
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        decision = AgentDecision(**data)
        path.unlink()
        log.debug(f"[{agent_id}] decision read: {decision.maneuver} @ {decision.target_speed_kmh} km/h")
        return decision
    except Exception as e:
        log.warning(f"[{agent_id}] decision parse error: {e}")
        return DEFAULT

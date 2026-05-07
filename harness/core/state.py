import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
from pathlib import Path
from config import WORKSPACE_BASE
from core.envelope import VehicleObservation, HarnessEnvelope, AgentDecision


def _state_dir(agent_id: str) -> Path:
    path = WORKSPACE_BASE / agent_id / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_observation(agent_id: str, envelope: HarnessEnvelope) -> None:
    (_state_dir(agent_id) / "observation.json").write_text(
        envelope.model_dump_json(indent=2), encoding="utf-8"
    )


def read_decision(agent_id: str) -> AgentDecision | None:
    path = _state_dir(agent_id) / "decision.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        decision = AgentDecision(**data)
        path.unlink()  # 읽은 후 삭제 (중복 적용 방지)
        return decision
    except Exception:
        return None

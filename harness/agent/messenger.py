import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import logging
from config import WORKSPACE_BASE
from core.envelope import HarnessEnvelope

log = logging.getLogger(__name__)


def send(agent_id: str, envelope: HarnessEnvelope) -> None:
    """
    Observation을 파일로 전달.
    agent는 heartbeat 또는 carla-driving skill에서 이 파일을 읽는다.

    경로: workspaces/{agent_id}/state/observation.json
    """
    state_dir = WORKSPACE_BASE / agent_id / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "observation.json").write_text(
        envelope.model_dump_json(indent=2), encoding="utf-8"
    )
    log.debug(f"[{agent_id}] observation written")

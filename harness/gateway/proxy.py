"""
CARLA Proxy API — 하네스 경계 강화
Agent는 CARLA에 직접 접근하지 않고 이 API만 사용한다.
GET  /v1/{agent_id}/observation  → 최신 observation 반환
POST /v1/{agent_id}/decision     → agent 결정 접수
GET  /v1/{agent_id}/history      → 최근 N개 observation 이력
GET  /v1/fleet/summary           → 전체 차량 요약
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import threading
import uvicorn
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import WORKSPACE_BASE, AGENT_IDS
from core.envelope import AgentDecision

app = FastAPI(title="CARLA Harness Proxy", version="1.0")

# orchestrator가 최신 observation을 여기에 주입
_latest_obs: dict[str, dict] = {}
_obs_history: dict[str, list[dict]] = {aid: [] for aid in AGENT_IDS}
_HISTORY_MAX = 20
_TOKEN = os.getenv("HARNESS_PROXY_TOKEN", "harness-proxy-local")


def _auth(token: str | None) -> None:
    if token != f"Bearer {_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def push_observation(agent_id: str, obs_dict: dict) -> None:
    """Orchestrator가 매 tick 호출해 최신 obs 주입"""
    _latest_obs[agent_id] = obs_dict
    history = _obs_history.setdefault(agent_id, [])
    history.append({**obs_dict, "_pushed_at": datetime.now(timezone.utc).isoformat()})
    if len(history) > _HISTORY_MAX:
        history.pop(0)


# ── Routes ────────────────────────────────────────────────

@app.get("/v1/{agent_id}/observation")
def get_observation(agent_id: str, authorization: str | None = Header(None)):
    _auth(authorization)
    if agent_id not in AGENT_IDS:
        raise HTTPException(404, f"unknown agent: {agent_id}")
    obs = _latest_obs.get(agent_id)
    if obs is None:
        raise HTTPException(503, "observation not yet available")
    return JSONResponse(obs)


@app.post("/v1/{agent_id}/decision")
def post_decision(agent_id: str, body: AgentDecision, authorization: str | None = Header(None)):
    _auth(authorization)
    if agent_id not in AGENT_IDS:
        raise HTTPException(404, f"unknown agent: {agent_id}")

    path = WORKSPACE_BASE / agent_id / "state" / "decision.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.model_dump_json(indent=2), encoding="utf-8")
    return {"status": "accepted", "agent_id": agent_id, "maneuver": body.maneuver}


@app.get("/v1/{agent_id}/history")
def get_history(agent_id: str, n: int = 5, authorization: str | None = Header(None)):
    _auth(authorization)
    if agent_id not in AGENT_IDS:
        raise HTTPException(404, f"unknown agent: {agent_id}")
    history = _obs_history.get(agent_id, [])
    return {"agent_id": agent_id, "history": history[-n:]}


@app.get("/v1/fleet/summary")
def fleet_summary(authorization: str | None = Header(None)):
    _auth(authorization)
    return {
        aid: {
            "speed_kmh": obs.get("speed_kmh"),
            "front_dist_m": obs.get("front_vehicle_dist_m"),
            "lane_id": obs.get("lane_id"),
        }
        for aid, obs in _latest_obs.items()
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ── Server ────────────────────────────────────────────────

def start(host: str = "0.0.0.0", port: int = 19000) -> None:
    """별도 스레드에서 서버 시작"""
    def _run():
        uvicorn.run(app, host=host, port=port, log_level="warning")
    t = threading.Thread(target=_run, daemon=True)
    t.start()

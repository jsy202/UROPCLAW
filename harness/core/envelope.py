from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field


class PeerMessage(BaseModel):
    from_vehicle: str
    content: str
    timestamp: str


class VehicleObservation(BaseModel):
    vehicle_id: str
    speed_kmh: float
    position: dict[str, float]           # x, y, z
    heading_deg: float
    lane_id: int
    lane_width: float
    front_vehicle_id: str | None
    front_vehicle_dist_m: float
    left_lane_available: bool
    right_lane_available: bool
    traffic_light_state: str             # green | red | yellow | unknown
    peer_messages: list[PeerMessage] = Field(default_factory=list)
    capture_path: str | None = None      # 최신 front 캡처 파일 경로


class HarnessEnvelope(BaseModel):
    schema_version: str = "1.0"
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    observation: VehicleObservation


class AgentDecision(BaseModel):
    maneuver: Literal[
        "keep_lane", "change_left", "change_right",
        "accelerate", "decelerate", "stop"
    ] = "keep_lane"
    target_speed_kmh: float = 30.0
    message: str | None = None    # drive-net 브로드캐스트 메시지
    confidence: float = 1.0


class PolicyDecision(BaseModel):
    action: Literal["allow", "deny", "override"]
    reason: str | None = None
    override_decision: AgentDecision | None = None

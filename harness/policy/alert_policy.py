from __future__ import annotations


class AlertPolicy:
    def __init__(self, color_score_threshold: float = 0.15) -> None:
        self.color_score_threshold = color_score_threshold

    def should_alert(
        self,
        candidate: dict,
        mission: dict | None,
        openclaw_result: dict | None = None,
    ) -> bool:
        if not mission or not mission.get("active"):
            return False

        if candidate.get("mission_id") != mission.get("mission_id"):
            return False  # stale event

        if candidate.get("color_score", 0) < self.color_score_threshold:
            return False

        target_color = mission.get("target_color")
        if target_color and candidate.get("color") != target_color:
            return False

        # Phase 3: body_type 지정 미션일 때 OpenClaw 결과로 최종 판단
        target_body_type = mission.get("target_body_type")
        if target_body_type:
            if openclaw_result is None:
                return False
            if not openclaw_result.get("confirmed", False):
                return False
            if openclaw_result.get("confidence", "low") not in ("medium", "high"):
                return False
            if not openclaw_result.get("target_body_type_match", False):
                return False

        return True

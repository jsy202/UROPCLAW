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

        # LLM(OpenClaw)이 항상 최종 판단: confirmed=false면 알림 차단
        if openclaw_result is not None:
            if not openclaw_result.get("confirmed", False):
                return False
            conf = openclaw_result.get("confidence", "low")
            if conf not in ("medium", "high", "n/a"):  # n/a = LLM 오류 시 자동 통과
                return False
            # body_type 지정 미션이면 추가로 body_type 일치 확인
            if mission.get("target_body_type"):
                if not openclaw_result.get("target_body_type_match", False):
                    return False

        return True

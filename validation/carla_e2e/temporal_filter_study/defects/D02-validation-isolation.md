# D02 — 비교 도구의 색상·시계 격리

발견: 검증용 대안 구현을 테스트로 검사하다가 late-HSV 구조가 추적 시 이미 색상 라벨을 사용하고, replay clock이 production tracker module에 남는 것을 발견했다. 실제 평가 분석 전 발견.

원인: 현재 구조의 tracker 입력을 재사용하면서 late-HSV의 정보 접근 제한을 누락. 시뮬레이션 시계 주입 후 원복 누락.

해결: late-HSV tracker에는 unknown만 전달하고, N회 존재 확인 이후 현재 검출의 캐시된 색상을 읽는다. tracker.update 동안만 시계를 주입하고 finally로 복구한다.

검증: test_late_hsv_tracking_does_not_use_color_before_confirmation 및 test_branch_does_not_change_production_tracker_clock이 각각 수정 전 실패/수정 후 통과. 기존 temporal·v2 parity 포함10tests통과. 캡처는 이 구현을 호출하지 않으므로 재수집 불필요.

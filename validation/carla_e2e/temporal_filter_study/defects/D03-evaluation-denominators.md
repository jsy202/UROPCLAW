# D03 — 독립 리뷰로 발견한 평가 오류

실제 평가 결과를 분석하기 전에 별도 리뷰어가 세 문제를 발견했다.
1. 동일하거나 비슷하게 겹친GT box도 무조건 최고IoU actor로 정답을 지정했다.
2. 검출이 GT비가시 구간을 이어서 서로 다른GT출현이 합쳐질 수 있었다.
3. COMPLETE60개라는 개수만 확인해서 조건누락/중복이나 짧은실행을 허용할 수 있었다.

수정: 고정IoU모호성규칙(.30최소/.05차이)으로 ambiguous분리 및 후보IoU로그. GT가시출현과 검출출현을 독립집계. 정확한조건set/1800frame/연속index·센서frame·시각/이미지실재 검증.

증거: test_equal_overlapping_ground_truth_is_ambiguous, test_detection_cannot_bridge_two_gt_visible_episodes, test_capture_validation_rejects_short_and_noncontiguous는 수정전실패/수정후통과. 전체13studytests통과. 원본프레임·GT투영이 보존되어 재수집없이 평가 로직을 수정할 수 있었다.

추가 리뷰: VLM 음성 대조군과 사례 이미지가 원본 capture actor를 재사용해, 같은 모호성 규칙을 모든 소비 코드에 적용했다. cleanup 필드 누락도 거부하고 생성 차량 수+카메라1과 대조한다. VLM 테스트의 최초 실행은 모듈 경로 설정 오류로 중단되어 경로를 수정한 뒤 기존 동작에서 실제 assertion 실패를 다시 확인하고 수정 후 통과했다. 추가 회귀 테스트 포함18개 study 테스트가 통과했다.

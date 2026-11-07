> 초기 180초 탐색의 역사적 명세다. 현재 600초·30개 수집과 평가 범위는 [후속 명세](../progressive_filter_study/PROTOCOL.ko.md)를 따른다.

# 수집량 축소 — 사용자 최신 지시
원래60개계획을사용자가과하다고판단해40개에서종료했다. Town10HD_Opt:3환경×2교통량×5seed=30개, Town03_Opt:맑은낮×2교통량×5seed=10개다. 총72000프레임/120분, 개발16개/평가24개. 두번째지도의날씨일반화는검증하지않는다. 이조건set을완료검사에사용한다. 이미완료된40개이외추가수집은하지않으며실제VLM금지지시도유지한다. 아래60개계획문단은기록으로보존하되현재실행범위가아니다.

# 실행 범위 변경 — 사용자 최신 지시 우선
본 실험 수집38개 완료 시점에 사용자가 실제VLM호출 금지를 명시했다. 이후 실제VLM표본·production VLMworker큐실측·실측VLM서비스시간기반큐모델은 실행하지 않는다. 자동후처리는 analyze/stress/make_cases/audit_labels/report만 실행한다. execution_policy.json의allow_real_vlm=false를 실제호출용CLI의진입점에서검사한다. 지시이전연결확인1장은본실험결과에서제외하고별도기록으로만보존한다. 아래사전계획중실제VLM을포함하는문단은폐기된계획기록이며현재범위가아니다. 후보요청트리거/목표누락/필터확인지연 비교와60개CARLA이미지수집은계속한다.

# 사전 실험 명세
사용자 승인: 제안된 설계를 실제 실행하며 N=3이 우수하지 않아도 결과를 보고한다.

## 고정 조건
CARLA 0.9.13, RenderOffScreen, Low quality, RGB800x600 FOV90, synchronous10Hz, no_rendering_mode=False. YOLOv8s conf.40 IoU.45. 기존 HSV/IoU tracker/per-target30s dedup 사용. 추론은 원본 센서 입력에서 한 번, 모든 비교에 동일 출력 재사용. RGB JPEG(q85) 전 프레임 저장(재분석 입력은 캐시된 원본 검출·색상 결과). CARLA ID는 평가에만 사용.

두 지도 Town10HD_Opt/Town03_Opt, 맑은 낮/흐린 낮은 태양/비·젖은 노면, 차량30/70, seed101/102(dev),201/202/203(test), 실행180초+사전안정화10초. 총60실행. 카메라는 평가 전 파일럿에서 고정. 페인트를 무시하는 알려진 microlino는 미리 제외하고, 추가 불일치는 증거와 함께 별도 집계한다.

## 비교
A: 현재 batch 규칙 N1/2/3/5/7/10 x dedup on/off.
B: N3 현재 unknown제외 / 전체분모2of3 / 3of3 / sliding2of3.
C: HSV/Temporal/Dedup 전체8조합(HSV없음의 temporal은 차량 존재 지속성).
D: 현재 / HSV로 미리 제거후tracking / tracking지속성확인후현재색 판별. 대안D는 순서뿐 아니라 증거 사용 방식도 변경됨을 명시.

## 평가
도달률: FOV출현 기준 및 YOLO검출된 출현 기준을 모두 보고. 출현은 GT가 마지막으로 보인 때부터1초 넘게 사라지면 새 episode. 원본 GT 투영·line-of-sight는 근사라 한계 명시. 검출·이벤트는 IoU>=.30로 정답에 연결하며 미연결 이벤트 별도 집계. 지연은 first YOLO detection -> confirmation / request의 simulation time; miss는 제외하지 않고 별도 보고. YOLO GPU동기화 wall latency 및 CPU branch latency는 별도. VLM응답/최종경보 지연으로 주장하지 않음.

N선택은 dev만: N1 대비 검출조건부 도달률 감소<=2%p, 확인지연p95<=.5s 조건 충족 중 false+unassociated requests 우선, 총요청수 다음, 낮은N 최종 동률해소. 안전한 선택이 없으면 단일N 추천 불가. test에서 paired clip-bootstrap95% CI(개발/평가분리,2000 resamples). frame을 독립표본으로 취급하지 않음. 2%p 비열등성을 통계적으로 입증하지 못하면 탐색적 근거로만 서술.

실제 VLM을 쓰지 못하면 request proxy만 보고하고 RealVLM 정확도·비용·queue latency 미측정으로 남긴다. 결과 보고에 이 차이를 명시한다. 기존구현 수정 없이 비교.

## 평가 도구 리뷰 후 명확화 (최종 평가 분석 전)
정답 연결은 최고IoU>=.30이며, 두번째 후보도>=.30이고 IoU차이가<=.05이면 ambiguous로 분리한다. 캡처시 저장된 최고IoU actor는 원자료로 보존하고 평가시 투영box로 연결을 다시 계산한다. ambiguous 요청은 전체 요청 및 미확정 요청에 포함하며 mapped precision에서 제외한다. 후보 actor/IoU목록도 사건 로그에 보존한다.

GT-visible 출현과 detector 출현은 각각 독립적으로 gap>1초에 나눈다. GT출현은 검출이 사이를 이어도 합치지 않는다. 주지표/개발N선택의 detected_recall은 검출로 정의한 출현 기준이다. 보조 visible_recall은 GT가 보인 출현 기준이며 해당 GT관측 프레임에서 요청에 도달했는지 집계한다. 후자는 raycast visibility의 근사오차에 민감하므로 검출조건부 지표와 혼용하지 않는다. 두 기준 episode CSV를 모두 제공한다.

완료조건은 정확한60조건tuple, 개발/평가seed분리, 매실행1800연속frame/index/simulationtimestamp,1800이미지실재,actor정리성공까지 확인한다. 60개 COMPLETE표시만으로 완료 판정하지 않는다.

구조 CPU replay시간에는 실제HSV연산을 포함하지 않으므로 전체구조의 실제계산절감으로 해석하지 않는다. 캡처된 원본YOLO/HSV wall-time과 별도 표로 제공한다. 합성 두차량 근접상황의 dedup 한계는 실제교통발생 빈도와 분리한다.

탐색적 추가: 합성 통제 입력에서 동시에 보이는 두 파란 차량이 fragment로 합쳐지는 것을 발견해 `dedup_active_guard` 비교를 추가한다. 현재매칭된 다른track의target에는 새track을fragment로 연결하지 않는 검사다. N선택에 사용하지 않으며 baseline은 변경하지 않는다. 합성재현 수정전1/2요청 -> 대안2/2요청 확인. 실제녹화에서도 기존N3와 비교하되 후속탐색으로 구분한다. 순차적으로 나타나는 다른차량·IDswitch 문제까지 해결한다고 주장하지 않는다.

지연 해석: 확인된 출현만의p95는 누락이 많은 설정에 유리할 수 있다. 그래서 두 설정 모두 확인/요청된 동일episode의 지연차이(대안-N1)도 paired_delays.csv로 제공하며, 기준만성공/대안만성공 수를 함께 남긴다. 최초검출부터 확인까지에는 색상판별이 안정화될 때까지의 시간도 포함된다. N-1개 관측의 이론적추가지연과 실측전체확인지연을 혼동하지 않는다.

追加 지연 탐색: 실제VLM표본에서 관측한 서비스시간으로 10Hz입력/worker1개/대기queue20/worker시점dedup의FIFO모델을 계산한다. production과 같은 위치에서dedup을 적용하되 결과queue·스케줄링·검출drop은 모델링하지 않음. 보고되는 대기/처리/drop은 실측종단간지연이 아닌 가정하의 모의추정임을 명시한다. 실제VLM표본도 전체성능검증이 아니라 표본 응답/서비스시간 확인으로 구분한다.

보조지표 추가(평가분석전): 재등장출현과고유차량을구분한다. 같은녹화에서검출된고유목표actor 중한번이라도요청된actor 비율을함께보고한다. 의도된30초재요청억제까지출현미도달로집계되는점이있어원래출현지표만으로새목표차량누락을주장하지않는다. 기존개발N선택기준은유지한다.

실제후단실측 추가: 고정평가녹화Town10HD_Opt_clear_v70_s201의캐시후보를실제10Hz속도로production OpenClawWorker+대기queue20에입력한다. N3와개발선택N을각각180초실행(선택동일/없음이면N1대조), 남은큐를배출한뒤실제enqueue/dequeue/VLM시작/완료/drop을보고한다. detector/camera는캐시이며AlertWorker를만들지않으므로최종경보측정아님. 설정별실제서비스시간이다를수있어N의순수효과로단정하지않고고정서비스모의비교와함께해석한다. 앞단측정/개발선택기준은변경하지않는다.

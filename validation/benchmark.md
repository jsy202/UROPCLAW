# Replay Benchmark — UROPCLAW (Post-project Validation)

## 0. Historical Result (연구 당시)

이 저장소에는 연구 당시의 수치 결과(OpenClaw 호출 절감률, FPS, drop rate 등)가 **기록되어 있지 않다.** README §8에는 지표의 정의만 있다.

따라서 아래의 새 benchmark 결과를 연구 당시 결과와 비교하거나 대체하지 않는다. 연구 당시 수치가 다른 곳(발표 자료 등)에 있더라도, 그 수치는 아래의 측정 조건과 다르다.

- 실제 CARLA 카메라를 썼다.
- 실제 YOLOv8과 실제 VLM을 썼다.
- baseline A/B에 dedup이 적용된 상태였다(DEF-U06).

## 1. 무엇을 측정했는가

목적은 AI 모델의 성능이 아니라 **파이프라인의 시스템 동작**이다. 같은 합성 입력에 대해 단계별 후보 감소, VLM 호출 수, 큐 깊이, drop, 경보 지연을 반복 측정했다.

| 항목 | 값 |
|---|---|
| 도구 | `tools/replay_benchmark.py` → JSON(`benchmark_results/`) → `tools/benchmark_table.py` |
| 입력 | 합성 장면 2개를 번갈아 push: `uropclaw1` = 파란 박스(미션 목표), `uropclaw2` = 빨간 박스(비목표). agent당 150 프레임, 총 300 프레임, 프레임 간격 20 ms |
| Detector | `FakeDetector`(윤곽 검출). **YOLOv8 아님** |
| VLM | `SuccessVLM`, 고정 지연 **0.2 s**(인위적 값). **실제 VLM 아님** |
| Alert | 기록용 sender(성공 반환). **Discord 아님** |
| 반복 | 모드(A, B, C, proposed)당 3회 |
| 환경 | Linux 6.8.0 x86_64, Python 3.10.12, opencv-python-headless 5.0.0, 2026-10-01 |

### 지표 정의

| 지표 | 정의 |
|---|---|
| E2E push→alert | alert sender가 호출된 시각 − 경보 대상 프레임의 push 시각. 3 프레임 시간적 확인에 걸리는 대기는 포함하지 않는다(경보를 일으킨 마지막 프레임 기준) |
| throughput | `frames_processed / (replay + drain 시간)`. drain은 큐가 빌 때까지 기다린 시간이다. 따라서 VLM 단계가 느리면 이 값이 낮아진다 |
| max queue depth | 5 ms 간격 샘플링의 최댓값 |
| detector stage | `yolo_latency_ms_list`(FakeDetector 실행 시간) |

### 측정하지 않은 것 (Not measured)

- YOLOv8 추론 지연
- HSV, tracking 단계별 지연(파이프라인에 계측점이 없음)
- 실제 VLM 지연과 정확도
- Discord 전달 지연
- CARLA 카메라 캡처 지연
- GPU 사용률

## 2. Before / After

| 구분 | commit | 상태 |
|---|---|---|
| Before | `312b8a3` | 주입 경계와 테스트만 있고, DEF-U01~U06 수정 전 |
| After | `0d79f2d` | DEF-U01~U06 수정 후. 이후 commit은 테스트와 도구만 추가했고 파이프라인 코드는 같다 |

두 측정 모두 같은 benchmark 도구, 같은 입력, 같은 장비에서 실행했다. Before에 없던 지표는 `n/a`로 표시했다. 형식은 `평균 [최소–최대]`, n = 반복 수다.

#### mode `A`

| metric | Before (312b8a3, n=3) | After (0d79f2d, n=3) |
|---|---|---|
| frames pushed | 300 | 300 |
| frames processed | 300 | 300 |
| frames dropped | 0 | 0 |
| candidates dropped | n/a | 0 |
| detections (FakeDetector) | 0 | 0 |
| candidates raised | 10 | 10 |
| duplicates suppressed | 9 | 0 |
| VLM calls | 1 | 10 |
| alerts attempted (alerts_sent) | 0 | 0 |
| alerts delivered | n/a | 0 |
| max frame-queue depth | 1 | 1 |
| max candidate-queue depth | 0 | 0 |
| max result-queue depth | 0 | 0 |
| detector stage mean ms (FakeDetector) | n/a | n/a |
| E2E push->alert mean ms | n/a | n/a |
| E2E push->alert max ms | n/a | n/a |
| throughput frames/s | 42.5 [42.5–42.5] | 42.5 [42.5–42.5] |

#### mode `B`

| metric | Before (312b8a3, n=3) | After (0d79f2d, n=3) |
|---|---|---|
| frames pushed | 300 | 300 |
| frames processed | 300 | 300 |
| frames dropped | 0 | 0 |
| candidates dropped | n/a | 247 |
| detections (FakeDetector) | 300 | 300 |
| candidates raised | 300 | 300 |
| duplicates suppressed | 298 | 0 |
| VLM calls | 2 | 53 |
| alerts attempted (alerts_sent) | 0 | 0 |
| alerts delivered | n/a | 0 |
| max frame-queue depth | 0.7 [0–1] | 1 |
| max candidate-queue depth | 16.7 [16–17] | 20 |
| max result-queue depth | 0 | 1 |
| detector stage mean ms (FakeDetector) | 5.6 [5.6–5.6] | 5.6 [5.6–5.7] |
| E2E push->alert mean ms | n/a | n/a |
| E2E push->alert max ms | n/a | n/a |
| throughput frames/s | 42.2 [42.2–42.2] | 27.3 [27.2–27.3] |

#### mode `C`

| metric | Before (312b8a3, n=3) | After (0d79f2d, n=3) |
|---|---|---|
| frames pushed | 300 | 300 |
| frames processed | 300 | 300 |
| frames dropped | 0 | 0 |
| candidates dropped | n/a | 0 |
| detections (FakeDetector) | 300 | 300 |
| candidates raised | 50 | 50 |
| duplicates suppressed | 0 | 0 |
| VLM calls | 0 | 0 |
| alerts attempted (alerts_sent) | 0 | 0 |
| alerts delivered | n/a | 0 |
| max frame-queue depth | 1 | 1 |
| max candidate-queue depth | 0 | 0 |
| max result-queue depth | 0 | 0 |
| detector stage mean ms (FakeDetector) | 5.6 [5.6–5.6] | 5.6 [5.6–5.7] |
| E2E push->alert mean ms | n/a | n/a |
| E2E push->alert max ms | n/a | n/a |
| throughput frames/s | 42.3 [42.2–42.3] | 42.3 [42.2–42.3] |

#### mode `proposed`

| metric | Before (312b8a3, n=3) | After (0d79f2d, n=3) |
|---|---|---|
| frames pushed | 300 | 300 |
| frames processed | 300 | 300 |
| frames dropped | 0 | 0 |
| candidates dropped | n/a | 0 |
| detections (FakeDetector) | 300 | 300 |
| candidates raised | 50 | 50 |
| duplicates suppressed | 49 | 49 |
| VLM calls | 1 | 1 |
| alerts attempted (alerts_sent) | 1 | 1 |
| alerts delivered | n/a | 1 |
| max frame-queue depth | 1 | 1 |
| max candidate-queue depth | 1 | 1 |
| max result-queue depth | 0 | 0.3 [0–1] |
| detector stage mean ms (FakeDetector) | 5.6 [5.6–5.7] | 5.6 [5.6–5.6] |
| E2E push->alert mean ms | 208.0 [206.8–208.7] | 208.3 [208.2–208.5] |
| E2E push->alert max ms | 208.0 [206.8–208.7] | 208.3 [208.2–208.5] |
| throughput frames/s | 42.4 [42.3–42.4] | 42.4 [42.4–42.4] |

## 3. 해석 (측정된 범위 안에서만)

- **proposed:** 수정 전후 동작이 같다.
  - 300 프레임에서 탐지 300건, candidate 50건(목표 색상만, 3 프레임 확인).
  - dedup으로 VLM은 1회, 경보는 1건.
  - E2E 약 208 ms 중 200 ms는 인위적인 VLM 지연이다. 나머지 약 8 ms에는 그 프레임의 detector 처리(FakeDetector 약 5.6 ms), HSV 분류와 tracking, 큐 대기, crop 저장과 event 기록, sender 호출이 모두 포함된다. 단계별로 나눠 측정하지는 않았다.
- **baseline B:** DEF-U06 수정 전에는 300 candidate 중 298건이 dedup으로 억제되어 VLM이 2회만 호출되었다. baseline 정의("dedup 없음")와 다르다.
  - 수정 후에는 VLM이 53회 호출되었다.
  - 0.2 s의 VLM 지연 때문에 candidate 큐(20)가 포화되어 **247건이 `candidates_dropped`** 로 기록되었다.
  - 필터링이 없는 구성에서는 VLM 단계가 병목이 된다는 것이 **이번 측정으로 처음 관측되었다.** 실제 VLM의 지연은 측정하지 않았으므로, 실제 환경에서 drop이 얼마나 날지는 알 수 없다.
  - throughput 27.3은 drain 시간을 포함한 값이다.
- **baseline A:** 30 프레임마다 candidate 1건씩, 10건이 생겼다. 수정 전에는 dedup으로 VLM 1회, 수정 후에는 10회였다. A의 candidate는 색상과 신뢰도 정보가 없어 AlertPolicy가 경보를 막는다(경보 0).
- **baseline C:** VLM 0회로 정의대로 동작했다.
- **frames_dropped:** 이 입력 속도(50 fps 상당)에서는 모든 모드에서 0이었다.

## 4. 재현 방법

```bash
pip install -r requirements-test.txt
python3 tools/replay_benchmark.py --modes A B C proposed --frames 150 --repeat 3 --out validation/benchmark_results/after_head.json
python3 tools/benchmark_table.py validation/benchmark_results/before_312b8a3.json validation/benchmark_results/after_head.json
```

Before 측정은 `git archive 312b8a3`으로 만든 스냅샷에 같은 benchmark 도구를 복사해 실행했다. 도구는 그 commit 이후에 만들어졌기 때문이다.

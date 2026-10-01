# Test Report — UROPCLAW AI Pipeline (Post-project Validation)

> 연구 종료 후(2026-10-01) 수행한 검증이다. 연구 당시의 CARLA, YOLOv8, VLM, Discord를 이용한 실행은 재현하지 않았다. 이 저장소에는 연구 당시의 수치 결과가 없다.

## 1. 환경

| 항목 | 값 |
|---|---|
| OS / Python | Linux 6.8.0 x86_64 / 3.10.12 |
| 테스트 의존성 | pytest 8.4.2, numpy 2.2.6, opencv-python-headless 5.0.0, requests. `pip --target`으로 별도 디렉터리에 설치했고 시스템 패키지는 건드리지 않았다 |
| 미사용 | CARLA, ultralytics/torch/GPU, `claude` CLI, Discord |
| baseline | `research-baseline` = `f0d7651`. 주입 경계가 없어 이 commit에서는 테스트를 실행할 수 없다. Before 기준은 경계만 추가한 `312b8a3`이다 |

## 2. 결과 (최종 `ec519cd`)

| 구분 | 수 |
|---|---|
| 전체 | 36 (integration 25, unit 11) |
| PASS | 36 |
| XFAIL / FAILED | 0 / 0 |

10회 연속 실행에서 매회 `36 passed`(19.6 s 안팎)였다(`evidence/repeat_runs.txt`).

## 3. 결함 이력

| 단계 | commit | pytest |
|---|---|---|
| 주입 경계 (동작 변경 없음) | `a70e54d` | – |
| replay, fakes, 테스트 18건 + 결함 5건 xfail | `312b8a3` | 13 passed, 5 xfailed |
| U01–U03 VLM 장애 집계 | `f20d51f` | 17 passed, 2 xfailed |
| U04 alert 전달 결과 집계 | `6878cb4` | 21 passed, 1 xfailed |
| U05 candidate drop 분리 | `2bfced2` | 22 passed |
| U06 기록 (benchmark 설계 중 발견) | `33c794d` | 23 passed, 2 xfailed |
| U06 baseline A/B dedup 수정 | `0d79f2d` | 25 passed |
| unit 11건, benchmark 도구, CI | `ec519cd` | 36 passed |

## 4. Before 교차 검증

현재 테스트 36건을 `312b8a3` 코드에 `--runxfail`로 실행한 결과: **11 failed, 25 passed**(`evidence/baseline_crosscheck.txt`).

실패한 11건은 U01–U06 테스트 7건과 수정으로 생긴 경로를 검사하는 보강 테스트 4건(깨진 JSON, delivered 집계, Discord sender 반환값 2건)이다.

## 5. Negative control

- 결함 테스트는 수정 전 commit에서 strict xfail(실제 실패) 상태였고, 수정 commit에서 PASS로 전환되었다.
- 테스트 작성 중 `glob()` generator를 그대로 assert하면 항상 참이 되는 실수가 있었다. 수정 후 `any(...)`로 실제 파일 존재를 확인한다.

## 6. Benchmark

`benchmark.md`를 참조한다. 합성 입력과 fake 의존성으로 Before/After를 각 3회씩 측정했다. YOLO와 실제 VLM 지연은 측정하지 않았다.

## 7. CI

`.github/workflows/test.yml`은 GitHub에서 아직 실행되지 않았다(push 안 함). 로컬 재현 결과: 문법 OK, unit 11 passed, integration 25 passed, benchmark smoke 정상(`evidence/ci_steps_local.txt`).

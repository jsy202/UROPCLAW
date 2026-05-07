# UROPCLAW — AI 멀티에이전트 차량 감시 시스템

> CARLA 시뮬레이터 + YOLOv8 + HSV 색상 필터 + OpenClaw (Discord AI 봇) 를 결합한  
> 실시간 차량 탐지 및 Discord 경보 시스템

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [주요 기능](#3-주요-기능)
4. [프로젝트 구조](#4-프로젝트-구조)
5. [사전 요구사항](#5-사전-요구사항)
6. [빠른 시작](#6-빠른-시작)
7. [Discord 사용법](#7-discord-사용법)
8. [평가 베이스라인](#8-평가-베이스라인)
9. [환경 변수](#9-환경-변수)
10. [파이프라인 상세](#10-파이프라인-상세)

---

## 1. 프로젝트 개요

UROPCLAW는 CARLA 자율주행 시뮬레이터 환경에서 **특정 색상의 차량을 자동 탐지**하고, 탐지 결과를 **Discord 채널에 한국어로 실시간 보고**하는 AI 멀티에이전트 감시 시스템입니다.

### 핵심 시나리오

```
사용자 (Discord) → 감시 명령 → AI 에이전트 수신 → mission.json 활성화
                                                         ↓
CARLA 시뮬레이터 → 카메라 피드 → YOLOv8 탐지 → HSV 색상 필터
                                                         ↓
                              탐지 이벤트 → Discord 경보 전송 ←
```

- **사용자**는 Discord에서 아무 에이전트에게나 한국어로 명령합니다.
- **4개의 AI 에이전트(uropclaw1~4)**가 각자의 카메라 구역을 독립적으로 감시합니다.
- 목표 차량이 카메라에 잡히면 즉시 Discord로 경보를 보냅니다.

---

## 2. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                       CARLA 시뮬레이터                               │
│  Town03_Opt / Town05 맵 — 동기화 모드 (20 FPS)                       │
│                                                                     │
│  [Observer Vehicle 1]  [Observer Vehicle 2]                         │
│     uropclaw1 탑승         uropclaw2 탑승                            │
│  [Observer Vehicle 3]  [Observer Vehicle 4]                         │
│     uropclaw3 탑승         uropclaw4 탑승                            │
│                                                                     │
│  [배경 NPC 20대]  [목표 색상 차량 2대]                                │
└─────────────┬───────────────────────────────────────────────────────┘
              │ 카메라 프레임 (1280×720, 4방향)
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    harness / Pipeline (5스레드)                      │
│                                                                     │
│  Thread-1: CarlaTickThread  — world.tick() 동기화                   │
│  Thread-2: YoloWorker       — YOLOv8s 추론 + HSV 색상 필터          │
│                               IoU 트래커 + 시간적 확인(3프레임)       │
│  Thread-3: OpenClawWorker   — 차종 검증 요청 (body_type 지정 시)     │
│  Thread-4: AlertWorker      — detection_event.json 작성             │
│  Thread-5: MetricsWriter    — 5초마다 metrics.json 갱신             │
└─────────────┬───────────────────────────────────────────────────────┘
              │ detection_event.json
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│              OpenClaw Gateway (Docker, port 18795)                   │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │uropclaw1 │  │uropclaw2 │  │uropclaw3 │  │uropclaw4 │           │
│  │ AI 봇   │  │ AI 봇   │  │ AI 봇   │  │ AI 봇   │           │
│  │Zone 1   │  │Zone 2   │  │Zone 3   │  │Zone 4   │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       └──────────────┴─────────────┴──────────────┘                 │
│                              Discord                                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 에이전트 역할

| 에이전트 | 역할 | 담당 구역 |
|---------|------|---------|
| uropclaw1 | 독립 감시 모니터 (Zone 1) | x≈245, y≈0 (동부) |
| uropclaw2 | 독립 감시 모니터 (Zone 2) | x≈-145, y≈-8 (서부) |
| uropclaw3 | 독립 감시 모니터 (Zone 3) | x≈-26, y≈-8 (중앙) |
| uropclaw4 | 독립 감시 모니터 (Zone 4) | x≈-149, y≈107 (북서부) |

> **모든 에이전트는 동등한 권한을 가집니다.** 사용자는 어느 에이전트에게나 명령할 수 있으며,  
> 명령을 받은 에이전트가 `mission.json`을 활성화합니다.

---

## 3. 주요 기능

### 🔍 YOLOv8 차량 탐지
- 모델: `yolov8s.pt` (경량 모델)
- 탐지 대상: 승용차(car), 오토바이(motorcycle), 버스(bus), 트럭(truck)
- 신뢰도 임계값: 0.40 / IoU 임계값: 0.45

### 🎨 HSV 색상 필터
- 8가지 색상 분류: 빨간색, 파란색, 초록색, 노란색, 흰색, 검은색, 회색/은색, 주황색
- 바운딩박스의 **중앙 60%** 영역만 분석 (상하 20% 제거로 하늘·도로 노이즈 제거)
- 최소 픽셀 비율 15% 미만은 `unknown`으로 처리

### 📦 IoU 트래커 + 시간적 확인
- **IoU 트래커**: 탐지 간 Intersection-over-Union으로 동일 차량 추적 (임계값 0.30)
- **재연결 로직**: 일시적으로 사라진 차량을 2초 내 재연결 (이전 트랙 ID 복원)
- **시간적 확인(TemporalConfirm)**: 연속 3프레임에서 동일 색상이 60% 이상이어야 후보 승격

### 🤖 OpenClaw AI 검증 (body_type 지정 시)
- 사용자가 차종(세단, SUV 등)을 명시한 경우에만 AI 검증 요청
- `verification_request.json` → AI 분석 → `verification_response.json`
- 타임아웃: 30초

### 🔔 Discord 경보
- 탐지 이벤트 발생 시 해당 구역 에이전트가 Discord에 한국어로 보고
- 탐지된 차량 이미지 크롭 첨부
- 중복 경보 억제: 동일 트랙 30초 / Discord 알림 120초 쿨다운

### 📊 평가 메트릭
- `frames_received`, `frames_processed`, `frame_drop_rate`
- `openclaw_call_reduction_rate` (핵심 지표: OpenClaw 호출 절감률)
- `avg_yolo_latency_ms`, `pipeline_fps`
- 4가지 베이스라인 비교 지원

---

## 4. 프로젝트 구조

```
uropclaw-docker/
│
├── docker-compose.yml          # OpenClaw 게이트웨이 컨테이너 정의
├── Dockerfile                  # Node.js 24 기반 OpenClaw 이미지
├── entrypoint.sh               # 환경변수 검증 후 OpenClaw 게이트웨이 실행
├── openclaw.json               # 에이전트 4개 설정 (Discord 연결, 모델 설정)
├── .env.example                # 환경변수 템플릿
│
├── harness/                    # Python 감시 파이프라인
│   ├── harness.py              # 메인 엔트리포인트 (CCTV 고정 카메라 모드)
│   ├── start.py                # 시나리오 스크립트 (차량 탑승 카메라 모드)
│   ├── config.py               # 전역 설정 (경로, CARLA 파라미터, 카메라)
│   ├── requirements.txt        # Python 패키지
│   │
│   ├── core/                   # 파이프라인 핵심
│   │   ├── pipeline.py         # 5스레드 파이프라인 (핵심)
│   │   ├── mission.py          # mission.json 읽기/쓰기
│   │   ├── orchestrator.py     # 에이전트 오케스트레이터
│   │   ├── session_store.py    # 세션 DB
│   │   └── state.py            # 공유 상태
│   │
│   ├── perception/             # 컴퓨터 비전
│   │   ├── yolo_detector.py    # YOLOv8 추론 래퍼
│   │   ├── color_filter.py     # HSV 색상 분류 (8색)
│   │   ├── iou_tracker.py      # IoU 기반 다중 객체 추적
│   │   ├── temporal_confirm.py # 3프레임 다수결 확인
│   │   └── deduplicator.py     # 중복 경보 억제
│   │
│   ├── sensors/                # CARLA 센서 관리
│   │   ├── camera.py           # 카메라 부착 / 프레임 수집
│   │   └── manager.py          # CARLA 연결 / NPC 스폰 / 맵 로드
│   │
│   ├── policy/
│   │   └── alert_policy.py     # 경보 발송 정책 (미션 일치 여부 확인)
│   │
│   ├── evaluation/
│   │   ├── metrics.py          # 메트릭 수집 / JSON 저장
│   │   └── baseline.py         # 4가지 베이스라인 모드 정의
│   │
│   ├── gateway/
│   │   └── proxy.py            # CARLA Proxy API (FastAPI)
│   │
│   └── obs/
│       ├── logger.py           # 이벤트 로거
│       └── evaluator.py        # 평가 리포트 생성
│
└── workspaces/                 # 에이전트별 작업 공간 (Docker 볼륨)
    ├── uropclaw1/
    │   ├── CLAUDE.md           # 에이전트 시스템 프롬프트
    │   ├── state/
    │   │   ├── mission.json          # 현재 미션 (active/target_color 등)
    │   │   ├── detection_event.json  # 최신 탐지 이벤트
    │   │   └── metrics.json          # 파이프라인 메트릭
    │   └── skills/
    │       └── carla-detect/SKILL.md  # 감시 명령 처리 스킬
    ├── uropclaw2/  (동일 구조)
    ├── uropclaw3/  (동일 구조)
    └── uropclaw4/  (동일 구조)
```

---

## 5. 사전 요구사항

| 구성요소 | 버전 | 비고 |
|---------|------|------|
| CARLA | 0.9.13 ~ 0.9.14 | UE4 기반 자율주행 시뮬레이터 |
| Python | 3.10+ | harness 실행 환경 |
| Docker + Docker Compose | 최신 | OpenClaw 게이트웨이 컨테이너 |
| NVIDIA GPU | 권장 | YOLOv8 추론 가속 |
| OpenClaw | npm 최신 | AI 봇 프레임워크 |
| Discord 봇 4개 | — | uropclaw1~4 각각의 토큰 필요 |

---

## 6. 빠른 시작

### Step 1. CARLA 서버 실행

```bash
# GUI 모드
./CarlaUE4.sh

# 헤드리스 (디스플레이 없는 서버)
./CarlaUE4.sh -RenderOffScreen

# Docker 이미지 사용 시
docker run --privileged --gpus all --net=host \
  carlasim/carla:0.9.14 ./CarlaUE4.sh -RenderOffScreen
```

CARLA가 포트 **2000**에서 준비될 때까지 대기합니다.

---

### Step 2. 환경 변수 설정

```bash
cd uropclaw-docker
cp .env.example .env
```

`.env` 파일을 열어 실제 값으로 수정합니다:

```env
DISCORD_BOT_TOKEN_UROPCLAW1=your_token_here
DISCORD_BOT_TOKEN_UROPCLAW2=your_token_here
DISCORD_BOT_TOKEN_UROPCLAW3=your_token_here
DISCORD_BOT_TOKEN_UROPCLAW4=your_token_here

OPENCLAW_MODEL=openai-codex/gpt-5.5   # 또는 google/gemini-2-flash

CARLA_HOST=localhost
CARLA_PORT=2000
CARLA_MAP=Town03_Opt
BG_VEHICLE_COUNT=20
TARGET_VEHICLE_COUNT=2
RANDOM_SEED=42
```

---

### Step 3. OpenClaw 게이트웨이 실행

```bash
docker compose up -d --build

# 봇 4개가 Discord에 연결됐는지 확인
docker compose logs -f
```

정상 출력 예:
```
discord gateway metrics: {"latency":190,"reconnects":0,...}
discord gateway metrics: {"latency":192,"reconnects":0,...}
```

---

### Step 4. Python 의존성 설치

```bash
cd harness
pip install -r requirements.txt

# CARLA Python API (CARLA 설치 경로에 맞게 조정)
pip install /path/to/CARLA/PythonAPI/carla/dist/carla-*.whl
```

---

### Step 5. 감시 파이프라인 실행

**시나리오 모드** (차량에 카메라 탑재 — 권장):
```bash
cd harness
python start.py --target-color blue --bg-count 20
```

**CCTV 고정 카메라 모드**:
```bash
python harness.py --map Town03_Opt --target-color blue --bg-count 20
```

**순찰 모드** (observer 차량이 자율주행하며 감시):
```bash
python start.py --target-color blue --patrol
```

---

### Step 6. Discord에서 명령

```
@uropclaw2 파란 차량 보이면 알려줘
@uropclaw3 빨간 SUV 추적해줘
@uropclaw1 감시 그만해
```

---

## 7. Discord 사용법

### 감시 명령

아무 에이전트에게나 멘션하여 감시 명령을 보냅니다.

```
@uropclaw1 파란 차량 도주했다 보이면 답장
@uropclaw3 빨간 세단 놓쳤는데 찾아줘
@uropclaw4 흰색 SUV 있으면 알려줘
```

### 지원 색상

| 한국어 | 영어 |
|-------|------|
| 파란/파랑/파란색 | blue |
| 빨간/빨강/빨간색 | red |
| 흰/흰색/하얀 | white |
| 검은/검정/검은색 | black |
| 초록/녹색 | green |
| 노란/노랑 | yellow |
| 회색/은색 | gray_silver |
| 주황/주황색 | orange |

### 지원 차종 (선택사항)

| 한국어 | 영어 |
|-------|------|
| 세단 | sedan |
| SUV / 에스유브이 | suv |
| 트럭 / 화물차 | truck |
| 버스 | bus |
| 밴 / 승합차 | van |
| 오토바이 / 바이크 | motorcycle |
| 스포츠카 | sports_car |

### 감시 중단

```
@uropclaw2 그만
@uropclaw2 중단
@uropclaw2 멈춰
```

### 경보 형식

탐지 시 담당 에이전트가 다음 형식으로 Discord에 보고합니다:

```
🚨 [구역2 카메라] 차량 포착
━━━━━━━━━━━━━━━━━━━━
색상: 파란색
차종: 승용차
신뢰도: 87%
색상 일치도: 92%
포착 시각: 2026-05-07 18:23:11
━━━━━━━━━━━━━━━━━━━━
[차량 이미지 첨부]
```

---

## 8. 평가 베이스라인

성능 비교를 위한 4가지 모드를 지원합니다:

```bash
python start.py --baseline A         # 매 30번째 프레임만 OpenClaw 전달 (무작위)
python start.py --baseline B         # YOLO만 사용, 색상 필터 없음
python start.py --baseline C         # YOLO + 색상 필터, OpenClaw 없음
python start.py --baseline proposed  # 전체 파이프라인 (기본값)
```

| 모드 | YOLO | 색상 필터 | IoU 트래커 | 시간적 확인 | OpenClaw 검증 |
|------|------|---------|-----------|-----------|--------------|
| A | ✗ | ✗ | ✗ | ✗ | ✗ |
| B | ✓ | ✗ | ✗ | ✗ | ✓ |
| C | ✓ | ✓ | ✓ | ✓ | ✗ |
| proposed | ✓ | ✓ | ✓ | ✓ | ✓ (차종 지정 시) |

### 핵심 평가 지표

- **OpenClaw 호출 절감률** = 1 − (openclaw_calls / frames_processed)
  - proposed 모드가 베이스라인 대비 얼마나 AI 호출을 줄이는지 측정
- **프레임 드롭률** = frames_dropped / frames_received
- **파이프라인 FPS** = frames_processed / uptime_seconds

---

## 9. 환경 변수

| 변수 | 기본값 | 설명 |
|------|-------|------|
| `DISCORD_BOT_TOKEN_UROPCLAW1` | — | uropclaw1 Discord 봇 토큰 (필수) |
| `DISCORD_BOT_TOKEN_UROPCLAW2` | — | uropclaw2 Discord 봇 토큰 (필수) |
| `DISCORD_BOT_TOKEN_UROPCLAW3` | — | uropclaw3 Discord 봇 토큰 (필수) |
| `DISCORD_BOT_TOKEN_UROPCLAW4` | — | uropclaw4 Discord 봇 토큰 (필수) |
| `OPENCLAW_MODEL` | `google/gemini-3-flash-preview` | AI 모델 |
| `CARLA_HOST` | `localhost` | CARLA 서버 호스트 |
| `CARLA_PORT` | `2000` | CARLA 서버 포트 |
| `CARLA_MAP` | `Town05` | 로드할 CARLA 맵 |
| `BG_VEHICLE_COUNT` | `20` | 배경 NPC 차량 수 |
| `TARGET_VEHICLE_COUNT` | `2` | 목표 색상 차량 수 |
| `RANDOM_SEED` | `42` | 재현성을 위한 시드 |

---

## 10. 파이프라인 상세

### 5스레드 구조

```
frame_queue ──▶ [YoloWorker]
                     │ 탐지 결과 + 색상 확인
                     ▼
              candidate_queue ──▶ [OpenClawWorker]
                                       │ AI 검증 (차종 지정 시)
                                       ▼
                                  result_queue ──▶ [AlertWorker]
                                                        │ detection_event.json 작성
                                                        ▼
                                                   Discord 에이전트 경보
```

### 데이터 흐름 (JSON 파일 IPC)

```
mission.json          ← AI 에이전트가 활성화 (active: true, target_color)
detection_event.json  ← AlertWorker가 탐지 시 작성
metrics.json          ← MetricsWriter가 5초마다 갱신
verification_request.json  ← OpenClawWorker가 차종 검증 요청 작성
verification_response.json ← AI 에이전트가 검증 결과 작성
```

### 카메라 설정

각 observer 차량에 4방향 카메라 부착:

| 방향 | 오프셋 | 시야각 |
|------|-------|-------|
| front | (2.5, 0, 1.2m), pitch -5° | 90° |
| rear | (-2.5, 0, 1.2m), pitch -5° | 90° |
| left | (0, -1.0, 1.5m), yaw -90° | 90° |
| right | (0, 1.0, 1.5m), yaw +90° | 90° |

해상도: **1280 × 720**

### 색상 필터 HSV 범위

```python
"red":         H(0-10 | 165-179),  S(60-255), V(40-220)
"blue":        H(95-135),           S(60-255), V(30-220)
"green":       H(35-85),            S(50-255), V(30-210)
"yellow":      H(18-38),            S(80-255), V(80-255)
"white":       H(0-179),            S(0-45),   V(160-255)
"black":       H(0-179),            S(0-255),  V(15-65)
"gray_silver": H(0-179),            S(0-45),   V(65-160)
"orange":      H(10-20),            S(100-255),V(60-230)
```

---

## 라이선스

이 프로젝트는 연구/교육 목적으로 제작되었습니다.  
CARLA 시뮬레이터는 [CARLA 라이선스](https://carla.org/), YOLOv8은 [AGPL-3.0](https://github.com/ultralytics/ultralytics)을 따릅니다.

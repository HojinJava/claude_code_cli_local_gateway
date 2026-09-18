---
description: claude-pool의 실제 제한·확장 설정(워커 min/max, 각종 타임아웃, job 보관·상한, 드레인 타임아웃, 클라이언트·운영 스크립트 대기값)과 측정 근거의 확인 상태
tags: [architecture]
status: as-built
---

# 15. 비기능 요구사항 (as-built)

코드에 구현된 제한·확장 설정값을 기록한다. 성능·가용성 목표치와 부하 가정은 코드·추적 파일에 없다(`미확인`).

## 워커 풀 확장

| 항목 | 값(코드 폴백) | 설정 키 | 적용 위치 |
|---|---|---|---|
| 상시 예열 수 | 4 | `CLAUDE_POOL_MIN_WORKERS` | 기동 예열 `pool.py:47`, 반납 시 1개 보충 `pool.py:199`, 초과분 축소 하한 `pool.py:223`. 유휴 축소가 발동하면 이 하한은 적용되지 않는다 |
| 동시 워커 상한 | 30 | `CLAUDE_POOL_MAX_WORKERS` | 증가 `pool.py:154`, `pool.py:177`, 대기 수요 보충 `pool.py:200` |
| 증가 단위 | 대기 루프 반복당 1개 예약, 스폰은 락 안에서 1개씩 | — | `pool.py:122-124`, `pool.py:154-155`, `pool.py:174-183` |
| idle 축소 주기 | 30.0초 | `CLAUDE_POOL_SCALE_DOWN_INTERVAL_SEC` | `pool.py:208` |
| 초과분 축소 기준 | 60.0초(스폰 시각 기준 경과) | `CLAUDE_POOL_IDLE_TIMEOUT_SEC` | `pool.py:229`, 기준 시각 `worker.py:62` |
| 유휴 축소 기준(0까지) | 60.0초(마지막 반납 이후 경과) | `CLAUDE_POOL_IDLE_SCALE_TO_ZERO_SEC` | 판정 `pool.py:216-224`, 기준 시각 기록 `pool.py:40`·`pool.py:198`. `0`이면 판정이 항상 거짓이라 기존 하한이 유지된다 |
| 워커 재사용 | 없음(요청 1건당 워커 1개 소모) | — | `pool.py:190-198` |
| 모델 | 데몬당 1개(기본 `"sonnet"`) | `CLAUDE_POOL_MODEL` | `worker.py:45` |

- 수평 확장은 코드상 다른 포트의 데몬을 추가로 띄우는 형태만 지원 구조가 있다(포트별 pid 파일 `daemon.py:16-23`). 데몬 간 부하 분산 코드는 없다.
- **유휴 상태의 하한은 0이다.** 마지막 반납 이후 `idle_scale_to_zero_sec`가 지나고 배포된 워커가 없으면(`self._total == len(self._idle)`) 축소 루프가 idle 워커를 전부 종료한다(`pool.py:216-232`). 데몬 프로세스와 바인딩은 유지되며, 다음 요청은 기존 획득 경로가 온디맨드로 스폰한다. 배포된 워커가 하나라도 있으면 그 주기는 건너뛰므로 실행 중인 요청·job의 워커는 대상이 아니다.
- 축소 뒤 재예열은 점진적이다. `release`가 반납 1건당 1개만 보충한다(`pool.py:199-204`).
- `min_workers <= max_workers` 검증은 없다([03-configuration](03-configuration.md#검증)).

## 타임아웃

| 항목 | 값 | 설정 키 | 적용 위치 |
|---|---|---|---|
| 요청 실행 기본 타임아웃 | 120.0초 | `CLAUDE_POOL_TIMEOUT_SEC`, 요청별 `timeout_sec` | `server.py:93`, `worker.py:84-87` |
| 워커 획득 대기 | 60.0초 | `CLAUDE_POOL_ACQUIRE_TIMEOUT_SEC` | `pool.py:128-134` |
| 풀 종료 드레인 | 5.0초(`STOP_DRAIN_TIMEOUT_SEC`) | 설정 불가(모듈 상수) | `pool.py:11`, `pool.py:70` |
| 클라이언트 health 탐침 | 1.0초 | 인자 없음 | `client.py:52` |
| 클라이언트 자동 기동 대기 | 15.0초, 0.2초 간격 | `start_timeout_sec` 인자 | `client.py:41`, `client.py:76-81` |
| 클라이언트 기본 요청 소켓 타임아웃 | 30.0초 | `_call`의 `request_timeout` | `client.py:89` |
| 클라이언트 `generate` 소켓 타임아웃 | `(timeout_sec or 120.0) + 5.0`초 | `timeout_sec` 인자 | `client.py:118` |
| 클라이언트 `health`/`api_info` | 5.0초 | 인자 없음 | `client.py:196`, `client.py:200` |
| 클라이언트 `wait` 폴링 | 1.0초 간격, 상한 없음(기본) | `poll_interval_sec`, `timeout_sec` 인자 | `client.py:147-148`, `client.py:155` |
| `daemon_ctl stop` 종료 확인 | 10.0초, 0.2초 간격 | `STOP_TIMEOUT_SEC` 상수 | `scripts/daemon_ctl.py:21`, `daemon_ctl.py:155-163` |

- 요청 `timeout_sec`의 상·하한 검사는 없다(`server.py:92-95`).

## 백그라운드 job 보관

| 항목 | 값 | 설정 키 | 적용 위치 |
|---|---|---|---|
| 종결 job 보관 기간 | 600.0초 | `CLAUDE_POOL_JOB_RETENTION_SEC` | `jobs.py:167-172` |
| job 저장 상한 | 500 | `CLAUDE_POOL_MAX_JOBS` | `jobs.py:177-183` (실행 중 job은 제거 대상 아님) |
| reap 시점 | `submit()`·`list()` 호출 시 | — | `jobs.py:90`, `jobs.py:138` |
| prompt preview 길이 | 80자 | `PROMPT_PREVIEW_CHARS` 상수 | `jobs.py:32` |
| 실행 중 job 수 제한 | 없음. 실제 동시 실행은 워커 획득(`max_workers`, 획득 타임아웃)에 묶인다 | — | `jobs.py:89-103`, `runner.py:41` |

## 제한 정책 부재 항목

| 항목 | 코드 상태 |
|---|---|
| 요청 속도 제한(rate limit) | 없음 |
| 요청 본문 최대 크기 | 코드에서 설정하지 않음(`web.Application(middlewares=...)`만 지정, `server.py:52`). aiohttp 기본값 적용 여부는 `미확인` |
| 동시 HTTP 연결 수 제한 | 코드에서 설정하지 않음 |
| 목록 페이지네이션 | 없음(`GET /jobs`, `server.py:148-150`) |
| 자동 재시도·서킷 브레이커 | 없음(`runner.py:37-67`) |
| 영속성·재시작 후 복구 | 없음. 풀·job 상태는 메모리에만 있다 |

## 가용성 관련 구현

- 스폰 실패 시 대기자 조기 실패: `pool.py:158-167`.
- 예열 워커 사망 감지 보고: `/health`의 `idle_alive`·`healthy` → [14-observability-logging](14-observability-logging.md).
- 데몬 비정상 종료 시 워커 정리: Windows Job Object(`winjob.py:1-9`) → [12-security-auth](12-security-auth.md).

## 측정 조건과 결과

| 항목 | 상태 |
|---|---|
| 예열 대비 cold 스폰 지연 | 측정 스크립트 `scripts/bench_cold_vs_warm.py`는 있으나 결과 수치가 추적 파일에 없다 — `미확인` |
| stream-json 입력 지연 허용 | 조사 스크립트 `scripts/investigate_stream_json_timeout.py`는 있으나 결과가 추적 파일에 없다 — `미확인` |
| 워커당 메모리·CPU, 처리량, 지연 분포 | 코드·추적 파일(분석 대상)에 없음 — `미확인` |
| 코드 주석에 적힌 관찰 기록 | `worker.py:16-17`(플래그 없을 때 스폰당 터미널 창 1개, 있을 때 0개), `worker.py:69`(스폰 약 150ms 후 종료하는 CLI가 배포됨), `tests/test_integration.py:62-63`(가짜 CLI 스폰 약 5-17ms). 이번 실측에서 재현하지 않았다 |

- 사용자 문서(`README.md`)에 기재된 수치는 분석 제외 대상이라 옮기지 않았다.

## 실측 근거

절마다 기준 시점이 다르다.

### 이번 갱신 기준 — `7cc905fc828abeb790f3e8d46de469e7021ed137`

- 갱신한 절: 「워커 풀 확장」과 「타임아웃」의 풀 관련 행. 유휴 축소 기준 시간을 추가하고 `pool.py` 줄 번호를 이번 tree에서 다시 읽었다.
- 확인한 소스: [pool.py](../../../src/claude_pool/pool.py)(`release`·`_scale_down_loop`), [config.py](../../../src/claude_pool/config.py)
- 확인 범위: 설정값과 적용 지점 정적 확인. 유휴 축소를 실제 데몬에서 관찰하지 않았고 부하·성능 측정도 하지 않았다.

### 이전 기준 — `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`

- 위에 적지 않은 나머지 절과 `pool.py`·`config.py` 외 파일의 줄 번호는 이 commit 기준이며 이번에 다시 확인하지 않았다.
- 당시 확인한 소스: [worker.py](../../../src/claude_pool/worker.py), [server.py](../../../src/claude_pool/server.py), [jobs.py](../../../src/claude_pool/jobs.py), [runner.py](../../../src/claude_pool/runner.py), [client.py](../../../src/claude_pool/client.py), [daemon.py](../../../src/claude_pool/daemon.py), [winjob.py](../../../src/claude_pool/winjob.py), [daemon_ctl.py](../../../scripts/daemon_ctl.py), 조사 스크립트 2개, [test_integration.py](../../../tests/test_integration.py)
- 미확인: 성능·가용성 목표, 실제 운영 설정값, 위 측정 항목의 수치, aiohttp 기본 제한값, 유휴 축소가 실제 환경에서 절약하는 자원량.

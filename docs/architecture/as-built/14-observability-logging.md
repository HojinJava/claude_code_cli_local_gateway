---
description: claude-pool의 /health 통계 구성, last_error·last_spawn_error 기록 지점, logging 모듈 미사용 등 로깅·계측 실측
tags: [architecture]
status: as-built
---

# 14. 관측성·로깅 (as-built)

## 요약

- `src/`에는 `logging` 모듈 import, `print`, 메트릭·트레이싱 라이브러리 사용이 없다(`grep`으로 확인).
- 데몬 상태 관측 수단은 `GET /health` JSON 하나다. 대시보드·경보·수집기 설정은 저장소에 없다.
- 운영 스크립트 `scripts/daemon_ctl.py`가 `/health`를 사람이 읽는 형태로 `print`한다(`daemon_ctl.py:103-122`).

## `/health` 구성

`handle_health`(`src/claude_pool/server.py:160-163`) = `WorkerPool.stats()` + `"jobs": JobStore.stats()`.

| 키 | 산출 | 위치 |
|---|---|---|
| `min_workers`, `max_workers` | 설정값 | `pool.py:235-236` |
| `total` | 카운터 `_total`(idle + 대여 중) | `pool.py:237` |
| `idle` | `len(_idle)` — 카운터 | `pool.py:238` |
| `idle_alive` | `_idle` 중 `is_alive()`인 수 — 생존 확인 | `pool.py:233`, `pool.py:239` |
| `busy` | `_total - len(_idle)` | `pool.py:240` |
| `healthy` | `idle_alive == len(_idle)` (idle 0개면 true) | `pool.py:241-244` |
| `last_spawn_error` | `str(_last_spawn_error)` 또는 null | `pool.py:245-247` |
| `last_error` | `_last_error` | `pool.py:248` |
| `jobs.total` | 저장된 job 수(reap하지 않음) | `jobs.py:185-187` |
| `jobs.running` | `status == "running"`인 job 수 | `jobs.py:186` |

- `idle`과 `idle_alive`를 함께 두는 이유는 docstring에 있다: 예열 워커 프로세스가 이미 죽어도 카운터만으로는 정상처럼 보이는 경우를 드러내기 위함(`pool.py:225-232`).
- `is_alive()`는 `returncode is None` 검사이며 docstring이 best-effort라고 명시한다(`worker.py:64-74`). 따라서 `idle_alive`·`healthy`도 같은 한계를 가진 값이다.
- `stats()`는 락을 잡지 않는 동기 메서드다(`pool.py:224`).

## 오류 상태 기록 지점

| 필드 | 기록 | 해제 |
|---|---|---|
| `_last_error` | `note_failure(error)` `pool.py:106-107` ← `runner._note` `runner.py:73-74` (모든 실행 실패: pool_unavailable, timeout, WorkerError, is_error 결과) | `note_success()` `pool.py:109-110` ← `runner.py:71-72` (실행 성공) |
| `_last_spawn_error` | `_try_spawn_and_add_idle_locked`의 예외 포착 `pool.py:100-101` (증가·보충 스폰 실패) | 다음 스폰 성공 `pool.py:89` |

- 두 필드는 마지막 한 건만 보관하며 이력·카운트·시각은 남기지 않는다.
- `pool.start()`의 초기 스폰 실패는 `_last_spawn_error`에 기록되지 않고 예외로 전파된다(`pool.py:41-43`, `pool.py:83-90`).
- 400 요청 오류, 404, Host 가드 403은 이 필드에 기록되지 않는다(`runner.execute`를 거치지 않음).

## 로그 출력

| 출처 | 동작 | 위치 |
|---|---|---|
| 데몬 애플리케이션 코드 | 로그 호출 없음 | `src/claude_pool/` 전체 |
| aiohttp access log | `web.AppRunner(app)`를 인자 없이 생성하고 logging 설정 코드가 없다. 실제 출력 여부는 `미확인` | `daemon.py:34` |
| 자동 기동된 데몬의 stdio | stdin/stdout/stderr 모두 `DEVNULL` | `client.py:63-67` |
| 워커 stderr | 파이프로 수집해 non-zero 종료 시 `WorkerError` 메시지에만 포함 | `worker.py:51-53`, `worker.py:92-96` |
| 워커 stdout | `result` 줄만 파싱, 나머지 줄은 버림 | `worker.py:98-111` |
| `scripts/daemon_ctl.py` | 상태·결과 `print`, usage는 stderr | `daemon_ctl.py:108-121`, `daemon_ctl.py:181` |
| 조사 스크립트 | 측정·관찰 결과 `print` | `scripts/bench_cold_vs_warm.py:72-83`, `scripts/investigate_stream_json_timeout.py:55-71` |

## 상관관계·마스킹

- 요청 ID·트레이스 ID 생성 코드는 없다. job에는 `job_id`가 있으나 로그와 연결되지 않는다.
- 오류 텍스트(워커 stderr 포함)의 민감정보 마스킹 코드는 없다 → [12-security-auth](12-security-auth.md#시크릿-취급).

## 테스트 위치

- `/health` 키·liveness·빈 풀 healthy·`last_error` 기록/해제: `tests/test_server.py:52-59`, `tests/test_server.py:112-135`, `tests/test_server.py:163-196`, `tests/test_server.py:214-223`
- job 수: `tests/test_jobs.py:223-226`
- 클라이언트 health: `tests/test_client.py:51-54`

## 실측 근거

- 기준 commit: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`
- 확인한 소스: [pool.py](../../../src/claude_pool/pool.py), [server.py](../../../src/claude_pool/server.py), [runner.py](../../../src/claude_pool/runner.py), [jobs.py](../../../src/claude_pool/jobs.py), [worker.py](../../../src/claude_pool/worker.py), [daemon.py](../../../src/claude_pool/daemon.py), [client.py](../../../src/claude_pool/client.py), [daemon_ctl.py](../../../scripts/daemon_ctl.py), 조사 스크립트 2개. `src/`·`scripts/`에서 `logging`·`logger`·`print(`를 `grep`했다.
- 확인 범위: 정적 확인. 데몬을 실행해 실제 출력·health 응답을 관찰하지 않았다.
- 미확인: aiohttp access log의 실제 출력 여부와 대상, 운영 중 health 조회 주기·외부 모니터링 연결.

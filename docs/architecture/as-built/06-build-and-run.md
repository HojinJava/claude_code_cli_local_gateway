---
description: claude-pool의 확인된 설치·실행·종료 절차와 전제 조건, 명령별 출처(매니페스트·코드·스크립트·사용자 문서) 구분
tags: [architecture]
status: as-built
---

# 06. 빌드와 실행 (as-built)

각 명령에 출처를 붙였다. **코드 확인**은 매니페스트·코드·스크립트로 존재가 확인된 진입점, **사용자 문서 기재**는 `README.md`·`CLAUDE.md`(분석 제외 문서)에만 쓰여 있는 명령 문자열이다. 이번 실측에서 어떤 명령도 실행하지 않았다.

## 전제 조건

| 전제 | 근거 |
|---|---|
| Python `>=3.11` | `pyproject.toml:4` |
| `aiohttp>=3.9`, Windows에서는 `pywin32>=306` 설치 | `pyproject.toml:5-8` |
| `claude_pool` 패키지가 import 가능해야 함(src 레이아웃, pytest `pythonpath` 설정 없음) | `pyproject.toml:31-32` |
| 워커 실행 파일: `PoolConfig.claude_cmd`(기본 `["claude"]`)가 실행 가능해야 함 | `src/claude_pool/config.py:39`, `src/claude_pool/worker.py:49-56` |
| `claude` CLI의 로그인 상태 | 코드가 확인하지 않음(`미확인`). 로그인 문제는 실행 결과 분류로만 드러난다 → [13-error-policy](13-error-policy.md) |
| `scratch_dir` 쓰기 가능 | 기동 시 `mkdir(parents=True, exist_ok=True)`(`daemon.py:27`), pid 파일 기록(`daemon.py:38`) |

## 설치·빌드

| 절차 | 출처 |
|---|---|
| 빌드 백엔드는 setuptools(`setuptools.build_meta`), 패키지는 `src/`에서 탐색 | 코드 확인: `pyproject.toml:27-32` |
| 개발 의존성은 `dev` extras | 코드 확인: `pyproject.toml:10-15` |
| `pip install -e ".[dev]"` | 사용자 문서 기재(`README.md`, `CLAUDE.md`) |

- 배포 산출물(wheel/sdist) 생성·게시 절차, CI 파이프라인, 컨테이너 설정은 저장소에 없다.

## 실행

| 방법 | 동작 | 출처 |
|---|---|---|
| `python -m claude_pool.daemon` | 포그라운드 데몬. `PoolConfig.from_env()` → `run_daemon` | 코드 확인: `src/claude_pool/daemon.py:65-71`. 명령 문자열은 사용자 문서에도 기재 |
| `claude-pool-daemon` | 위와 같은 `main()` 콘솔 스크립트 | 코드 확인: `pyproject.toml:17-18` |
| `ClaudePoolClient()` 생성(`auto_start=True` 기본) | `/health`가 1초 안에 열리지 않으면 `[sys.executable, "-m", "claude_pool.daemon"]`을 stdio `DEVNULL`로, Windows에서는 `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP`로 기동하고 최대 15초 health 대기 | 코드 확인: `src/claude_pool/client.py:36-82` |
| `python scripts/daemon_ctl.py start` | 클라이언트 자동 기동 경로로 기동(이미 응답하면 기동하지 않음) 후 `status` 출력 | 코드 확인: `scripts/daemon_ctl.py:1-8`, `daemon_ctl.py:125-129` |
| `python scripts/daemon_ctl.py status` (인자 없음도 동일) | `/health` 조회 결과와 검증된 pid 출력. 응답 없으면 종료 코드 1 | 코드 확인: `scripts/daemon_ctl.py:103-122`, `daemon_ctl.py:178-183` |
| `CLAUDE_POOL_MODEL=haiku python scripts/daemon_ctl.py start` 형태의 환경변수 지정 | `daemon_ctl`이 `PoolConfig.from_env()`를 읽으므로 같은 변수로 대상 결정 | 코드 확인: `scripts/daemon_ctl.py:5-7`(docstring) |
| 다른 포트로 두 번째 데몬 | pid 파일이 포트별(`daemon-{port}.pid`)이라 공존 | 코드 확인: `src/claude_pool/daemon.py:16-23`. 명령 예시는 사용자 문서 기재 |

- `python scripts/daemon_ctl.py`는 `claude_pool`을 import하므로 패키지 설치 후 실행을 전제한다(`scripts/daemon_ctl.py:17-19`).
- 설정 키는 [03-configuration](03-configuration.md)을 본다.

## 테스트 실행

| 절차 | 출처 |
|---|---|
| pytest 설정(`asyncio_mode = "auto"`, `filterwarnings`) | 코드 확인: `pyproject.toml:20-25` |
| `pytest -v` | 사용자 문서 기재(`README.md`, `CLAUDE.md`) |

상세는 [04-testing-strategy](04-testing-strategy.md).

## 종료

| 방법 | 동작 | 출처 |
|---|---|---|
| SIGTERM/SIGINT | `loop.add_signal_handler`로 종료 이벤트 설정. 등록이 `NotImplementedError`/`AttributeError`/`ValueError`면 건너뛴다(주석: Windows·비 메인 스레드 미지원, Ctrl+C로 풀림) | 코드 확인: `src/claude_pool/daemon.py:54-62` |
| `python scripts/daemon_ctl.py stop` | pid 파일 pid의 명령줄에 `claude_pool.daemon`이 있으면 그 pid가 대상. pid 파일로 대상을 못 찾았는데 포트가 응답하면, 명령줄로 찾은 데몬 후보가 정확히 1개일 때만 그 pid가 대상(포트와의 대응은 확인하지 않음, `scripts/daemon_ctl.py:139-152`). Windows `taskkill /F /PID`, 그 외 `SIGTERM`. 10초 동안 0.2초 간격 확인 | 코드 확인: `scripts/daemon_ctl.py:132-166` |
| `python scripts/daemon_ctl.py restart` | `stop`이 0일 때만 `start` | 코드 확인: `scripts/daemon_ctl.py:169-172` |

- 정상 종료 시 정리 순서(pid 파일 삭제 → `runner.cleanup()` → `jobs.shutdown()` → `pool.stop()`)는 [10-data-flow](10-data-flow.md#데몬-종료-순서).
- 강제 종료(`taskkill /F`)에서는 Python `finally`가 실행되지 않으므로 pid 파일이 남을 수 있다는 전제가 주석에 있다(`daemon.py:41-42`). 워커 정리는 Windows Job Object에 맡긴다는 주석이 `scripts/daemon_ctl.py:159-160`, `src/claude_pool/worker.py:57-60`에 있다.

## 복구 절차 (코드에 구현된 것)

| 상황 | 처리 | 근거 |
|---|---|---|
| 남은 pid 파일, 데몬 없음 | `stop`이 pid 파일을 지우고 `stopped (nothing running ...)`, 종료 코드 0 | `scripts/daemon_ctl.py:133-138` |
| pid 파일 없음, 포트는 응답 | 명령줄로 찾은 데몬이 정확히 1개면 그 pid를 종료, 아니면 후보별 수동 종료 명령 출력 후 종료 코드 1 | `scripts/daemon_ctl.py:139-152` |
| 기동 중 풀 시작 실패 | `run_daemon`이 예외 전파, `finally`에서 pid 파일 삭제·jobs·pool 정리 | `src/claude_pool/daemon.py:31-51` |

## 실측 근거

- 기준 commit: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`
- 확인한 소스: [pyproject.toml](../../../pyproject.toml), [daemon.py](../../../src/claude_pool/daemon.py), [client.py](../../../src/claude_pool/client.py), [config.py](../../../src/claude_pool/config.py), [worker.py](../../../src/claude_pool/worker.py), [daemon_ctl.py](../../../scripts/daemon_ctl.py). 명령 출처 구분을 위해 `README.md`의 명령 줄만 검색했다(사실 근거로 사용하지 않음).
- 확인 범위: 정적 읽기. 설치·데몬·스크립트·테스트를 실행하지 않았다.
- 미확인: 명령의 실제 성공 여부, 대상 환경의 `claude` CLI 설치·로그인 상태, 비 Windows에서의 자동 기동 분리 동작.

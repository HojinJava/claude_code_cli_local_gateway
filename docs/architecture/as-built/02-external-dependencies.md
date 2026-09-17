---
description: claude-pool의 매니페스트 선언 패키지·버전 제약·용도, lockfile 부재, stdlib 전용 클라이언트, 외부 실행 의존(claude CLI·OS 도구)
tags: [architecture]
status: as-built
---

# 02. 외부 의존성 (as-built)

## 매니페스트와 lockfile

- 유일한 매니페스트는 [`pyproject.toml`](../../../pyproject.toml)이다.
- lockfile은 없다. 기준 commit tree에 `requirements*.txt`, `poetry.lock`, `uv.lock`, `Pipfile.lock` 등 잠금 파일이 존재하지 않는다. 따라서 실제 설치되는 버전은 설치 시점의 해석 결과에 따르며 저장소로는 `미확인`이다.

## 선언 패키지

| 구분 | 패키지 | 버전 제약 | 선언 위치 | 코드상 용도 |
|---|---|---|---|---|
| Python | (인터프리터) | `>=3.11` | `pyproject.toml:4` | 전체. `X \| None` 타입 표기와 `from __future__ import annotations` 사용 |
| 런타임 | `aiohttp` | `>=3.9` | `pyproject.toml:6` | HTTP 서버(`web.Application`, 미들웨어, `json_response`, `AppRunner`/`TCPSite`) — `src/claude_pool/server.py:5`, `src/claude_pool/daemon.py:8`. 테스트의 `aiohttp.ClientSession` — `tests/test_daemon.py:7` |
| 런타임(Windows 한정) | `pywin32` | `>=306; sys_platform == 'win32'` | `pyproject.toml:7` | `win32api`·`win32con`·`win32job`으로 kill-on-close Job Object 생성·할당 — `src/claude_pool/winjob.py:14-17`. 테스트는 `win32process`도 사용 — `tests/test_winjob.py:13-15`, `tests/test_pool.py:262-264` |
| dev extras | `pytest` | `>=8.0` | `pyproject.toml:12` | 테스트 러너 |
| dev extras | `pytest-asyncio` | `>=0.23` | `pyproject.toml:13` | `asyncio_mode = "auto"`(`pyproject.toml:21`)로 async 테스트·fixture 실행 |
| dev extras | `pytest-aiohttp` | `>=1.0` | `pyproject.toml:14` | `aiohttp_client` fixture — 예: `tests/test_server.py:25-29` |
| 빌드 | `setuptools` | `>=68` | `pyproject.toml:28` | `build-backend = "setuptools.build_meta"` |

## 표준 라이브러리 전용 영역

- 클라이언트 `src/claude_pool/client.py`는 `from __future__ import annotations`와 `json`, `os`, `subprocess`, `sys`, `time`, `urllib.error`, `urllib.request`만 import하고(`client.py:1-9`) `claude_pool`의 다른 모듈이나 서드파티를 import하지 않는다.
- `config.py`, `errors.py`, `runner.py`, `jobs.py`, `apidocs.py`, `worker.py`는 stdlib과 패키지 내부 모듈만 사용한다. `apidocs.py`는 `importlib.metadata.version("claude-pool")`으로 설치 메타데이터에서 버전을 읽고, 없으면 `"0+unknown"`을 쓴다(`src/claude_pool/apidocs.py:18-21`).
- 스크립트 3개 중 `bench_cold_vs_warm.py`·`investigate_stream_json_timeout.py`는 stdlib만 사용한다. `daemon_ctl.py`는 `claude_pool` 패키지를 import한다(`scripts/daemon_ctl.py:17-19`).

## 외부 실행 의존

| 대상 | 사용 위치 | 내용 |
|---|---|---|
| `claude` CLI | `src/claude_pool/worker.py:34-56` | `PoolConfig.claude_cmd`(기본 `["claude"]`, `config.py:39`) 뒤에 stream-json 플래그를 붙여 자식 프로세스로 실행. 설치 여부·버전·로그인 상태는 코드가 확인하지 않는다(`미확인`) |
| `claude` CLI (직접) | `scripts/bench_cold_vs_warm.py:14-28`, `scripts/investigate_stream_json_timeout.py:13-26` | `CLAUDE_BIN = "claude"`, `MODEL = "haiku"`로 직접 스폰 |
| Python 인터프리터(자식) | `src/claude_pool/client.py:74` | `sys.executable -m claude_pool.daemon`으로 데몬 기동 |
| `powershell` (`Get-CimInstance`) | `scripts/daemon_ctl.py:35-39`, `daemon_ctl.py:69-75` | Windows에서 pid의 명령줄 조회·데몬 프로세스 탐색 |
| `ps`, `pgrep` | `scripts/daemon_ctl.py:41-43`, `daemon_ctl.py:77-79` | 비 Windows에서 같은 목적 |
| `taskkill` | `scripts/daemon_ctl.py:92-94` | Windows에서 `/F /PID`로 데몬 종료 |

외부 시스템과의 관계 전체는 [08-system-context](08-system-context.md)에서 다룬다.

## 실측 근거

- 기준 commit: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`
- 확인한 소스: [pyproject.toml](../../../pyproject.toml), `src/claude_pool/*.py` 12개와 `scripts/*.py` 3개의 import 절, [winjob.py](../../../src/claude_pool/winjob.py), [worker.py](../../../src/claude_pool/worker.py), [client.py](../../../src/claude_pool/client.py), [daemon_ctl.py](../../../scripts/daemon_ctl.py), 테스트의 서드파티 import
- 확인 범위: 기준 commit tree 파일 목록에서 잠금 파일 부재 확인, import 문 정적 확인. 패키지 설치·버전 해석은 수행하지 않았다.
- 미확인: 실제 설치된 패키지 버전, `claude` CLI 버전과 지원 플래그, 대상 환경의 `powershell`/`ps`/`pgrep`/`taskkill` 존재 여부.

---
description: claude-pool의 린터·포매터 설정 부재 사실과 코드에서 확인한 네이밍·import·타입 표기·주석 관례
tags: [architecture]
status: as-built
---

# 05. 코딩 관례 (as-built)

## 도구 설정

- 린터·포매터·타입 검사 설정은 저장소에 없다. `pyproject.toml`에 `[tool.ruff]`·`[tool.black]`·`[tool.isort]`·`[tool.mypy]` 섹션이 없고, `setup.cfg`·`tox.ini`·`.flake8`·`ruff.toml`·`mypy.ini`·`.editorconfig`·`.pre-commit-config.yaml` 파일도 기준 commit tree에 없다.
- `.gitattributes`도 없다. 줄바꿈 정규화 규칙은 `미확인`이다.
- 따라서 아래 항목은 도구가 강제하는 규칙이 아니라 코드에서 관찰한 관례다.

## 관찰한 관례

| 관례 | 확인 범위 | 근거 |
|---|---|---|
| 모듈 첫 import가 `from __future__ import annotations` | `src/claude_pool/`의 비어 있지 않은 11개 모듈 전부, `scripts/` 3개 전부, `tests/fixtures/fake_claude_cli.py`. 그 외 테스트 모듈과 빈 `__init__.py`에는 없다 | 예: `src/claude_pool/server.py:1`, `scripts/daemon_ctl.py:9` |
| 내장 제네릭·`X \| None` 타입 표기 | 패키지 전반 | `src/claude_pool/pool.py:26`, `src/claude_pool/pool.py:30`, `src/claude_pool/jobs.py:42` |
| 패키지 내부는 명시적 상대 import | `src/claude_pool/` | `src/claude_pool/server.py:7-12`, `src/claude_pool/runner.py:13-15` |
| 테스트·스크립트는 절대 import(`from claude_pool.x import ...`) | `tests/`, `scripts/daemon_ctl.py` | `tests/test_server.py:7-8`, `scripts/daemon_ctl.py:17-19` |
| 클래스 `PascalCase`, 함수·변수 `snake_case`, 모듈 상수 `UPPER_SNAKE_CASE` | 전반 | `STOP_DRAIN_TIMEOUT_SEC`(`pool.py:11`), `DEFAULT_RETRY_AFTER_SEC`(`errors.py:20`), `PROMPT_PREVIEW_CHARS`(`jobs.py:32`), `STOP_TIMEOUT_SEC`(`daemon_ctl.py:21`) |
| 모듈 내부용 이름은 `_` 접두 | 전반 | `_read_prompt_request`(`server.py:77`), `_note`(`runner.py:70`), `_RATE_LIMIT_PATTERNS`(`errors.py:22`), `_ERROR_SCHEMA`(`apidocs.py:122`) |
| 초 단위 값은 `_sec`, 밀리초는 `_ms` 접미 | 설정·응답 키 | `acquire_timeout_sec`(`config.py:29`), `retry_after_sec`(`errors.py:60`), `duration_ms`(`runner.py:24`) |
| bool을 돌려주는 메서드·속성·키는 `is_` 접두 | 일부 | `is_alive`(`worker.py:64`), `is_terminal`(`jobs.py:49`), `is_loopback_host`(`config.py:12`), 결과 키 `is_error`(`worker.py:119`) |
| 값 객체는 `@dataclass(frozen=True)` | `Outcome`, `Failure` | `runner.py:18`, `errors.py:53` |
| 문자열은 f-string으로 조립 | 전반 | `server.py:42`, `pool.py:128` |
| 주석·docstring은 영어이며 "왜"를 설명 | 전반. 설계 이유·실측 관찰·되돌리면 안 되는 이유를 적는다 | `worker.py:12-19`(CREATE_NO_WINDOW 이유와 관찰), `server.py:30-38`(DNS rebinding), `runner.py:1-7`, `daemon.py:41-42`, `daemon.py:48-49` |
| 모듈 docstring은 모듈의 존재 이유를 서술 | `runner.py`, `errors.py`, `jobs.py`, `apidocs.py`, `winjob.py`, `scripts/*.py`, `fake_claude_cli.py` | `errors.py:1-12`, `jobs.py:1-11` |
| 테스트 이름은 기대 동작을 서술하는 긴 `test_<동작>` 형태 | `tests/` | `tests/test_jobs.py:129` `test_max_jobs_drops_oldest_finished_but_never_running_ones` |
| 파일 텍스트 I/O에 `encoding="utf-8"` 명시 | pid 파일 | `daemon.py:38`, `daemon_ctl.py:27` |

## 예외 위치

- 테스트 모듈 대부분은 `from __future__ import annotations`를 쓰지 않는다(위 표).
- `tests/` 모듈 중 모듈 docstring이 있는 것은 `tests/test_host_guard.py:1-3`과 가짜 CLI `tests/fixtures/fake_claude_cli.py:1-7`뿐이다.
- `print` 출력은 `src/`에는 없고, `scripts/`와 가짜 CLI(`tests/fixtures/fake_claude_cli.py:31`, `37`, `40`, `48`)에 있다([14-observability-logging](14-observability-logging.md)).

반복 구현 형태(핸들러 모양, 자원 정리 위치 등)는 [07-development-patterns](07-development-patterns.md)에서 다룬다.

## 실측 근거

- 기준 commit: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`
- 확인한 소스: 34개 대상 파일 전부, 기준 commit tree 파일 목록(도구 설정 파일 부재 확인)
- 확인 범위: `grep`으로 `from __future__` 사용 파일 집계, 명명·주석 형태 정적 관찰. 포매터·린터를 실행하지 않았다.
- 미확인: 줄바꿈(CRLF/LF) 규칙, 줄 길이 등 포맷 일관성 수준(도구로 측정하지 않음).

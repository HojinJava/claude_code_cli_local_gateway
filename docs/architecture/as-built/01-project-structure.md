---
description: claude-pool 저장소의 실제 폴더·진입점 구성과 분석 대상 34개 파일의 기능별 책임표(File Responsibility Map)
tags: [architecture]
status: as-built
---

# 01. 프로젝트 구조 (as-built)

## 실제 폴더 구성

```text
.
├── .gitignore                 # 추적 설정 파일
├── pyproject.toml             # 패키지·의존성·pytest·빌드 설정 (유일한 매니페스트)
├── src/
│   └── claude_pool/           # 배포 패키지 (setuptools packages.find where=["src"])
├── scripts/                   # 수동 실행 스크립트 (패키지에 포함되지 않음)
└── tests/                     # pytest 테스트
    └── fixtures/              # 가짜 claude CLI와 그 테스트
```

- src 레이아웃이다. 패키지 탐색은 `pyproject.toml:31-32`의 `where = ["src"]`로 정해진다. `pyproject.toml`에 pytest `pythonpath` 설정이 없으므로 `claude_pool` import는 패키지 설치를 전제로 한다(설치 절차는 [06-build-and-run](06-build-and-run.md)).
- `scripts/`는 패키지 탐색 대상(`src`) 밖이다. `scripts/daemon_ctl.py`는 `claude_pool`을 import한다(`scripts/daemon_ctl.py:17-19`).
- 모듈 간 import는 모두 명시적 상대 import이며(예: `src/claude_pool/server.py:7-12`), 자동 등록·경로 별칭은 없다. `src/claude_pool/__init__.py`는 빈 파일로 re-export가 없다.

## 주요 진입점

| 진입점 | 파일 |
|---|---|
| 데몬 `main()` / 콘솔 스크립트 `claude-pool-daemon` | `src/claude_pool/daemon.py:65-71`, `pyproject.toml:17-18` |
| aiohttp 앱 팩토리 `create_app` | `src/claude_pool/server.py:51-70` |
| 클라이언트 `ClaudePoolClient` | `src/claude_pool/client.py:35-200` |
| 운영 CLI `main()` | `scripts/daemon_ctl.py:178-187` |

실행 경로 상세는 [00-overview](00-overview.md), 모듈 의존 방향은 [09-component-architecture](09-component-architecture.md)를 본다.

## File Responsibility Map

대상: 기준 commit tree에서 분석 제외 파일(아래)을 뺀 34개 파일 전부.

### 설정·빌드

| 기능·모듈 | 파일 경로 | 책임 |
|---|---|---|
| 빌드·의존성·테스트 설정 | [`pyproject.toml`](../../../pyproject.toml) | 패키지 메타데이터(`claude-pool` 0.1.0, Python `>=3.11`), 런타임 의존성(`aiohttp`, Windows 한정 `pywin32`), `dev` extras(pytest 계열), 콘솔 스크립트 `claude-pool-daemon`, pytest 설정(`asyncio_mode`, `filterwarnings`), setuptools 빌드 백엔드와 `src` 패키지 탐색 |
| 저장소 위생 | [`.gitignore`](../../../.gitignore) | `.worktrees/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `*.egg-info/`, `.venv/`, `*.log`, `.superpowers/`, `.coverage` 추적 제외 |

### 데몬 패키지 `src/claude_pool/`

| 기능·모듈 | 파일 경로 | 책임 |
|---|---|---|
| 패키지 표지 | [`src/claude_pool/__init__.py`](../../../src/claude_pool/__init__.py) | 빈 파일(0줄). 패키지 수준 export 없음 |
| 설정 (데몬·클라이언트 운영 공용) | [`src/claude_pool/config.py`](../../../src/claude_pool/config.py) | `PoolConfig` 데이터클래스와 기본값, `from_env()` 환경변수 로딩, `__post_init__`의 loopback host·`claude_cmd` 검증, Host 가드와 공유하는 `is_loopback_host` 판정 |
| 데몬 조립·수명주기 | [`src/claude_pool/daemon.py`](../../../src/claude_pool/daemon.py) | `main()` 진입점, `run_daemon`에서 풀·job 저장소·앱 조립과 TCP 바인딩, 포트별 pid 파일 경로(`pid_file`, `daemon_ctl`도 사용)와 기록·삭제, SIGTERM/SIGINT 대기, 종료 순서(runner cleanup → jobs → pool) |
| HTTP 서버·라우팅·Host 가드 | [`src/claude_pool/server.py`](../../../src/claude_pool/server.py) | `create_app`의 라우트 등록과 앱 dict 주입, `require_loopback_host` 미들웨어와 Host 헤더 파싱, `/generate`·`/jobs` 공통 본문 검증, `Outcome`→HTTP 응답 변환, job·health·자기 문서 핸들러 |
| 요청 실행 (동기·백그라운드 공용) | [`src/claude_pool/runner.py`](../../../src/claude_pool/runner.py) | `execute()`: 워커 획득 → 실행 → 예외면 분류·`note_failure` 기록 후 shield된 백그라운드 반납, 결과면 반납 후 분류·`note_success`/`note_failure` 기록. 전송 방식 무관 `Outcome` 값 객체 |
| 실패 분류 | [`src/claude_pool/errors.py`](../../../src/claude_pool/errors.py) | 워커 오류 텍스트 정규식 매칭으로 `rate_limited`/`not_authenticated`/`worker_failed` `Failure`(kind·status·retryable·retry_after_sec) 결정, `DEFAULT_RETRY_AFTER_SEC` |
| 백그라운드 job | [`src/claude_pool/jobs.py`](../../../src/claude_pool/jobs.py) | `Job` 상태·직렬화(`to_dict`), `JobStore`의 제출(무작위 id)·실행 태스크·조회·목록·취소·보관 기간/상한 reap·통계·종료 취소 |
| 워커 풀 | [`src/claude_pool/pool.py`](../../../src/claude_pool/pool.py) | `WorkerPool`: 풀당 kill-on-close job 생성, min 예열, acquire 대기·수요 기반 증가, 1회용 release(kill 후 보충), idle 축소 루프, stop 드레인, 마지막 오류 기록, `/health`용 `stats()` |
| 워커 프로세스 | [`src/claude_pool/worker.py`](../../../src/claude_pool/worker.py) | `claude -p` stream-json argv 구성, `CREATE_NO_WINDOW` 스폰과 Job Object 할당, best-effort 생존 확인, 프롬프트 1건 실행·`result` 줄 파싱·타임아웃 kill, `WorkerError` |
| Windows Job Object | [`src/claude_pool/winjob.py`](../../../src/claude_pool/winjob.py) | Windows에서만 pywin32로 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` job 생성과 pid 할당, 비 Windows는 `None`/no-op |
| 자기 문서 | [`src/claude_pool/apidocs.py`](../../../src/claude_pool/apidocs.py) | 살아있는 `PoolConfig`로 `GET /` JSON(`api_info`), OpenAPI 3.1(`openapi_spec`), 자체 완결 HTML(`render_html`) 생성. 문서용 `FAILURE_KINDS`·`CONSTRAINTS`·예제 |
| Python 클라이언트 | [`src/claude_pool/client.py`](../../../src/claude_pool/client.py) | stdlib(`urllib`) 전용 `ClaudePoolClient`: health 확인·데몬 자동 기동(host·port 환경변수 주입), generate/submit/job/jobs/cancel/wait/health/api_info, HTTP 오류 → `ClaudePoolError`(kind·retryable·retry_after_sec) 변환 |

### 스크립트 `scripts/`

| 기능·모듈 | 파일 경로 | 책임 |
|---|---|---|
| 데몬 운영 CLI | [`scripts/daemon_ctl.py`](../../../scripts/daemon_ctl.py) | `start`/`stop`/`restart`/`status`. `PoolConfig.from_env()`·`pid_file`·`ClaudePoolClient` 재사용, pid 파일 pid의 명령줄 검증, 명령줄 기반 폴백 탐색, `taskkill /F`·`SIGTERM` 종료 |
| 조사: 예열 효과 측정 | [`scripts/bench_cold_vs_warm.py`](../../../scripts/bench_cold_vs_warm.py) | 실제 `claude` CLI(haiku, text/json 형식)로 cold 스폰과 예열 후 입력의 소요 시간을 각 10회 측정·출력. 수동 실행 |
| 조사: stream-json 대기 | [`scripts/investigate_stream_json_timeout.py`](../../../scripts/investigate_stream_json_timeout.py) | 실제 `claude` CLI(haiku, stream-json)를 스폰해 15초 후 입력했을 때의 종료 코드·출력 줄을 관찰 출력. 수동 실행 |

### 테스트 `tests/`

| 기능·모듈 | 파일 경로 | 책임 |
|---|---|---|
| 테스트 패키지 표지 | [`tests/__init__.py`](../../../tests/__init__.py) | 빈 파일(0줄) |
| 공용 fixture | [`tests/conftest.py`](../../../tests/conftest.py) | `unused_tcp_port`(127.0.0.1 임시 포트), `make_pool`(생성한 `WorkerPool`을 teardown에서 `stop()`) |
| 테스트 대역 패키지 표지 | [`tests/fixtures/__init__.py`](../../../tests/fixtures/__init__.py) | 빈 파일(0줄) |
| 가짜 CLI (워커·풀·서버·job·데몬·클라이언트 테스트 공용) | [`tests/fixtures/fake_claude_cli.py`](../../../tests/fixtures/fake_claude_cli.py) | 실제 `claude` 대신 `claude_cmd`로 주입되는 스크립트. `--fake-mode echo\|error\|crash`, `--fake-delay-sec`, `--fake-error-text`, 알 수 없는 플래그 무시, stream-json 형태 출력 |
| 가짜 CLI 검증 | [`tests/fixtures/test_fake_claude_cli.py`](../../../tests/fixtures/test_fake_claude_cli.py) | echo/error/crash 모드와 실제 CLI 플래그 무시를 subprocess로 확인 |
| 설정 | [`tests/test_config.py`](../../../tests/test_config.py) | 기본값, 환경변수 override, loopback host 허용·거부, `scratch_dir`·`claude_cmd`(JSON) 검증 |
| 워커 | [`tests/test_worker.py`](../../../tests/test_worker.py) | 스폰·실행 결과 파싱·error/crash/timeout 처리, stream-json argv, kill 멱등성, `creationflags` 전달 |
| 워커 풀 | [`tests/test_pool.py`](../../../tests/test_pool.py) | 예열, acquire/release·보충, max 한도, 축소 루프, 취소된 run의 kill, 죽은 idle 폐기, 스폰 실패, stop 드레인·대기자 깨우기, Windows job 핸들 닫힘 시 워커 종료 |
| Job Object | [`tests/test_winjob.py`](../../../tests/test_winjob.py) | Windows 전용: job 생성, 핸들 닫힘 시 할당 프로세스 종료, job 없음 no-op |
| 실패 분류 | [`tests/test_errors.py`](../../../tests/test_errors.py) | rate limit·인증·폴백 분류와 대기 힌트 추출 |
| HTTP 라우트·health | [`tests/test_server.py`](../../../tests/test_server.py) | `/generate` 성공·400·실패 분류·503, `/health` 통계·liveness·`last_error` |
| Host 가드 | [`tests/test_host_guard.py`](../../../tests/test_host_guard.py) | Host 헤더 파싱, 비 loopback 403, loopback 허용, `/health` 가드 적용 |
| 백그라운드 job | [`tests/test_jobs.py`](../../../tests/test_jobs.py) | `JobStore` 제출·실패 기록·취소·종료·reap·상한, `/jobs` 라우트 202·폴링·404·검증·목록·health job 수·Host 가드 |
| 자기 문서 | [`tests/test_apidocs.py`](../../../tests/test_apidocs.py) | `/`·`/docs`·`/openapi.json` 내용, HTML 자체 완결성·이스케이프, `FAILURE_KINDS`와 `classify` 일치, Host 가드 |
| 데몬 조립 | [`tests/test_daemon.py`](../../../tests/test_daemon.py) | 실제 TCP 포트로 `run_daemon` 요청 처리, 종료 시 워커 종료, 포트별 pid 파일 기록·삭제, 기동 실패 시 pid 파일 미잔존 |
| 클라이언트 | [`tests/test_client.py`](../../../tests/test_client.py) | 스레드에서 띄운 데몬 대상 generate/submit/wait/jobs/cancel/job/health/api_info, `Popen` monkeypatch로 자동 기동 argv·env, 합성 `HTTPError`로 오류 변환 |
| 통합 | [`tests/test_integration.py`](../../../tests/test_integration.py) | 동시 요청 간 응답 섞임 없음, 버스트 증가와 idle 축소 |

### 분석 제외

| 경로 | 사유 |
|---|---|
| `README.md`, `CLAUDE.md` | 사용자 문서. `pyproject.toml`에 `readme` 키가 없고 빌드·코드가 참조하지 않는다. 명령 출처로만 인용한다 |
| `.`으로 시작하는 폴더(`.git/`, 로컬 `.pytest_cache/` 등) | 추적 대상 아님 또는 도구 산출물 |
| `docs/` | 이번 migration이 생성한 문서(기준 commit tree에 없음) |
| `__pycache__/`·`*.pyc` 등 | 자동 생성물(`.gitignore` 대상, 추적되지 않음) |

## 실측 근거

- 기준 commit: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`
- 파일 집합: `git ls-tree -r --name-only 821f6e9c83edc2b2f11434cc00e52c106f6f7b42`에서 `README.md`·`CLAUDE.md`를 뺀 34개 경로와 위 표의 경로 집합을 스크립트로 대조했다.
- 확인한 소스: 위 표의 34개 파일 본문 전체(빈 `__init__.py` 3개는 줄 수 0 확인).
- 확인 범위: 정적 읽기와 `git` 읽기 명령. 테스트는 실행하지 않았고 테스트 책임은 테스트 본문이 표현하는 대상으로 기록했다.
- 미확인: 없음(대상 파일 전량 확인).

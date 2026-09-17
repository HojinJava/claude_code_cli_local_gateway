---
description: claude-pool의 환경변수·코드 폴백값·검증 규칙·설정 주입 경로와 pytest·빌드 설정 실측
tags: [architecture]
status: as-built
---

# 03. 설정 (as-built)

## 설정 소스

- 런타임 설정은 `PoolConfig` 데이터클래스 하나다([`src/claude_pool/config.py`](../../../src/claude_pool/config.py)).
- 값의 출처는 두 가지다: 데이터클래스 기본값(`config.py:23-39`)과 환경변수를 읽는 `PoolConfig.from_env()`(`config.py:61-101`).
- `.env` 파일·설정 파일(YAML/INI/JSON) 로딩 코드는 없고, 저장소에 그런 파일도 없다. CLI 인자 파싱도 데몬에는 없다(`daemon.py:65-67`).

## 환경변수와 코드 폴백값

| 필드 | 환경변수 | 폴백값 | 변환 | 사용처 |
|---|---|---|---|---|
| `min_workers` | `CLAUDE_POOL_MIN_WORKERS` | 4 | `int()` | 예열·축소 하한 (`pool.py:42`, `pool.py:193`, `pool.py:205`) |
| `max_workers` | `CLAUDE_POOL_MAX_WORKERS` | 30 | `int()` | 증가 상한 (`pool.py:149`, `pool.py:172`, `pool.py:194`) |
| `model` | `CLAUDE_POOL_MODEL` | `"sonnet"` | 문자열 | 워커 `--model` (`worker.py:45`) |
| `host` | `CLAUDE_POOL_HOST` | `"127.0.0.1"` | 문자열 | 바인딩 (`daemon.py:36`) |
| `port` | `CLAUDE_POOL_PORT` | 8756 | `int()` | 바인딩, pid 파일명 (`daemon.py:23`, `daemon.py:36`) |
| `default_timeout_sec` | `CLAUDE_POOL_TIMEOUT_SEC` | 120.0 | `float()` | 요청 `timeout_sec` 생략 시 (`server.py:93`) |
| `acquire_timeout_sec` | `CLAUDE_POOL_ACQUIRE_TIMEOUT_SEC` | 60.0 | `float()` | 워커 획득 대기 상한 (`pool.py:124`) |
| `idle_timeout_sec` | `CLAUDE_POOL_IDLE_TIMEOUT_SEC` | 60.0 | `float()` | 축소 대상 판정 (`pool.py:211`) |
| `scale_down_interval_sec` | `CLAUDE_POOL_SCALE_DOWN_INTERVAL_SEC` | 30.0 | `float()` | 축소 루프 주기 (`pool.py:202`) |
| `job_retention_sec` | `CLAUDE_POOL_JOB_RETENTION_SEC` | 600.0 | `float()` | 종결 job 보관 (`daemon.py:29`, `jobs.py:170`) |
| `max_jobs` | `CLAUDE_POOL_MAX_JOBS` | 500 | `int()` | job 저장 상한 (`daemon.py:29`, `jobs.py:181`) |
| `scratch_dir` | `CLAUDE_POOL_SCRATCH_DIR` | `Path.home() / ".claude-pool" / "scratch"` | `Path()`; 값이 비었으면 폴백 | 워커 cwd, pid 파일 위치 (`worker.py:54`, `daemon.py:23`, `daemon.py:27`) |
| `claude_cmd` | `CLAUDE_POOL_CLAUDE_CMD_JSON` | `["claude"]` | `json.loads()`; 값이 비었으면 폴백 | 워커 argv 앞부분 (`worker.py:36`) |

- 환경변수 표의 근거: `config.py:63-101`. 데이터클래스 기본값도 같은 값이다(`config.py:23-39`).
- 표의 값은 코드 폴백값이며 실제 실행 환경에 주입되는 값은 저장소로 확인되지 않는다(`미확인`).
- 문서용으로 살아있는 설정 일부(`model`, `min_workers`, `max_workers`, `default_timeout_sec`, `host`, `port`)가 `GET /`·`/docs`·`/openapi.json`에 노출된다(`apidocs.py:84`, `apidocs.py:113-118`, `apidocs.py:236`).

## 검증

`PoolConfig.__post_init__`(`config.py:41-59`)가 직접 생성과 `from_env()` 두 경로 모두에서 실행된다.

| 규칙 | 위치 | 실패 시 |
|---|---|---|
| `host`가 `"localhost"`이거나 `ipaddress.ip_address(host).is_loopback`이어야 함 (`is_loopback_host`, `config.py:12-18`) | `config.py:44-49` | `ValueError`(메시지에 `loopback`) |
| `claude_cmd`가 비어 있지 않은 list | `config.py:52-55` | `ValueError`(메시지에 `claude_cmd`) |
| `claude_cmd` 원소가 모두 str | `config.py:56-59` | `ValueError` |
| `CLAUDE_POOL_CLAUDE_CMD_JSON` JSON 파싱 | `config.py:64-70` | `ValueError("CLAUDE_POOL_CLAUDE_CMD_JSON is not valid JSON: ...")` |

- 숫자 환경변수의 `int()`/`float()` 변환 실패는 별도 처리 없이 `ValueError`로 전파된다(`config.py:82-98`).
- `min_workers <= max_workers`, 포트 범위, 타임아웃·보관 시간·`max_jobs`의 부호/범위를 검사하는 코드는 없다.
- 요청 단위 입력 `timeout_sec`는 `float()` 변환만 검사한다(`server.py:92-95`) → [11-api-contract](11-api-contract.md).

## 주입 경로

| 경로 | 위치 | 방식 |
|---|---|---|
| 데몬 | `src/claude_pool/daemon.py:66` | `PoolConfig.from_env()` → `run_daemon(config)` → `WorkerPool(config)`·`JobStore(retention_sec, max_jobs)`(`daemon.py:28-29`) |
| 앱 핸들러 | `src/claude_pool/server.py:53` | `app["pool"]`에 풀 저장, 핸들러가 `request.app["pool"].config`로 읽음(`server.py:79`, `server.py:167`) |
| 앱(jobs 미전달) | `src/claude_pool/server.py:54-56` | `pool.config.job_retention_sec`·`max_jobs`로 `JobStore` 생성 |
| 클라이언트 자동 기동 | `src/claude_pool/client.py:60-62` | 호출 프로세스 환경 복사 후 `CLAUDE_POOL_HOST`·`CLAUDE_POOL_PORT`를 클라이언트 값으로 덮어써 자식에 전달. 나머지 `CLAUDE_POOL_*`는 상속 |
| 운영 스크립트 | `scripts/daemon_ctl.py:183` | `PoolConfig.from_env()`로 대상 host·port·scratch_dir를 결정 |
| 테스트 | 예: `tests/test_server.py:13-21` | `PoolConfig(...)` 직접 생성으로 `claude_cmd`·`scratch_dir`·타이밍 값 주입 |

## 시크릿

- 코드·설정에 API 키·토큰·비밀번호 키가 없다. `claude` CLI 인증 정보는 데몬이 읽거나 전달하지 않는다(워커 argv `worker.py:34-46`) → [12-security-auth](12-security-auth.md).

## pytest 설정

`pyproject.toml:20-25`의 `[tool.pytest.ini_options]`:

- `asyncio_mode = "auto"` — async 테스트·fixture를 마커 없이 실행.
- `filterwarnings = ["error::pytest.PytestUnraisableExceptionWarning"]` — 주석(`pyproject.toml:22-24`)은 asyncio가 닫지 못한 서브프로세스 파이프의 `__del__` 경고를 오류로 올리기 위함이라고 밝힌다.
- `testpaths`·`pythonpath`·마커 등록 설정은 없다.

## 빌드 설정

- `[build-system]` `requires = ["setuptools>=68"]`, `build-backend = "setuptools.build_meta"` (`pyproject.toml:27-29`).
- `[tool.setuptools.packages.find]` `where = ["src"]` (`pyproject.toml:31-32`).
- `[project.scripts]` `claude-pool-daemon = "claude_pool.daemon:main"` (`pyproject.toml:17-18`).
- 패키지 데이터·버전 동적 생성·환경별 빌드 분기 설정은 없다.

## 실측 근거

- 기준 commit: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`
- 확인한 소스: [config.py](../../../src/claude_pool/config.py), [daemon.py](../../../src/claude_pool/daemon.py), [server.py](../../../src/claude_pool/server.py), [pool.py](../../../src/claude_pool/pool.py), [worker.py](../../../src/claude_pool/worker.py), [jobs.py](../../../src/claude_pool/jobs.py), [client.py](../../../src/claude_pool/client.py), [apidocs.py](../../../src/claude_pool/apidocs.py), [daemon_ctl.py](../../../scripts/daemon_ctl.py), [pyproject.toml](../../../pyproject.toml), [test_config.py](../../../tests/test_config.py)
- 확인 범위: 설정 정의·검증·사용 지점 정적 확인. 환경변수를 실제로 주입해 실행하지 않았다.
- 미확인: 실제 운영 환경의 환경변수 값, 사용자 홈 경로에서의 기본 `scratch_dir` 실제 위치.

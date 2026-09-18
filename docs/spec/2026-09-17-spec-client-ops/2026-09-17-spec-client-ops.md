---
description: "기존 코드에서 역추론한 claude-pool Python 클라이언트(ClaudePoolClient)와 운영·조사 스크립트(daemon_ctl, bench_cold_vs_warm, investigate_stream_json_timeout)의 요구사항·설계"
status: implemented
revision: 1
plan: 없음
origin: migration
architecture:
  - ../../architecture/as-built/00-overview.md
  - ../../architecture/as-built/01-project-structure.md
  - ../../architecture/as-built/02-external-dependencies.md
  - ../../architecture/as-built/04-testing-strategy.md
  - ../../architecture/as-built/06-build-and-run.md
  - ../../architecture/as-built/07-development-patterns.md
  - ../../architecture/as-built/08-system-context.md
  - ../../architecture/as-built/13-error-policy.md
  - ../../architecture/as-built/15-non-functional-requirements.md
---

# claude-pool 클라이언트와 운영·조사 스크립트 spec

## 분석 기준

- 분석 커밋 앵커: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` (branch `master`, 작업공간 clean)
- 확인 범위: `src/claude_pool/client.py`, `scripts/daemon_ctl.py`, `scripts/bench_cold_vs_warm.py`, `scripts/investigate_stream_json_timeout.py`, `tests/test_client.py`, 그리고 클라이언트·스크립트가 소비하는 범위의 `src/claude_pool/daemon.py`(`pid_file`), `src/claude_pool/server.py`(`/health`·`/jobs` 응답 형태), `src/claude_pool/pool.py`·`src/claude_pool/jobs.py`의 `stats()`, `tests/test_daemon.py`의 pid 파일 테스트.
- 이력 근거: `git log`/`git show`로 확인한 커밋 `7f729fe`, `c130f07`, `bbbd72d`, `8f979c0`, `821f6e9`.
- 테스트는 실행하지 않았고, 실제 `claude` CLI나 데몬도 실행하지 않았다. 아래 내용은 코드가 무엇을 하는지의 기술이다.

## 배경과 해결할 문제

claude-pool 데몬은 `claude -p` 워커를 예열해 두고 HTTP(`POST /generate`, `/jobs`, `GET /health`, `GET /`)로 노출한다. 이 영역은 그 데몬을 **소비하고 운영하는** 쪽의 코드다.

1. **Python 클라이언트** (`ClaudePoolClient`): 다른 Python 프로그램이 별도 의존성 설치 없이 데몬을 호출하고, 데몬이 없으면 스스로 띄울 수 있게 한다. 데몬이 내려주는 실패 분류(`kind`/`retryable`/`Retry-After`)를 예외 객체로 옮겨, 호출자가 재시도 여부를 판단할 수 있게 한다(`client.py:12-20` docstring: "callers can back off instead of hammering").
2. **운영 스크립트** (`scripts/daemon_ctl.py`): 데몬 start/stop/restart/status를 한 명령으로 제공한다. 커밋 `821f6e9` 메시지에 따르면 이전에는 기동이 `python -c` 한 줄, 종료가 프로세스 목록을 긁는 PowerShell 명령이었고, 이를 감싸기 위해 추가되었다.
3. **조사 스크립트** (`scripts/bench_cold_vs_warm.py`, `scripts/investigate_stream_json_timeout.py`): 예열 풀 설계의 전제(예열이 부팅 비용을 줄이는지, 예열된 프로세스가 입력을 오래 기다릴 수 있는지)를 실제 CLI로 확인하기 위한 수동 실행 스크립트다. 커밋 `7f729fe`("spike: validate pre-warm saves boot time vs cold spawn"), `c130f07`("docs: confirm stream-json input avoids the 3s stdin timeout")로 추가되었다.

## 범위와 비범위

### 범위

- `ClaudePoolError` 예외 타입과 필드(`kind`, `retryable`, `retry_after_sec`)
- `ClaudePoolClient`의 생성자(자동 기동 포함)와 공개 메서드 `generate`, `submit`, `job`, `jobs`, `cancel`, `wait`, `health`, `api_info`
- HTTP 오류 응답 → `ClaudePoolError` 변환 규칙
- `daemon_ctl.py`의 `start`/`stop`/`restart`/`status` 명령, pid 파일 검증, 명령줄 기반 폴백
- 두 조사 스크립트의 목적과 측정 방식

### 비범위

- 서버 라우트 계약 자체(상태 코드 결정, 응답 JSON 생성, Host 헤더 검사, job 보관·취소 의미론) — gateway-api 영역 담당. 이 문서는 클라이언트가 그 응답을 소비하는 방식만 다룬다.
- 워커 풀·워커 프로토콜·실패 분류 규칙(`errors.classify`) 자체
- 데몬 프로세스 내부 수명주기(`run_daemon`의 pid 파일 기록·삭제는 daemon_ctl이 소비하는 범위에서만 언급)
- 조사 스크립트의 실행 결과 수치 — 코드에 기록되어 있지 않다.

## 현재 구조와 책임

### 1. `src/claude_pool/client.py`

**의존성 제약.** 모듈 import는 `from __future__ import annotations`와 `json`, `os`, `subprocess`, `sys`, `time`, `urllib.error`, `urllib.request`뿐이다(`client.py:1-9`). 서드파티 패키지(`aiohttp` 포함)나 `claude_pool`의 다른 모듈을 import하지 않는다. 커밋 `bbbd72d` 제목이 "add dependency-free ClaudePoolClient"로 이 제약을 의도로 밝힌다.

**`ClaudePoolError(Exception)`** (`client.py:12-32`)

- 생성자 인자: `message`, `kind="unknown"`, `retryable=False`, `retry_after_sec: int | None = None`.
- `str(exc)`는 `message`다.

**생성자 `ClaudePoolClient(host="127.0.0.1", port=8756, auto_start=True, start_timeout_sec=15.0)`** (`client.py:36-48`)

- `base_url = f"http://{host}:{port}"`.
- `auto_start`가 참이고 `_is_healthy()`가 거짓이면 `_start_daemon()` 후 `_wait_until_healthy(start_timeout_sec)`를 호출한다. `auto_start=False`면 생성자는 네트워크 호출을 하지 않는다.
- 클라이언트 쪽 host 검증(loopback 여부)은 없다. 자동 기동된 데몬에는 host가 환경변수로 전달되며, loopback 검증은 데몬의 `PoolConfig.__post_init__`에서 이루어진다(`config.py:41-49`, gateway-api 영역).

**헬스 판정 `_is_healthy()`** (`client.py:50-55`)

- `GET {base_url}/health`를 타임아웃 1.0초로 `urlopen`한다. 예외 없이 열리면 `True`, `URLError`/`OSError`/`TimeoutError`면 `False`. 응답 본문의 `healthy` 필드는 보지 않는다. `HTTPError`는 `URLError`의 하위 클래스이므로 4xx/5xx 응답도 `False`로 처리된다.

**자동 기동 `_start_daemon()`** (`client.py:57-74`)

- 현재 프로세스 환경을 복사한 뒤 `CLAUDE_POOL_HOST=self.host`, `CLAUDE_POOL_PORT=str(self.port)`를 덮어쓴다. 주석(`client.py:58-59`): 데몬은 `PoolConfig.from_env()`를 읽으므로, 이 클라이언트의 host·port를 넘겨야 클라이언트가 기대하는 곳에 바인딩된다. 그 외 `CLAUDE_POOL_*` 변수(모델, 워커 수 등)는 호출 프로세스 환경에서 그대로 상속된다.
- 실행 argv: `[sys.executable, "-m", "claude_pool.daemon"]` — 클라이언트를 실행 중인 같은 인터프리터를 쓴다.
- stdin/stdout/stderr 모두 `DEVNULL`, `close_fds=True`.
- Windows(`sys.platform == "win32"`)에서는 `creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`. 비Windows에서는 `creationflags`를 넘기지 않으며 `start_new_session` 등 별도 분리 옵션도 없다.
- `Popen` 객체를 보관하거나 기다리지 않는다(반환값을 버림).

**기동 대기 `_wait_until_healthy(timeout_sec)`** (`client.py:76-82`)

- `time.monotonic()` 기준 마감 시각까지 0.2초 간격으로 `_is_healthy()`를 반복한다. 마감까지 성공하지 못하면 `ClaudePoolError("daemon did not become healthy in time")`(기본 `kind="unknown"`, `retryable=False`)를 던진다.

**공통 호출 `_call(method, path, payload=None, request_timeout=30.0)`** (`client.py:84-101`)

- `payload`가 있으면 JSON 직렬화(UTF-8) 본문과 `Content-Type: application/json` 헤더를 붙이고, 없으면 본문·헤더 없이 보낸다.
- 성공 응답 본문을 `json.loads`로 파싱해 반환한다.
- `urllib.error.HTTPError`만 잡아 `_error_from(exc)`로 변환해 `raise ... from exc` 한다. 연결 거부 등 `HTTPError`가 아닌 `URLError`, 소켓 타임아웃, 성공 응답의 JSON 파싱 오류는 변환하지 않고 그대로 전파된다.

**요청 본문 `_prompt_payload(prompt, timeout_sec)`** (`client.py:103-108`): `{"prompt": prompt}`에 `timeout_sec`가 `None`이 아닐 때만 `"timeout_sec"` 키를 추가한다.

**공개 메서드**

| 메서드 | HTTP | 반환 | 클라이언트 쪽 소켓 타임아웃 | 근거 |
|---|---|---|---|---|
| `generate(prompt, timeout_sec=None)` | `POST /generate` | 응답의 `text` (str) | `(timeout_sec or 120.0) + 5.0` | `client.py:110-120` |
| `submit(prompt, timeout_sec=None)` | `POST /jobs` | 응답의 `job_id` (str) | 30.0 (기본) | `client.py:122-130` |
| `job(job_id)` | `GET /jobs/{job_id}` | 응답 dict 그대로 | 30.0 | `client.py:132-135` |
| `jobs()` | `GET /jobs` | 응답의 `jobs` (list) | 30.0 | `client.py:137-138` |
| `cancel(job_id)` | `DELETE /jobs/{job_id}` | 응답 dict 그대로 | 30.0 | `client.py:140-142` |
| `wait(job_id, poll_interval_sec=1.0, timeout_sec=None)` | `job()` 반복 | 성공 시 `text` (str) | — | `client.py:144-174` |
| `health()` | `GET /health` | 응답 dict 그대로 | 5.0 | `client.py:195-196` |
| `api_info()` | `GET /` | 응답 dict 그대로 | 5.0 | `client.py:198-200` |

- `generate`의 소켓 타임아웃 설계 의도는 주석으로 확인된다(`client.py:116-117`): 데몬 자체 타임아웃보다 오래 기다려, 느린 완료가 클라이언트 소켓 타임아웃이 아니라 데몬의 504로 드러나게 한다. `timeout_sec`가 falsy(`None` 또는 0)일 때 쓰는 120.0은 클라이언트 코드의 상수이며, 실행 중인 데몬의 `CLAUDE_POOL_TIMEOUT_SEC` 값을 조회하지 않는다.
- `job()` docstring(`client.py:133-134`): 실패한 job에 대해 예외를 던지지 않으며 호출자가 `status`를 읽는다. 이는 서버가 실패 job 조회에도 200을 돌려주는 것(`server.py:143-144` 주석)에 기대는 소비 방식이다. 존재하지 않는 job은 서버가 404를 반환하므로 `_call`을 거쳐 `ClaudePoolError`가 된다(`test_client_unknown_job_raises`).
- `cancel()` docstring(`client.py:141`)은 "실행 중 job 취소(워커 종료), 또는 끝난 job 잊기"라고 기술한다. 클라이언트는 서버 응답 dict를 그대로 반환할 뿐이며, 실제 취소·보관 의미론은 서버(`jobs.py` `JobStore.cancel`) 영역이다.

**`wait()` 폴링 규칙** (`client.py:155-174`)

1. `timeout_sec`가 주어지면 `time.monotonic() + timeout_sec`를 마감으로 둔다. `None`이면 마감 없음.
2. 매 반복마다 `self.job(job_id)`를 호출하고 `status`를 본다.
   - `"succeeded"` → `job["text"]` 반환.
   - `"failed"` 또는 `"cancelled"` → `ClaudePoolError(job.get("error", status), kind=job.get("kind", status), retryable=bool(job.get("retryable", False)), retry_after_sec=job.get("retry_after_sec"))`를 던진다. 즉 job 본문에 분류 키가 없으면(예: cancelled) `kind`는 상태 문자열 자체가 된다.
   - 그 외 상태에서 마감이 지났으면 `ClaudePoolError(f"job {job_id} still {status} after {timeout_sec}s", kind="timeout", retryable=True)`를 던진다. 이 `timeout` 분류는 서버가 아니라 클라이언트가 만든다.
   - 아니면 `poll_interval_sec`만큼 `time.sleep` 후 반복.
3. `wait()`의 `timeout_sec`는 폴링 대기 상한일 뿐, 서버의 job을 취소하지 않는다(코드에 취소 호출 없음).
4. `job()` 호출 자체가 던지는 예외(404 등)는 `wait()`에서 잡지 않고 전파된다.

**HTTP 오류 변환 `_error_from(exc)`** (`client.py:176-193`)

1. 본문을 `json.loads(exc.read())`로 파싱한다. `ValueError`/`OSError`면 빈 dict로 간주한다. 주석(`client.py:181-182`): 프록시·크래시 페이지 같은 비 JSON 오류 본문도 클라이언트 내부 디코드 오류가 아니라 `ClaudePoolError`로 올라와야 한다.
2. `retry_after_sec`: 본문의 `retry_after_sec`를 우선 사용한다. 없으면 `Retry-After` 헤더를 읽어 `str.isdigit()`인 경우에만 `int`로 변환하고, 아니면(HTTP-date 형식 등) `None`.
3. `message = body.get("error", f"HTTP {exc.code}")`, `kind = body.get("kind", "unknown")`, `retryable = bool(body.get("retryable", False))`.
4. 결과: 서버의 400 요청 오류(`{"error"}`만 있음, `server.py:118-119`, `server.py:130-131`)는 `kind="unknown"`, `retryable=False`로, 서버의 `forbidden_host`·`rate_limited` 등 분류된 실패는 본문의 `kind`/`retryable`을 그대로 옮긴 예외가 된다.

### 2. `scripts/daemon_ctl.py`

**실행 형태.** `python scripts/daemon_ctl.py start | stop | restart | status` (`daemon_ctl.py:1-8`). 인자가 없으면 `status`(`daemon_ctl.py:179`). 알 수 없는 명령이면 stderr에 `usage: ...`를 출력하고 종료 코드 2(`daemon_ctl.py:180-182`). 명령 함수의 반환값이 프로세스 종료 코드가 된다(`raise SystemExit(main())`, `daemon_ctl.py:186-187`).

**설정 출처.** `PoolConfig.from_env()`를 사용한다(`daemon_ctl.py:183`). docstring(`daemon_ctl.py:5-7`): 데몬과 같은 환경변수를 읽으므로, `CLAUDE_POOL_MODEL=haiku ... start`로 띄운 데몬을 같은 `CLAUDE_POOL_PORT`의 이후 명령이 다룬다. 스크립트는 `claude_pool.client`, `claude_pool.config`, `claude_pool.daemon`을 import하므로(`daemon_ctl.py:17-19`) `claude_pool` 패키지가 import 가능한 환경(src 레이아웃, `pyproject.toml:31-32`)을 전제한다.

**pid 파일.** 경로는 `claude_pool.daemon.pid_file(config)` = `config.scratch_dir / f"daemon-{config.port}.pid"`(`daemon.py:16-23`). 데몬은 리슨 시작 후 자기 pid를 기록하고 `finally`에서 삭제한다(`daemon.py:38`, `daemon.py:41-43`). 포트별로 둔 이유는 docstring과 커밋 `821f6e9`에 기록되어 있다: 다른 모델용 데몬을 다른 포트로 하나 더 띄우는 구성이 지원되며, 포트는 환경변수로 전달되어 명령줄에 나타나지 않으므로 명령줄 매칭으로는 데몬을 구분할 수 없다.

**내부 함수**

- `_read_pid(config)` (`daemon_ctl.py:24-29`): pid 파일을 읽어 `int`로 변환. `OSError`/`ValueError`면 `None`.
- `_command_line(pid)` (`daemon_ctl.py:32-44`): Windows에서는 `powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"`, 그 외는 `ps -p {pid} -o args=`의 stdout을 strip해 반환. 프로세스가 없거나 읽을 수 없으면 빈 문자열이 된다.
- `_live_daemon_pid(config)` (`daemon_ctl.py:47-57`): pid 파일의 pid의 명령줄에 `"claude_pool.daemon"` 문자열이 포함될 때만 그 pid를 반환, 아니면 `None`. docstring: 강제 종료는 pid 파일을 남기고 OS는 pid를 재사용하므로, 파일만으로는 무엇을 죽일 근거가 되지 않는다.
- `_daemon_pids_by_command_line()` (`daemon_ctl.py:60-80`): Windows에서는 이름이 `python.exe`이고 명령줄에 `claude_pool.daemon`이 포함된 프로세스의 `ProcessId` 목록(PowerShell `Get-CimInstance`), 그 외는 `pgrep -f claude_pool.daemon`. 출력에서 숫자 토큰만 `int`로 모은다. docstring: 포트를 모르므로 "어떤 데몬"은 식별해도 "어느 데몬"인지는 식별하지 못하는 폴백이다.
- `_is_answering(config)` (`daemon_ctl.py:83-88`): `ClaudePoolClient(host, port, auto_start=False).health()`가 예외 없이 끝나면 `True`, 어떤 예외든 `False`.
- `_terminate(pid)` (`daemon_ctl.py:91-96`): Windows는 `taskkill /F /PID {pid}`, 그 외는 `os.kill(pid, SIGTERM)`.
- `STOP_TIMEOUT_SEC = 10.0` (`daemon_ctl.py:21`).

**`status(config)`** (`daemon_ctl.py:103-122`)

- `ClaudePoolClient(auto_start=False).health()`가 예외를 던지면 `stopped  (http://{host}:{port} is not answering)`을 출력하고 1 반환.
- 응답하면 `_live_daemon_pid`로 pid를 구해(없으면 `?`) `running  pid=...  {base_url}`를 출력하고, 이어서 다음을 출력한 뒤 0 반환:
  - `model` — 이 값은 데몬 응답이 아니라 **daemon_ctl 프로세스의 `PoolConfig.from_env()`** 값이다(`daemon_ctl.py:112`).
  - `workers` — `/health`의 `idle_alive`/`idle`, `busy`, `min_workers`, `max_workers`.
  - `jobs` — `/health`의 `jobs.running`, `jobs.total`(서버가 `pool.stats()`에 `jobs.stats()`를 합쳐 제공, `server.py:160-163`, `jobs.py:185-187`).
  - `healthy`가 거짓이면 `UNHEALTHY: pre-warmed workers are dying`.
  - `last_spawn_error`, `last_error` 중 값이 있는 것.
  - `docs     {base_url}/docs`.
- `/health` 응답에 위 키가 없으면 `KeyError`가 전파된다(키 존재 확인 없음).

**`start(config)`** (`daemon_ctl.py:125-129`)

- `ClaudePoolClient(host, port, auto_start=True)`를 생성해 클라이언트의 자동 기동 경로를 그대로 쓴 뒤 `status(config)`의 반환값을 돌려준다. 주석: 이미 응답하는 데몬이 있으면 새로 띄우지 않으므로 두 번 실행해도 안전하다.
- 기동 대기가 15초(클라이언트 기본값) 안에 끝나지 않으면 `ClaudePoolError`가 `start`에서 잡히지 않고 전파된다.

**`stop(config)`** (`daemon_ctl.py:132-166`)

1. `_live_daemon_pid`가 `None`이면:
   - pid 파일을 삭제(`missing_ok=True`)한다.
   - 포트가 응답하지 않으면 `stopped  (nothing running on port {port})` 출력, 0 반환.
   - 포트가 응답하면 `_daemon_pids_by_command_line()`로 후보를 구한다. 후보가 정확히 1개가 아니면 "cannot tell which one serves this port" 메시지와 후보별 수동 종료 명령(`taskkill /F /PID n` 또는 `kill n`)을 출력하고 1 반환. 주석(`daemon_ctl.py:139-141`): 이 경우 "nothing running"이라고 말하는 것은 거짓이고, 어느 데몬을 죽일지 추측하는 것은 더 나쁘다.
   - 후보가 1개면 `no pid file; falling back to the only running daemon (pid=...)`를 출력하고 그 pid를 대상으로 삼는다.
2. `_terminate(pid)` 후 10초 마감까지 0.2초 간격으로 `_live_daemon_pid(config)`가 `None`이 되는지 확인한다. `None`이 되면 pid 파일을 삭제하고 `stopped  pid=...` 출력, 0 반환. 주석(`daemon_ctl.py:159-160`): 워커는 kill-on-close job object에 묶여 있어 데몬 핸들이 닫히면 OS가 정리하므로 여기서 정리할 것이 없다.
3. 마감까지 `None`이 되지 않으면 `FAILED to stop pid=... within 10.0s` 출력, 1 반환.
4. 종료 확인 루프의 판정 기준은 pid 파일 기반 `_live_daemon_pid`이다. 따라서 1단계의 명령줄 폴백 경로(pid 파일을 읽을 수 없는 상태)에서는 루프의 첫 확인이 `None`을 반환하는 코드 흐름이 된다. 포트 응답 여부나 대상 pid의 명령줄을 루프에서 직접 확인하지는 않는다.

**`restart(config)`** (`daemon_ctl.py:169-172`): `stop`이 0이 아니면 1 반환, 0이면 `start` 결과를 반환한다.

### 3. `scripts/bench_cold_vs_warm.py`

- 목적(docstring `bench_cold_vs_warm.py:1-6`): `claude -p`를 미리 스폰해 두고 나중에 stdin을 넣는 방식이 요청마다 새로 스폰하는 방식보다 부팅 비용을 건너뛰는지 확인하는 spike. 가장 싼 모델과 한 단어 응답 프롬프트로 실제 API 비용을 줄이며, 수동 실행(`python scripts/bench_cold_vs_warm.py`)을 전제한다.
- 상수: `CLAUDE_BIN="claude"`, `MODEL="haiku"`, `PROMPT="reply with the single word OK"`, `ITERATIONS=10` (`:14-17`).
- argv(`:19-28`): `claude -p --input-format text --output-format json --no-session-persistence --tools "" --strict-mcp-config --safe-mode --model haiku`. 현재 데몬 워커가 쓰는 `stream-json` 입출력(`worker.py:37-40`)과 다른 `text`/`json` 형식이다.
- `run_cold()` (`:31-45`): 타이머 시작 → 스폰 → 즉시 `communicate(input=PROMPT)` → 경과 시간. 즉 스폰+응답 전체 벽시계 시간.
- `run_prewarmed(prewarm_settle_sec=1.0)` (`:48-65`): 스폰 → 1초 대기(풀에서 idle로 대기하는 상황 모사) → 타이머 시작 → `communicate` → 경과 시간. 요청 도착 시점 이후의 비용만 잰다.
- 둘 다 returncode≠0이면 stderr를 담은 `RuntimeError`, stdout은 `json.loads`로 파싱 가능한지만 확인한다.
- `main()` (`:68-83`): cold 10회, warm 10회를 순차 실행하며 회차별 시간을 출력하고, 각각 `statistics.mean`·`median` 요약을 출력한다.
- 실행 결과 수치는 코드에 없다. 커밋 `7f729fe`가 결과 문서 `docs/superpowers/plans/2026-07-28-claude-pool-spike-results.md`를 함께 추가했으나 그 문서는 앵커 tree에 없다(커밋 `5ad4e5f`에서 삭제).

### 4. `scripts/investigate_stream_json_timeout.py`

- 목적(docstring `investigate_stream_json_timeout.py:1-7`): 예열된 워커가 입력을 받기 전 idle로 있을 때 `--input-format text`에서 발생하는 약 3초의 "no stdin data received, proceeding without it" 타임아웃을 `--input-format stream-json`이 피하는지 조사. haiku와 최소 프롬프트로 비용을 줄인다.
- 배경 이력(커밋 `c130f07` 메시지): 실제 CLI 스모크 테스트에서 text 입력이 약 3초 후 stdin 대기를 포기하는 것이 발견되었고, stream-json 입출력 + `--verbose` 조합은 0s/6s/15s 지연에서 그런 타임아웃이 없었다고 기록되어 있다. 워커가 입출력 형식을 바꾸고 여러 줄 stream-json 출력에서 `result` 줄을 파싱해야 한다는 결론도 같은 메시지에 있다. 이 이력은 CLAUDE.md의 "워커는 stream-json 프로토콜로만 실행한다" 지침과 연결된다.
- argv(`:16-26`): `claude -p --input-format stream-json --output-format stream-json --verbose --no-session-persistence --tools "" --strict-mcp-config --safe-mode --model haiku`.
- `try_delayed_feed(delay_sec)` (`:29-71`): 스폰 → `delay_sec` 대기 → `{"type":"user","message":{"role":"user","content":"reply with the single word OK"}}` + 개행을 UTF-8로 stdin에 넣고 `communicate`를 30초 `wait_for`로 기다린다. 타임아웃이면 kill·wait 후 `TIMED OUT ...` 출력. 완료되면 returncode, stdout 각 줄의 `type`/`subtype`(파싱 불가 줄은 앞 300자), `type == "result"` 줄 전체, stderr 앞 2000자를 출력한다. 판정 로직은 없고 관찰 출력만 한다.
- `main()` (`:74-77`): 현재 코드에서는 `delay_sec=15.0` 한 번만 실행한다. 주석: 텍스트 모드에서 관찰된 약 3초 임계와 현실적인 풀 idle 간격을 충분히 넘기기 위함. 커밋 메시지의 0s/6s 지연은 현재 코드의 `main()`에 없다.

## 사용자 관찰 동작과 수용 기준

### 클라이언트 — 의존성·생성·자동 기동

- **AC-001** `claude_pool.client` 모듈은 표준 라이브러리(`__future__`, `json`, `os`, `subprocess`, `sys`, `time`, `urllib`)만 import한다. — 근거: `src/claude_pool/client.py:1-9`, 커밋 `bbbd72d`
- **AC-002** `ClaudePoolClient`의 기본 엔드포인트는 `http://127.0.0.1:8756`이며, `host`/`port` 인자로 `base_url`을 구성한다. — 근거: `client.py:36-45`
- **AC-003** `auto_start=False`로 생성하면 생성자는 데몬을 기동하지 않으며, 데몬이 없는 포트로 `health()`를 호출하면 예외가 발생한다. — 근거: `client.py:46`, `tests/test_client.py::test_client_raises_on_missing_daemon_when_auto_start_disabled`
- **AC-004** `auto_start=True`이고 `GET /health`가 1초 안에 열리지 않으면, 클라이언트는 `[sys.executable, "-m", "claude_pool.daemon"]`을 자식 프로세스로 실행한다. — 근거: `client.py:46-47`, `client.py:74`, `test_auto_start_passes_client_host_and_port_to_daemon`
- **AC-005** 자동 기동되는 데몬의 환경에는 호출 프로세스 환경을 복사한 뒤 `CLAUDE_POOL_HOST`와 `CLAUDE_POOL_PORT`가 클라이언트의 host·port 값으로 설정된다. — 근거: `client.py:60-62`, `test_auto_start_passes_client_host_and_port_to_daemon`
- **AC-006** 자동 기동되는 데몬은 표준 입출력이 모두 `DEVNULL`로 연결되고, Windows에서는 `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` 플래그로 실행된다. — 근거: `client.py:63-73`
- **AC-007** 자동 기동 후 클라이언트는 0.2초 간격으로 헬스를 확인하며, `start_timeout_sec`(기본 15초) 안에 응답이 없으면 `ClaudePoolError("daemon did not become healthy in time")`를 던진다. — 근거: `client.py:41`, `client.py:76-82`

### 클라이언트 — 호출 메서드

- **AC-008** `generate(prompt)`는 `POST /generate`에 `{"prompt": ...}`를 보내고 응답의 `text`를 문자열로 반환한다. — 근거: `client.py:110-120`, `test_client_generate_returns_text`
- **AC-009** `generate`/`submit`은 `timeout_sec`가 주어질 때만 요청 본문에 `timeout_sec` 키를 포함한다. — 근거: `client.py:103-108`
- **AC-010** `generate`의 클라이언트 소켓 타임아웃은 `(timeout_sec 또는 120.0) + 5.0`초로, 데몬 타임아웃보다 길게 잡는다. — 근거: `client.py:116-118` 주석과 코드
- **AC-011** `submit(prompt)`는 `POST /jobs`를 보내고 응답의 `job_id`를 즉시 반환하며, 연속 제출한 job들은 서로 다른 id를 갖는다. — 근거: `client.py:122-130`, `test_client_submit_and_wait_runs_in_the_background`, `test_client_batches_prompts_without_holding_a_connection`
- **AC-012** `job(job_id)`는 `GET /jobs/{job_id}` 응답 dict를 그대로 반환하고, 실패한 job이라도 응답이 200이면 예외를 던지지 않는다. — 근거: `client.py:132-135` docstring, `test_client_submit_and_wait_runs_in_the_background`
- **AC-013** 존재하지 않는 job id로 `job()`을 호출하면 `ClaudePoolError`가 발생한다. — 근거: `test_client_unknown_job_raises`
- **AC-014** `jobs()`는 `GET /jobs` 응답의 `jobs` 리스트를 반환하며, 제출한 job의 id가 그 목록에 포함된다. — 근거: `client.py:137-138`, `test_client_lists_jobs`
- **AC-015** `cancel(job_id)`는 `DELETE /jobs/{job_id}` 응답 dict를 반환한다(응답 `status`는 `cancelled` 또는 이미 끝난 경우 `succeeded`). — 근거: `client.py:140-142`, `test_client_cancel_reports_the_cancelled_job`
- **AC-016** `health()`는 `GET /health`를 5초 타임아웃으로 호출해 응답 dict를 반환한다. — 근거: `client.py:195-196`, `test_client_health_reports_stats`
- **AC-017** `api_info()`는 `GET /`를 5초 타임아웃으로 호출해 데몬 자기 기술 dict를 반환한다(`name == "claude-pool"`, `endpoints`에 `"POST /jobs"` 포함). — 근거: `client.py:198-200`, `test_client_reads_the_daemons_self_description`

### 클라이언트 — `wait()`

- **AC-018** `wait(job_id)`는 `poll_interval_sec` 간격으로 `job()`을 폴링하다가 `status == "succeeded"`이면 `text`를 반환한다. — 근거: `client.py:156-160`, `test_client_submit_and_wait_runs_in_the_background`
- **AC-019** 폴링 중 `status`가 `failed`/`cancelled`이면 job 본문의 `error`/`kind`/`retryable`/`retry_after_sec`를 담은 `ClaudePoolError`를 던지고, 본문에 해당 키가 없으면 메시지와 `kind`는 상태 문자열, `retryable`은 `False`가 된다. — 근거: `client.py:161-167`, `test_client_wait_raises_the_jobs_own_classification`
- **AC-020** `wait`에 `timeout_sec`가 주어지고 마감까지 job이 끝나지 않으면 `kind="timeout"`, `retryable=True`인 `ClaudePoolError`를 던진다. `timeout_sec`가 없으면 마감 없이 폴링한다. — 근거: `client.py:155`, `client.py:168-173`, `test_client_wait_gives_up_on_its_own_timeout`

### 클라이언트 — 오류 변환

- **AC-021** HTTP 오류 응답은 `ClaudePoolError`로 변환되며, 메시지·`kind`·`retryable`은 JSON 본문의 `error`·`kind`·`retryable`에서 가져온다. — 근거: `client.py:100-101`, `client.py:188-193`, `test_error_carries_the_daemons_classification`, `test_error_marks_non_retryable_failures`
- **AC-022** `retry_after_sec`는 본문의 `retry_after_sec`를 우선하고, 없으면 숫자로만 된 `Retry-After` 헤더를 정수로 사용하며, 숫자가 아닌 헤더(HTTP-date 등)는 `None`으로 둔다. — 근거: `client.py:184-187`, `test_error_carries_the_daemons_classification`, `test_error_ignores_a_non_numeric_retry_after_header`
- **AC-023** 오류 본문이 JSON이 아니면 메시지 `"HTTP {code}"`, `kind="unknown"`, `retryable=False`인 `ClaudePoolError`를 만든다. — 근거: `client.py:178-183`, `test_error_survives_a_non_json_error_body`
- **AC-024** `HTTPError`가 아닌 전송 계층 예외(연결 거부 `URLError`, 소켓 타임아웃 등)는 `ClaudePoolError`로 변환하지 않고 그대로 전파한다. — 근거: `client.py:97-101`(`except urllib.error.HTTPError`만 존재)

### daemon_ctl

- **AC-025** `daemon_ctl.py`는 `start`/`stop`/`restart`/`status` 네 명령을 받고, 인자가 없으면 `status`를 실행하며, 그 외 인자는 usage를 stderr에 출력하고 종료 코드 2로 끝난다. — 근거: `scripts/daemon_ctl.py:175-183`
- **AC-026** `daemon_ctl.py`는 `PoolConfig.from_env()`로 host·port·scratch_dir·model을 정해, 같은 환경변수로 띄운 데몬을 대상으로 동작한다. — 근거: `daemon_ctl.py:5-7`, `daemon_ctl.py:183`
- **AC-027** pid 파일 경로는 `{scratch_dir}/daemon-{port}.pid`로 포트별이다. — 근거: `src/claude_pool/daemon.py:16-23`, `tests/test_daemon.py::test_daemon_writes_a_per_port_pid_file_and_removes_it_on_shutdown`
- **AC-028** pid 파일의 pid는 해당 프로세스 명령줄에 `claude_pool.daemon`이 포함될 때만 살아 있는 데몬 pid로 취급한다. — 근거: `daemon_ctl.py:47-57`
- **AC-029** `status`는 `/health`가 응답하지 않으면 `stopped (...)`를 출력하고 종료 코드 1, 응답하면 pid(확인 불가 시 `?`)·model·워커 수·job 수·오류 필드·docs URL을 출력하고 종료 코드 0을 반환한다. `healthy`가 거짓이면 `UNHEALTHY` 줄을 추가로 출력한다. — 근거: `daemon_ctl.py:103-122`
- **AC-030** `start`는 `ClaudePoolClient(auto_start=True)`로 기동(이미 응답하는 데몬이 있으면 기동하지 않음)한 뒤 `status` 결과를 반환한다. — 근거: `daemon_ctl.py:125-129`
- **AC-031** `stop`은 검증된 pid가 없고 포트가 응답하지 않으면 남은 pid 파일을 지우고 `stopped (nothing running ...)`를 출력하며 종료 코드 0을 반환한다. — 근거: `daemon_ctl.py:133-138`
- **AC-032** `stop`은 검증된 pid가 없는데 포트가 응답하면, 명령줄로 찾은 데몬 프로세스가 정확히 1개일 때만 그 pid를 종료 대상으로 삼고, 0개 또는 2개 이상이면 후보별 수동 종료 명령을 출력하고 종료 코드 1을 반환한다. — 근거: `daemon_ctl.py:139-152`, 커밋 `821f6e9`
- **AC-033** `stop`은 Windows에서 `taskkill /F /PID`, 그 외에서 `SIGTERM`으로 대상 프로세스를 종료하고, 10초 동안 0.2초 간격으로 pid 파일 기반 확인이 `None`이 되기를 기다려 pid 파일 삭제 후 종료 코드 0, 마감 초과 시 `FAILED ...` 출력 후 종료 코드 1을 반환한다. — 근거: `daemon_ctl.py:21`, `daemon_ctl.py:91-96`, `daemon_ctl.py:154-166`
- **AC-034** `restart`는 `stop`이 0을 반환할 때만 `start`를 실행하고, 아니면 종료 코드 1을 반환한다. — 근거: `daemon_ctl.py:169-172`

### 조사 스크립트

- **AC-035** `bench_cold_vs_warm.py`는 `haiku` 모델·`text`/`json` 형식의 `claude -p`로 cold(스폰 포함 전체 시간)와 prewarmed(스폰 1초 후 입력 시점부터의 시간)를 각각 10회 순차 측정하고, 회차별 시간과 평균·중앙값을 출력한다. — 근거: `scripts/bench_cold_vs_warm.py:14-83`
- **AC-036** `investigate_stream_json_timeout.py`는 `stream-json` 입출력·`--verbose`의 `claude -p`를 스폰해 15초 대기 후 stream-json user 메시지 한 줄을 넣고, 30초 안의 종료 코드·stdout 줄 타입·result 줄·stderr를 출력한다(30초 초과 시 kill 후 `TIMED OUT` 출력). — 근거: `scripts/investigate_stream_json_timeout.py:16-77`

## 아키텍처 참조

이 spec이 다루는 영역의 실측 구조 문서다. 공통 색인은 [architecture.md](../../architecture/architecture.md)이며, 사전 설계(design) 문서는 없다.

- [00-overview.md](../../architecture/as-built/00-overview.md) — 실제 진입점·실행 경로, 요청 1건 런타임 플로우
- [01-project-structure.md](../../architecture/as-built/01-project-structure.md) — 실제 폴더·진입점, File Responsibility Map(34개 파일)
- [02-external-dependencies.md](../../architecture/as-built/02-external-dependencies.md) — 매니페스트 패키지·버전 제약, lockfile 부재, 외부 실행 의존
- [04-testing-strategy.md](../../architecture/as-built/04-testing-strategy.md) — 테스트 구성·가짜 CLI 경계·실행 방법
- [06-build-and-run.md](../../architecture/as-built/06-build-and-run.md) — 확인된 설치·실행·종료·복구 절차와 출처
- [07-development-patterns.md](../../architecture/as-built/07-development-patterns.md) — 2회 이상 반복된 구현 형태·확장 경로·이탈 지점
- [08-system-context.md](../../architecture/as-built/08-system-context.md) — 호출자·`claude` CLI·Job Object·파일시스템·OS 도구 관계
- [13-error-policy.md](../../architecture/as-built/13-error-policy.md) — 예외 처리 지점, kind↔HTTP 매핑, 응답 구현, `FAILURE_KINDS` 관계
- [15-non-functional-requirements.md](../../architecture/as-built/15-non-functional-requirements.md) — 워커·타임아웃·job 보관 제한값, 측정 근거 확인 상태

## 위험·테스트·문서 영향

### 위험(코드에서 관찰되는 결합·전제, 결함 평가 아님)

- 클라이언트의 `generate` 소켓 타임아웃 기본값 120.0은 클라이언트 상수이고, 데몬의 `CLAUDE_POOL_TIMEOUT_SEC`와 코드로 연결되어 있지 않다(`client.py:118`).
- 클라이언트의 `wait()`/`job()`은 서버의 job 조회 응답 규약(실패 job도 200, 없는 job은 404, `status` 값 집합)에 결합되어 있다. 서버 규약은 gateway-api 영역이다.
- `daemon_ctl.status`는 `/health` 응답의 `idle_alive`, `idle`, `busy`, `min_workers`, `max_workers`, `jobs.running`, `jobs.total`, `healthy` 키를 직접 인덱싱한다(`daemon_ctl.py:113-116`). `pool.stats()`·`jobs.stats()`의 키 집합에 결합되어 있다.
- `daemon_ctl`의 프로세스 식별은 명령줄 문자열 `claude_pool.daemon` 포함 여부에 의존하고, Windows 폴백은 프로세스 이름 `python.exe`로 필터한다(`daemon_ctl.py:57`, `daemon_ctl.py:71-73`). 외부 명령(`powershell`, `ps`, `pgrep`, `taskkill`)의 존재를 전제한다.
- 두 조사 스크립트는 실제 `claude` CLI를 호출하므로 인증된 CLI와 구독 쿼터를 사용한다. 이 저장소의 지침상 테스트에서 호출하지 않는 대상이다.

### 테스트

- 클라이언트: `tests/test_client.py`가 가짜 CLI(`tests/fixtures/fake_claude_cli.py`, echo 모드)로 스레드에서 띄운 데몬을 상대로 generate/submit/wait/jobs/cancel/job/health/api_info를 검증하고, `_error_from`은 합성 `HTTPError`로, 자동 기동은 `subprocess.Popen`을 monkeypatch해 argv·env만 검증한다(실제 데몬 프로세스를 띄우지 않음).
- 자동 기동의 health 대기 루프·Windows 분리 플래그, `_call`의 비 HTTPError 전파는 전용 테스트가 없다(`tests/` 검색 기준).
- `scripts/daemon_ctl.py`를 import하거나 호출하는 테스트는 `tests/`에 없다. 관련 테스트는 `tests/test_daemon.py`의 pid 파일 기록·삭제 테스트 2건(데몬 쪽)뿐이다.
- 두 조사 스크립트에 대한 테스트는 없다(수동 실행 스크립트).

### 문서 영향

- `src/claude_pool/apidocs.py:65-66`이 데몬 자기 문서의 사용 예로 `from claude_pool.client import ClaudePoolClient` / `ClaudePoolClient()`를 싣는다. 클라이언트 공개 API가 바뀌면 이 예제도 영향을 받는다.
- README·CLAUDE.md가 `daemon_ctl.py` 명령과 클라이언트 사용법을 안내한다(사용자 문서, 사실 근거로는 사용하지 않음).

## 열린 질문과 확정 결정

### 확정 결정(코드·주석·커밋으로 확인됨)

- 클라이언트는 stdlib만 사용한다 — `client.py:1-9`, 커밋 `bbbd72d`.
- 자동 기동 시 클라이언트의 host·port를 환경변수로 넘긴다 — `client.py:58-62` 주석.
- `generate`는 데몬 타임아웃보다 5초 긴 소켓 타임아웃을 쓴다 — `client.py:116-117` 주석.
- 비 JSON 오류 본문도 `ClaudePoolError`로 올린다 — `client.py:181-182` 주석.
- `wait()`는 실패·취소된 job을 `generate()`와 같은 방식(분류를 담은 예외)으로 실패시킨다 — `client.py:152-153` docstring.
- pid 파일은 포트별이며 힌트로만 취급하고, 종료 전 명령줄로 데몬임을 확인한다 — `daemon.py:16-23`, `daemon_ctl.py:47-57`, 커밋 `821f6e9`.
- pid 파일이 없고 후보 데몬이 여럿이면 추측하지 않고 거부한다 — `daemon_ctl.py:139-150`, 커밋 `821f6e9`.
- 워커 입출력을 stream-json으로 정한 근거가 조사 스크립트와 커밋 `c130f07`에 있다.

### 추정·열린 질문

- 추정: `_is_healthy()`가 본문의 `healthy` 필드를 보지 않고 응답 여부만 보는 것은 "데몬 프로세스가 떠 있는가"만을 자동 기동 판단 기준으로 삼으려는 의도다(코드 주석 없음). (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 추정: 비 Windows에서 자동 기동 시 세션 분리 옵션을 주지 않는 이유는 기록되어 있지 않다(미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음). 사용자 확인(2026-09-17 migration): 비 Windows도 공식 지원 대상이므로, 'Windows만 주 대상이라서'라는 이전 추론은 성립하지 않는다.
- 추정: `generate`의 기본 120.0은 데몬 기본 `CLAUDE_POOL_TIMEOUT_SEC`(120, `config.py:28`, `config.py:87`)에 맞춘 값이다(코드에서 두 값을 연결하지 않음). (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 추정: `daemon_ctl.status`가 model을 데몬 응답이 아니라 로컬 `PoolConfig.from_env()`에서 출력하는 이유는 기록되어 있지 않다. `/health`에는 model 필드가 없지만(`pool.py:234-249`) 데몬은 `GET /`의 설정 정보로 model을 노출하고(`apidocs.py:114`의 `api_info`) 클라이언트에도 `api_info()`가 있으므로(`client.py:198-200`), `/health`에 없다는 것만으로는 이유가 설명되지 않는다. (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 추정: `investigate_stream_json_timeout.py`의 `main()`이 15초 한 가지만 실행하는 것은 커밋 메시지의 0s/6s 실행 이후 코드가 최종 형태로 정리된 결과다(커밋 `c130f07`은 이 파일을 처음 추가한 커밋이며, 0s/6s를 실행한 코드 형태는 확인 불가). (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 확인된 사실: `bench_cold_vs_warm.py`의 유일한 커밋은 `7f729fe`이고, 같은 시기 워커 구현(`git show cffca1f:src/claude_pool/worker.py`)도 `--input-format text`·`--output-format json`을 썼다. 워커는 이후 `c130f07`의 조사를 거쳐 `f6f9fb4`에서 stream-json으로 바뀌었고 이 스크립트는 바뀌지 않았다.
- 열린 질문: 두 조사 스크립트의 실측 수치(cold/warm 평균·중앙값, 지연별 결과)는 결과 문서가 커밋 `5ad4e5f`에서 삭제되어 앵커 tree에서 확인할 수 없다. 삭제 직전 판은 `git show 5ad4e5f^:docs/superpowers/plans/2026-07-28-claude-pool-spike-results.md`(최초 추가 `7f729fe` 뒤 `eea6e36`에서 수정됨)와 `git show 5ad4e5f^:docs/superpowers/plans/2026-07-28-stream-json-investigation.md`로 읽을 수 있으나 이 분석에서는 수치를 옮기지 않았다.
- 확인된 사실: `cancel()` docstring의 "forget a finished one"과 달리 서버 `JobStore.cancel`은 종결된 job의 상태를 바꾸지 않고 그대로 반환하며 저장소에서 지우지 않는다. 제거는 보관 기간 경과 뒤 reap으로만 일어난다(gateway-api spec AC-028·AC-029, `jobs.py:141-154`). 사용자 확인(2026-09-17 migration): 이 동작이 의도한 계약이며 docstring 문구가 이와 다르게 읽힌다.

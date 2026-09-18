---
description: 기존 코드에서 역추론한 워커 풀·워커 수명주기 spec — 예열 `claude -p` 워커 스폰(stream-json·CREATE_NO_WINDOW·Job Object), 1회용 워커 정책, acquire/release, min~max 오토스케일, 스폰 실패 처리, stop 드레인, /health용 stats
status: implemented
revision: 1
plan: 없음
origin: migration
architecture:
  - ../../architecture/as-built/00-overview.md
  - ../../architecture/as-built/01-project-structure.md
  - ../../architecture/as-built/02-external-dependencies.md
  - ../../architecture/as-built/04-testing-strategy.md
  - ../../architecture/as-built/07-development-patterns.md
  - ../../architecture/as-built/08-system-context.md
  - ../../architecture/as-built/09-component-architecture.md
  - ../../architecture/as-built/10-data-flow.md
  - ../../architecture/as-built/12-security-auth.md
  - ../../architecture/as-built/14-observability-logging.md
  - ../../architecture/as-built/15-non-functional-requirements.md
---

# 워커 풀과 워커 수명주기 (역작성 spec)

## 분석 기준

- 분석 커밋 앵커: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` (브랜치 `master`, 작업공간 clean — 추적 파일이 앵커 tree와 같음)
- 확인 범위: `src/claude_pool/worker.py`, `src/claude_pool/pool.py`, `src/claude_pool/winjob.py`, `src/claude_pool/config.py`(풀·워커가 쓰는 필드), 경계 확인용 `src/claude_pool/runner.py`·`src/claude_pool/daemon.py`, 테스트 `tests/test_worker.py`·`tests/test_pool.py`·`tests/test_winjob.py`·`tests/conftest.py`·`tests/fixtures/fake_claude_cli.py`·`tests/fixtures/test_fake_claude_cli.py`, 보조 참조 `tests/test_server.py`·`tests/test_integration.py`·`tests/test_daemon.py`의 풀 관련 테스트.
- 이력 근거는 `git log`/`git show`로 확인한 커밋 해시를 적었다. 테스트는 실행하지 않았고, 테스트 코드가 표현하는 기대 동작만 근거로 삼았다.

## 배경과 해결할 문제

`claude-pool`은 Claude Code CLI를 로컬 HTTP LLM 엔드포인트로 노출한다. `claude -p` 프로세스를 요청마다 새로 띄우면 CLI 부팅 비용을 매번 치르게 되므로, 이 영역은 다음을 해결한다.

1. **부팅 비용 선지불**: 요청이 오기 전에 `claude -p` 워커 프로세스를 미리 스폰해 stdin 입력 대기 상태로 둔다(예열). 커밋 `7f729fe`("spike: validate pre-warm saves boot time vs cold spawn")가 예열 설계의 사전 검증 기록이다.
2. **요청 간 컨텍스트 격리**: 워커 하나는 프롬프트 하나만 처리하고 폐기된다(1회용). 다른 요청과 대화 상태를 공유하지 않는다.
3. **부하에 따른 워커 수 조절**: `min_workers`를 기저로 유지하고, 대기 수요가 있으면 `max_workers`까지 늘리며, idle이 지속되면 `min_workers`까지 줄인다.
4. **고아 프로세스 방지**: 정상 종료(`stop()`), 요청 취소, 데몬 비정상 종료(크래시·강제 종료) 모든 경로에서 워커 프로세스가 남지 않도록 한다. 비정상 종료는 Windows Job Object(`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`)로 OS 커널이 정리한다(커밋 `ecb5d0e`).
5. **Windows 콘솔 창 억제**: 콘솔 없는 데몬이 콘솔 앱을 스폰할 때 워커마다 터미널 창이 뜨는 현상을 `CREATE_NO_WINDOW`로 억제한다(커밋 `7970bb6`, 주석 `worker.py:12-20`).
6. **겉보기 정상 탐지**: 카운터만 보면 정상으로 보이지만 예열 워커 프로세스가 이미 죽어 있는 상태를 `/health`에서 드러낼 수 있도록 `idle`(카운터)과 `idle_alive`(생존 확인)를 분리해 보고한다(`pool.py:224-249` docstring).

## 범위와 비범위

### 범위

- `Worker`: argv 구성, 서브프로세스 스폰(파이프·cwd·creationflags), Job Object 할당, 생존 확인(`is_alive`), 단일 프롬프트 실행(`run`)과 stream-json 결과 파싱, 종료(`kill`).
- `WorkerPool`: 초기 예열(`start`), 워커 대여(`acquire`/`_acquire`), 반납(`release`/`release_in_background`), 수요 기반 증가(`_schedule_grow`/`_grow_by_one`), idle 축소 루프(`_scale_down_loop`), 스폰 실패 기록과 대기자 깨우기, 종료 드레인(`stop`), 실행 결과 메모(`note_failure`/`note_success`), 상태 보고(`stats`).
- `winjob`: kill-on-close Job Object 생성과 프로세스 할당(Windows 전용, 그 외 플랫폼 no-op).
- `PoolConfig` 중 이 영역이 읽는 필드: `min_workers`, `max_workers`, `model`, `acquire_timeout_sec`, `idle_timeout_sec`, `scale_down_interval_sec`, `scratch_dir`, `claude_cmd`.
- 테스트 대역 가짜 CLI(`tests/fixtures/fake_claude_cli.py`)가 흉내 내는 워커 프로토콜 부분집합.

### 비범위 (경계만 언급)

- HTTP 라우트(`/generate`, `/health`, `/jobs`)와 Host 헤더 미들웨어 — 서버 영역. 이 영역은 `stats()` dict를 제공하고 `server.py:161-162`가 이를 `/health` 응답에 쓰며 `jobs` 통계를 덧붙인다.
- 워커 실패 분류(`errors.classify`, `Failure`의 kind/status/retryable) — 실패 분류 영역. 이 영역은 `WorkerError`·`asyncio.TimeoutError`·`PoolUnavailableError`를 발생시키고, 분류는 `runner.execute()`(`runner.py:37-67`)가 수행한다.
- 백그라운드 job 저장·취소(`JobStore`) — job 영역. 데몬 종료 시 `jobs.shutdown()`이 `pool.stop()`보다 먼저 호출된다(`daemon.py:48-51`).
- 데몬 조립·pid 파일·클라이언트 자동 기동 — 데몬/클라이언트 영역.
- `PoolConfig`의 host 검증·환경변수 로딩 규칙 전체 — 설정 영역(이 문서는 필드 사용만 다룬다).

## 현재 구조와 책임

역작성 문서이므로 바뀌는 책임은 없다. 현재 구조는 다음과 같다.

| 구성 요소 | 파일 | 책임 |
|---|---|---|
| `CREATION_FLAGS` | `worker.py:20` | win32면 `subprocess.CREATE_NO_WINDOW`, 그 외 `0` |
| `WorkerError` | `worker.py:23-24` | 워커가 non-zero 종료했거나 결과를 파싱할 수 없을 때 발생 |
| `Worker` | `worker.py:27-126` | `claude -p` 프로세스 1개를 감싸는 1회용 래퍼 |
| `STOP_DRAIN_TIMEOUT_SEC = 5.0` | `pool.py:11` | `stop()`이 진행 중 백그라운드 작업을 기다리는 상한 |
| `PoolUnavailableError` | `pool.py:14-15` | 워커를 내줄 수 없을 때(스폰 실패·대기 타임아웃·종료 중) 발생 |
| `WorkerPool` | `pool.py:18-249` | 워커 집합·카운터·조건변수 관리, 오토스케일, 종료, 상태 보고 |
| `create_kill_on_close_job` | `winjob.py:20-29` | kill-on-close Job Object 생성, 비 Windows는 `None` |
| `assign_process_to_job` | `winjob.py:32-41` | pid를 job에 할당, job이 `None`이면 no-op |

### 풀 내부 상태 (`pool.py:19-38`)

- `_job`: 풀당 1개의 kill-on-close Job Object(비 Windows는 `None`). 풀이 스폰하는 모든 워커가 이 job을 받는다(`pool.py:85`).
- `_idle: deque[Worker]`: 대여 가능한 예열 워커.
- `_total`: 풀이 보유한 것으로 계산하는 워커 수(idle + 대여 중).
- `_waiting`: `_cond.wait()`로 대기 중인 acquire 호출 수.
- `_cond: asyncio.Condition`: 상태 변경의 직렬화와 대기자 깨우기에 쓰는 단일 조건변수.
- `_last_spawn_error`: 마지막 스폰 실패 예외. 스폰 성공 시 `None`으로 초기화(`pool.py:89`).
- `_last_error`: 마지막 요청 실패 메시지(`note_failure`/`note_success`로 갱신).
- `_pending_grows`: 예약됐지만 아직 끝나지 않은 증가 작업 수.
- `_scale_down_task`, `_background_tasks`(증가·반납 작업 추적 집합), `_stopped`.

모든 상태는 프로세스 메모리에만 있다. 영속 저장은 없다.

### 워커 사용 경로의 외부 경계

- 풀의 소비자는 `runner.execute()` 하나다(`runner.py:41` `pool.acquire()`, `runner.py:61` `asyncio.shield(pool.release_in_background(worker))`, `runner.py:70-75` `note_success`/`note_failure`). `/generate`와 `/jobs` 모두 이 함수를 거친다(`runner.py:1-7` docstring).
- 데몬은 `WorkerPool(config)` 생성 → `pool.start()` → 종료 시 `jobs.shutdown()` → `pool.stop()` 순서로 호출한다(`daemon.py:28-51`).

## 동작 상세

### 1. 워커 argv와 프로토콜 (`worker.py:34-46`)

argv는 다음 순서로 구성된다.

```
*claude_cmd, "-p",
"--input-format", "stream-json",
"--output-format", "stream-json",
"--verbose",
"--no-session-persistence",
"--tools", "",
"--strict-mcp-config",
"--safe-mode",
"--model", <config.model>
```

- `claude_cmd`는 리스트로 펼쳐 앞에 붙는다(기본 `["claude"]`, `config.py:39`). 테스트는 `[sys.executable, fake_claude_cli.py, ...]`를 주입한다.
- `--model`은 `config.model` 하나로 고정된다. 요청별 모델 인자를 받는 경로는 `Worker`/`WorkerPool`에 없다.
- `--bare` 플래그는 argv에 없다.
- 설계 결정 근거: stream-json 입력으로 바꾼 커밋은 `f6f9fb4`("fix: switch worker to stream-json protocol to avoid the 3s stdin timeout")이며, 그보다 앞선 `c130f07`("docs: confirm stream-json input avoids the 3s stdin timeout", 사이에 설계 문서 커밋 `8b10824`·`ab1cca5`가 있다)이 확인 기록이다. 즉 `--input-format text`에서 stdin 대기 약 3초 후 포기하는 현상이 예열 설계와 맞지 않아 stream-json으로 전환했다.

### 2. 스폰 (`Worker.start`, `worker.py:48-62`)

1. `asyncio.create_subprocess_exec(*argv, stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=str(config.scratch_dir), creationflags=CREATION_FLAGS)`로 프로세스를 만든다.
2. 곧바로 `winjob.assign_process_to_job(self.job, pid)`로 Job Object에 할당한다. `job`이 `None`이면 아무것도 하지 않는다(`winjob.py:35-36`).
3. `became_idle_at = time.monotonic()`을 기록한다.

- `Worker(config)`를 `job` 인자 없이 만들 수도 있다(기본 `None`, `worker.py:28`). 풀은 항상 `job=self._job`을 넘긴다(`pool.py:85`).
- `start()` 내부에는 할당 단계에서 예외가 날 때 이미 생성된 프로세스를 정리하는 별도 코드가 없고, 예외는 호출자에게 전파된다.

### 3. Job Object (`winjob.py`)

- `create_kill_on_close_job()`: `CreateJobObject(None, "")` → `QueryInformationJobObject(JobObjectExtendedLimitInformation)` → `LimitFlags |= JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` → `SetInformationJobObject`. win32가 아니면 `None` 반환.
- `assign_process_to_job(job, pid)`: `OpenProcess(PROCESS_ALL_ACCESS, False, pid)`로 핸들을 열어 `AssignProcessToJobObject` 후 `finally`에서 핸들을 닫는다.
- `win32api`·`win32con`·`win32job` import는 `sys.platform == "win32"`일 때만 수행된다(`winjob.py:14-17`). 의존성은 `pywin32>=306; sys_platform == 'win32'`(`pyproject.toml`).
- 의도(모듈 docstring `winjob.py:1-9`, 커밋 `ecb5d0e`): job의 마지막 핸들이 닫히면 커널이 할당된 모든 프로세스를 종료하므로, 데몬이 Python 정리 코드를 실행하지 못하고 죽어도 워커가 정리된다. 커밋 `ecb5d0e` 본문에 실제 데몬을 `Stop-Process -Force`로 종료했을 때 워커 2개가 정리됐다는 실측 기록이 있다.

### 4. 생존 확인 (`Worker.is_alive`, `worker.py:64-74`)

- `self._proc is not None and self._proc.returncode is None`을 반환한다. 시작 전 워커는 `False`다.
- docstring이 이것을 보증이 아닌 best-effort 필터로 규정한다: `returncode`는 asyncio가 자식을 수확한 뒤에야 세팅되므로, 방금 죽은 프로세스는 짧은 동안 살아있다고 보고된다(주석상 실측: 스폰 후 약 150ms에 종료하는 CLI가 여전히 배포됨). 실제 오류는 `run()`의 exit code·stderr로 드러난다.

### 5. 실행 (`Worker.run`, `worker.py:76-121`)

1. 시작 전이면 `WorkerError("worker not started")`.
2. stdin에 `{"type":"user","message":{"role":"user","content":<prompt>}}` + `\n`을 UTF-8로 쓰고 `communicate()`로 EOF까지 기다린다. 전체를 `asyncio.wait_for(timeout=timeout_sec)`로 감싼다.
3. 타임아웃이면 `kill()` 후 `asyncio.TimeoutError`를 다시 발생시킨다.
4. `returncode != 0`이면 `WorkerError("worker exited with code {rc}: {stderr}")` (stderr는 `errors="replace"` 디코딩).
5. stdout을 `errors="replace"`로 디코딩해 줄 단위로 JSON 파싱하며, 빈 줄·파싱 불가 줄은 건너뛰고 첫 `"type": "result"` 줄을 채택한다. 없으면 `WorkerError("no 'result' line found in worker stream-json output")`.
6. 반환: `{"text": result.get("result",""), "duration_ms": result.get("duration_ms",0), "is_error": bool(result.get("is_error",False)), "subtype": result.get("subtype","")}`.

- `is_error: true`인 result 줄은 예외가 아니라 반환값의 `is_error=True`로 전달된다(해석은 `runner.py:63-66`).
- `communicate()`가 stdin을 닫고 프로세스 종료까지 기다리므로, `run()` 완료 후 워커 프로세스는 종료 상태다(`test_run_returns_parsed_result`가 `not worker.is_alive()`를 기대).
- `run()`이 외부에서 취소되면 `communicate()` 해제만으로는 프로세스가 종료되지 않는다(`test_release_kills_worker_whose_run_was_cancelled`의 주석과 `assert worker.is_alive()`). 종료는 `release()`가 담당한다.

### 6. 종료 (`Worker.kill`, `worker.py:123-126`)

- 프로세스가 있고 `returncode is None`일 때만 `kill()` 후 `wait()`. 이미 종료했거나 시작 전이면 no-op이므로 여러 번 호출해도 된다.

### 7. 초기 예열 (`WorkerPool.start`, `pool.py:40-44`)

- `_cond`를 잡은 상태에서 `min_workers`번 `_spawn_and_add_idle_locked()`를 순차 호출한다. 이 경로는 예외를 삼키지 않으므로 스폰이 실패하면 `start()`가 예외를 전파하고, 그 경우 축소 루프 태스크는 만들어지지 않는다.
- 모두 성공하면 `_scale_down_loop()`를 `asyncio.ensure_future`로 시작한다.
- `_spawn_and_add_idle_locked()`(`pool.py:83-90`): `Worker(config, job=_job)` 생성 → `start()` → `_idle`에 추가 → `_total += 1` → `_last_spawn_error = None` → `_cond.notify()`.

### 8. 대여 (`acquire`/`_acquire`, `pool.py:121-167`)

- `acquire()`는 `_acquire()`를 `asyncio.wait_for(timeout=config.acquire_timeout_sec)`로 감싸며, 타임아웃이면 `PoolUnavailableError("no worker available within {n}s")`로 바꾼다.
- `_acquire()`는 `_cond`를 잡고 다음을 반복한다.
  1. `_stopped`이면 `PoolUnavailableError("pool is shutting down")`.
  2. `_idle`에서 왼쪽부터 꺼내 `is_alive()`면 반환한다(FIFO). 죽은 것으로 판정되면 `_total -= 1` 후 `kill()`하고 다음 워커를 본다.
  3. idle이 비었고 `_total < max_workers`면 `_schedule_grow()`로 증가 작업 1개를 예약한다(`_pending_grows += 1`, 추적 태스크로 `_grow_by_one()` 실행).
  4. `_waiting += 1` 후 `_cond.wait()`, 깨어나면 `_waiting -= 1`.
  5. 깨어난 뒤 `_idle`이 비었고 `_pending_grows == 0`이며 `_last_spawn_error`가 있으면 `PoolUnavailableError("worker spawn failed: ...")`를 발생시킨다. 진행 중인 다른 증가 작업이 있으면 포기하지 않는다(커밋 `3842a27` 본문: 동시 진행 중인 grow가 곧 충족시킬 요청을 거절하던 경우를 고친 것).
- `_grow_by_one()`(`pool.py:169-178`): `_cond`를 잡고 `_total >= max_workers` 또는 `_stopped`면 아무것도 하지 않는다. 아니면 `_try_spawn_and_add_idle_locked()`. `finally`에서 `_pending_grows -= 1`.
- `_try_spawn_and_add_idle_locked()`(`pool.py:92-104`): 스폰 예외를 삼켜 `_last_spawn_error`에 기록하고 `_cond.notify()` 후 `False`를 반환한다. 실패해도 대기자를 깨워 빠르게 실패하게 하기 위함이다(docstring).
- 대여 중 워커는 `_idle`에 없고 `_total`에만 포함된다. 풀은 대여 중 워커 목록을 따로 보관하지 않는다.

### 9. 반납 (`release`/`release_in_background`, `pool.py:180-198`)

- `release(worker)`:
  1. 무조건 `worker.kill()` — 워커는 재사용하지 않는다. 주석(`pool.py:186-189`)은 성공·오류·타임아웃·클라이언트 연결 끊김으로 인한 취소 모든 경로를 덮기 위함이라고 밝힌다.
  2. `_cond`를 잡고 `_total -= 1`.
  3. `_total < min_workers`(기저 미달)이거나 `_waiting > 0 and _total < max_workers`(대기 수요)이고 `_stopped`가 아니면 `_try_spawn_and_add_idle_locked()`로 1개를 보충한다. 이 보충은 예외를 던지지 않는다(주석 `pool.py:196-197`: 호출자의 finally에서 예외가 나면 이미 계산된 응답이 500이 되기 때문).
- `release_in_background(worker)`: `release()`를 `_background_tasks`에 추적되는 태스크로 실행하고 그 태스크를 반환한다. 호출자가 취소돼도 반납이 버려지지 않고, `stop()`이 이 태스크를 기다린다(docstring `pool.py:181-182`). `runner.execute()`는 이를 `asyncio.shield`로 감싸 await한다.
- 설계 이력: `release()`가 회계 전에 무조건 kill하도록 한 변경과 스폰 실패 기록·notify, `acquire_timeout_sec` 도입, `stop()` 추가는 커밋 `3842a27`에 기록돼 있다.

### 10. idle 축소 (`_scale_down_loop`, `pool.py:200-222`)

- `scale_down_interval_sec`마다 깨어나 `_cond`를 잡고:
  - `excess_allowed = max(0, len(_idle) - min_workers)`.
  - `_idle`을 앞에서부터 순회하며, 이미 고른 수가 `excess_allowed` 미만이고 `now - became_idle_at > idle_timeout_sec`인 워커를 제거 대상으로, 나머지를 생존자로 분류한다. `_idle`을 생존자 deque로 교체한다.
- 락을 놓은 뒤 제거 대상마다 `kill()`하고 워커 1개당 `_cond`를 잡아 `_total -= 1`. 주석(`pool.py:218-219`)과 커밋 `3842a27` 본문: `stop()`이 이 루프를 취소할 수 있으므로, 일괄 감소 후 kill 도중 취소되면 카운터와 실제 종료가 어긋나던 것을 워커별 감소로 바꿨다.
- 1회용 모델에서 순차적인 acquire/release만으로는 idle이 `min_workers`를 넘게 쌓이지 않는다는 점을 테스트 주석이 명시하며(`test_scale_down_loop_kills_only_expired_excess_idle_workers`, `test_burst_scales_up_and_idle_scales_back_down`), 테스트는 `_idle`에 만료된 워커를 직접 넣어 축소 동작을 확인한다.
- `became_idle_at`은 `start()` 시점에만 설정되므로 워커의 idle 경과 시간은 스폰 시각 기준이다.

### 11. 종료 드레인 (`stop`, `pool.py:46-81`)

1. `_stopped = True`.
2. 축소 루프 태스크를 취소하고 `CancelledError`를 삼킨 뒤 `None`으로 둔다.
3. `_background_tasks`의 스냅샷을 `asyncio.wait(timeout=STOP_DRAIN_TIMEOUT_SEC=5.0)`로 기다린 뒤, 남은 것을 모두 `cancel()`하고 `gather(return_exceptions=True)`로 수거한다. 주석(`pool.py:61-62`): 진행 중인 스폰·반납이 착지해야 그 워커가 아래에서 kill된다.
4. `_cond`를 잡고 `_idle`을 비우고 `notify_all()`로 대기자를 모두 깨운다. 깨어난 대기자는 `_stopped` 검사에서 `PoolUnavailableError`를 받는다.
5. 비운 idle 워커마다 `kill()` 후 `_cond`를 잡아 `_total -= 1`.

- 대여 중(busy) 워커는 `stop()`이 건드리지 않는다. docstring(`pool.py:47-51`): 진행 중 요청의 `release()`가 나가면서 kill한다. `stop()` 이후의 `release()`는 kill·감소만 하고 보충하지 않는다(`not self._stopped` 조건).
- 데몬 종료 순서상 `jobs.shutdown()`이 먼저 job을 취소해 워커를 반납시키고, 그 다음 `pool.stop()`이 호출된다(`daemon.py:48-51` 주석).
- `stop()`을 거치지 못하는 종료에서는 Job Object가 정리를 맡는다(3절).

### 12. 실행 결과 메모 (`note_failure`/`note_success`, `pool.py:106-110`)

- `note_failure(error)`는 `_last_error = error`, `note_success()`는 `_last_error = None`. 호출자는 `runner._note()`(`runner.py:70-75`)다. 주석(`pool.py:31-33`): 카운터상 정상인 풀이 왜 응답하지 못하는지(로그인 만료, 레이트 리밋)를 `/health`가 보여주기 위함.

### 13. 상태 보고 (`stats`, `pool.py:224-249`)

반환 dict 키:

| 키 | 값 |
|---|---|
| `min_workers` | `config.min_workers` |
| `max_workers` | `config.max_workers` |
| `total` | `_total` |
| `idle` | `len(_idle)` (카운터) |
| `idle_alive` | `_idle` 중 `is_alive()`인 수 (생존 확인) |
| `busy` | `_total - len(_idle)` |
| `healthy` | `idle_alive == len(_idle)` |
| `last_spawn_error` | `str(_last_spawn_error)` 또는 `None` |
| `last_error` | `_last_error` |

- `healthy`는 idle로 계산된 워커가 전부 살아있을 때 `True`다. 빈 풀(`min_workers=0`)에서는 `0 == 0`이라 `True`다(주석 `pool.py:241-243`, `test_an_empty_on_demand_pool_is_not_reported_unhealthy`).
- `stats()`는 락을 잡지 않는 동기 메서드다.

### 14. 테스트 대역 (`tests/fixtures/fake_claude_cli.py`)

- `--fake-mode echo|error|crash`(기본 echo), `--fake-delay-sec`, `--fake-error-text`를 받고 알 수 없는 인자(실제 CLI 플래그)는 무시한다.
- stdin을 EOF까지 읽고 → 지연 → crash면 stderr 출력 후 exit 1; 아니면 user 메시지의 `content`를 꺼내 `{"type":"system","subtype":"init"}` 줄과 `{"type":"result", ...}` 줄을 출력한다. error 모드는 `is_error: true`, echo 모드는 `result`에 프롬프트를 그대로 담는다. `duration_ms`는 1.
- `tests/conftest.py`의 `make_pool` fixture는 생성한 풀을 teardown에서 `stop()`한다.

## 사용자 관찰 동작과 수용 기준

### 워커 스폰과 프로토콜

- **AC-001** 워커는 `claude_cmd` 뒤에 `-p`, `--input-format stream-json`, `--output-format stream-json`, `--verbose`, `--no-session-persistence`, `--tools ""`, `--strict-mcp-config`, `--safe-mode`, `--model <config.model>`을 붙인 argv로 스폰한다. 근거: `worker.py:34-46`, `tests/test_worker.py::test_build_argv_uses_stream_json_protocol`.
- **AC-002** 워커 프로세스는 stdin/stdout/stderr를 파이프로 연결하고 cwd를 `config.scratch_dir`로 두어 스폰한다. 근거: `worker.py:49-55`.
- **AC-003** 워커 스폰 시 `creationflags`를 항상 전달하며, Windows에서는 `CREATE_NO_WINDOW` 비트를 포함하고 그 외 플랫폼에서는 `0`이다. 근거: `worker.py:20`, `worker.py:55`, `tests/test_worker.py::test_worker_spawns_without_allocating_a_console_window`.
- **AC-004** 워커는 스폰 직후 자신의 pid를 전달받은 Job Object에 할당하며, job이 `None`이면 할당을 생략한다. 근거: `worker.py:61`, `winjob.py:32-41`, `tests/test_winjob.py::test_assign_process_to_job_is_a_noop_with_no_job`.
- **AC-005** 스폰이 끝난 워커는 살아있는 것으로 보고되고 `became_idle_at`에 양수 monotonic 시각이 기록된다. 근거: `worker.py:62`, `tests/test_worker.py::test_start_leaves_worker_alive_and_timestamped`.

### Job Object

- **AC-006** Windows에서 `create_kill_on_close_job()`은 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`가 설정된 job 핸들을 반환하고, 비 Windows에서는 `None`을 반환한다. 근거: `winjob.py:20-29`, `tests/test_winjob.py::test_create_kill_on_close_job_returns_a_job_handle`.
- **AC-007** job 핸들이 닫히면 그 job에 할당된 프로세스가 OS에 의해 종료된다. 근거: `winjob.py:1-9`, `tests/test_winjob.py::test_closing_the_job_kills_the_assigned_process`.
- **AC-008** 풀은 인스턴스당 job 하나를 만들어 자신이 스폰하는 모든 워커에 넘기며, `stop()` 없이 그 job 핸들만 닫혀도 풀의 워커 프로세스가 종료된다. 근거: `pool.py:25`, `pool.py:85`, `tests/test_pool.py::test_pool_workers_die_if_job_handle_closes_without_stop`.

### 워커 실행과 1회용 정책

- **AC-009** `run(prompt, timeout_sec)`은 stdin에 stream-json user 메시지 한 줄을 쓰고 EOF까지 기다린 뒤, stdout의 첫 `type: result` 줄에서 `text`·`duration_ms`·`is_error`·`subtype`을 담은 dict를 반환한다. 근거: `worker.py:79-121`, `tests/test_worker.py::test_run_returns_parsed_result`.
- **AC-010** `run()`이 반환된 뒤 해당 워커 프로세스는 종료 상태로 보고된다. 근거: `tests/test_worker.py::test_run_returns_parsed_result`(`assert not worker.is_alive()`).
- **AC-011** result 줄의 `is_error`가 참이면 `run()`은 예외 없이 `is_error=True`를 반환한다. 근거: `worker.py:119`, `tests/test_worker.py::test_run_raises_on_error_flagged_result`(테스트 이름과 달리 반환값의 `is_error is True`를 확인한다).
- **AC-012** 워커가 non-zero로 종료하면 `run()`은 종료 코드와 stderr를 포함한 `WorkerError`를 발생시킨다. 근거: `worker.py:92-96`, `tests/test_worker.py::test_run_raises_worker_error_on_crash`.
- **AC-013** stdout에 `type: result` 줄이 없으면 `run()`은 `WorkerError`를 발생시키고, 시작 전 워커에서 `run()`을 호출해도 `WorkerError`를 발생시킨다. 근거: `worker.py:77-78`, `worker.py:113-114`.
- **AC-014** `run()`이 `timeout_sec` 안에 끝나지 않으면 워커 프로세스를 kill하고 `asyncio.TimeoutError`를 발생시킨다. 근거: `worker.py:88-90`, `tests/test_worker.py::test_run_raises_timeout_and_kills_process`.
- **AC-015** `kill()`은 여러 번 호출하거나 시작 전에 호출해도 예외 없이 끝난다. 근거: `worker.py:123-126`, `tests/test_worker.py::test_kill_is_idempotent`, `tests/test_worker.py::test_kill_before_start_is_a_no_op`.
- **AC-016** `release(worker)`는 워커 프로세스를 무조건 kill하고 풀에 다시 넣지 않으며, `run()`이 취소돼 아직 살아있는 워커도 종료한다. 근거: `pool.py:185-192`, `tests/test_pool.py::test_release_kills_worker_whose_run_was_cancelled`.
- **AC-017** 동시에 들어온 서로 다른 프롬프트의 응답은 각 요청에 자기 프롬프트 결과로 대응된다. 근거: `tests/test_integration.py::test_concurrent_requests_do_not_bleed_context`.

### 예열·대여·보충

- **AC-018** `start()`는 `min_workers`개의 워커를 스폰해 idle로 둔다. 근거: `pool.py:40-43`, `tests/test_pool.py::test_start_primes_min_workers`.
- **AC-019** `acquire()`는 idle 워커를 내주고 그 워커를 busy로 집계하며, 반납 후 `total`이 `min_workers` 미만이 되면 1개를 보충한다. 근거: `pool.py:137-140`, `pool.py:193-198`, `tests/test_pool.py::test_acquire_and_release_serves_one_request_then_replenishes`.
- **AC-020** idle 워커가 없고 `total < max_workers`면 `acquire()`는 워커 1개 증가를 예약하고 그 워커가 준비되기를 기다린다. 근거: `pool.py:149-156`, `tests/test_pool.py::test_acquire_beyond_idle_capacity_grows_and_waits`, `tests/test_integration.py::test_burst_scales_up_and_idle_scales_back_down`.
- **AC-021** 풀의 `total`은 `max_workers`를 넘지 않으며, 한도에 도달하면 추가 `acquire()`는 반납으로 워커가 보충될 때까지 기다린다. 근거: `pool.py:149`, `pool.py:172`, `pool.py:194`, `tests/test_pool.py::test_acquire_never_exceeds_max_workers`.
- **AC-022** `acquire()`는 idle 중 이미 죽은 것으로 판정되는 워커를 내주지 않고 폐기하며 `total`에서 뺀다. 근거: `pool.py:137-147`, `tests/test_pool.py::test_acquire_discards_dead_idle_workers`.
- **AC-023** 반납 시점에 대기 중인 `acquire()`가 있고 `total < max_workers`면, `min_workers` 이상이어도 1개를 보충한다. 근거: `pool.py:194-198`.
- **AC-024** `acquire_timeout_sec` 안에 워커를 얻지 못하면 `acquire()`는 `PoolUnavailableError`를 발생시킨다. 근거: `pool.py:121-129`, `tests/test_pool.py::test_acquire_times_out_when_pool_is_exhausted`.

### 스폰 실패

- **AC-025** 증가를 위한 스폰이 실패하고 진행 중인 다른 증가 작업이 없으며 idle이 비어 있으면, `acquire()`는 타임아웃을 기다리지 않고 `PoolUnavailableError("worker spawn failed: ...")`를 발생시킨다. 근거: `pool.py:92-104`, `pool.py:158-167`, `tests/test_pool.py::test_acquire_fails_fast_when_worker_spawn_fails`.
- **AC-026** `release()` 안의 보충 스폰이 실패해도 `release()`는 예외를 호출자에게 전파하지 않으며, 실패한 보충은 `total`에 더해지지 않는다. 근거: `pool.py:196-198`, `tests/test_pool.py::test_release_never_propagates_a_failed_replenish`.
- **AC-027** 스폰 실패는 `last_spawn_error`로 기록되고 다음 스폰 성공 시 `None`으로 지워진다. 근거: `pool.py:89`, `pool.py:101`, `pool.py:245-247`.
- **AC-028** `start()`의 초기 예열 스폰은 실패 예외를 삼키지 않고 호출자에게 전파한다. 근거: `pool.py:41-43`(`_spawn_and_add_idle_locked` 사용).

### idle 축소

- **AC-029** 축소 루프는 `scale_down_interval_sec`마다 idle 워커 중 `idle_timeout_sec`를 초과한 워커를 kill하되, idle 수가 `min_workers` 아래로 내려가지 않는 개수까지만 kill한다. 근거: `pool.py:200-222`, `tests/test_pool.py::test_scale_down_loop_kills_only_expired_excess_idle_workers`, `tests/test_integration.py:79-88`(만료 워커를 직접 넣어 축소를 확인하는 구간). `tests/test_pool.py::test_scale_down_shrinks_idle_workers_back_to_min`은 주석(`tests/test_pool.py:107-110`)대로 축소 루프 유무와 무관하게 같은 결과가 나오므로 이 AC의 근거로 쓰지 않는다.
- **AC-030** 축소 루프는 `idle_timeout_sec`를 넘지 않은 idle 워커를 살려두고 idle 목록에 유지한다. 근거: `tests/test_pool.py::test_scale_down_loop_kills_only_expired_excess_idle_workers`(originals 유지 확인).

### 종료 드레인

- **AC-031** `stop()`은 축소 루프를 취소하고(`_scale_down_task`를 `None`으로), idle 워커를 모두 kill하며 `total`을 그만큼 줄인다. 근거: `pool.py:52-81`, `tests/test_pool.py::test_stop_kills_idle_workers_and_cancels_scale_down_loop`.
- **AC-032** `stop()`은 대기 중인 `acquire()`를 깨워 `acquire_timeout_sec`를 기다리지 않고 `PoolUnavailableError`로 끝나게 하며, 종료 이후의 `acquire()`도 같은 예외를 발생시킨다. 근거: `pool.py:134-135`, `pool.py:73-75`, `tests/test_pool.py::test_stop_wakes_parked_acquire_waiters`.
- **AC-033** `stop()`은 추적 중인 증가·반납 백그라운드 작업을 최대 5초(`STOP_DRAIN_TIMEOUT_SEC`) 기다린 뒤 남은 작업을 취소하고 idle 워커 정리로 넘어간다. 근거: `pool.py:11`, `pool.py:63-68`.
- **AC-034** `stop()`은 대여 중 워커를 kill하지 않으며, 종료 후 들어온 `release()`는 워커를 kill하고 보충 스폰을 하지 않는다. 근거: `pool.py:47-51`, `pool.py:172-173`, `pool.py:195`.
- **AC-035** 데몬이 종료되면 풀의 예열 워커 프로세스가 종료된다. 근거: `daemon.py:48-51`, `tests/test_daemon.py::test_run_daemon_kills_pool_workers_on_shutdown`.

### 상태 보고

- **AC-036** `stats()`는 `min_workers`, `max_workers`, `total`, `idle`, `idle_alive`, `busy`, `healthy`, `last_spawn_error`, `last_error` 키를 반환하며 `busy = total - idle`이다. 근거: `pool.py:233-249`, `tests/test_pool.py::test_start_primes_min_workers`, `tests/test_server.py::test_health_reports_pool_stats`.
- **AC-037** idle로 집계된 워커 프로세스가 죽어 있으면 `idle`은 그대로이고 `idle_alive`는 그만큼 작게, `healthy`는 `false`로 보고된다. 근거: `pool.py:233`, `pool.py:244`, `tests/test_server.py::test_health_reports_dead_prewarmed_workers_as_not_alive`.
- **AC-038** idle 워커가 0개인 풀(`min_workers=0`)은 `healthy: true`로 보고된다. 근거: `pool.py:241-244`, `tests/test_server.py::test_an_empty_on_demand_pool_is_not_reported_unhealthy`.
- **AC-039** `note_failure(error)`는 `last_error`를 해당 메시지로, `note_success()`는 `None`으로 설정한다. 근거: `pool.py:106-110`, `tests/test_server.py::test_successful_run_clears_the_last_error`.

### 테스트 대역

- **AC-040** 가짜 CLI는 알 수 없는 실제 CLI 플래그를 무시하고, echo 모드에서 user 메시지 내용을 `result`로, error 모드에서 `is_error: true`를 출력하며, crash 모드에서 non-zero로 종료한다. 근거: `tests/fixtures/fake_claude_cli.py`, `tests/fixtures/test_fake_claude_cli.py`의 4개 테스트.

## 아키텍처 참조

이 spec이 다루는 영역의 실측 구조 문서다. 공통 색인은 [architecture.md](../../architecture/architecture.md)이며, 사전 설계(design) 문서는 없다.

- [00-overview.md](../../architecture/as-built/00-overview.md) — 실제 진입점·실행 경로, 요청 1건 런타임 플로우
- [01-project-structure.md](../../architecture/as-built/01-project-structure.md) — 실제 폴더·진입점, File Responsibility Map(34개 파일)
- [02-external-dependencies.md](../../architecture/as-built/02-external-dependencies.md) — 매니페스트 패키지·버전 제약, lockfile 부재, 외부 실행 의존
- [04-testing-strategy.md](../../architecture/as-built/04-testing-strategy.md) — 테스트 구성·가짜 CLI 경계·실행 방법
- [07-development-patterns.md](../../architecture/as-built/07-development-patterns.md) — 2회 이상 반복된 구현 형태·확장 경로·이탈 지점
- [08-system-context.md](../../architecture/as-built/08-system-context.md) — 호출자·`claude` CLI·Job Object·파일시스템·OS 도구 관계
- [09-component-architecture.md](../../architecture/as-built/09-component-architecture.md) — 모듈 구성·의존 방향·조립 위치
- [10-data-flow.md](../../architecture/as-built/10-data-flow.md) — 미들웨어 순서, 동기·백그라운드 경로, 워커 획득·반납, 기동·종료 순서
- [12-security-auth.md](../../architecture/as-built/12-security-auth.md) — 인증 부재, loopback·Host 가드, job ID, 워커 플래그 적용 지점
- [14-observability-logging.md](../../architecture/as-built/14-observability-logging.md) — `/health` 구성, 오류 상태 기록, 로깅 미사용
- [15-non-functional-requirements.md](../../architecture/as-built/15-non-functional-requirements.md) — 워커·타임아웃·job 보관 제한값, 측정 근거 확인 상태

## 위험·테스트·문서 영향

### 위험 (코드가 명시하는 전제와 제약)

- `is_alive()`는 best-effort이므로 `acquire()`가 방금 죽은 워커를 내줄 수 있으며, 이 경우의 오류는 `run()`의 `WorkerError`로 나타난다(`worker.py:64-73`). 호출자(`runner.execute`)가 이를 분류한다.
- 워커 kill의 유일한 공통 경로는 `release()`/`release_in_background()`다. 워커를 쓰는 새 경로가 이를 거치지 않으면 취소 시 프로세스가 남을 수 있다는 점을 `runner.py:1-7` docstring과 `pool.py:186-189` 주석이 전제로 둔다.
- 비정상 종료 시 정리는 Windows Job Object에 의존하므로 비 Windows 플랫폼에서는 이 보호가 없다(`winjob.py:23-24`, `winjob.py:35-36`).
- `CREATE_NO_WINDOW`의 효과는 스폰 순간에만 관찰된다. 커밋 `7970bb6` 본문은 이미 떠 있는 워커의 `MainWindowHandle`로는 검증되지 않는다고 기록한다.
- 풀 상태는 메모리에만 있어 데몬 재시작 시 새로 예열한다.

### 테스트

- 모든 풀·워커 테스트는 `tests/fixtures/fake_claude_cli.py`를 `claude_cmd`로 주입하며 실제 `claude` CLI를 호출하지 않는다.
- Job Object 동작 테스트(`tests/test_winjob.py` 전체, `test_pool_workers_die_if_job_handle_closes_without_stop`)는 `sys.platform != "win32"`에서 skip된다.
- 축소 루프 테스트는 순차 acquire/release로는 초과 idle이 생기지 않으므로 `_idle`과 `_total`을 직접 조작한다(테스트 주석).
- 스폰 실패는 존재하지 않는 실행 파일 이름(`claude-pool-no-such-binary-xyz`)으로 재현한다.
- `max_workers` 한도·대기 동작은 짧은 sleep과 `done()` 확인 등 타이밍에 기대는 테스트가 포함돼 있다.

### 문서 영향

- 사용자 문서 `README.md`·`CLAUDE.md`가 이 영역의 제약(stream-json 고정, 1회용 워커, `CREATE_NO_WINDOW`, Job Object 할당, `idle` vs `idle_alive`, `is_alive` best-effort)을 서술한다. 코드 변경 시 함께 맞춰야 하는 대상이다.
- `/health` 응답 스키마와 `apidocs`의 문서 표는 `stats()` 키 집합에 의존한다(서버·문서 영역).

## 열린 질문과 확정 결정

### 확정 결정 (코드·주석·커밋으로 확인)

- 워커 입출력 프로토콜은 stream-json이다 — 커밋 `f6f9fb4`, `c130f07`.
- 워커는 1회용이며 반납 시 무조건 kill한다 — `pool.py:185-192`, 커밋 `3842a27`.
- 풀당 kill-on-close Job Object 1개에 모든 워커를 할당한다 — `pool.py:25`, `pool.py:85`, 커밋 `ecb5d0e`.
- Windows에서 워커를 `CREATE_NO_WINDOW`로 스폰한다 — `worker.py:12-20`, 커밋 `7970bb6`, `48ec227`.
- 모델은 풀(데몬)당 하나로 고정되며 요청별 override 경로가 없다 — `worker.py:45`.
- `acquire()`는 `acquire_timeout_sec`로 상한이 있고, 스폰 실패는 다른 증가 작업이 없을 때만 즉시 실패로 이어진다 — `pool.py:121-167`, 커밋 `3842a27`.
- `stop()`은 idle만 kill하고 busy는 각자의 `release()`에 맡긴다 — `pool.py:47-51`.
- `/health`는 카운터(`idle`)와 생존 확인(`idle_alive`)을 함께 보고한다 — `pool.py:224-249`.
- 설정 기본값은 코드 폴백값이다: `min_workers=4`, `max_workers=30`, `model="sonnet"`, `acquire_timeout_sec=60.0`, `idle_timeout_sec=60.0`, `scale_down_interval_sec=30.0`, `scratch_dir=~/.claude-pool/scratch`, `claude_cmd=["claude"]`(`config.py:23-39`, `config.py:81-101`). 운영 환경에서 실제로 주입되는 값은 저장소에서 확인할 수 없다.

### 열린 질문 (`추정:`)

- 추정: 증가를 대기자 수만큼이 아니라 `_acquire()` 루프 반복마다 1건씩 예약하고 한도 초과분은 `_grow_by_one()`에서 걸러내는 방식은, 스폰을 락 안에서 직렬화하면서 동시 대기자 각각이 최소 1회 증가를 트리거하도록 하려는 의도로 보인다. 코드 주석에 명시적 설명은 없다. (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 확인된 사실: 워커가 `_idle`에 들어가는 곳은 `pool.py:87`(스폰 직후)과 축소 루프의 생존자 재구성(`pool.py:216`)뿐이며 `release()`는 재삽입하지 않는다(`pool.py:185-198`). 따라서 워커는 idle 상태에 한 번만 들어가고, 스폰 시각이 곧 idle 시작 시각이다. 추정: `became_idle_at`을 스폰 시점에만 기록한 것은 이 전제를 의도한 설계다. (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 확인된 사실: `STOP_DRAIN_TIMEOUT_SEC=5.0`을 도입한 커밋 `3842a27`의 보고는 "`asyncio.wait` with a 5s budget"이라고만 적고 값의 선정 근거는 기록하지 않았다.
- 추정: `start()`의 초기 예열 스폰 실패를 삼키지 않고 전파하는 것은 데몬 기동 자체를 실패시키려는 의도로 보이며, 데몬은 이때 `finally`에서 `pool.stop()`을 호출한다(`daemon.py:40-51`). 의도를 밝힌 주석은 없다. (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 추정: `Worker.start()`에서 Job Object 할당이 예외를 내는 경우(프로세스는 생성된 상태) 그 프로세스를 어떻게 다룰지에 대한 설계 의도는 코드·커밋에서 확인되지 않는다. (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 확인된 사실: `PoolConfig.__post_init__`에는 `min_workers ≤ max_workers` 검증이 없고(`config.py:41-59`), `start()`는 `max_workers`와 무관하게 `min_workers`개를 스폰하므로(`pool.py:42`) 이 조합에서는 `total`이 `max_workers`를 넘는다. 사용자 확인(2026-09-17 migration): 이 값 검증 부재는 의도한 선택이 아니다(이 migration은 코드를 수정하지 않는다).
- 사용자 확인(2026-09-17 migration): 비 Windows 플랫폼(Linux/macOS)도 공식 지원 대상이다. 코드상 데몬 비정상 종료 시 고아 워커를 OS가 정리하는 수단(kill-on-close Job Object, `winjob.py:20-41`)은 Windows 분기에만 있고, 비 Windows에서는 `create_kill_on_close_job()`이 `None`을 반환해 할당이 no-op이다(`winjob.py:23-24`, `winjob.py:35-36`).

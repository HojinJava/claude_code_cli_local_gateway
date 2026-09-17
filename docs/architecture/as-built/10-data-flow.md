---
description: claude-pool의 실제 미들웨어 순서, 동기(/generate)·백그라운드(/jobs) 요청 경로, 워커 획득·반납·보충·축소, 취소와 데몬 기동·종료 순서
tags: [architecture]
status: as-built
---

# 10. 데이터 흐름 (as-built)

DB 호출은 없다. 요청 데이터는 메모리 객체(`Job`, `WorkerPool` 상태)와 자식 프로세스 파이프 사이에서만 이동한다.

## 미들웨어 파이프라인

- 등록된 미들웨어는 `require_loopback_host` 1개다(`src/claude_pool/server.py:52`). 모든 라우트가 이것을 먼저 통과한다.
- 순서: aiohttp 라우팅 → `require_loopback_host`(`server.py:28-48`) → 라우트 핸들러. 가드는 `request.host`에서 포트·IPv6 괄호를 떼어(`server.py:15-25`) `is_loopback_host`로 판정하고, 실패하면 핸들러를 호출하지 않고 403을 돌려준다.
- 요청 본문 크기 제한·CORS·압축·인증 미들웨어는 코드에 없다.

## 동기 경로 `POST /generate`

런타임 시퀀스 다이어그램은 [00-overview](00-overview.md#런타임-플로우--요청-1건)에 있다. 단계:

1. `handle_generate`(`server.py:115-124`) → `_read_prompt_request`(`server.py:77-97`): JSON 파싱, object 확인, `prompt` 문자열·비어 있지 않음 확인, `timeout_sec` `float()` 변환(생략 시 `config.default_timeout_sec`).
2. `runner.execute(pool, prompt, timeout_sec)`(`src/claude_pool/runner.py:37-67`).
3. `pool.acquire()`(`src/claude_pool/pool.py:121-167`) — 아래 [워커 획득](#워커-획득).
4. `worker.run(prompt, timeout_sec)`(`src/claude_pool/worker.py:76-121`): `{"type":"user","message":{"role":"user","content":prompt}}` + `\n`을 UTF-8로 stdin에 쓰고 `communicate()`를 `wait_for(timeout)`으로 감싼다. stdout에서 첫 `"type":"result"` JSON 줄의 `result`·`duration_ms`·`is_error`·`subtype`을 꺼낸다.
5. `finally`: `await asyncio.shield(pool.release_in_background(worker))`(`runner.py:57-61`) — 아래 [워커 반납](#워커-반납과-보충). 단 `TimeoutError`·`WorkerError` 분기는 `except` 안의 `return _note(...)` 식이 먼저 평가되므로 분류와 `note_failure` 기록이 이 반납보다 먼저 실행된다(`runner.py:51-56`).
6. 결과가 반환된 경우(반납 뒤): `result["is_error"]`면 결과 텍스트로 `classify`(`runner.py:63-66`), 아니면 `Outcome.ok`. 모든 결과는 `_note`로 `pool.note_success()`/`note_failure(error)`에 기록된다(`runner.py:70-75`).
7. 핸들러가 `Outcome`을 HTTP로 변환: 200 `{text, duration_ms}` 또는 `_failure_response`(`server.py:100-112`).

HTTP 연결은 5단계 완료까지 유지된다. 호출자 연결 끊김 등으로 핸들러 태스크가 취소되면, `finally`의 반납은 shield와 풀의 태스크 추적으로 계속 진행된다(주석 `runner.py:58-60`).

## 백그라운드 경로 `/jobs`

```mermaid
sequenceDiagram
    autonumber
    participant C as 호출자
    participant S as server.py 핸들러
    participant JS as JobStore (jobs.py)
    participant T as job 태스크 _run
    participant R as runner.execute

    C->>S: POST /jobs {prompt, timeout_sec?}
    S->>S: _read_prompt_request (400 경로는 /generate와 동일)
    S->>JS: submit(prompt, timeout_sec) (jobs.py:89-103)
    JS->>JS: _reap() → Job(id=token_urlsafe(12), status=running)
    JS->>T: asyncio.ensure_future(_run(job, prompt, timeout_sec))
    S-->>C: 202 job.to_dict() + url, Location: /jobs/{id}
    T->>R: execute(pool, prompt, timeout_sec) (jobs.py:107)
    R-->>T: Outcome
    T->>JS: _finish(job, succeeded|failed, ...) (jobs.py:119-125)
    C->>S: GET /jobs/{id} (반복 폴링)
    S->>JS: get(id) (jobs.py:134-135)
    S-->>C: 200 to_dict() / 404
```

- 전체 프롬프트는 `Job`에 저장하지 않고 태스크 인자로만 전달된다. `Job`에는 앞 80자 `prompt_preview`만 남는다(`jobs.py:32`, `jobs.py:96`, `jobs.py:100`).
- `_run`의 예외 처리(`jobs.py:105-125`): `CancelledError` → `cancelled` 기록 후 재발생, 그 외 예외 → `failed`·`worker_failed`/502 기록, 정상 반환 → `Outcome`에 따라 `succeeded`/`failed`.
- 태스크 완료 콜백이 `_tasks`에서 id를 제거한다(`jobs.py:102`). 종결 job 객체는 `_jobs`에 보관 규칙이 허용하는 동안 남는다.

### 취소 `DELETE /jobs/{id}`

`handle_cancel_job`(`server.py:153-157`) → `JobStore.cancel`(`jobs.py:141-154`):

1. id가 없으면 `None` → 404.
2. 태스크가 끝나지 않았으면 `task.cancel()` 후 `await asyncio.gather(task, return_exceptions=True)`로 태스크 종료까지 기다린다. 태스크 안의 `runner.execute`는 `finally`에서 shield된 반납을 수행하고, `_run`이 `cancelled`를 기록한다.
3. 태스크가 없거나 끝났는데 job이 종결 상태가 아니면 `cancelled`로 기록한다.
4. 이미 종결된 job은 변경하지 않는다. 이 경로에 저장소 삭제 문장은 없다.
5. 200 + 그 시점 `to_dict()`.

### 보관·상한 reap

`_reap()`(`jobs.py:164-183`)은 `submit()`(`jobs.py:90`)과 `list()`(`jobs.py:138`)에서만 호출된다. `get()`, `cancel()`, `stats()`는 reap하지 않는다. 순서: 보관 기간(`retention_sec`) 초과 종결 job 삭제 → 전체 수가 `max_jobs`를 넘으면 종결 job을 `finished_at` 오름차순으로 초과분 삭제(실행 중 job 제외). 수치는 [15-non-functional-requirements](15-non-functional-requirements.md).

## 워커 획득

`WorkerPool.acquire`(`pool.py:121-129`)가 `_acquire`(`pool.py:131-167`)를 `acquire_timeout_sec`로 감싼다. `_acquire`는 `_cond`를 잡고 반복한다.

```mermaid
flowchart TD
    A["acquire"] --> B{"_stopped?"}
    B -- 예 --> X1["PoolUnavailableError: shutting down"]
    B -- 아니오 --> C{"_idle 비어 있지 않음?"}
    C -- 예 --> D["popleft"]
    D --> E{"is_alive?"}
    E -- 예 --> R["워커 반환"]
    E -- 아니오 --> F["_total -= 1, kill"] --> C
    C -- 아니오 --> G{"_total < max_workers?"}
    G -- 예 --> H["_schedule_grow: _pending_grows += 1, _grow_by_one 태스크"]
    G -- 아니오 --> I
    H --> I["_waiting += 1, _cond.wait"]
    I --> J{"idle 없음 AND pending_grows == 0 AND last_spawn_error 있음?"}
    J -- 예 --> X2["PoolUnavailableError: spawn failed"]
    J -- 아니오 --> B
    A -. "acquire_timeout_sec 초과" .-> X3["PoolUnavailableError: no worker available"]
```

- `_grow_by_one`(`pool.py:169-178`)은 락 안에서 한도·종료를 재확인한 뒤 `_try_spawn_and_add_idle_locked`로 1개 스폰하고, `finally`에서 `_pending_grows`를 줄인다.
- 스폰(`pool.py:83-90`): `Worker(config, job=self._job)` → `worker.start()`(`worker.py:48-62`: `create_subprocess_exec`, `CREATION_FLAGS`, Job Object 할당, `became_idle_at` 기록) → `_idle` 추가 → `_total += 1` → `_last_spawn_error = None` → `notify()`.

## 워커 반납과 보충

- `release_in_background(worker)`(`pool.py:180-183`)는 `release`를 `_background_tasks`에 추적되는 태스크로 실행한다.
- `release(worker)`(`pool.py:185-198`): 무조건 `worker.kill()` → 락 안에서 `_total -= 1` → `_total < min_workers`이거나 (`_waiting > 0` 그리고 `_total < max_workers`)이고 종료 중이 아니면 `_try_spawn_and_add_idle_locked`로 1개 보충. 워커는 idle로 되돌아가지 않는다.

## idle 축소

`_scale_down_loop`(`pool.py:200-222`): `scale_down_interval_sec`마다 락 안에서 `len(_idle) - min_workers`개까지, `became_idle_at`에서 `idle_timeout_sec`가 지난 idle 워커를 골라 `_idle`에서 뺀다 → 락 밖에서 워커마다 kill 후 락을 잡고 `_total -= 1`. `became_idle_at`은 `Worker.start()`에서만 기록된다(`worker.py:62`).

## 데몬 기동 순서

`run_daemon`(`src/claude_pool/daemon.py:26-39`):

1. `config.scratch_dir.mkdir(parents=True, exist_ok=True)`
2. `WorkerPool(config)`(이때 Job Object 생성), `JobStore(pool, ...)`
3. `await pool.start()` — `min_workers`개를 순차 스폰하고 축소 루프 시작(`pool.py:40-44`)
4. `create_app(pool, jobs)` → `AppRunner.setup()` → `TCPSite(host, port).start()`
5. pid 파일에 `os.getpid()` 기록
6. `_wait_for_shutdown_signal()`

## 데몬 종료 순서

`run_daemon`의 `finally`(`daemon.py:40-51`):

```mermaid
flowchart LR
    s0["종료 신호 또는 예외/취소"] --> s1["pid 파일 unlink<br/>daemon.py:43"]
    s1 --> s2["runner.cleanup<br/>runner가 있을 때, daemon.py:45-46"]
    s2 --> s3["jobs.shutdown<br/>실행 중 job 태스크 cancel·gather, jobs.py:156-162"]
    s3 --> s4["pool.stop<br/>pool.py:46-81"]
```

- `jobs.shutdown()`과 `pool.stop()`은 중첩 `finally`에 있어 `runner.cleanup()`이 예외를 내도 실행된다(`daemon.py:44-51`). 주석(`daemon.py:48-49`): job을 먼저 취소해야 워커가 풀로 반납되고 그 다음 `pool.stop()`이 정리한다.
- `pool.stop()`(`pool.py:46-81`): `_stopped = True` → 축소 루프 태스크 cancel → `_background_tasks`(증가·반납)를 최대 `STOP_DRAIN_TIMEOUT_SEC`(5.0초) 기다린 뒤 남은 태스크 cancel·gather → 락 안에서 idle 목록을 비우고 `notify_all()` → idle 워커마다 kill 후 `_total -= 1`. 대여 중 워커는 건드리지 않고 각 `release()`에 맡긴다(docstring `pool.py:47-51`).
- Python `finally`가 실행되지 않는 종료에서는 Job Object의 kill-on-close가 워커 정리 수단으로 설계돼 있다(`winjob.py:1-9`, `worker.py:57-60`).

## 실측 근거

- 기준 commit: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`
- 확인한 소스: [server.py](../../../src/claude_pool/server.py), [runner.py](../../../src/claude_pool/runner.py), [jobs.py](../../../src/claude_pool/jobs.py), [pool.py](../../../src/claude_pool/pool.py), [worker.py](../../../src/claude_pool/worker.py), [winjob.py](../../../src/claude_pool/winjob.py), [daemon.py](../../../src/claude_pool/daemon.py)
- 확인 범위: 제어 흐름 정적 추적. 동시성 경합·취소 타이밍을 실행으로 관찰하지 않았다.
- 미확인: aiohttp가 클라이언트 연결 끊김 시 핸들러 태스크를 취소하는 조건(프레임워크 버전·설정 의존), 신호 미지원 플랫폼에서 종료 시 `finally`가 실행되는 범위.

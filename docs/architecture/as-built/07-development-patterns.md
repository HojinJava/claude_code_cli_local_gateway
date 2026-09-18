---
description: claude-pool 코드에서 2회 이상 반복 확인된 구현 형태(핸들러 모양, runner 경유 워커 사용, 조건변수 하의 상태 변경, 태스크 추적, 플랫폼 분기, 가짜 CLI 주입 테스트)와 확장 경로·이탈 지점
tags: [architecture]
status: as-built
---

# 07. 개발 패턴 (as-built)

2회 이상 실제로 반복되고 파일 경로로 지목 가능한 형태만 기록한다. 모듈이 무엇인지는 [09-component-architecture](09-component-architecture.md), 실패 매핑 규약은 [13-error-policy](13-error-policy.md), 네이밍은 [05-coding-conventions](05-coding-conventions.md)가 소관이다.

## 1. 계층·의존 방향 관용구

### 1.1 핸들러는 앱 dict에서 의존 객체를 꺼낸다

- `create_app`이 `app["pool"]`, `app["jobs"]`에 객체를 넣고(`src/claude_pool/server.py:53-56`), 모든 핸들러가 `request.app["pool"]` 또는 `request.app["jobs"]`로 꺼낸다. 반복 위치: `server.py:79`, `server.py:121`, `server.py:133`, `server.py:140`, `server.py:149`, `server.py:154`, `server.py:161-162`, `server.py:167`, `server.py:171`, `server.py:175`.
- 별도 DI 컨테이너·전역 싱글턴은 없다. 조립은 `daemon.run_daemon`이 생성자 인자로 한다(`src/claude_pool/daemon.py:28-33`).

### 1.2 워커를 쓰는 경로는 `runner.execute()`를 거친다

- 동기 경로 `handle_generate`(`server.py:121`)와 백그라운드 경로 `JobStore._run`(`src/claude_pool/jobs.py:107`)이 같은 `execute(pool, prompt, timeout_sec)`를 호출한다.
- `execute`는 transport 무관 `Outcome`을 돌려주고, HTTP 변환은 호출자가 한다: 동기는 `_failure_response`/`json_response`(`server.py:122-124`), 백그라운드는 `JobStore._finish`에 기록 후 `to_dict()`(`jobs.py:119-125`, `jobs.py:52-71`).
- 워커 반납은 `execute` 안의 `finally`에만 있다(`src/claude_pool/runner.py:57-61`). 필요한 최소 형태:

```python
# src/claude_pool/runner.py:49-61 발췌 (분류 분기 일부 생략)
try:
    result = await worker.run(prompt, timeout_sec=timeout_sec)
except asyncio.TimeoutError:
    return _note(pool, Outcome.failed("worker timed out", Failure("timeout", 504, retryable=True)))
except WorkerError as exc:
    return _note(pool, Outcome.failed(str(exc), classify(str(exc))))
finally:
    await asyncio.shield(pool.release_in_background(worker))
```

### 1.3 예외는 경계에서 값으로 바꿔 위로 올린다

- `pool`·`worker`는 예외(`PoolUnavailableError`, `asyncio.TimeoutError`, `WorkerError`)를 던지고, `runner.execute`가 이를 `Outcome.failed(...)`로 바꾼다(`runner.py:40-56`). 핸들러는 `outcome.succeeded`만 분기한다(`server.py:122`, `jobs.py:120`).
- 요청 본문 오류는 `BadRequest` 예외로 올리고 핸들러가 잡아 400으로 바꾼다(`server.py:73-97`, `server.py:116-119`, `server.py:128-131`).

## 2. 반복 구현 형태

| 형태 | 반복 위치 | 설명 |
|---|---|---|
| 공통 본문 파서 + `BadRequest`→400 | `server.py:116-119`, `server.py:128-131` | `_read_prompt_request`로 `(prompt, timeout_sec)`를 얻고 `web.json_response({"error": str(exc)}, status=400)` |
| job 조회 실패 → 404 `{"error": "no such job"}` | `server.py:140-142`, `server.py:154-156` | `JobStore.get`/`cancel`이 `None`이면 같은 본문 |
| 결과를 `json_response`로 직렬화 | `server.py:124`, `server.py:136`, `server.py:145`, `server.py:150`, `server.py:157`, `server.py:163`, `server.py:167`, `server.py:171` | `/docs`만 `web.Response(text=..., content_type="text/html")`(`server.py:176`) |
| 풀 상태 변경은 `async with self._cond:` 안에서 | `pool.py:41`, `pool.py:70`, `pool.py:80`, `pool.py:132`, `pool.py:171`, `pool.py:191`, `pool.py:203`, `pool.py:221` | 단일 `asyncio.Condition`(`pool.py:29`)으로 직렬화·대기자 깨우기. 락이 필요한 내부 함수는 `_locked` 접미와 "Caller must hold" docstring(`pool.py:83-84`, `pool.py:92-97`) |
| 워커 kill 후 워커 1개마다 락을 잡고 `_total -= 1` | `pool.py:76-81`, `pool.py:217-222` | 주석: 도중 취소 시 카운터와 실제 종료가 어긋나지 않게(`pool.py:77-78`, `pool.py:218-219`) |
| 스폰 실패를 삼키고 기록·notify | `pool.py:92-104` 정의, 호출 `pool.py:174`, `pool.py:198` | `_try_spawn_and_add_idle_locked`가 `_last_spawn_error` 기록 후 `False` |
| 백그라운드 태스크를 컬렉션에 넣고 완료 콜백으로 제거 | `pool.py:112-115`(`set.discard`), `jobs.py:100-102`(`dict.pop`) | 종료 시 이 컬렉션을 모아 cancel·gather(`pool.py:63-68`, `jobs.py:158-162`) |
| 취소 후 `asyncio.gather(..., return_exceptions=True)`로 수거 | `pool.py:68`, `jobs.py:151`, `jobs.py:162` | 취소된 태스크 종료를 기다린 뒤 진행 |
| 프로세스 kill 후 `wait()` | `worker.py:123-126`, `scripts/investigate_stream_json_timeout.py:53-54` | kill만 하고 끝내지 않음 |
| `sys.platform == "win32"` 분기 | `worker.py:20`, `winjob.py:14`, `winjob.py:23`, `client.py:70`, `scripts/daemon_ctl.py:34`, `daemon_ctl.py:68`, `daemon_ctl.py:92` | Windows 전용 플래그·API·명령과 그 외 대체 |
| frozen dataclass 값 객체 | `runner.py:18-34`(`Outcome`, `ok`/`failed` classmethod), `errors.py:53-60`(`Failure`) | 결과·분류를 불변 값으로 전달 |
| 살아있는 `PoolConfig`로 문서 생성 | `server.py:167`, `server.py:171`, `server.py:175` → `apidocs.api_info`/`openapi_spec`/`render_html` | 요청마다 생성 |
| `PoolConfig.from_env()`로 설정 결정 | `daemon.py:66`, `scripts/daemon_ctl.py:183` | 데몬과 운영 스크립트가 같은 환경변수 규칙 사용 |

## 3. 테스트 작성 형태

| 형태 | 반복 위치 | 설명 |
|---|---|---|
| `FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"` | `tests/test_apidocs.py:11`, `test_client.py:14`, `test_daemon.py:13`, `test_host_guard.py:12`, `test_integration.py:12`, `test_jobs.py:11`, `test_pool.py:12`, `test_server.py:10`, `test_worker.py:10` | 가짜 CLI 경로 상수 |
| 모듈별 `make_config(tmp_path, ...)` 헬퍼 | `tests/test_apidocs.py:14-22`, `test_jobs.py:14-22`, `test_pool.py:16-26`, `test_server.py:13-21`, `test_worker.py:13-19` | 기본값에 `scratch_dir=tmp_path`, `claude_cmd=[sys.executable, str(FAKE_CLI), ...]`를 두고 override 병합 |
| `make_pool` fixture로 풀 생성 + `create_app(pool)` + `aiohttp_client` | `tests/test_server.py:24-29`, `test_jobs.py:149-153`, `test_apidocs.py:25-29`, `test_host_guard.py:15-26` | teardown에서 `stop()`(`tests/conftest.py:16-29`) |
| 없는 실행 파일로 스폰 실패 재현 | `tests/test_pool.py:13`, `test_server.py:81`, `test_server.py:204`, `test_daemon.py:139` | `"claude-pool-no-such-binary-xyz"` |
| Windows 전용 테스트 skip | `tests/test_winjob.py:9`, `test_pool.py:260` | `pytest.mark.skipif(sys.platform != "win32")` |
| Host 가드 적용 확인을 라우트 묶음마다 | `tests/test_host_guard.py:59-61`, `test_jobs.py:229-232`, `test_apidocs.py:89-92` | `Host: evil.example.com`으로 403 기대 |

## 4. 확장점 — 라우트 하나를 추가할 때 건드리는 파일

현재 `/jobs` 라우트 묶음이 걸쳐 있는 위치를 따라 도출했다(구현 사실, 규범 아님).

1. 업무 처리 모듈: 워커를 쓰면 `runner.execute()`를 호출한다(예: `src/claude_pool/jobs.py:105-125`).
2. 라우트 등록과 핸들러: `create_app`에 `app.router.add_*`(`server.py:61-64`), 핸들러 함수(`server.py:127-157`). 필요하면 `app[...]`에 의존 객체 추가(`server.py:54-56`).
3. 데몬 조립: 새 객체의 생성과 종료 순서(`daemon.py:28-29`, `daemon.py:48-51`).
4. 자기 문서: `api_info`의 `endpoints`(`apidocs.py:90-105`), `openapi_spec`의 `paths`(`apidocs.py:237-307`). `/docs` 엔드포인트 표는 `api_info`에서 파생된다(`apidocs.py:329-334`). 실패 kind가 추가되면 `FAILURE_KINDS`(`apidocs.py:31-45`).
5. 클라이언트 메서드: `client.py`에 `_call` 기반 메서드(`client.py:122-142`).
6. 테스트: 라우트 테스트 모듈, 경로 집합을 고정 비교하는 `tests/test_apidocs.py:67-73`, Host 가드 확인.

## 5. 패턴 이탈 지점

- `JobStore` 생성 위치가 두 곳이다: `daemon.py:29`와 `jobs`가 전달되지 않았을 때의 `server.py:54-56`. 테스트는 후자를 쓴다(예: `tests/test_server.py:28`).
- 400 본문은 `{"error"}`만 있고 `kind`·`retryable`이 없다(`server.py:119`, `server.py:131`). 다른 실패 응답은 세 키를 갖는다(`server.py:39-47`, `server.py:102-106`).
- `pool.start()`의 초기 스폰은 실패를 삼키지 않는 `_spawn_and_add_idle_locked`를 쓴다(`pool.py:41-43`). 증가·보충 경로는 삼키는 `_try_...`를 쓴다.
- 테스트 일부는 풀 비공개 상태(`_idle`, `_total`, `_proc`)를 직접 조작·조회한다(`tests/test_integration.py:79-84`, `tests/test_pool.py:123-140`, `tests/test_pool.py:278`).
- `tests/test_pool.py:227-257`의 두 테스트와 Windows 전용 테스트(`tests/test_pool.py:260-295`)는 `make_pool` 대신 `WorkerPool`을 직접 만든다. Windows 전용 테스트는 `stop()` 대신 `pool._job.Close()`와 워커 `kill()`로 정리한다.
- `tests/test_client.py`·`tests/test_daemon.py`는 `aiohttp_client` 대신 실제 TCP 포트(`conftest.unused_tcp_port`)를 쓴다.

## 실측 근거

- 기준 commit: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`
- 확인한 소스: [server.py](../../../src/claude_pool/server.py), [runner.py](../../../src/claude_pool/runner.py), [jobs.py](../../../src/claude_pool/jobs.py), [pool.py](../../../src/claude_pool/pool.py), [worker.py](../../../src/claude_pool/worker.py), [winjob.py](../../../src/claude_pool/winjob.py), [errors.py](../../../src/claude_pool/errors.py), [apidocs.py](../../../src/claude_pool/apidocs.py), [daemon.py](../../../src/claude_pool/daemon.py), [client.py](../../../src/claude_pool/client.py), [daemon_ctl.py](../../../scripts/daemon_ctl.py), [investigate_stream_json_timeout.py](../../../scripts/investigate_stream_json_timeout.py), `tests/**/*.py` 전부
- 확인 범위: 반복 위치를 정적 읽기와 `grep`으로 확인. 패턴의 효과(동시성 안전성 등)는 검증하지 않았다.
- 미확인: 없음(반복이 확인되지 않은 형태는 기록하지 않았다).

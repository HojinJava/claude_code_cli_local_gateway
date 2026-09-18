---
description: "claude-pool HTTP 게이트웨이 데몬 API(라우트 계약·요청 검증·Host 가드·설정·실패 분류·백그라운드 job·자기 문서·데몬 조립)를 기존 코드에서 역추론한 spec"
status: implemented
revision: 1
plan: 없음
origin: migration
architecture:
  - ../../architecture/as-built/00-overview.md
  - ../../architecture/as-built/01-project-structure.md
  - ../../architecture/as-built/02-external-dependencies.md
  - ../../architecture/as-built/03-configuration.md
  - ../../architecture/as-built/04-testing-strategy.md
  - ../../architecture/as-built/06-build-and-run.md
  - ../../architecture/as-built/07-development-patterns.md
  - ../../architecture/as-built/09-component-architecture.md
  - ../../architecture/as-built/10-data-flow.md
  - ../../architecture/as-built/11-api-contract.md
  - ../../architecture/as-built/12-security-auth.md
  - ../../architecture/as-built/13-error-policy.md
  - ../../architecture/as-built/14-observability-logging.md
  - ../../architecture/as-built/15-non-functional-requirements.md
---

# HTTP 게이트웨이 데몬 API spec (기존 코드에서 역추론)

## 분석 근거

- 분석 커밋 앵커: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` (브랜치 `master`, 작업공간 clean)
- 확인 범위(주 대상): `src/claude_pool/server.py`, `src/claude_pool/runner.py`, `src/claude_pool/jobs.py`, `src/claude_pool/errors.py`, `src/claude_pool/apidocs.py`, `src/claude_pool/daemon.py`, `src/claude_pool/config.py`
- 확인 범위(관련 테스트): `tests/test_server.py`, `tests/test_jobs.py`, `tests/test_errors.py`, `tests/test_apidocs.py`, `tests/test_host_guard.py`, `tests/test_daemon.py`, `tests/test_config.py`, `tests/test_integration.py`, `tests/conftest.py`
- 경계 확인용으로만 읽음: `src/claude_pool/pool.py`(`acquire`·`stats`·`release_in_background`·`note_failure`/`note_success`), `tests/fixtures/fake_claude_cli.py`
- 설계 의도 근거로 읽은 커밋: `7460a70`, `bd84920`, `f0d3662`, `3842a27`, `8f979c0`, `821f6e9`
- 테스트는 실행하지 않았다. 아래 수용 기준은 코드와 테스트 본문에서 읽어낸 관찰 동작이다.

## 배경과 해결할 문제

`claude-pool`은 이미 로그인된 `claude` CLI를 로컬 HTTP LLM 엔드포인트로 노출한다. 이 spec이 다루는 게이트웨이 API 계층은 다음 문제를 해결하기 위해 존재한다(코드 주석·커밋 메시지 근거).

1. **프로그램이 호출할 수 있는 HTTP 계약**: 미리 띄워 둔 워커 풀(worker-pool 영역)을 `POST /generate`로 감싸 프롬프트 하나에 완성 텍스트 하나를 돌려준다(`7460a70`).
2. **긴 완성 동안 연결을 붙잡지 않는 경로**: `/generate`는 완성될 때까지 연결을 유지하므로, 같은 본문을 받아 즉시 job id를 돌려주고 나중에 폴링하게 하는 `/jobs`를 둔다(`jobs.py:1-11`, `8f979c0`).
3. **호출자가 행동할 수 있는 실패 정보**: CLI는 rate limit·로그인 만료·모델 오류를 같은 모양으로 보고하므로, 메시지 텍스트를 분류해 `kind`·`retryable`·HTTP 상태·`Retry-After`로 내려준다. 재시도는 구독 쿼터를 쓰는 행위이므로 데몬은 자동 재시도하지 않는다(`errors.py:1-12`, `8f979c0` 본문).
4. **인증 없는 API의 안전 경계**: 인증 계층을 두지 않는 대신 loopback 바인딩 강제(`config.py:41-49`, `3842a27`)와 DNS rebinding을 막는 Host 헤더 가드(`server.py:28-48`, `8f979c0`)를 둔다.
5. **README 없이 발견되는 포트의 자기 설명**: 포트를 발견한 스크립트·에이전트가 사용법과 비용을 알 수 있도록 `GET /`, `GET /docs`, `GET /openapi.json`을 살아있는 `PoolConfig`에서 생성해 제공한다(`apidocs.py:1-9`).
6. **health가 카운터가 아닌 liveness를 보고**: 예열 워커가 모두 죽어도 카운터만으로는 정상으로 보이던 문제를 `idle_alive`·`healthy`·`last_error`·`last_spawn_error`로 드러낸다(`pool.py` `stats()` docstring, `8f979c0`).
7. **데몬 제어용 pid 파일**: `scripts/daemon_ctl.py`가 종료 대상을 알 수 있도록 포트별 pid 파일을 쓴다(`daemon.py:16-23`, `821f6e9`).

## 범위와 비범위

### 범위

- 라우트 전체의 요청·응답 계약: `POST /generate`, `GET /health`, `POST /jobs`, `GET /jobs`, `GET /jobs/{job_id}`, `DELETE /jobs/{job_id}`, `GET /`, `GET /docs`, `GET /openapi.json`
- `/generate`·`/jobs` 공통 요청 본문 검증
- Host 헤더 loopback 미들웨어 `require_loopback_host`
- 설정 `PoolConfig`: 필드·기본값·환경변수·`__post_init__` 검증
- 실패 분류: `errors.classify`, `runner.execute`의 `pool_unavailable`·`timeout`, HTTP 상태·`retryable`·`Retry-After`, 자동 재시도 없음
- 백그라운드 job: 상태 수명주기, 보관(retention), 상한(`max_jobs`), 취소, 종료 처리
- 자기 문서: `api_info`, `openapi_spec`, `render_html`, `FAILURE_KINDS`, `CONSTRAINTS`
- 데몬 조립: `run_daemon`, pid 파일, 종료 신호 대기, 종료 순서

### 비범위 (경계만 언급)

- 워커 스폰·argv·stream-json 프로토콜·`Worker.run` 결과 파싱, `WorkerPool`의 획득 대기·오토스케일·scale-down·Job Object(`worker.py`, `pool.py`, `winjob.py`) — worker-pool 영역 담당. 이 spec은 `pool.acquire()`가 `PoolUnavailableError`를 던질 수 있고, `worker.run()`이 `asyncio.TimeoutError`/`WorkerError`를 던지거나 `{"text","duration_ms","is_error",...}` dict를 돌려준다는 인터페이스만 전제한다.
- `/health` 본문의 풀 통계 키 산출 로직(`WorkerPool.stats()`) — worker-pool 영역. 이 spec은 서버가 그 dict에 `jobs` 키를 덧붙여 그대로 직렬화한다는 점만 다룬다.
- `ClaudePoolClient`(`client.py`)와 `scripts/daemon_ctl.py`의 자동 기동·pid 검증 로직 — 클라이언트/운영 스크립트 영역.

## 사용자 관찰 동작

### 공통

- 모든 라우트는 `web.Application(middlewares=[require_loopback_host])`에 등록되어 Host 가드를 먼저 통과한다(`server.py:51-70`).
- 응답 본문은 `/docs`(HTML)를 제외하고 모두 `web.json_response`로 직렬화된 JSON object다. 성공·실패 공통 envelope 클래스는 없고 경로마다 키 집합이 다르다.
- 요청별 모델 override 필드는 없다. 모델은 `PoolConfig.model` 하나이며 문서(`api_info.config.model`)에만 노출된다.

### Host 가드 (`require_loopback_host`, `server.py:15-48`)

- `request.host`에서 `hostname_from_host_header`로 호스트 부분을 꺼낸다: `[`로 시작하면 `]` 전까지를 IPv6 주소로, 아니면 마지막 `:` 뒤가 숫자일 때 포트로 보고 떼어낸다(`server.py:15-25`).
- 꺼낸 값이 `is_loopback_host`(문자열 `"localhost"`와 일치하거나 `ipaddress.ip_address(...).is_loopback`)가 아니면 핸들러를 호출하지 않고 403을 돌려준다.
- 403 본문: `{"error": "Host header '<원래 Host>' is not a loopback address", "kind": "forbidden_host", "retryable": false}`.

### `POST /generate` (`server.py:115-124`)

요청 본문(JSON object):

| 키 | 타입 | 필수 | 처리 |
|---|---|---|---|
| `prompt` | string | 예 | 문자열이 아니거나 빈 문자열이면 400 |
| `timeout_sec` | number(또는 `float()` 변환 가능한 값) | 아니오 | 생략 시 `PoolConfig.default_timeout_sec`. `float()` 변환이 `ValueError`/`TypeError`면 400. 범위 검사는 하지 않는다 |

그 밖의 키는 읽지 않는다.

응답:

| 상황 | 상태 | 본문 키 | 헤더 |
|---|---|---|---|
| 성공 | 200 | `text`(string), `duration_ms`(int) | — |
| 본문 오류 | 400 | `error` | — |
| 실행 실패 | `Failure.status` | `error`, `kind`, `retryable`, `duration_ms`(0이 아닐 때만) | `Retry-After`(`retry_after_sec`가 있을 때, 정수 문자열) |
| Host 가드 거절 | 403 | `error`, `kind`, `retryable` | — |

400 메시지는 검사 순서대로 `"invalid JSON body"`(JSON 파싱 실패), `"request body must be a JSON object"`, `"'prompt' is required"`, `"'timeout_sec' must be numeric"` 중 하나다(`server.py:77-97`). 400 본문에는 `kind`·`retryable`이 없다.

실행 실패 응답 본문에는 `retry_after_sec` 키가 들어가지 않는다. 대기 힌트는 `Retry-After` 헤더로만 전달된다(`server.py:100-112`).

### 실패 분류표

| `kind` | HTTP | `retryable` | 발생 지점 | `error` 값 |
|---|---|---|---|---|
| `pool_unavailable` | 503 | true | `pool.acquire()`가 `PoolUnavailableError` (`runner.py:40-47`) | 예외 메시지(예: 획득 타임아웃, 스폰 실패, 종료 중) |
| `timeout` | 504 | true | `worker.run()`이 `asyncio.TimeoutError` (`runner.py:51-54`) | `"worker timed out"` |
| `rate_limited` | 429 | true | `classify()` rate limit 패턴 일치 (`errors.py:76-84`) | 워커 오류 텍스트 |
| `not_authenticated` | 503 | false | `classify()` 인증 패턴 일치 (`errors.py:86-89`) | 워커 오류 텍스트 |
| `worker_failed` | 502 | false | `classify()` 폴백 (`errors.py:91`) 또는 job 태스크의 예기치 않은 예외 (`jobs.py:111-118`) | 워커 오류 텍스트 / `"unexpected error: <repr>"` |
| `forbidden_host` | 403 | false | Host 가드 미들웨어 (`server.py:39-47`) | Host 헤더 설명 |

`classify(text)` 규칙(`errors.py:22-91`):

- 대소문자 무시 정규식 검색. rate limit 패턴을 인증 패턴보다 먼저 검사한다.
- rate limit 패턴: `rate[ _-]?limit`, `too many requests`, `\b429\b`, `\b529\b`, `usage limit`, `quota`, `overloaded`, `\bat capacity\b`.
- 인증 패턴: `not authenticated`, `unauthorized`, `\b401\b`, `\b403\b`, `authentication[ _-]?error`, `invalid api key`, `credit balance`, `please run [`/]?login`, `/login\b`, `log ?in again`.
- `retry_after_sec`는 rate_limited에만 설정된다. 텍스트에서 `(try again in|retry after|wait)\s+(\d+)\s*(s\b|sec|second)`를 찾으면 그 정수, 없으면 `DEFAULT_RETRY_AFTER_SEC = 60`.
- `None`/빈 문자열은 `""`로 취급하며 예외를 던지지 않는다.
- `classify`에 들어가는 텍스트: `WorkerError`의 문자열(비정상 종료 시 stderr 포함) 또는 워커 결과가 `is_error: true`일 때의 `result["text"]`. 후자의 경우 `duration_ms`는 워커 결과 값을 쓴다(`runner.py:55-66`).

### 자동 재시도 없음과 실행 상태 기록 (`runner.py`)

- `execute()`는 획득 1회·실행 1회만 수행하며, 실패 시 재시도 루프가 없다.
- 워커를 획득한 뒤에는 성공·실패·취소 어느 경로로 빠져나가든 `finally`에서 `asyncio.shield(pool.release_in_background(worker))`를 await한다(`runner.py:57-61`). 주석상 목적은 클라이언트 연결 종료·job 취소·종료로 호출이 취소되어도 워커 반납(곧 kill)이 풀의 태스크 추적 하에서 실행되게 하는 것이다.
- 결과가 확정되면 `_note()`가 성공 시 `pool.note_success()`(→ `last_error = None`), 실패 시 `pool.note_failure(error)`(→ `last_error = error`)를 호출한다(`runner.py:70-75`). 400 본문 오류는 `execute()`에 도달하지 않으므로 이 상태를 바꾸지 않는다.

### `GET /health` (`server.py:160-163`)

- 항상 200. 본문은 `pool.stats()` dict에 `"jobs": {"total": int, "running": int}`를 덧붙인 것이다.
- `pool.stats()` 키(경계 참조, `pool.py` `stats()`): `min_workers`, `max_workers`, `total`, `idle`, `idle_alive`, `busy`, `healthy`, `last_spawn_error`(string|null), `last_error`(string|null).
- `jobs.total`은 현재 저장된 job 수, `jobs.running`은 `status == "running"`인 수다. 이 호출은 reap을 수행하지 않는다(`jobs.py:185-187`).

### 백그라운드 job

#### `POST /jobs` (`server.py:127-136`)

- 본문 검증은 `/generate`와 같은 `_read_prompt_request`를 쓰며 400 계약도 같다.
- 성공 시 202, `Location: /jobs/<job_id>` 헤더, 본문은 `Job.to_dict()`에 `"url": "/jobs/<job_id>"`를 더한 것이다. 제출 직후라 `status`는 `"running"`이다.
- 워커 획득 실패(`pool_unavailable`)를 포함한 모든 실행 실패는 이 응답이 아니라 이후 job 상태로 나타난다.

#### job 직렬화 `Job.to_dict()` (`jobs.py:52-71`)

| 조건 | 키 |
|---|---|
| 항상 | `job_id`(string), `status`(`running`/`succeeded`/`failed`/`cancelled`), `prompt_preview`(프롬프트 앞 80자), `created_at`(epoch 초 float), `finished_at`(epoch 초 float 또는 null) |
| `succeeded` | + `text`, `duration_ms` |
| `failed` | + `error`, `kind`(failure가 없으면 `"worker_failed"`), `retryable`(bool), `retry_after_sec`(값이 있을 때), `duration_ms`(0이 아닐 때) |
| `running`, `cancelled` | 추가 키 없음 |

`timeout_sec`와 전체 프롬프트는 직렬화되지 않는다. 전체 프롬프트는 job 객체에 저장하지 않고 실행 태스크 인자로만 넘긴다(`jobs.py:30-32`, `jobs.py:89-103`).

#### job 상태 수명주기 (`jobs.py:89-154`)

- 생성: `id = secrets.token_urlsafe(12)`(16자 URL-safe 문자열), `status = "running"`, `created_at = time.time()`. 주석상 인증이 없으므로 다른 로컬 프로세스가 id를 열거하지 못하게 하려는 것이다.
- 실행: `asyncio.ensure_future(self._run(...))`로 태스크를 만들고, 완료 콜백에서 `_tasks`에서 제거한다.
- `running → succeeded`: `execute()` 결과 성공. `text`·`duration_ms` 기록.
- `running → failed`: `execute()` 결과 실패. `error`·`failure`·`duration_ms` 기록. 또는 `execute()`가 예기치 않은 예외를 던지면 `error = "unexpected error: <repr>"`, `failure = worker_failed/502/false`.
- `running → cancelled`: 태스크가 `CancelledError`를 받으면 `error = "cancelled"`로 기록한 뒤 예외를 다시 던진다.
- 종결 전이마다 `finished_at = time.time()`.

#### `GET /jobs/{job_id}` (`server.py:139-145`)

- 저장소에 있으면 job의 성공·실패와 무관하게 200 + `to_dict()`. 주석상 "조회는 성공했고 job의 결과는 본문에 있으므로 폴러는 상태 코드 하나만 본다"는 의도다.
- 없으면 404 `{"error": "no such job"}`.
- 조회는 reap을 수행하지 않는다.

#### `GET /jobs` (`server.py:148-150`, `jobs.py:137-139`)

- 먼저 reap을 수행한 뒤, 남은 job을 `created_at` 내림차순(최신 우선)으로 `{"jobs": [to_dict(), ...]}`로 돌려준다. 페이지네이션은 없다.

#### `DELETE /jobs/{job_id}` (`server.py:153-157`, `jobs.py:141-154`)

- 없는 id면 404 `{"error": "no such job"}`.
- 태스크가 아직 끝나지 않았으면 `task.cancel()` 후 `asyncio.gather(task, return_exceptions=True)`로 태스크 종료를 기다린 다음 응답한다. 주석상 "워커가 실제로 죽은 뒤에 답해야 cancelled가 주장이 아니라 사실이 된다".
- 태스크가 없거나 끝났는데 job이 종결 상태가 아니면 `cancelled`로 기록한다.
- 이미 종결된 job이면 상태를 바꾸지 않는다. 코드상 이 경로에서 저장소에서 job을 삭제하는 문장은 없다.
- 응답은 200 + 그 시점의 `to_dict()`.

#### 보관·상한 (`jobs.py:164-183`)

`_reap()`은 `submit()`(새 job 삽입 전)과 `list()`에서만 호출된다. 별도 주기 청소 태스크는 없다(docstring: 저장소는 제출 시에만 커지므로 그때만 줄이면 되고, 종료 시 정리할 두 번째 루프를 만들지 않기 위해).

1. 종결 상태이고 `finished_at`이 있으며 `now - finished_at > retention_sec`인 job을 삭제한다.
2. 이어서 `overflow = len(jobs) - max_jobs`가 양수면, 종결된 job을 `finished_at` 오름차순으로 정렬해 앞에서부터 `overflow`개까지 삭제한다. `running` job은 삭제 대상에서 제외된다.

따라서 `submit()` 직후 저장 개수는 `max_jobs`를 넘을 수 있다(삽입 전 기준으로 줄이고, 실행 중 job은 줄이지 않으므로).

#### 종료 (`jobs.py:156-162`)

- `shutdown()`은 끝나지 않은 모든 job 태스크를 cancel하고 `gather(..., return_exceptions=True)`로 기다린다. 해당 job은 `cancelled`가 된다.

### 자기 문서 (`apidocs.py`)

- `VERSION`: `importlib.metadata.version("claude-pool")`, 패키지 메타데이터가 없으면 `"0+unknown"`(`apidocs.py:18-21`).
- `GET /` → `api_info(config)` JSON. 키: `name`(`"claude-pool"`), `version`, `summary`, `base_url`(`http://{host}:{port}`), `endpoints`(9개 라우트 설명 dict), `example`(`curl`, `python`, `background`), `failure_kinds`(= `FAILURE_KINDS`), `constraints`(= `CONSTRAINTS`, 6개 문장), `config`(`model`, `min_workers`, `max_workers`, `default_timeout_sec`).
- `GET /openapi.json` → `openapi_spec(config)` JSON. `openapi: "3.1.0"`, `info.version = VERSION`, `info.description = SUMMARY + Constraints 목록`, `servers[0].url = http://{host}:{port}`, `paths` 키는 `/generate`, `/jobs`, `/jobs/{job_id}`, `/health`, `/`, `/docs`, `/openapi.json` 7개.
  - `/generate` post 응답: `200`, `400`, 그리고 `FAILURE_KINDS`의 각 상태(503, 429, 504, 502, 403). 같은 상태 코드를 공유하는 kind(503의 `pool_unavailable`·`not_authenticated`)는 설명을 줄바꿈으로 이어 붙인다. `429`에는 `Retry-After`(integer) 헤더가 선언된다.
  - `/jobs` post 응답: `202`(`Location` 헤더, job 스키마), `400`, `403`. get 응답: `200`(`jobs` 배열).
  - `/jobs/{job_id}` get·delete 응답: `200`(job 스키마), `404`.
  - 오류 스키마 속성: `error`(필수), `kind`(enum = `FAILURE_KINDS`의 kind), `retryable`, `duration_ms`.
  - job 스키마 속성: `job_id`, `status`(enum 4종), `prompt_preview`, `created_at`, `finished_at`, `text`, `duration_ms`, `error`, `kind`, `retryable`; 필수 `job_id`, `status`.
  - 요청 본문 스키마: `prompt`(string, minLength 1, 필수), `timeout_sec`(number, default = `config.default_timeout_sec`).
- `GET /docs` → `render_html(config)`, `content_type="text/html"`. `<!doctype html>`로 시작하는 단일 HTML 문자열이며 외부 스크립트·스타일시트를 참조하지 않는다(docstring: 오프라인 박스에서도 떠야 함). 문자열 값(버전, base URL, 엔드포인트 설명, 예제, 제약, 실패 kind·설명, 모델)은 `html.escape`를 거치고, 숫자 값(`min_workers`·`max_workers`·`default_timeout_sec`, 실패 표의 HTTP status)은 그대로 삽입한다(`apidocs.py:315`, `apidocs.py:386-387`). 쿼터 소모 경고, 엔드포인트 표, 예제, "Background jobs" 절, 실패 표(재시도하지 않는다는 문장 포함), 제약 목록, 현재 데몬 설정 표, `/openapi.json`·`/health` 상대 링크를 포함한다.
- 세 문서 모두 요청마다 `request.app["pool"].config`(살아있는 설정)에서 생성한다.
- `FAILURE_KINDS`는 `errors.classify`·`runner`가 만드는 5종과 미들웨어의 `forbidden_host`를 합친 6개 항목(`kind`, `status`, `retryable`, `meaning`)이다. `rate_limited`의 `meaning`에는 `DEFAULT_RETRY_AFTER_SEC` 값이 문자열로 들어간다.

### 설정 (`config.py`)

| 필드 | 환경변수 | 코드 기본값 | 변환 |
|---|---|---|---|
| `min_workers` | `CLAUDE_POOL_MIN_WORKERS` | 4 | `int` |
| `max_workers` | `CLAUDE_POOL_MAX_WORKERS` | 30 | `int` |
| `model` | `CLAUDE_POOL_MODEL` | `"sonnet"` | 문자열 |
| `host` | `CLAUDE_POOL_HOST` | `"127.0.0.1"` | 문자열 |
| `port` | `CLAUDE_POOL_PORT` | 8756 | `int` |
| `default_timeout_sec` | `CLAUDE_POOL_TIMEOUT_SEC` | 120.0 | `float` |
| `acquire_timeout_sec` | `CLAUDE_POOL_ACQUIRE_TIMEOUT_SEC` | 60.0 | `float` |
| `idle_timeout_sec` | `CLAUDE_POOL_IDLE_TIMEOUT_SEC` | 60.0 | `float` |
| `scale_down_interval_sec` | `CLAUDE_POOL_SCALE_DOWN_INTERVAL_SEC` | 30.0 | `float` |
| `job_retention_sec` | `CLAUDE_POOL_JOB_RETENTION_SEC` | 600.0 | `float` |
| `max_jobs` | `CLAUDE_POOL_MAX_JOBS` | 500 | `int` |
| `scratch_dir` | `CLAUDE_POOL_SCRATCH_DIR` | `Path.home()/".claude-pool"/"scratch"` | `Path` (빈 문자열이면 기본값) |
| `claude_cmd` | `CLAUDE_POOL_CLAUDE_CMD_JSON` | `["claude"]` | `json.loads` (빈 문자열이면 기본값) |

- 위 기본값은 코드 폴백값이며, 실제 실행 환경에 주입되는 값은 저장소에서 확인되지 않는다.
- `from_env()`는 `.env` 파일을 읽지 않는다. `int()`/`float()` 변환 실패는 별도 처리 없이 `ValueError`로 전파된다. `CLAUDE_POOL_CLAUDE_CMD_JSON` 파싱 실패는 `"CLAUDE_POOL_CLAUDE_CMD_JSON is not valid JSON: ..."` `ValueError`로 바뀐다(`config.py:63-72`).
- `__post_init__` 검증(`config.py:41-59`): host가 loopback이 아니면 `ValueError`(메시지에 `loopback` 포함), `claude_cmd`가 list가 아니거나 비었으면 `ValueError`, 원소 중 문자열이 아닌 것이 있으면 `ValueError`(메시지에 `claude_cmd` 포함). 직접 생성자 호출과 `from_env()` 모두 이 검증을 거친다.
- `min_workers ≤ max_workers`, 포트 범위, 타임아웃·보관 시간·`max_jobs`의 부호/범위는 검증하지 않는다.

### 데몬 조립 (`daemon.py`)

- 진입점: `main()` → `PoolConfig.from_env()` → `asyncio.run(run_daemon(config))`. 콘솔 스크립트 `claude-pool-daemon`과 `python -m claude_pool.daemon`이 이 함수를 쓴다.
- `run_daemon(config)` 순서:
  1. `scratch_dir.mkdir(parents=True, exist_ok=True)`
  2. `WorkerPool(config)`, `JobStore(pool, retention_sec=config.job_retention_sec, max_jobs=config.max_jobs)` 생성
  3. `await pool.start()` (최소 워커 예열 — worker-pool 영역)
  4. `create_app(pool, jobs)` → `AppRunner.setup()` → `TCPSite(host=config.host, port=config.port).start()`
  5. `pid_file(config)`(= `scratch_dir / f"daemon-{port}.pid"`)에 `os.getpid()`를 UTF-8 텍스트로 쓴다
  6. SIGTERM/SIGINT에 `add_signal_handler`로 이벤트를 걸고 대기한다. 등록이 `NotImplementedError`/`AttributeError`/`ValueError`면 무시한다(주석: Windows·비 메인 스레드에서는 미지원, Ctrl+C로 풀려남).
- 종료(`finally`) 순서: pid 파일 `unlink(missing_ok=True)` → `runner.cleanup()`(runner가 만들어졌을 때) → 중첩 `finally`로 `jobs.shutdown()` → `pool.stop()`. 주석상 job을 먼저 취소해야 워커가 풀로 반납되고, 그다음 `pool.stop()`이 전부 정리할 수 있다.
- `pool.start()`나 바인딩이 실패하면 pid 파일은 쓰이지 않고, `finally`의 unlink·`jobs.shutdown()`·`pool.stop()`은 그대로 실행된 뒤 예외가 전파된다.
- `create_app(pool, jobs=None)`은 `jobs`가 없으면 `pool.config.job_retention_sec`·`max_jobs`로 `JobStore`를 직접 만든다(`server.py:54-56`). 테스트는 이 경로를 쓴다.

## 수용 기준

### Host 가드

- **AC-001**: 서버는 `Host` 헤더의 호스트 부분이 loopback 리터럴(`127.0.0.0/8`, `::1`, `localhost`)이 아니면 핸들러를 실행하지 않고 403과 `{"error", "kind": "forbidden_host", "retryable": false}`를 돌려준다. 근거: `server.py:28-48`, `tests/test_host_guard.py::test_non_loopback_host_header_is_rejected`
- **AC-002**: 서버는 `127.0.0.1:8756`, `localhost:1234`, `[::1]:8756` 같은 포트 포함·IPv6 괄호 표기 loopback Host 헤더를 허용한다. 근거: `server.py:15-25`, `tests/test_host_guard.py::test_hostname_from_host_header`, `::test_loopback_host_headers_are_accepted`
- **AC-003**: Host 가드는 `/generate`뿐 아니라 `/health`, `/jobs`, `/`, `/docs`, `/openapi.json`을 포함한 모든 등록 라우트에 적용된다. 근거: `server.py:52`, `tests/test_host_guard.py::test_health_is_guarded_too`, `tests/test_jobs.py::test_job_endpoints_are_behind_the_host_guard`, `tests/test_apidocs.py::test_docs_endpoints_are_behind_the_host_guard`

### `POST /generate`

- **AC-004**: `POST /generate`는 유효한 `prompt`에 대해 200과 `{"text": <완성 텍스트>, "duration_ms": <int>}`를 돌려준다. 근거: `server.py:115-124`, `tests/test_server.py::test_generate_returns_text`
- **AC-005**: `/generate`와 `/jobs`는 JSON 파싱 실패, JSON object가 아닌 본문, 누락되었거나 빈/비문자열 `prompt`, `float()`로 변환되지 않는 `timeout_sec`에 대해 400과 `{"error": <메시지>}`를 돌려주며 워커를 사용하지 않는다. 근거: `server.py:77-97,115-131`, `tests/test_server.py::test_generate_requires_prompt`, `::test_generate_rejects_invalid_json`, `::test_generate_rejects_non_dict_json_body`, `::test_generate_rejects_non_numeric_timeout_sec`, `tests/test_jobs.py::test_jobs_validate_the_body_like_generate_does`
- **AC-006**: `timeout_sec`가 생략되면 `PoolConfig.default_timeout_sec`를 워커 실행 타임아웃으로 쓴다. 근거: `server.py:92-93`
- **AC-007**: 워커 실행이 실패하면 응답 상태는 분류된 `Failure.status`이고 본문은 `error`, `kind`, `retryable`을 포함하며, 실패 결과의 `duration_ms`가 0이 아니면 `duration_ms`도 포함한다. 근거: `server.py:100-112`, `tests/test_server.py::test_generate_classifies_rate_limit_as_retryable_429`
- **AC-008**: 분류 결과에 `retry_after_sec`가 있으면 `Retry-After` 헤더에 그 정수를 문자열로 싣고, 없으면 헤더를 싣지 않는다. 근거: `server.py:109-111`, `tests/test_server.py::test_generate_classifies_rate_limit_as_retryable_429`, `::test_generate_classifies_logged_out_cli_as_not_retryable`

### 실패 분류와 재시도

- **AC-009**: 워커 획득이 `PoolUnavailableError`로 끝나면 `kind="pool_unavailable"`, 503, `retryable=true`로 보고한다. 근거: `runner.py:40-47`, `tests/test_server.py::test_generate_returns_503_when_no_worker_can_be_acquired`, `::test_pool_exhaustion_is_reported_as_retryable`
- **AC-010**: 워커 실행이 `asyncio.TimeoutError`로 끝나면 `error="worker timed out"`, `kind="timeout"`, 504, `retryable=true`로 보고한다. 근거: `runner.py:51-54`
- **AC-011**: `classify()`는 rate limit 패턴(`usage limit`, `429`, `too many requests`, `529`/`overloaded`, `quota` 등)이 대소문자 무시로 일치하면 `rate_limited`/429/`retryable=true`를 돌려주며, 인증 패턴보다 먼저 검사한다. 근거: `errors.py:22-31,76-84`, `tests/test_errors.py::test_rate_limit_text_is_retryable_429`
- **AC-012**: `rate_limited`의 `retry_after_sec`는 메시지의 `try again in N seconds`/`retry after Ns`/`wait N sec` 힌트가 있으면 N, 없으면 60이다. 근거: `errors.py:20,48-50,67-69`, `tests/test_errors.py::test_rate_limit_uses_wait_hint_from_the_message_when_present`, `::test_rate_limit_text_is_retryable_429`
- **AC-013**: `classify()`는 인증 패턴(`not authenticated`, `401`, `unauthorized`, `invalid api key`, `/login`, `credit balance` 등)이 일치하면 `not_authenticated`/503/`retryable=false`/`retry_after_sec=None`을 돌려준다. 근거: `errors.py:33-44,86-89`, `tests/test_errors.py::test_auth_text_is_not_retryable`
- **AC-014**: `classify()`는 어떤 패턴에도 맞지 않는 텍스트(빈 문자열 포함)에 대해 예외 없이 `worker_failed`/502/`retryable=false`를 돌려준다. 근거: `errors.py:72-91`, `tests/test_errors.py::test_unrecognised_failure_falls_back_to_502`, `tests/test_server.py::test_generate_surfaces_worker_error`
- **AC-015**: 워커가 `WorkerError`를 던지면 그 문자열을, 워커 결과가 `is_error: true`면 결과 텍스트와 결과 `duration_ms`를 `classify()`와 실패 응답에 쓴다. 근거: `runner.py:55-66`, `tests/test_server.py::test_generate_classifies_rate_limit_as_retryable_429`(`duration_ms == 1`)
- **AC-016**: 데몬은 실패한 요청을 자동으로 재시도하지 않는다 — `execute()`는 획득·실행을 각각 한 번만 수행하고 분류 결과를 그대로 반환한다. 근거: `runner.py:37-67`, 커밋 `8f979c0` 본문
- **AC-017**: 워커를 획득한 실행은 성공·실패·타임아웃·호출 취소 어느 경로에서도 `finally`에서 shield된 `pool.release_in_background(worker)`를 await한다. 근거: `runner.py:57-61`, `tests/test_jobs.py::test_cancel_kills_the_running_worker`
- **AC-018**: 실행 실패는 `pool.note_failure(error)`로 `/health`의 `last_error`에 남고, 이후 성공한 실행은 `last_error`를 null로 되돌리며, 400 본문 오류는 이 값에 영향을 주지 않는다. 근거: `runner.py:70-75`, `tests/test_server.py::test_generate_classifies_logged_out_cli_as_not_retryable`, `::test_successful_run_clears_the_last_error`

### `GET /health`

- **AC-019**: `GET /health`는 200과 풀 통계(`min_workers`, `max_workers`, `total`, `idle`, `idle_alive`, `busy`, `healthy`, `last_spawn_error`, `last_error`)에 `jobs: {"total", "running"}`을 더한 JSON을 돌려준다. 근거: `server.py:160-163`, `jobs.py:185-187`, `tests/test_server.py::test_health_reports_pool_stats`, `::test_health_reports_liveness_not_just_counters`, `tests/test_jobs.py::test_health_reports_job_counts`
- **AC-020**: 예열된 idle 워커 프로세스가 죽어 있으면 `/health`는 `idle`과 다른 `idle_alive`와 `healthy=false`를 보고하고, idle 워커가 0개인 풀은 `healthy=true`로 보고한다. 근거: `pool.py` `stats()`, `tests/test_server.py::test_health_reports_dead_prewarmed_workers_as_not_alive`, `::test_an_empty_on_demand_pool_is_not_reported_unhealthy`

### 백그라운드 job

- **AC-021**: `POST /jobs`는 워커 완료를 기다리지 않고 202, `Location: /jobs/<job_id>` 헤더, `status="running"`을 포함한 job 본문과 `url` 키를 돌려준다. 근거: `server.py:127-136`, `jobs.py:89-103`, `tests/test_jobs.py::test_post_jobs_returns_202_with_a_location`, `::test_submit_returns_immediately_and_completes_in_the_background`
- **AC-022**: job id는 `secrets.token_urlsafe(12)`로 생성되어 순차적이지 않고 16자 이상이다. 근거: `jobs.py:91-95`, `tests/test_jobs.py::test_job_ids_are_unguessable`
- **AC-023**: job은 `runner.execute()`를 통해 실행되어 성공 시 `succeeded`와 `text`·`duration_ms`를, 실패 시 `failed`와 `error`·`kind`·`retryable`·(있으면)`retry_after_sec`·(0이 아니면)`duration_ms`를 직렬화한다. 근거: `jobs.py:52-71,105-125`, `tests/test_jobs.py::test_polling_a_job_eventually_yields_the_text`, `::test_a_failed_run_lands_on_the_job_with_its_classification`
- **AC-024**: job 실행 중 `execute()`가 예기치 않은 예외를 던지면 job은 `failed`, `error="unexpected error: <repr>"`, `kind="worker_failed"`, `retryable=false`로 기록된다. 근거: `jobs.py:111-118`
- **AC-025**: `GET /jobs/{job_id}`는 존재하는 job이면 job 결과가 실패여도 200을, 없는 id면 404 `{"error": "no such job"}`를 돌려준다. 근거: `server.py:139-145`, `tests/test_jobs.py::test_querying_a_failed_job_still_returns_200`, `::test_unknown_job_is_404`
- **AC-026**: `GET /jobs`는 reap 후 남은 job을 `created_at` 최신순으로 `{"jobs": [...]}`에 담아 돌려준다. 근거: `jobs.py:137-139`, `server.py:148-150`, `tests/test_jobs.py::test_list_jobs_is_newest_first`
- **AC-027**: `DELETE /jobs/{job_id}`는 실행 중 job의 태스크를 취소하고 job 태스크의 종료를 기다린 뒤(`jobs.py:151`; 취소가 `runner.py:61`의 shield된 반납 대기 중에 도착하면 태스크는 먼저 끝나고 풀의 반납·보충은 응답 뒤에도 계속될 수 있다) `status="cancelled"` job을 200으로 돌려주며, 없는 id면 404를 돌려준다. 근거: `jobs.py:141-154`, `server.py:153-157`, `tests/test_jobs.py::test_cancel_kills_the_running_worker`, `::test_cancel_of_an_unknown_job_returns_none`, `::test_unknown_job_is_404`
- **AC-028**: `DELETE /jobs/{job_id}`는 이미 종결된 job의 상태를 바꾸지 않고 그 job을 200으로 돌려준다. 근거: `jobs.py:146-154`
- **AC-029**: 종결 후 `retention_sec`를 초과한 job은 다음 `submit()` 또는 `list()` 호출 시 저장소에서 제거된다. 근거: `jobs.py:164-172`, `tests/test_jobs.py::test_finished_jobs_are_reaped_after_retention`
- **AC-030**: reap 시 저장 개수가 `max_jobs`를 넘으면 종결된 job을 `finished_at`이 오래된 순으로 초과분만큼 제거하고, `running` job은 제거하지 않는다. 근거: `jobs.py:174-183`, `tests/test_jobs.py::test_max_jobs_drops_oldest_finished_but_never_running_ones`
- **AC-031**: `JobStore.shutdown()`은 끝나지 않은 모든 job 태스크를 취소하고 종료를 기다리며, 해당 job은 `cancelled`가 되고 워커는 반납된다. 근거: `jobs.py:156-162`, `tests/test_jobs.py::test_shutdown_cancels_running_jobs`
- **AC-032**: job 목록·조회 응답의 `prompt_preview`는 프롬프트의 앞 80자이며 전체 프롬프트는 job 본문에 포함되지 않는다. 근거: `jobs.py:32,96`, `tests/test_jobs.py::test_list_jobs_is_newest_first`

### 자기 문서

- **AC-033**: `GET /`는 `name`, `version`, `summary`, `base_url`, `endpoints`, `example`(`curl`/`python`/`background`), `failure_kinds`, `constraints`, `config`를 담은 JSON을 돌려주며, `config`와 `base_url`은 기본값이 아니라 실행 중인 `PoolConfig` 값을 반영한다. 근거: `apidocs.py:82-119`, `server.py:166-167`, `tests/test_apidocs.py::test_index_describes_the_api`, `::test_index_reflects_this_daemon_not_the_defaults`, `::test_index_shows_how_to_run_in_the_background`
- **AC-034**: 자기 문서는 구독 쿼터를 소모한다는 점과 대화 기억이 없다는 제약을 명시한다. 근거: `apidocs.py:23-27,47-57`, `tests/test_apidocs.py::test_index_warns_about_the_quota_it_spends`
- **AC-035**: `GET /openapi.json`은 `openapi: "3.1.0"` 문서를 돌려주며 `paths`는 7개 라우트 경로 전체를, `servers[0].url`은 실행 중 host·port를 담는다. 근거: `apidocs.py:227-308`, `tests/test_apidocs.py::test_openapi_is_served_and_covers_every_route`
- **AC-036**: OpenAPI의 `/generate` 503 응답 설명은 `pool_unavailable`과 `not_authenticated`를 모두 포함하고, 429 응답은 `Retry-After` 헤더를 선언한다. 근거: `apidocs.py:136-168`, `tests/test_apidocs.py::test_openapi_documents_both_meanings_of_503`, `::test_openapi_429_carries_the_retry_after_header`
- **AC-037**: `GET /docs`는 `text/html`로 `<!doctype html>`로 시작하는 자체 완결 페이지를 돌려주며, loopback base URL 외의 `http://`·`https://` 참조를 포함하지 않고, 문자열 설정 값(모델 등)은 HTML 이스케이프해 삽입하고 숫자 설정 값은 그대로 삽입한다. 근거: `apidocs.py:327-390`, `server.py:174-176`, `tests/test_apidocs.py::test_docs_serves_a_self_contained_html_page`, `::test_render_html_escapes_config_values`, `::test_docs_page_explains_background_jobs`
- **AC-038**: `FAILURE_KINDS`는 kind가 중복되지 않는 6개 항목이며, `classify()`가 돌려주는 `rate_limited`·`not_authenticated`·`worker_failed`의 `status`·`retryable`과 일치한다. 근거: `apidocs.py:31-45`, `tests/test_apidocs.py::test_documented_failures_match_what_the_classifier_actually_returns`, `::test_every_documented_kind_is_unique`
- **AC-039**: `api_info`와 `openapi_spec`은 같은 `version` 값을 쓴다. 근거: `apidocs.py:18-21,87,232`, `tests/test_apidocs.py::test_api_info_and_spec_agree_on_version`

### 설정

- **AC-040**: `PoolConfig()` 기본값은 `min_workers=4`, `max_workers=30`, `model="sonnet"`, `host="127.0.0.1"`, `port=8756`, `default_timeout_sec=120.0`, `acquire_timeout_sec=60.0`, `idle_timeout_sec=60.0`, `scale_down_interval_sec=30.0`, `job_retention_sec=600.0`, `max_jobs=500`, `scratch_dir=~/.claude-pool/scratch`, `claude_cmd=["claude"]`이다. 근거: `config.py:21-39`, `tests/test_config.py::test_defaults`
- **AC-041**: `PoolConfig.from_env()`는 `CLAUDE_POOL_*` 환경변수가 있으면 그 값을 형 변환해 쓰고, 없으면 코드 기본값을 쓴다. `CLAUDE_POOL_CLAUDE_CMD_JSON`은 JSON으로 파싱하며 파싱 실패 시 `not valid JSON` `ValueError`를 던진다. 근거: `config.py:61-101`, `tests/test_config.py::test_from_env_reads_overrides`, `::test_scratch_dir_env_override`, `::test_scratch_dir_defaults_under_home`, `::test_from_env_rejects_unparsable_claude_cmd_json`
- **AC-042**: `PoolConfig`는 host가 loopback 주소(예: `127.0.0.1`, `127.0.0.2`, `localhost`, `::1`)가 아니면(`0.0.0.0`, 사설 IP, 도메인, 빈 문자열 포함) 생성 시 `ValueError`를 던지며, `from_env()` 경로도 같다. 근거: `config.py:41-49`, `tests/test_config.py::test_loopback_hosts_are_accepted`, `::test_non_loopback_host_is_rejected`, `::test_from_env_rejects_non_loopback_host`
- **AC-043**: `PoolConfig`는 `claude_cmd`가 비어 있지 않은 문자열 리스트가 아니면(bare 문자열, 빈 리스트, 비문자열 원소, dict, None, JSON 문자열 값) `ValueError`를 던진다. 근거: `config.py:50-59`, `tests/test_config.py::test_claude_cmd_must_be_a_non_empty_list_of_strings`, `::test_from_env_rejects_claude_cmd_json_that_is_not_a_list`

### 데몬 조립

- **AC-044**: `run_daemon`은 풀 시작 후 `config.host:config.port`에 앱을 바인딩해 `/health`·`/generate` 요청을 처리한다. 근거: `daemon.py:26-39`, `tests/test_daemon.py::test_run_daemon_serves_generate_requests`
- **AC-045**: `run_daemon`은 바인딩 후 `<scratch_dir>/daemon-<port>.pid`에 현재 pid를 쓰고, 종료 시 이 파일을 삭제한다. 근거: `daemon.py:16-23,38,43`, `tests/test_daemon.py::test_daemon_writes_a_per_port_pid_file_and_removes_it_on_shutdown`
- **AC-046**: 풀 시작이 실패하면 `run_daemon`은 예외를 전파하고 pid 파일을 남기지 않는다. 근거: `daemon.py:31-43`, `tests/test_daemon.py::test_shutdown_removes_the_pid_file_even_if_startup_failed`
- **AC-047**: 데몬 종료 시 `runner.cleanup()` 다음에 `jobs.shutdown()`을, 그다음 `pool.stop()`을 호출하며, 종료 후 풀의 idle 워커 프로세스는 살아있지 않다. 근거: `daemon.py:40-51`, `tests/test_daemon.py::test_run_daemon_kills_pool_workers_on_shutdown`
- **AC-048**: 동시에 들어온 여러 `/generate` 요청은 각자 자기 프롬프트에 대한 응답을 받는다(요청 간 응답이 섞이지 않는다). 근거: `runner.py:37-67`, `tests/test_integration.py::test_concurrent_requests_do_not_bleed_context`

## 현재 구조와 책임

역작성이므로 바뀌는 책임은 없다. 현재 모듈별 책임은 다음과 같다.

| 모듈 | 책임 | 의존 |
|---|---|---|
| `config.py` | `PoolConfig` 데이터클래스, 환경변수 로딩(`from_env`), loopback·`claude_cmd` 검증, `is_loopback_host` 공용 판정 | stdlib |
| `errors.py` | `Failure`(kind/status/retryable/retry_after_sec) 값 객체, 오류 텍스트 → `Failure` 분류, `DEFAULT_RETRY_AFTER_SEC` | stdlib |
| `runner.py` | 전송 방식 무관 `Outcome`, 프롬프트 1건의 획득→실행→반납→분류→`note_*` 기록(`execute`). `/generate`와 job이 워커를 쓰는 유일한 경로 | `errors`, `pool`, `worker.WorkerError` |
| `jobs.py` | `Job` 상태·직렬화, `JobStore`의 제출·실행 태스크·조회·목록·취소·reap·통계·종료 | `errors`, `pool`, `runner` |
| `apidocs.py` | 살아있는 설정 기반 자기 문서(`api_info`, `openapi_spec`, `render_html`)와 문서용 `FAILURE_KINDS`·`CONSTRAINTS` | `config`, `errors.DEFAULT_RETRY_AFTER_SEC` |
| `server.py` | aiohttp 앱 생성·라우팅, Host 가드 미들웨어, 요청 본문 파싱, `Outcome` → HTTP 응답 매핑, job/health/문서 핸들러 | `apidocs`, `config`, `errors`, `jobs`, `pool`, `runner` |
| `daemon.py` | 설정 로딩, 풀·job 저장소·앱 조립, 바인딩, pid 파일, 종료 신호 대기, 종료 순서 | `config`, `jobs`, `pool`, `server` |

요청 흐름:

- 동기: HTTP → `require_loopback_host` → `handle_generate` → `_read_prompt_request` → `runner.execute` → (`pool.acquire` → `worker.run` → `pool.release_in_background`) → `Outcome` → 200 또는 `_failure_response`.
- 백그라운드: HTTP → 가드 → `handle_submit_job` → `_read_prompt_request` → `JobStore.submit`(reap, `Job` 생성, 태스크 시작) → 202. 태스크: `JobStore._run` → `runner.execute` → `_finish`. 폴링은 `handle_get_job` → `JobStore.get`.

상태는 모두 프로세스 메모리(`JobStore._jobs`, `_tasks`, `WorkerPool` 내부)에 있으며, 디스크에 쓰는 것은 pid 파일 하나다. 데몬 재시작 시 job 기록은 남지 않는다.

worker-pool 영역과의 경계: 이 영역은 `WorkerPool`의 `acquire()`/`release_in_background()`/`note_success()`/`note_failure()`/`stats()`/`start()`/`stop()`/`config`와 `Worker.run()`의 반환·예외 계약에만 의존한다.

## 아키텍처 참조

이 spec이 다루는 영역의 실측 구조 문서다. 공통 색인은 [architecture.md](../../architecture/architecture.md)이며, 사전 설계(design) 문서는 없다.

- [00-overview.md](../../architecture/as-built/00-overview.md) — 실제 진입점·실행 경로, 요청 1건 런타임 플로우
- [01-project-structure.md](../../architecture/as-built/01-project-structure.md) — 실제 폴더·진입점, File Responsibility Map(34개 파일)
- [02-external-dependencies.md](../../architecture/as-built/02-external-dependencies.md) — 매니페스트 패키지·버전 제약, lockfile 부재, 외부 실행 의존
- [03-configuration.md](../../architecture/as-built/03-configuration.md) — 환경변수·폴백·검증·주입, pytest·빌드 설정
- [04-testing-strategy.md](../../architecture/as-built/04-testing-strategy.md) — 테스트 구성·가짜 CLI 경계·실행 방법
- [06-build-and-run.md](../../architecture/as-built/06-build-and-run.md) — 확인된 설치·실행·종료·복구 절차와 출처
- [07-development-patterns.md](../../architecture/as-built/07-development-patterns.md) — 2회 이상 반복된 구현 형태·확장 경로·이탈 지점
- [09-component-architecture.md](../../architecture/as-built/09-component-architecture.md) — 모듈 구성·의존 방향·조립 위치
- [10-data-flow.md](../../architecture/as-built/10-data-flow.md) — 미들웨어 순서, 동기·백그라운드 경로, 워커 획득·반납, 기동·종료 순서
- [11-api-contract.md](../../architecture/as-built/11-api-contract.md) — 라우트·JSON 키·상태코드·헤더, 자기 문서 생성과 `/docs` HTML 이스케이프
- [12-security-auth.md](../../architecture/as-built/12-security-auth.md) — 인증 부재, loopback·Host 가드, job ID, 워커 플래그 적용 지점
- [13-error-policy.md](../../architecture/as-built/13-error-policy.md) — 예외 처리 지점, kind↔HTTP 매핑, 응답 구현, `FAILURE_KINDS` 관계
- [14-observability-logging.md](../../architecture/as-built/14-observability-logging.md) — `/health` 구성, 오류 상태 기록, 로깅 미사용
- [15-non-functional-requirements.md](../../architecture/as-built/15-non-functional-requirements.md) — 워커·타임아웃·job 보관 제한값, 측정 근거 확인 상태

## 위험·테스트·문서 영향

### 변경 시 함께 봐야 하는 결합 지점 (코드 주석·CLAUDE.md 근거)

- `errors.classify`의 kind·status·retryable을 바꾸면 `apidocs.FAILURE_KINDS`도 같이 바뀌어야 한다. `tests/test_apidocs.py::test_documented_failures_match_what_the_classifier_actually_returns`가 세 kind에 대해 둘을 대조한다. `pool_unavailable`·`timeout`은 `runner.py`에 하드코딩되어 있어 이 테스트의 대조 대상이 아니다.
- 워커를 쓰는 새 경로는 `runner.execute()`를 거쳐야 한다(`runner.py:1-7` docstring). 반납이 여기에만 있다.
- `daemon.py`의 종료 순서(`jobs.shutdown()` → `pool.stop()`)는 주석으로 의도가 고정되어 있다.
- `require_loopback_host`는 인증 계층을 대신하는 DNS rebinding 방어로 주석·커밋(`8f979c0`)에 기록되어 있다.
- 라우트를 추가하면 `api_info.endpoints`, `openapi_spec.paths`, `render_html` 엔드포인트 표가 따로 관리된다. `tests/test_apidocs.py::test_openapi_is_served_and_covers_every_route`는 경로 집합을 고정값으로 비교한다.

### 테스트 구성

- 모든 관련 테스트는 `tests/fixtures/fake_claude_cli.py`(`--fake-mode echo|error|crash`, `--fake-delay-sec`, `--fake-error-text`)를 `claude_cmd`로 주입하며 실제 `claude` CLI를 호출하지 않는다.
- HTTP 계약은 `pytest-aiohttp`의 `aiohttp_client`로, 데몬 조립은 실제 TCP 포트(`conftest.unused_tcp_port`)와 `aiohttp.ClientSession`으로 검증한다.
- `conftest.make_pool`은 teardown에서 생성한 풀을 `stop()`한다.
- 테스트 본문에서 직접 확인되지 않은 동작(AC-006, AC-010, AC-016, AC-024, AC-028)은 코드 줄만 근거로 둔다.

### 문서 영향

- `CLAUDE.md`는 Host 가드를 "`/generate`와 `/health`는 `Host` 헤더가 loopback 리터럴일 때만 응답한다"로 기술하지만, 코드는 앱 미들웨어로 모든 라우트에 적용한다(`server.py:52`). 사실의 근거는 코드다.
- `api_info.endpoints["DELETE /jobs/{job_id}"]`와 `openapi_spec`의 delete 요약은 "or forget a finished one"이라고 설명하고, `JobStore.cancel` docstring도 같은 표현을 쓴다. 코드상 종결된 job에 대한 DELETE 경로에는 저장소에서 삭제하는 문장이 없다(`jobs.py:141-154`).
- OpenAPI job 스키마에는 `url`, `retry_after_sec` 속성이, 오류 스키마에는 `retry_after_sec`가 선언되어 있지 않다. `POST /jobs` 응답 선언에는 `202`/`400`/`403`만 있다.

## 열린 질문과 확정 결정

### 확정 결정 (코드·주석·커밋으로 확인)

- 인증 계층을 두지 않고 loopback 바인딩 강제 + Host 헤더 가드로 대신한다(`config.py:41-49`, `server.py:28-48`, 커밋 `3842a27`, `8f979c0`).
- 데몬은 실패를 분류만 하고 재시도하지 않는다(`errors.py:1-12`, 커밋 `8f979c0`).
- rate limit은 502가 아니라 429로, 인증 실패는 재시도 불가 503으로 보고한다(`errors.py:77-89` 주석).
- 재시도 가능 실패에 대기 힌트가 없으면 보수적 하한 60초를 쓴다(`errors.py:18-20` 주석).
- `GET /jobs/{id}`는 job 결과와 무관하게 200을 쓴다(`server.py:143-144` 주석).
- job id는 열거 불가능한 무작위 값이다(`jobs.py:92-94` 주석).
- 보관 기간 만료 job은 주기 태스크가 아니라 제출 시점에 reap한다(`jobs.py:77-79` docstring).
- 실행 중 job은 `max_jobs` 상한으로 제거하지 않는다(`jobs.py:174-176` 주석).
- DELETE는 워커가 실제로 반납될 때까지 기다린 뒤 응답한다(`jobs.py:149-150` 주석, 커밋 `8f979c0`).
- 자기 문서는 기본값이 아닌 살아있는 설정에서 생성하고, HTML은 CDN을 쓰지 않는다(`apidocs.py:1-9`, `apidocs.py:328`).
- pid 파일은 포트별로 두며, 강제 종료 시 남을 수 있어 힌트로만 취급한다(`daemon.py:16-23,41-42` 주석, 커밋 `821f6e9`).
- 종료 시 job을 풀보다 먼저 정리한다(`daemon.py:48-49` 주석).
- 설정 기본값 표는 코드 폴백값이며, 실행 환경의 실제 주입값은 저장소에서 확인되지 않는다.

### 열린 질문 (`추정:`)

- 사용자 확인(2026-09-17 migration): 종결 job에 대한 `DELETE /jobs/{job_id}`는 현재 코드대로 job을 그대로 반환하고 제거는 보관 기간 경과 뒤 reap에 맡기는 것이 의도한 계약이다. `api_info`·클라이언트 docstring의 "forget a finished one" 문구는 이 계약과 다르게 읽힌다.
- 추정: `Host` 헤더가 없는 요청의 경우 aiohttp `request.host`가 로컬 FQDN 등 헤더 이외의 값으로 대체되어 403이 될 가능성이 있으나, aiohttp 내부 동작이라 이 저장소 코드·테스트로 확인되지 않는다. (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 확인된 사실: 요청의 `timeout_sec`는 `float()` 변환만 하고 범위 검사를 하지 않는다(`server.py:92-95`). 사용자 확인(2026-09-17 migration): 범위 검사 부재는 의도한 선택이 아니다(이 migration은 코드를 수정하지 않는다).
- 확인된 사실: 취소된 job은 내부에 `error="cancelled"`를 저장하지만 `to_dict()`는 succeeded·failed에만 키를 추가한다(`jobs.py:60-70`). 클라이언트는 이 부재를 전제로 `job.get("error", status)`·`job.get("kind", status)`를 쓴다(`client.py:163-164`). 추정: 이 비노출이 의도인지는 확인되지 않는다. (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 추정: `/generate` 실패 본문에는 `retry_after_sec`가 없고 job 실패 본문에는 있는 비대칭(헤더를 쓸 수 없는 폴링 경로를 위한 것)은 설계로 보이나 주석·커밋에 명시되어 있지 않다. (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)
- 확인된 사실: `min_workers ≤ max_workers`, 포트 범위, `max_jobs`·보관 시간의 양수 여부 검증은 `config.py:41-59`에 없다(`min_workers > max_workers`일 때의 결과는 worker-pool spec 참고). 사용자 확인(2026-09-17 migration): 이 값 검증 부재는 의도한 선택이 아니다(이 migration은 코드를 수정하지 않는다).
- 확인된 사실: `scripts/daemon_ctl.py stop`은 Windows에서 `taskkill /F`로 강제 종료하므로(`daemon_ctl.py:92-94`) `daemon.py:41-42` 주석대로 `finally`에 도달하지 않는다. 이 경로에서는 `daemon_ctl`이 pid 파일을 지우고(`daemon_ctl.py:157-158`) 워커는 Job Object가 정리한다(주석 `daemon_ctl.py:159-160`). 추정: Ctrl+C(`KeyboardInterrupt`) 경로에서 `finally` 정리가 어느 범위까지 실행되는지는 코드·테스트로 확인되지 않는다(테스트는 태스크 cancel로만 종료를 검증한다). (미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음)

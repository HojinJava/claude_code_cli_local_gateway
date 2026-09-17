---
description: claude-pool 데몬의 실제 라우트·요청/응답 JSON 키·상태코드·헤더와 자기 문서(GET /, /docs, /openapi.json) 생성 위치 및 /docs HTML 이스케이프 처리
tags: [architecture]
status: as-built
---

# 11. API 계약 (as-built)

## 계약 정의 위치

- 라우트 등록: `create_app`(`src/claude_pool/server.py:51-70`). 모든 라우트에 `require_loopback_host` 미들웨어가 먼저 적용된다(`server.py:52`) → 403 계약은 [12-security-auth](12-security-auth.md).
- 요청·응답 타입 정의 클래스(pydantic·TypedDict·스키마 검증 라이브러리)는 없다. 요청 검증은 `_read_prompt_request`(`server.py:77-97`)의 수동 검사, 응답은 핸들러 안의 dict 리터럴과 `Job.to_dict()`(`src/claude_pool/jobs.py:52-71`), `WorkerPool.stats()`(`src/claude_pool/pool.py:224-249`)가 정한다.
- 기계 판독 명세는 코드에서 요청 시점에 생성되는 `GET /openapi.json`(`src/claude_pool/apidocs.py:227-308`)이며, 파일로 저장된 명세는 없다.
- 공통 응답 envelope 클래스는 없다. `/docs`를 제외한 모든 응답은 `web.json_response`로 직렬화한 JSON object다.

## 라우트 목록

| 메서드 | 경로 | 핸들러 | 성공 상태 |
|---|---|---|---|
| POST | `/generate` | `handle_generate` (`server.py:115-124`) | 200 |
| GET | `/health` | `handle_health` (`server.py:160-163`) | 200 |
| POST | `/jobs` | `handle_submit_job` (`server.py:127-136`) | 202 |
| GET | `/jobs` | `handle_list_jobs` (`server.py:148-150`) | 200 |
| GET | `/jobs/{job_id}` | `handle_get_job` (`server.py:139-145`) | 200 |
| DELETE | `/jobs/{job_id}` | `handle_cancel_job` (`server.py:153-157`) | 200 |
| GET | `/` | `handle_index` (`server.py:166-167`) | 200 |
| GET | `/docs` | `handle_docs` (`server.py:174-176`) | 200 (`text/html`) |
| GET | `/openapi.json` | `handle_openapi` (`server.py:170-171`) | 200 |

모든 라우트는 Host 가드 실패 시 403을 돌려줄 수 있다. 요청 모델을 요청별로 바꾸는 필드는 없다(모델은 데몬 설정 하나, `worker.py:45`).

## 요청 본문 (`POST /generate`, `POST /jobs` 공통)

`_read_prompt_request`(`server.py:77-97`)의 검사 순서와 400 메시지:

| 순서 | 조건 | 400 `error` |
|---|---|---|
| 1 | `await request.json()`이 `json.JSONDecodeError` | `"invalid JSON body"` |
| 2 | 본문이 dict가 아님 | `"request body must be a JSON object"` |
| 3 | `prompt`가 str이 아니거나 빈 문자열 | `"'prompt' is required"` |
| 4 | `float(body.get("timeout_sec", default_timeout_sec))`가 `ValueError`/`TypeError` | `"'timeout_sec' must be numeric"` |

- 다른 키는 읽지 않는다. `timeout_sec`의 범위(0·음수 등)는 검사하지 않는다.
- 400 본문은 `{"error": str}`뿐이다(`server.py:119`, `server.py:131`).

## `POST /generate` 응답

| 상황 | 상태 | 본문 키 | 헤더 | 근거 |
|---|---|---|---|---|
| 성공 | 200 | `text`(str), `duration_ms`(int) | — | `server.py:124` |
| 본문 오류 | 400 | `error` | — | `server.py:118-119` |
| 실행 실패 | `Failure.status` (429/502/503/504) | `error`, `kind`, `retryable`, `duration_ms`(0이 아닐 때) | `Retry-After`(`retry_after_sec`가 None이 아닐 때, `str(int)`) | `server.py:100-112` |
| Host 가드 거절 | 403 | `error`, `kind`=`"forbidden_host"`, `retryable`=false | — | `server.py:39-47` |

- 실행 실패 본문에는 `retry_after_sec` 키가 없고 헤더로만 전달된다(`server.py:102-111`).
- kind별 상태·retryable 매핑은 [13-error-policy](13-error-policy.md).

## `GET /health` 응답

200, 본문 = `pool.stats()`(`pool.py:233-249`) + `"jobs": jobs.stats()`(`server.py:161-162`, `jobs.py:185-187`).

| 키 | 타입 |
|---|---|
| `min_workers`, `max_workers`, `total`, `idle`, `idle_alive`, `busy` | int |
| `healthy` | bool |
| `last_spawn_error`, `last_error` | str 또는 null |
| `jobs` | `{"total": int, "running": int}` |

필드 의미는 [14-observability-logging](14-observability-logging.md).

## job 라우트

### job 객체 직렬화 `Job.to_dict()` (`jobs.py:52-71`)

| 조건 | 키 |
|---|---|
| 항상 | `job_id`(str), `status`(`"running"`/`"succeeded"`/`"failed"`/`"cancelled"`), `prompt_preview`(프롬프트 앞 80자), `created_at`(epoch float), `finished_at`(epoch float 또는 null) |
| `succeeded` | `text`, `duration_ms` |
| `failed` | `error`, `kind`(failure 없으면 `"worker_failed"`), `retryable`(bool), `retry_after_sec`(값이 있을 때), `duration_ms`(0이 아닐 때) |
| `running`, `cancelled` | 추가 키 없음 |

### 라우트별

| 라우트 | 상태·본문 | 헤더 | 근거 |
|---|---|---|---|
| `POST /jobs` | 202, `to_dict()` + `"url": "/jobs/{id}"` (제출 직후 `status="running"`) / 400 `{error}` | `Location: /jobs/{id}` | `server.py:127-136` |
| `GET /jobs/{job_id}` | 200 `to_dict()`(job이 실패여도 200) / 404 `{"error": "no such job"}` | — | `server.py:139-145` |
| `GET /jobs` | 200 `{"jobs": [to_dict(), ...]}` `created_at` 내림차순, 페이지네이션 없음 | — | `server.py:148-150`, `jobs.py:137-139` |
| `DELETE /jobs/{job_id}` | 200 취소 처리 후 `to_dict()` / 404 `{"error": "no such job"}` | — | `server.py:153-157`, `jobs.py:141-154` |

- 실행 실패(획득 실패 포함)는 `POST /jobs` 응답이 아니라 job의 `failed` 상태로 나타난다.
- 취소·보관 흐름은 [10-data-flow](10-data-flow.md#백그라운드-경로-jobs).

## 자기 문서

세 라우트 모두 요청마다 `request.app["pool"].config`(살아있는 `PoolConfig`)로 생성한다(`server.py:166-176`). 생성 코드는 [`src/claude_pool/apidocs.py`](../../../src/claude_pool/apidocs.py) 한 파일이다.

### `GET /` — `api_info(config)` (`apidocs.py:82-119`)

키: `name`(`"claude-pool"`), `version`(`importlib.metadata` 또는 `"0+unknown"`, `apidocs.py:18-21`), `summary`, `base_url`(`http://{host}:{port}`), `endpoints`(라우트 9개 설명 dict), `example`(`curl`, `python`, `background`), `failure_kinds`(= `FAILURE_KINDS`), `constraints`(= `CONSTRAINTS` 6문장), `config`(`model`, `min_workers`, `max_workers`, `default_timeout_sec`).

### `GET /openapi.json` — `openapi_spec(config)` (`apidocs.py:227-308`)

- `openapi: "3.1.0"`, `info.version = VERSION`, `info.description = SUMMARY + Constraints`, `servers[0].url = http://{host}:{port}`.
- `paths` 7개: `/generate`, `/jobs`, `/jobs/{job_id}`, `/health`, `/`, `/docs`, `/openapi.json`.
- `/generate` post 응답은 `_generate_responses()`(`apidocs.py:136-168`)가 `200`, `400`과 `FAILURE_KINDS`의 각 상태(429, 502, 503, 504, 403)로 만든다. 같은 상태(503)의 kind 설명은 이어 붙이고, `429`에 `Retry-After` integer 헤더를 선언한다.
- `/jobs` post: `202`(`Location` 헤더, job 스키마), `400`, `403`. get: `200`(`jobs` 배열). `/jobs/{job_id}` get·delete: `200`, `404`.
- 선언 스키마 속성: 오류 `_ERROR_SCHEMA`(`apidocs.py:122-131`) = `error`(필수)·`kind`(enum)·`retryable`·`duration_ms`. job `_JOB_SCHEMA`(`apidocs.py:189-205`) = `job_id`·`status`(필수)·`prompt_preview`·`created_at`·`finished_at`·`text`·`duration_ms`·`error`·`kind`·`retryable`. health `_HEALTH_SCHEMA`(`apidocs.py:171-186`). 요청 `_prompt_body`(`apidocs.py:213-224`) = `prompt`(minLength 1, 필수)·`timeout_sec`(default = `config.default_timeout_sec`).
- 선언과 구현 키의 차이(실측 사실): 구현 job 본문의 `url`(`server.py:135`)과 `retry_after_sec`(`jobs.py:67-68`)은 `_JOB_SCHEMA`에 선언돼 있지 않다.

### `GET /docs` — `render_html(config)` (`apidocs.py:327-390`)

- 템플릿 엔진을 쓰지 않는다. 하나의 f-string으로 `<!doctype html>`부터 `</html>`까지 단일 페이지를 조립하고, 핸들러가 `web.Response(text=page, content_type="text/html")`로 돌려준다(`server.py:174-176`). 페이지 조각·레이아웃 파일·정적 자원 디렉터리는 없다.
- 인라인 `<style>`만 사용하고 외부 스크립트·스타일시트를 참조하지 않는다(docstring `apidocs.py:328`). 링크는 상대 경로 `/openapi.json`, `/health` 두 개다(`apidocs.py:389`).
- 구성: 제목·요약, 쿼터 소모 경고, 엔드포인트 표, curl·Python 예제, 백그라운드 job 설명과 예제, 실패 표(`_failure_table`, `apidocs.py:311-324`), 제약 목록, 현재 데몬 설정 표.

**출력 이스케이프 처리 (코드 실측)**

| 삽입 값 | 처리 | 위치 |
|---|---|---|
| `VERSION`(제목·헤더) | `html.escape` | `apidocs.py:339`, `apidocs.py:354` |
| `SUMMARY` | `html.escape` | `apidocs.py:355` |
| 엔드포인트 표의 키·설명 | `html.escape` | `apidocs.py:331-334` |
| 제약 목록 항목 | `html.escape` | `apidocs.py:335` |
| curl·Python·background 예제 | `html.escape` | `apidocs.py:364`, `apidocs.py:366`, `apidocs.py:372` |
| `base_url`(host·port 포함) | `html.escape` 후 삽입 | `apidocs.py:330`, `apidocs.py:384` |
| `config.model` | `html.escape` | `apidocs.py:385` |
| 실패 표의 `kind`, `meaning` | `html.escape` | `apidocs.py:314`, `apidocs.py:317` |
| 실패 표의 `status`, `yes`/`no` | 이스케이프 없이 삽입(값은 `FAILURE_KINDS` 모듈 상수의 int와 코드 리터럴) | `apidocs.py:315-316` |
| `config.min_workers`, `config.max_workers`, `config.default_timeout_sec` | 이스케이프 없이 삽입. `from_env()` 경로에서는 `int()`/`float()` 변환값이며, 데이터클래스는 런타임 타입을 강제하지 않는다 | `apidocs.py:386-387`, `config.py:82-87` |
| `_failure_table()` 결과, `endpoints`, `constraints` 조립 문자열 | 이미 각 값을 이스케이프해 조립한 HTML을 그대로 삽입 | `apidocs.py:361`, `apidocs.py:377`, `apidocs.py:380` |

- 요청 데이터(헤더·본문·쿼리)는 `/docs` 출력에 들어가지 않는다. 출력 값의 출처는 모듈 상수와 `PoolConfig`다.
- 설정값 이스케이프를 확인하는 테스트: `tests/test_apidocs.py:117-121`(`model="<script>x</script>"`).
- 이 문서는 이스케이프 처리 지점을 기록한 것이며 XSS 방어 효과를 검증한 결과가 아니다.

## 계약 확인 근거 (테스트 위치)

| 계약 | 테스트 |
|---|---|
| `/generate` 성공·400·실패 응답 | `tests/test_server.py` |
| job 라우트 202·Location·폴링·404·목록 순서 | `tests/test_jobs.py:156-227` |
| Host 가드 403 | `tests/test_host_guard.py`, `tests/test_jobs.py:229-232`, `tests/test_apidocs.py:89-92` |
| 자기 문서 내용·OpenAPI 경로 집합·HTML 자체 완결성 | `tests/test_apidocs.py` |
| 클라이언트가 소비하는 키 | `tests/test_client.py` |

테스트를 실행하지 않았으므로 통과 여부는 기록하지 않는다.

## 실측 근거

- 기준 commit: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`
- 확인한 소스: [server.py](../../../src/claude_pool/server.py), [jobs.py](../../../src/claude_pool/jobs.py), [pool.py](../../../src/claude_pool/pool.py), [apidocs.py](../../../src/claude_pool/apidocs.py), [config.py](../../../src/claude_pool/config.py), [errors.py](../../../src/claude_pool/errors.py), [runner.py](../../../src/claude_pool/runner.py), 위 표의 테스트 파일
- 확인 범위: 라우트·직렬화·문서 생성 코드 정적 읽기. HTTP 요청을 실제로 보내지 않았다.
- 미확인: aiohttp의 요청 본문 최대 크기 기본값 적용 결과, `Host` 헤더가 없는 요청에서 `request.host`가 갖는 값, 실제 응답 헤더 전체(aiohttp가 추가하는 헤더).

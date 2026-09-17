---
description: 워커 실패를 CLI 문구 정규식이 아니라 stream-json 출력의 구조화된 값(result.api_error_status, assistant.error)으로 분류한다 — GitHub 이슈 #1
status: approved
revision: 1
plan:
origin: brain
architecture:
  - ../../architecture/design/00-overview.md
  - ../../architecture/design/01-project-structure.md
  - ../../architecture/design/02-external-dependencies.md
  - ../../architecture/design/04-testing-strategy.md
  - ../../architecture/design/05-coding-conventions.md
  - ../../architecture/design/07-development-patterns.md
  - ../../architecture/design/13-error-policy.md
  - ../../architecture/as-built/13-error-policy.md
  - ../../architecture/as-built/04-testing-strategy.md
---

# 구조화된 값으로 워커 실패 분류하기

- 출처: [GitHub 이슈 #1](https://github.com/HojinJava/claude_code_cli_local_gateway/issues/1), 실측·결정 댓글 [issuecomment-5710930609](https://github.com/HojinJava/claude_code_cli_local_gateway/issues/1#issuecomment-5710930609)
- 선행 spec: [HTTP 게이트웨이 데몬 API](../2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md)(`origin: migration`)의 실패 분류 부분을 이 spec이 바꾼다. 선행 spec은 역작성 기록으로 유지한다.

## 배경과 해결할 문제

호출자(예: RAG_law 서버)는 이 데몬 응답의 `kind`·HTTP 상태·`Retry-After`로 재시도·대기·즉시 실패를 가른다. 그런데 현재 `rate_limited`·`not_authenticated` 판정은 CLI가 출력한 사람이 읽는 문구에 대한 정규식 매칭이다(`errors.py:22-50`). 문구가 바뀌거나 다른 오류 문구에 `quota`·`429` 같은 낱말이 섞이면 분류가 조용히 틀린다. 호출자가 정확한 값으로 분기해도 입력이 추정이면 소용이 없다.

## 실측으로 확정한 사실 (2026-09-17, Claude Code 2.1.274)

워커와 같은 인자로, 빈 설정 폴더(`CLAUDE_CONFIG_DIR`)에서 CLI를 1회 실행해 인증 실패를 재현했다.

- exit code는 1이고 stderr는 비어 있었다. stdout은 `system`(init) → `assistant` → `result` 세 줄이었다.
- `assistant` 줄: `"error": "authentication_failed"`, `"is_api_error_message": true`, 본문 `Not logged in · Please run /login`.
- `result` 줄: `is_error: true`, `subtype: "success"`, `api_error_status: null`, `terminal_reason: "api_error"`.
- 따라서 인증 실패는 결과 줄만으로 구별되지 않고, 앞선 `assistant` 줄의 `error`로 구별된다.
- CLI가 결과 줄을 낸 뒤에도 exit code 1로 끝나므로, exit code가 0이 아니면 결과 줄을 읽기 전에 `WorkerError`를 올리는 현재 `Worker.run`(`worker.py:92-96`)으로는 이 값을 읽을 수 없다.
- CLI 실행 파일의 SDK 스키마에서 `assistant.error` enum 13개를 확인했다: `authentication_failed`, `oauth_org_not_allowed`, `account_on_hold`, `verification_required`, `billing_error`, `rate_limit`, `overloaded`, `invalid_request`, `model_not_found`, `server_error`, `unknown`, `max_output_tokens`, `cloud_credential_error`.
- 같은 실행 파일의 매핑: API 상태 529(또는 `overloaded_error`) → `overloaded`, 429 → `rate_limit`, 401·403 → `authentication_failed`.
- 인증 실패 경로의 어느 줄에도 `retry_after` 류 필드는 없었다. 429·529 실패의 실제 출력은 일부러 일으킬 수 없어 **미실측**이다.

## 범위

- 워커가 stdout에서 결과 줄의 `api_error_status`와, 최상위(`parent_tool_use_id`가 `null`) `assistant` 줄의 `error` 값을 꺼내 `runner`까지 넘긴다.
- 결과 줄이 있으면 exit code와 무관하게 결과 줄로 성공·실패를 판단한다.
- `is_error: true` 결과를 아래 표의 구조화된 값만으로 분류한다. 판정용 문구 정규식을 제거한다.
- 결과 줄 없이 비정상 종료한 경우는 `worker_failed`로 분류한다.
- 가짜 CLI를 실측한 출력 모양에 맞춰 구조화된 값을 지정할 수 있게 확장하고, 테스트를 새 판정으로 바꾼다.
- `apidocs.FAILURE_KINDS`, `errors.py` 머리 주석, `CLAUDE.md`, `README.md`를 새 판정과 실측 결과에 맞춘다.
- 구현 후 실제 CLI로 정상 응답 1건 스모크 테스트를 한다(사용자 승인: 지금 떠 있는 데몬과 다른 포트에 임시 데몬을 띄운다).

## 비범위

- HTTP 계약 변경: `kind` 이름 6개, 각 `kind`의 HTTP 상태와 `retryable`, `Retry-After` 헤더 이름, 응답 본문 키는 바꾸지 않는다.
- 자동 재시도 도입(데몬은 재시도하지 않는다).
- 워커 실행 인자, stream-json 프로토콜, 1회용 워커, `runner.execute` 단일 경로 변경.
- `pool_unavailable`·`timeout`·`forbidden_host` 판정 변경(이미 데몬이 직접 판단한 정확한 값이다).
- `oauth_org_not_allowed`·`account_on_hold`·`verification_required`·`billing_error` 등 상태코드와 대응하지 않는 enum 값의 별도 분류(사용자 결정: 상태코드 대응값만 쓴다).
- 결과 줄의 `usage`·`total_cost_usd`·`modelUsage` 전달(별도 이슈로 판단).
- 429·529의 실제 출력 실측.

## 분류 규칙 (판단 순서가 우선순위)

`is_error: true`인 결과 줄에 적용한다. `api_error_status`가 `null`이 아니면 1·2행만 보고, 해당하지 않으면 5행이다. `null`이면 3·4행을 본다.

| 순서 | 조건 | `kind` | HTTP | `retryable` | `Retry-After` |
|---|---|---|---|---|---|
| 1 | `api_error_status` ∈ {429, 529} | `rate_limited` | 429 | true | 60 |
| 2 | `api_error_status` ∈ {401, 403} | `not_authenticated` | 503 | false | 없음 |
| 3 | `api_error_status`가 `null`이고 `assistant.error` ∈ {`rate_limit`, `overloaded`} | `rate_limited` | 429 | true | 60 |
| 4 | `api_error_status`가 `null`이고 `assistant.error` = `authentication_failed` | `not_authenticated` | 503 | false | 없음 |
| 5 | 그 밖의 `is_error: true` | `worker_failed` | 502 | false | 없음 |
| — | 결과 줄 없이 프로세스가 끝남(`WorkerError`) | `worker_failed` | 502 | false | 없음 |

- 숫자·문자열 집합은 이름 붙은 상수로 둔다.
- 대기 시간을 담은 구조화된 값이 없으므로 `Retry-After`는 `DEFAULT_RETRY_AFTER_SEC`(60) 고정이다.
- 응답 본문 `error`에는 지금처럼 CLI 결과 문구(또는 `WorkerError` 메시지)를 그대로 싣는다. 이 문구는 판정에 쓰지 않는다.

## 사용자 관찰 동작과 수용 기준

- **AC-001** 결과 줄이 `is_error: true`, `api_error_status` 429 또는 529이면 `POST /generate`는 429, 본문 `kind: "rate_limited"`, `retryable: true`, 헤더 `Retry-After: 60`을 돌려준다.
- **AC-002** 결과 줄이 `is_error: true`, `api_error_status` 401 또는 403이면 503, `kind: "not_authenticated"`, `retryable: false`이고 `Retry-After` 헤더가 없다.
- **AC-003** 결과 줄의 `api_error_status`가 `null`이고 앞선 최상위 `assistant` 줄의 `error`가 `authentication_failed`이면 AC-002와 같은 응답이다(실측한 인증 실패 모양).
- **AC-004** 결과 줄의 `api_error_status`가 `null`이고 앞선 최상위 `assistant` 줄의 `error`가 `rate_limit` 또는 `overloaded`이면 AC-001과 같은 응답이다.
- **AC-005** 위에 해당하지 않는 `is_error: true` 결과는 502, `kind: "worker_failed"`, `retryable: false`이다. 여기에는 `api_error_status` 500, `null` 상태에 `billing_error` 같은 그 밖의 enum, 구조화된 값이 전혀 없는 경우가 포함된다.
- **AC-006** 문구는 판정을 바꾸지 않는다. `api_error_status` 500에 결과 문구가 `rate limit 429 please run /login`이어도 `worker_failed`이고, `api_error_status` 429에 문구가 무관한 내용이어도 `rate_limited`이다.
- **AC-007** 결과 줄을 낸 뒤 exit code 1로 끝난 워커도 결과 줄의 구조화된 값으로 분류된다.
- **AC-008** 결과 줄 없이 비정상 종료한 워커는 stderr에 `please run /login` 같은 문구가 있어도 502 `worker_failed`이며, 본문 `error`에 exit code와 stderr가 담긴다.
- **AC-009** 모든 실패 응답의 본문 `error`에는 CLI 결과 문구 또는 `WorkerError` 메시지가 그대로 실린다.
- **AC-010** `POST /jobs` 경로도 같은 분류를 쓴다. `rate_limited`로 끝난 job의 `GET /jobs/{id}` 본문에는 `kind: "rate_limited"`, `retryable: true`, `retry_after_sec: 60`이 있다.
- **AC-011** `src/claude_pool/errors.py`에 판정용 문구 정규식(`_RATE_LIMIT_PATTERNS`, `_AUTH_PATTERNS`, `_RETRY_AFTER_RE`)이 남아 있지 않다.
- **AC-012** `kind` 이름 6개와 각 `kind`의 HTTP 상태·`retryable`, `Retry-After` 헤더 이름, 성공·실패 응답 본문 키가 변경 전과 같다.
- **AC-013** `apidocs.FAILURE_KINDS`의 `meaning`이 새 판정 근거를 설명하고, `tests/test_apidocs.py`가 분류 함수와 문서 표의 일치를 검사한다.
- **AC-014** `errors.py` 머리 주석, `CLAUDE.md`의 `errors.py` 설명, `README.md`의 실패 분류 절이 새 판정과 맞는다. README에는 실측한 CLI 버전(2.1.274)과 "429·529 실제 출력은 미실측"이 적혀 있다.
- **AC-015** 가짜 CLI가 실측 출력 모양(`system` → `assistant` → `result`)으로 `api_error_status`, `assistant.error`, exit code를 지정할 수 있고, 위 AC가 가짜 CLI → `create_app` → HTTP 응답까지 테스트된다. 실제 CLI는 테스트에서 호출하지 않는다.
- **AC-016** `pytest -v` 전체가 통과한다.
- **AC-017** 실제 `claude` CLI로 임시 데몬(기존 데몬과 다른 포트)을 띄워 `POST /generate` 정상 응답 1건을 확인한다.

## 기존 구조와 바뀌는 책임

| 파일 | 현재 책임 | 바뀌는 책임 |
|---|---|---|
| `src/claude_pool/worker.py` | exit code ≠ 0이면 결과 줄을 보기 전에 `WorkerError`, 결과 줄에서 4개 값 반환 | 결과 줄을 먼저 찾고, 있으면 exit code와 무관하게 반환. `api_error_status`와 최상위 `assistant.error`를 추가 반환. 결과 줄이 없을 때만 `WorkerError` |
| `src/claude_pool/errors.py` | 문구 정규식 `classify(text)` | 구조화된 값 분류 함수와 이름 붙은 상수. 정규식 제거 |
| `src/claude_pool/runner.py` | `WorkerError`·`is_error` 결과 모두 `classify(문구)` | `WorkerError`는 `worker_failed`, `is_error` 결과는 구조화된 값으로 분류 |
| `src/claude_pool/apidocs.py` | `FAILURE_KINDS` 의미가 문구 기반 | 의미를 구조화된 값 기준으로 수정 |
| `tests/fixtures/fake_claude_cli.py` | `error` 모드는 `system`·`result` 2줄, exit 0 | 실측 모양의 `assistant` 줄과 구조화된 값·exit code 옵션 |
| `tests/test_errors.py`, `tests/test_server.py`, `tests/test_jobs.py`, `tests/test_apidocs.py`, `tests/test_worker.py` | 문구 기반 기대값 | 구조화된 값 기반 기대값과 AC 테스트 |
| `CLAUDE.md`, `README.md` | 문구 분류 설명 | 새 판정·실측 결과 설명 |

## 아키텍처 참조

- [design/13-error-policy.md](../../architecture/design/13-error-policy.md) — 이번 변경의 목표 분류 규칙·입력 추출·경계(설계 본문)
- [design/07-development-patterns.md](../../architecture/design/07-development-patterns.md) — 분류를 순수 함수로 두고 워커는 값 추출만 하는 작성 규칙
- [design/04-testing-strategy.md](../../architecture/design/04-testing-strategy.md) — 가짜 CLI 확장과 AC별 검증 방법
- [design/00-overview.md](../../architecture/design/00-overview.md), [design/01-project-structure.md](../../architecture/design/01-project-structure.md), [design/02-external-dependencies.md](../../architecture/design/02-external-dependencies.md), [design/05-coding-conventions.md](../../architecture/design/05-coding-conventions.md) — 필수 코어(기존 구조 유지·기본값 적용)
- 현재 구조: [as-built/13-error-policy.md](../../architecture/as-built/13-error-policy.md), [as-built/04-testing-strategy.md](../../architecture/as-built/04-testing-strategy.md)

## 위험·테스트·문서 영향

- **미실측 위험:** 429·529 실패에서 `api_error_status`가 실제로 채워지는지, `assistant.error`가 `rate_limit`·`overloaded`로 오는지는 실측하지 못했다. 둘 다 오지 않으면 `worker_failed`(retryable false)로 떨어진다. 코드 주석과 README에 미실측임을 적는다.
- **호환 영향:** 문구만으로 `rate_limited`·`not_authenticated`가 되던 실패(예: 결과 줄 없는 비정상 종료의 stderr 문구)가 `worker_failed`로 바뀐다. `kind` 이름과 HTTP 계약은 그대로다.
- **exit code 처리 변경:** 결과 줄이 `is_error: false`인데 exit code가 0이 아닌 경우도 성공으로 처리된다. 실측에서 이런 조합은 관찰하지 않았다.
- **테스트:** 가짜 CLI만 사용한다(이 저장소 규칙). 실제 CLI는 AC-017 수동 스모크 1건뿐이다.
- **문서:** as-built 문서는 구현 뒤 sync가 갱신한다. 이번 brain 단계는 design과 색인의 미반영 표시만 갱신한다.

## 열린 질문과 확정 결정

확정 결정(2026-09-17 사용자 합의, 이슈 댓글에 기록):

- R3: 구조화된 값으로 구별되지 않는 실패는 문구 매칭 없이 `worker_failed`로 둔다.
- 분류 입력: `result.api_error_status`를 먼저 보고, `null`이면 `assistant.error` 중 CLI가 상태코드에서 만드는 값(`rate_limit`, `overloaded`, `authentication_failed`)만 쓴다.
- 결과 줄이 있으면 exit code와 무관하게 결과 줄로 판단한다.
- spec은 gateway-api spec을 갱신하지 않고 이 후속 spec으로 분리한다.
- 외부 작업 승인: 이슈 #1 댓글 작성, 구현 후 실제 CLI 스모크 테스트 1건.

열린 질문: 없음.

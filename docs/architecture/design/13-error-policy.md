---
description: claude-pool 사전 에러 정책 — 워커 실패를 stream-json 구조화된 값으로 분류하는 목표 규칙(이슈 #1)
tags: [architecture]
status: design
---

# 13. 에러 정책 (design)

- 근거 spec: [구조화된 값으로 워커 실패 분류하기](../../spec/2026-09-17-spec-structured-failure-classification/2026-09-17-spec-structured-failure-classification.md)
- 적용 영역: `is_error: true` 결과와 `WorkerError`의 분류. `pool_unavailable`·`timeout`·`forbidden_host` 판정과 HTTP 응답 구현(`_failure_response`, `Job.to_dict`)은 현재 구조를 유지한다([as-built/13-error-policy](../as-built/13-error-policy.md)).

## 분류 입력 (워커가 추출)

| 값 | 출처 | 비고 |
|---|---|---|
| `is_error`, `result`(문구), `duration_ms`, `subtype` | `type: "result"` 줄 | 기존 |
| `api_error_status` | `type: "result"` 줄 | 새로 추출. 성공·인증 실패에서 `null`로 실측 |
| `error` | 최상위(`parent_tool_use_id`가 `null`) `type: "assistant"` 줄 중 마지막 줄의 `error` | 새로 추출. 문자열이 아니면 `None` |

- 결과 줄이 있으면 exit code와 무관하게 결과 줄을 반환한다(실측: 인증 실패는 결과 줄을 출력한 뒤 exit 1로 끝난다).
- 결과 줄이 없으면 exit code ≠ 0일 때 기존처럼 exit code·stderr를 담은 `WorkerError`를, exit 0일 때 "no result line" `WorkerError`를 올린다.

## 분류 규칙 (판단 순서가 우선순위)

| 순서 | 조건 | `kind` | HTTP | `retryable` | `retry_after_sec` |
|---|---|---|---|---|---|
| 1 | `api_error_status` ∈ `{429, 529}` | `rate_limited` | 429 | true | 60 |
| 2 | `api_error_status` ∈ `{401, 403}` | `not_authenticated` | 503 | false | 없음 |
| 3 | `api_error_status` ≠ `null` (1·2 외) | `worker_failed` | 502 | false | 없음 |
| 4 | `api_error_status` = `null`, `error` ∈ `{"rate_limit", "overloaded"}` | `rate_limited` | 429 | true | 60 |
| 5 | `api_error_status` = `null`, `error` = `"authentication_failed"` | `not_authenticated` | 503 | false | 없음 |
| 6 | 그 밖의 `is_error: true` | `worker_failed` | 502 | false | 없음 |
| — | `WorkerError` | `worker_failed` | 502 | false | 없음 |

- 상수: 상태 집합 2개, `error` 값 집합 2개, `DEFAULT_RETRY_AFTER_SEC = 60`.
- `error` enum 중 상태코드와 대응하지 않는 값(`billing_error`, `oauth_org_not_allowed` 등)은 6행이다(사용자 결정).
- 문구(`result`, stderr)는 응답 본문 `error`로만 전달하고 판정에 쓰지 않는다.

## 불변조건과 검증

- HTTP 계약 불변: `kind` 6개, 각 HTTP 상태·`retryable`, `Retry-After` 헤더 이름. 검증: 기존 `tests/test_apidocs.py`·`tests/test_server.py` 유지.
- `apidocs.FAILURE_KINDS`는 분류 함수와 항상 일치한다(`CLAUDE.md` 규칙). 검증: `tests/test_apidocs.py`가 분류 함수 결과와 표를 대조한다.
- 데몬은 자동 재시도하지 않는다. 검증: `runner.execute`의 획득·실행 각 1회 구조를 유지한다.

## 미확정 사항

- 429·529 실패의 실제 출력(`api_error_status` 채움 여부, `error` 값)은 미실측이다.
  - 영향: 둘 다 오지 않으면 `worker_failed`로 떨어진다.
  - 확인 방법: 실제 한도에 도달했을 때 출력을 수집한다.
  - 확정 시점: 관찰되는 대로 이 문서와 README를 갱신한다.

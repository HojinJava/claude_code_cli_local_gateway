---
task: 003
status: pending
risk: medium
---

# task-003 구조화된 값으로 분류하고 연결

## 목표

`is_error` 결과를 구조화된 값만으로 분류하고, `WorkerError`는 `worker_failed`로 둔다. 문구 정규식을 제거하고 자기 문서와 HTTP·jobs 테스트를 새 판정에 맞춘다.

## 의존성

task-001, task-002.

## 설계 입력

- [design/13-error-policy.md — 분류 규칙](../../architecture/design/13-error-policy.md#분류-규칙-판단-순서가-우선순위), [불변조건과 검증](../../architecture/design/13-error-policy.md#불변조건과-검증)
- [design/07-development-patterns.md — 채택 방식](../../architecture/design/07-development-patterns.md#채택-방식-값-추출과-분류-판정의-분리)
- [design/05-coding-conventions.md](../../architecture/design/05-coding-conventions.md#이번-변경에-적용할-규칙)

## 파일 책임

- `src/claude_pool/errors.py`: 구조화된 값(`api_error_status`, `error`)을 받는 순수 분류 함수와 이름 붙은 `frozenset` 상수(`{429, 529}`, `{401, 403}`, `{"rate_limit", "overloaded"}`, `{"authentication_failed"}`), `DEFAULT_RETRY_AFTER_SEC = 60` 유지. `_RATE_LIMIT_PATTERNS`·`_AUTH_PATTERNS`·`_RETRY_AFTER_RE`와 문구 기반 `classify(text)` 제거. `WorkerError`용 `worker_failed` `Failure`를 제공한다.
- `src/claude_pool/runner.py`: `WorkerError` → `worker_failed`, `is_error` 결과 → 분류 함수. 본문 `error`는 기존처럼 문구·예외 메시지를 싣는다. 그 밖의 흐름(획득·shield 반납·`_note`)은 유지.
- `src/claude_pool/apidocs.py`: `FAILURE_KINDS`의 `rate_limited`·`not_authenticated`·`worker_failed` `meaning`을 구조화된 값 기준으로 수정. kind·status·retryable은 그대로.
- `tests/test_errors.py`: 분류 표 각 행의 파라미터 테스트, 정규식 상수 부재 검사(AC-011).
- `tests/test_apidocs.py`: 문구 기반 일치 검사를 분류 함수 기반으로 교체.
- `tests/test_server.py`: 가짜 CLI → `create_app` → HTTP로 AC-001~AC-009 확인. 기존 문구 기반 기대값을 새 판정으로 교체.
- `tests/test_jobs.py`: `/jobs` 경로 AC-010, 기존 문구 기반 기대값 교체(예: crash + `please run /login`은 `worker_failed`).

## 완료 기준

- 구현: 위 책임. HTTP 계약(kind 6개·상태·retryable·헤더 이름·본문 키) 불변.
- 검증: RED → GREEN, `pytest tests/test_errors.py tests/test_apidocs.py tests/test_server.py tests/test_jobs.py`.
- 담당 AC: AC-001~AC-006, AC-007(HTTP 수준), AC-008(HTTP 수준), AC-009~AC-013, AC-015(일부).

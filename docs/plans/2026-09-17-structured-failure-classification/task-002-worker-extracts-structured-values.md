---
task: 002
status: pending
risk: medium
---

# task-002 워커가 구조화된 값을 추출

## 목표

`Worker.run`이 stdout의 결과 줄을 exit code보다 먼저 찾고, `api_error_status`와 최상위 `assistant.error`를 추가로 반환한다.

## 의존성

task-001.

## 설계 입력

- [design/13-error-policy.md — 분류 입력](../../architecture/design/13-error-policy.md#분류-입력-워커가-추출)
- [design/07-development-patterns.md — 채택 방식](../../architecture/design/07-development-patterns.md#채택-방식-값-추출과-분류-판정의-분리)

## 파일 책임

- `src/claude_pool/worker.py` `Worker.run`:
  - stdout을 줄 단위로 파싱해 `type: "result"` 첫 줄과, 그 앞의 최상위(`parent_tool_use_id`가 `null`) `type: "assistant"` 줄 중 마지막 줄의 `error`(문자열일 때만)를 찾는다.
  - 결과 줄이 있으면 exit code와 무관하게 `text`, `duration_ms`, `is_error`, `subtype`, `api_error_status`(정수가 아니면 `None`), `error`를 반환한다.
  - 결과 줄이 없으면 exit code ≠ 0일 때 기존 메시지(exit code·stderr)의 `WorkerError`, exit 0일 때 기존 "no 'result' line" `WorkerError`.
  - 판정 로직은 두지 않는다. 타임아웃·kill 처리는 유지한다.
- `tests/test_worker.py`: 구조화된 값 반환, exit 1 + 결과 줄, 결과 줄 없는 crash의 `WorkerError` 유지를 검증한다.

## 완료 기준

- 구현: 위 반환값·예외 규칙.
- 검증: RED → GREEN, `pytest tests/test_worker.py`.
- 담당 AC: AC-007(워커 수준), AC-008(워커 수준), AC-015(일부).

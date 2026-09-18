---
task: 001
status: pending
risk: low
---

# task-001 가짜 CLI를 실측 출력 모양으로 확장

## 목표

`tests/fixtures/fake_claude_cli.py`의 `error` 모드가 2026-09-17 실측한 실제 CLI 출력 모양으로 구조화된 값을 내게 한다. 이후 Task의 테스트 입력이 된다.

## 의존성

없음.

## 설계 입력

[design/04-testing-strategy.md — 가짜 CLI 확장](../../architecture/design/04-testing-strategy.md#가짜-cli-확장)

## 파일 책임

- `tests/fixtures/fake_claude_cli.py`: `error` 모드 출력 순서를 `system`(init) → 최상위 `assistant` → `result`로 바꾸고 옵션 `--fake-api-error-status N`, `--fake-assistant-error VALUE`, `--fake-exit-code N`을 추가한다.
  - `assistant` 줄: `type: "assistant"`, `parent_tool_use_id: null`, `is_api_error_message: true`, 지정 시 `error`, 본문은 `--fake-error-text`.
  - `result` 줄: `is_error: true`, `subtype: "success"`, `api_error_status`(미지정 시 `null`), `terminal_reason: "api_error"`, `result`, `duration_ms`.
  - 결과 줄을 출력한 뒤 `--fake-exit-code`(기본 0)로 종료한다.
  - `echo`·`crash` 모드와 알 수 없는 플래그 무시는 유지한다.
- `tests/fixtures/test_fake_claude_cli.py`: 새 출력 모양과 옵션을 검증한다.

## 완료 기준

- 구현: 위 출력·옵션이 있다. 기존 `echo`·`crash` 동작이 바뀌지 않는다.
- 검증: RED(새 옵션 테스트 실패) → GREEN, `pytest tests/fixtures/test_fake_claude_cli.py`.
- 담당 AC: AC-015(일부).

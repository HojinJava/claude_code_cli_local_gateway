---
description: claude-pool 사전 테스트 전략 — 이슈 #1 수용 기준별 검증 방법과 가짜 CLI 확장
tags: [architecture]
status: design
---

# 04. 테스트 전략 (design)

- 근거 spec: [구조화된 값으로 워커 실패 분류하기](../../spec/2026-09-17-spec-structured-failure-classification/2026-09-17-spec-structured-failure-classification.md)
- 기존 테스트 구성·실행 방법은 [as-built/04-testing-strategy](../as-built/04-testing-strategy.md)를 유지한다. 테스트는 실제 `claude` CLI를 호출하지 않는다(`CLAUDE.md` 규칙).

## 가짜 CLI 확장

`tests/fixtures/fake_claude_cli.py`의 `error` 모드를 실측 출력 모양으로 맞춘다.

- 출력 순서: `system`(init) → 최상위 `assistant`(`parent_tool_use_id: null`, `is_api_error_message: true`, 지정 시 `error`) → `result`(`is_error: true`, `subtype: "success"`, `api_error_status`, `terminal_reason: "api_error"`, `result` 문구).
- 옵션: `--fake-api-error-status N`(없으면 `null`), `--fake-assistant-error VALUE`(없으면 `error` 키 생략), `--fake-exit-code N`(결과 줄 출력 뒤 종료 코드, 기본 0), 기존 `--fake-error-text`.

## 수용 기준별 검증

| AC | 계층 | 방법 |
|---|---|---|
| AC-001~AC-006 | 순수 함수 + HTTP 인프로세스 | 분류 함수 파라미터 테스트, 가짜 CLI → `create_app` → 상태코드·`kind`·`retryable`·`Retry-After` 확인 |
| AC-007 | 서브프로세스 단위 + HTTP | `--fake-exit-code 1`과 구조화된 값으로 워커 반환값·HTTP 분류 확인 |
| AC-008 | HTTP | `crash` 모드 + `--fake-error-text "please run /login"` → 502 `worker_failed`, 본문 `error`에 exit code·stderr |
| AC-009 | HTTP | 실패 응답 본문 `error`가 결과 문구와 같은지 |
| AC-010 | HTTP(`/jobs`) | 429 구조값 job의 `GET /jobs/{id}` 본문 `kind`·`retryable`·`retry_after_sec` |
| AC-011 | 정적 | `errors.py`에 판정용 정규식 상수가 없는지 검사 |
| AC-012 | 기존 테스트 | `test_apidocs`의 kind 목록·상태 검사와 서버 응답 키 테스트 유지 |
| AC-013 | 순수 함수 | 분류 함수 결과와 `FAILURE_KINDS` 표의 status·retryable 일치 검사 |
| AC-014 | 정적 대조 | 문서 문구·버전 표기 확인 |
| AC-015 | 서브프로세스 단위 | 가짜 CLI 출력 줄 순서·필드 확인 |
| AC-016 | 전체 | `pytest -v` |
| AC-017 | 수동 | 임시 포트 데몬에 실제 CLI로 `POST /generate` 1건 |

## 이슈 #2 — 유휴 축소 검증

- 근거 spec: [유휴 시 워커를 0까지 줄이기](../../spec/2026-09-18-spec-idle-scale-to-zero/2026-09-18-spec-idle-scale-to-zero.md)
- 실제 `claude` CLI·실제 데몬을 쓰지 않는다. 가짜 CLI와 인프로세스 앱으로 검증한다.

| AC | 방법 |
|---|---|
| AC-001, AC-003, AC-006 | 짧은 기준 시간·짧은 축소 주기로 풀을 만들고 `stats()`의 `idle`·`total` 변화를 확인 |
| AC-002 | 축소 후 `POST /generate`가 200을 돌려주는지 인프로세스 앱으로 확인 |
| AC-004, AC-005 | 느린 가짜 CLI(`--fake-delay-sec`)로 처리 중 상태를 만들고 그 사이 축소가 없음을 확인. job 경로도 같은 방식 |
| AC-007 | `PoolConfig.from_env` 파라미터 테스트 |
| AC-008 | 축소 후 `/health`의 `healthy`·`last_error` 확인 |
| AC-009, AC-010 | 런처를 부분 검증한다. 실제 데몬을 띄우지 않도록 클라이언트를 monkeypatch해 성공·실패 경로의 출력과 종료 코드를 확인 |
| AC-011 | 문서 정적 대조 |
| AC-013 | `pytest -v` |

타이밍에 기대는 테스트는 기존 축소 테스트와 같은 방식(짧은 주기 + `asyncio.sleep`)을 따르되, 가능하면 시각 값을 직접 조작해 대기 시간을 줄인다.

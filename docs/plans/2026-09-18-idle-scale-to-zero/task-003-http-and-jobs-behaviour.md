---
task: 003
status: done
risk: low
---

# task-003 HTTP·job 경로에서 관찰되는 동작

## 목표

축소가 일어난 뒤에도 요청이 정상 처리되고, 실행 중인 job이 있으면 축소가 일어나지 않음을 실제 앱 경로에서 확인한다.

## 의존성

task-002.

## 설계 입력

[design/15-non-functional-requirements.md — 복구](../../architecture/design/15-non-functional-requirements.md#복구), [관측](../../architecture/design/15-non-functional-requirements.md#관측), [design/04-testing-strategy.md — 이슈 #2](../../architecture/design/04-testing-strategy.md#이슈-2--유휴-축소-검증)

## 파일 책임

- `tests/test_integration.py`: 짧은 기준 시간으로 인프로세스 앱을 띄워, 축소 후 `/health`가 `idle: 0`·`total: 0`·`healthy: true`·`last_error: null`을 보고하고, 그 상태에서 `POST /generate`가 200을 돌려주며, 처리 후 `idle`이 `min_workers`로 복구되는지 확인한다.
- `tests/test_jobs.py`: 느린 가짜 CLI로 job을 실행 중인 동안 축소가 일어나지 않고, job이 `succeeded`로 끝나는지 확인한다.
- 코드 변경은 없다. 변경이 필요하면 task-002의 책임이다.

## 완료 기준

- 구현: 없음(테스트만 추가).
- 검증: RED(축소 뒤 요청 경로가 아직 검증되지 않음) → GREEN, `pytest tests/test_integration.py tests/test_jobs.py`.
- 담당 AC: AC-002, AC-005, AC-008(HTTP 수준).

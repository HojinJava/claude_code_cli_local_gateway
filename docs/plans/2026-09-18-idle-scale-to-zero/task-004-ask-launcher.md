---
task: 004
status: pending
risk: low
---

# task-004 런처 `scripts/ask.py`

## 목표

데몬이 없으면 띄우고 프롬프트 1건을 보내 결과를 출력하는 런처를 추가한다.

## 의존성

task-001.

## 설계 입력

[design/07-development-patterns.md — 이슈 #2](../../architecture/design/07-development-patterns.md#이슈-2--축소-판정의-위치), [design/01-project-structure.md — 이슈 #2](../../architecture/design/01-project-structure.md#이슈-2--유휴-축소가-책임을-바꾸는-예정-경로), [design/02-external-dependencies.md — 이슈 #2](../../architecture/design/02-external-dependencies.md#이슈-2--의존-관계)

## 파일 책임

- `scripts/ask.py`:
  - 사용법을 모듈 docstring에 적는다(`python scripts/ask.py "프롬프트"`).
  - `ClaudePoolClient`를 그대로 쓴다(자동 기동 포함). HTTP 호출을 새로 구현하지 않는다.
  - 성공: 응답 텍스트를 표준 출력에 그대로 찍고 종료 코드 0.
  - 실패(`ClaudePoolError`): 메시지와 `kind`·`retryable`(있으면 `retry_after_sec`)을 표준 오류에 적고 종료 코드 1.
  - 인자가 없으면 사용법을 표준 오류에 적고 종료 코드 2.
  - 프롬프트는 인자 전체를 공백으로 이어 붙인다. 표준 입력 지원은 이번 범위 밖이다.
- `tests/test_ask_script.py`: 클라이언트를 monkeypatch해 성공·실패·인자 없음 세 경로의 출력과 종료 코드를 확인한다. 실제 데몬을 띄우지 않는다.

## 완료 기준

- 구현: 위 동작.
- 검증: RED → GREEN, `pytest tests/test_ask_script.py`.
- 담당 AC: AC-009, AC-010.

---
task: 006
status: pending
risk: low
---

# task-006 전체 테스트와 정적 확인

## 목표

전체 테스트가 통과하고, 테스트가 실제 `claude` CLI를 부르지 않음을 확인한다.

## 의존성

task-001~task-005.

## 설계 입력

[design/04-testing-strategy.md — 이슈 #2](../../architecture/design/04-testing-strategy.md#이슈-2--유휴-축소-검증)

## 파일 책임

- 코드 변경 없음. `acceptance-evidence.md`에 결과를 기록한다.
- 정적 확인: 새로 추가한 테스트의 `claude_cmd` 주입이 모두 가짜 CLI이거나 스폰하지 않는 값인지, 실제 데몬을 띄우는 테스트가 없는지 검색으로 확인한다.

## 완료 기준

- 검증: `pytest -v` 전체 PASS, 위 정적 확인 결과 기록.
- 담당 AC: AC-012, AC-013.

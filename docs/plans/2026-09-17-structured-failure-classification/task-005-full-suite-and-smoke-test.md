---
task: 005
status: pending
risk: low
---

# task-005 전체 테스트와 실제 CLI 스모크

## 목표

전체 테스트가 통과하고, 실제 `claude` CLI로 정상 응답 1건을 확인한다.

## 의존성

task-001~task-004.

## 설계 입력

[design/04-testing-strategy.md — 수용 기준별 검증](../../architecture/design/04-testing-strategy.md#수용-기준별-검증)

## 파일 책임

- 코드 변경 없음. `acceptance-evidence.md`에 결과를 기록한다.
- 스모크(사용자 승인됨): 지금 떠 있는 데몬(8756)은 건드리지 않는다. `~/.claude/PORTS.md`를 확인해 비어 있는 포트에 `CLAUDE_POOL_MIN_WORKERS=1 CLAUDE_POOL_MODEL=haiku`로 임시 데몬을 띄우고 `POST /generate`(`reply with the single word PONG`) 1건을 보낸 뒤 그 데몬만 종료한다. 쿼터 사용은 1건으로 제한한다.

## 완료 기준

- 검증: `pytest -v` 전체 PASS, 스모크 응답 200과 `text` 확인, 임시 데몬 종료 확인.
- 담당 AC: AC-016, AC-017.

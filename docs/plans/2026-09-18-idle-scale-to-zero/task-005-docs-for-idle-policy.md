---
task: 005
status: pending
risk: low
---

# task-005 문서 갱신

## 목표

README와 `CLAUDE.md`가 새 축소 정책과 런처를 설명하게 한다.

## 의존성

task-002, task-004.

## 설계 입력

[design/15-non-functional-requirements.md — 관측](../../architecture/design/15-non-functional-requirements.md#관측), [성능·비용 근거](../../architecture/design/15-non-functional-requirements.md#성능비용-근거)

## 파일 책임

- `README.md`:
  - 워커 사이징 절에 유휴 축소 정책을 적는다. 기준 시간·기본값 60초·`0`으로 끄는 방법, 축소 시 `/health`에서 보이는 값, 다음 요청에서 다시 예열된다는 점, 60초 넘게 쉰 뒤 첫 요청이 부팅 비용을 낸다는 대가.
  - 런처 사용법과 전역 `~\.local\bin\claude-pool-ask.cmd`의 내용을 적는다.
- `CLAUDE.md`: "반드시 지켜야 할 것"에 두 가지를 추가한다. 축소 하한이 `min_workers`가 아니라 유휴 조건에서 0이라는 점, 배포된 워커가 있으면 축소하지 않는다는 점.

## 완료 기준

- 구현: 두 문서가 spec의 동작 규칙과 일치한다.
- 검증: static — 문구 대조와 `git diff --check`.
- 담당 AC: AC-011.

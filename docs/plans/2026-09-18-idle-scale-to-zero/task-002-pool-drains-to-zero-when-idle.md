---
task: 002
status: pending
risk: medium
---

# task-002 유휴 시 풀이 0까지 줄어든다

## 목표

축소 루프가 유휴 조건에서 idle 워커를 전부 종료하고, 처리 중이거나 비활성 설정일 때는 기존 동작을 유지한다.

## 의존성

task-001.

## 설계 입력

- [design/15-non-functional-requirements.md — 판정 규칙](../../architecture/design/15-non-functional-requirements.md#판정-규칙), [복구](../../architecture/design/15-non-functional-requirements.md#복구)
- [design/07-development-patterns.md — 이슈 #2](../../architecture/design/07-development-patterns.md#이슈-2--축소-판정의-위치)

## 파일 책임

- `src/claude_pool/pool.py`:
  - 마지막 요청 종료 시각을 비공개 필드로 두고 `release` 경로에서 `time.monotonic()`으로 갱신한다. 초기값은 풀 기동 시각이다.
  - `_scale_down_loop`의 종료 대상 계산을 확장한다. 기준 시간이 `0`보다 크고, 배포된 워커가 없으며(`_total == len(self._idle)`), 마지막 종료 이후 경과가 기준을 넘으면 idle 워커를 전부 종료한다. 그 밖에는 기존 계산(`min_workers` 초과분 중 `idle_timeout_sec` 경과분)을 유지한다.
  - 판정은 기존 조건 변수(`self._cond`) 안에서 한다. 새 태스크·새 타이머를 만들지 않는다.
  - 워커별 `kill()` 후 `_total` 감소는 기존 방식을 유지한다(중단되어도 카운터가 어긋나지 않게).
  - 공개 API(`acquire`·`release`·`stats`)의 시그니처와 `stats()` 키를 바꾸지 않는다.
- `tests/test_pool.py`: 0까지 축소, 처리 중 비축소, 기준 시간 `0`일 때 기존 동작 유지, 축소 후 재획득 시 온디맨드 스폰과 `min_workers` 복구를 확인한다. 대기 시간을 줄이려면 워커의 `became_idle_at`과 풀의 마지막 종료 시각을 직접 조작한다(기존 테스트가 쓰는 방식).

## 완료 기준

- 구현: 위 판정과 축소. 기존 축소·보충 동작이 회귀하지 않는다.
- 검증: RED → GREEN, `pytest tests/test_pool.py`.
- 담당 AC: AC-001, AC-003, AC-004, AC-006, AC-008(풀 수준).

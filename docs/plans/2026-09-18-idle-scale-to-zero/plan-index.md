---
status: planned
spec: docs/spec/2026-09-18-spec-idle-scale-to-zero/2026-09-18-spec-idle-scale-to-zero.md
spec-revision: 1
acceptance-evidence: ./acceptance-evidence.md
---

# 유휴 시 워커를 0까지 줄이기 — 실행 계획

- spec: [유휴 시 워커를 0까지 줄이기](../../spec/2026-09-18-spec-idle-scale-to-zero/2026-09-18-spec-idle-scale-to-zero.md) (revision 1)
- 출처: GitHub 이슈 #2
- 수용 기준 증거: [acceptance-evidence.md](acceptance-evidence.md)

## 설계 입력

채택 시점: commit `a07426c`(`docs(spec): add idle scale-to-zero spec`, branch `master`). execute-dev는 이 시점의 문서를 읽는다.

| 문서 | 관련 절 | 적용 범위 |
|---|---|---|
| [design/15-non-functional-requirements.md](../../architecture/design/15-non-functional-requirements.md) | 목표, 판정 규칙, 복구, 관측 | task-001(설정), task-002(판정·축소), task-003(통합 확인) |
| [design/07-development-patterns.md](../../architecture/design/07-development-patterns.md) | 이슈 #2 — 축소 판정의 위치 | task-002, task-004 |
| [design/04-testing-strategy.md](../../architecture/design/04-testing-strategy.md) | 이슈 #2 — 유휴 축소 검증 | task-001~task-006 |
| [design/05-coding-conventions.md](../../architecture/design/05-coding-conventions.md) | 이슈 #2 — 적용할 규칙 | 코드 변경 Task 전체 |
| [design/01-project-structure.md](../../architecture/design/01-project-structure.md) | 이슈 #2 — 예정 경로 | File Task Map의 근거 |
| [design/00-overview.md](../../architecture/design/00-overview.md), [design/02-external-dependencies.md](../../architecture/design/02-external-dependencies.md) | 이슈 #2 절 | 참고(새 의존성 없음) |

변경 없는 주제의 현재 구조는 [as-built](../../architecture/architecture.md)와 코드로 확인한다. 이슈 #1 구현은 `feat/2026-09-17-structured-failure-classification` 브랜치에 있고 `master`에는 반영되지 않았다. 이 계획은 `master` 코드를 기준으로 하며 분류 로직을 건드리지 않는다.

## Task

| Task | 목표 | 의존성 | 상태 |
|---|---|---|---|
| [task-001](task-001-idle-scale-to-zero-config.md) | 유휴 축소 기준 시간 설정을 `PoolConfig`에 추가한다 | 없음 | pending |
| [task-002](task-002-pool-drains-to-zero-when-idle.md) | 풀이 유휴 조건에서 idle 워커를 0까지 줄이고, 처리 중에는 줄이지 않는다 | task-001 | pending |
| [task-003](task-003-http-and-jobs-behaviour.md) | 축소 후 요청 처리·재예열과 job 실행 중 비축소를 HTTP 경로에서 확인한다 | task-002 | pending |
| [task-004](task-004-ask-launcher.md) | 런처 `scripts/ask.py`를 추가한다 | task-001 | pending |
| [task-005](task-005-docs-for-idle-policy.md) | README·`CLAUDE.md`에 정책과 런처를 적는다 | task-002, task-004 | pending |
| [task-006](task-006-full-suite-and-static-checks.md) | 전체 테스트와 정적 확인 | task-001~task-005 | pending |

실행 그룹: 기능 전체를 하나의 그룹으로 본다(task-001~task-006).

## File Task Map

| 경로 | 변경 종류 | 담당 Task |
|---|---|---|
| `src/claude_pool/config.py` | 수정 | [task-001](task-001-idle-scale-to-zero-config.md) |
| `tests/test_config.py` | 수정 | [task-001](task-001-idle-scale-to-zero-config.md) |
| `src/claude_pool/pool.py` | 수정 | [task-002](task-002-pool-drains-to-zero-when-idle.md) |
| `tests/test_pool.py` | 수정 | [task-002](task-002-pool-drains-to-zero-when-idle.md) |
| `tests/test_integration.py` | 수정 | [task-003](task-003-http-and-jobs-behaviour.md) |
| `tests/test_jobs.py` | 수정 | [task-003](task-003-http-and-jobs-behaviour.md) |
| `scripts/ask.py` | 생성 | [task-004](task-004-ask-launcher.md) |
| `tests/test_ask_script.py` | 생성 | [task-004](task-004-ask-launcher.md) |
| `README.md` | 수정 | [task-005](task-005-docs-for-idle-policy.md) |
| `CLAUDE.md` | 수정 | [task-005](task-005-docs-for-idle-policy.md) |
| `docs/plans/2026-09-18-idle-scale-to-zero/acceptance-evidence.md` | 수정 | [task-006](task-006-full-suite-and-static-checks.md) |

전역 `~\.local\bin\claude-pool-ask.cmd`는 저장소 밖 파일이라 이 표에 넣지 않는다. 내용은 task-005가 README에 적는다.

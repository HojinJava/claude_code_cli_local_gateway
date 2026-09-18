---
status: planned
spec: docs/spec/2026-09-17-spec-structured-failure-classification/2026-09-17-spec-structured-failure-classification.md
spec-revision: 1
acceptance-evidence: ./acceptance-evidence.md
---

# 구조화된 값으로 워커 실패 분류하기 — 실행 계획

- spec: [구조화된 값으로 워커 실패 분류하기](../../spec/2026-09-17-spec-structured-failure-classification/2026-09-17-spec-structured-failure-classification.md) (revision 1)
- 출처: GitHub 이슈 #1
- 수용 기준 증거: [acceptance-evidence.md](acceptance-evidence.md)

## 설계 입력

채택 시점: commit `920a346`(`docs(spec): add structured failure classification spec`). execute-dev는 이 시점의 문서를 읽는다.

| 문서 | 관련 절 | 적용 범위 |
|---|---|---|
| [design/13-error-policy.md](../../architecture/design/13-error-policy.md) | 분류 입력, 분류 규칙, 불변조건과 검증, 미확정 사항 | task-002(입력 추출), task-003(분류·연결), task-004(주석·문서) |
| [design/07-development-patterns.md](../../architecture/design/07-development-patterns.md) | 채택 방식: 값 추출과 분류 판정의 분리 | task-002, task-003 |
| [design/04-testing-strategy.md](../../architecture/design/04-testing-strategy.md) | 가짜 CLI 확장, 수용 기준별 검증 | task-001~task-005 |
| [design/05-coding-conventions.md](../../architecture/design/05-coding-conventions.md) | 이번 변경에 적용할 규칙 | 코드 변경 Task 전체 |
| [design/01-project-structure.md](../../architecture/design/01-project-structure.md) | 이번 변경이 책임을 바꾸는 예정 경로 | File Task Map의 근거 |
| [design/00-overview.md](../../architecture/design/00-overview.md), [design/02-external-dependencies.md](../../architecture/design/02-external-dependencies.md) | 목표 흐름, 이번 변경의 의존 관계 | 참고(새 의존성 없음) |

변경 없는 주제의 현재 구조는 [as-built](../../architecture/architecture.md)와 코드로 확인한다.

## Task

| Task | 목표 | 의존성 | 상태 |
|---|---|---|---|
| [task-001](task-001-fake-cli-structured-errors.md) | 가짜 CLI가 실측 출력 모양과 구조화된 값·exit code를 낸다 | 없음 | pending |
| [task-002](task-002-worker-extracts-structured-values.md) | 워커가 결과 줄을 exit code보다 먼저 읽고 구조화된 값을 반환한다 | task-001 | pending |
| [task-003](task-003-classify-by-structured-values.md) | 분류를 구조화된 값으로 바꾸고 runner·apidocs·HTTP 테스트를 맞춘다 | task-001, task-002 | pending |
| [task-004](task-004-docs-for-structured-classification.md) | `errors.py` 머리 주석·`CLAUDE.md`·`README.md`를 새 판정에 맞춘다 | task-003 | pending |
| [task-005](task-005-full-suite-and-smoke-test.md) | 전체 테스트와 실제 CLI 스모크 1건 | task-001~task-004 | pending |

실행 그룹: 기능 전체를 하나의 그룹으로 본다(task-001~task-005).

## File Task Map

| 경로 | 변경 종류 | 담당 Task |
|---|---|---|
| `tests/fixtures/fake_claude_cli.py` | 수정 | [task-001](task-001-fake-cli-structured-errors.md) |
| `tests/fixtures/test_fake_claude_cli.py` | 수정 | [task-001](task-001-fake-cli-structured-errors.md) |
| `src/claude_pool/worker.py` | 수정 | [task-002](task-002-worker-extracts-structured-values.md) |
| `tests/test_worker.py` | 수정 | [task-002](task-002-worker-extracts-structured-values.md) |
| `src/claude_pool/errors.py` | 수정 | [task-003](task-003-classify-by-structured-values.md), [task-004](task-004-docs-for-structured-classification.md) |
| `src/claude_pool/runner.py` | 수정 | [task-003](task-003-classify-by-structured-values.md) |
| `src/claude_pool/apidocs.py` | 수정 | [task-003](task-003-classify-by-structured-values.md) |
| `tests/test_errors.py` | 수정 | [task-003](task-003-classify-by-structured-values.md) |
| `tests/test_apidocs.py` | 수정 | [task-003](task-003-classify-by-structured-values.md) |
| `tests/test_server.py` | 수정 | [task-003](task-003-classify-by-structured-values.md) |
| `tests/test_jobs.py` | 수정 | [task-003](task-003-classify-by-structured-values.md) |
| `CLAUDE.md` | 수정 | [task-004](task-004-docs-for-structured-classification.md) |
| `README.md` | 수정 | [task-004](task-004-docs-for-structured-classification.md) |
| `docs/plans/2026-09-17-structured-failure-classification/acceptance-evidence.md` | 수정 | [task-005](task-005-full-suite-and-smoke-test.md) |

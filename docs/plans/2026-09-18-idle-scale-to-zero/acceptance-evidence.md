---
spec: docs/spec/2026-09-18-spec-idle-scale-to-zero/2026-09-18-spec-idle-scale-to-zero.md
spec-revision: 2
plan: ./plan-index.md
---

# 수용 기준 증거

## Acceptance Coverage

| AC | 담당 Task | 검증 방법 | 증거 ID | 결과 |
|---|---|---|---|---|
| AC-001 | task-002 | tdd | EV-002 | pass |
| AC-002 | task-003 | tdd | EV-003 | pass |
| AC-003 | task-002, task-003 | tdd | EV-002, EV-003 | pass |
| AC-004 | task-002 | tdd | EV-002 | pass |
| AC-005 | task-003 | tdd | EV-004 | pass |
| AC-006 | task-002 | tdd | EV-002 | pass |
| AC-007 | task-001 | tdd | EV-001 | pass |
| AC-008 | task-002, task-003 | tdd | EV-002, EV-003 | pass |
| AC-009 | task-004 | tdd | EV-005 | pass |
| AC-010 | task-004 | tdd | EV-005 | pass |
| AC-011 | task-005 | static | EV-006 | pass |
| AC-012 | task-006 | static | EV-007 | pass |
| AC-013 | task-006 | baseline | EV-008 | pass |

## TDD Cycles

### EV-001
- origin: execute-dev
- acceptance: [AC-007]
- tasks: [task-001]
- method: tdd
- target: tests/test_config.py::test_idle_scale_to_zero_defaults_to_a_minute, ::test_idle_scale_to_zero_is_read_from_the_environment, ::test_idle_scale_to_zero_can_be_disabled_with_zero
- RED: `python -m pytest -q tests/test_config.py` · cwd `.` · exit 1 · `AttributeError: 'PoolConfig' object has no attribute 'idle_scale_to_zero_sec'` 3건 (기능 부재)
- GREEN: `python -m pytest -q tests/test_config.py` · cwd `.` · exit 0 · `23 passed`
- FAST: `python -m pytest -v` · cwd `.` · exit 0 · `159 passed` (그룹 경계, 커밋 전 작업공간 · 기준 커밋 `ffeaead`)
- source/test fingerprint: src/claude_pool/config.py@7ac8bbcc50ac, tests/test_config.py@4663c51681f2

### EV-002
- origin: execute-dev
- acceptance: [AC-001, AC-003, AC-004, AC-006, AC-008]
- tasks: [task-002]
- method: tdd
- target: tests/test_pool.py::test_idle_workers_drain_to_zero_once_nothing_has_used_the_pool, ::test_a_drained_pool_serves_the_next_request_and_rewarms, ::test_a_worker_that_is_out_stops_the_drain, ::test_setting_the_drain_to_zero_keeps_the_min_workers_floor
- RED: `python -m pytest -q tests/test_pool.py -k drain` · cwd `.` · exit 1 · `2 failed, 2 passed` — 유휴가 지나도 축소가 없어 `assert 2 == 0`(idle·total) (기능 부재)
- GREEN: `python -m pytest -q tests/test_pool.py` · cwd `.` · exit 0 · `18 passed`
- 비고: revision 2로 정정한 AC-003(반납 1건당 1개 보충)에 맞춰 재예열 기대값을 `total == 1`로 확정했다.
- FAST: `python -m pytest -v` · cwd `.` · exit 0 · `159 passed` (그룹 경계, 커밋 전 작업공간 · 기준 커밋 `ffeaead`)
- source/test fingerprint: src/claude_pool/pool.py@25b4a895396c, src/claude_pool/config.py@7ac8bbcc50ac, tests/test_pool.py@6c4a77edc34a

### EV-003
- origin: execute-dev
- acceptance: [AC-002, AC-003, AC-008]
- tasks: [task-003]
- method: tdd
- target: tests/test_integration.py::test_a_drained_pool_still_answers_and_reports_itself_healthy
- RED: `git stash push src/claude_pool/pool.py` 후 `python -m pytest -q tests/test_integration.py tests/test_jobs.py -k drain` · cwd `.` · exit 1 · `1 failed, 1 passed` · `assert 2 == 0`(축소 전 `/health`의 idle). 확인 후 `git stash pop`으로 복원
- GREEN: `python -m pytest -q tests/test_integration.py tests/test_jobs.py` · cwd `.` · exit 0 · `20 passed`
- FAST: `python -m pytest -v` · cwd `.` · exit 0 · `159 passed` (그룹 경계, 커밋 전 작업공간 · 기준 커밋 `ffeaead`)
- source/test fingerprint: src/claude_pool/pool.py@25b4a895396c, tests/test_integration.py@8f3b3bda8ae4

### EV-004
- origin: execute-dev
- acceptance: [AC-005]
- tasks: [task-003]
- method: regression
- target: tests/test_jobs.py::test_a_running_job_holds_off_the_idle_drain
- RED: not-observed — 축소 기능이 없던 코드에서도 통과한다(축소 자체가 없으므로). 이 테스트는 새 축소가 실행 중 job의 워커를 가져가지 못하도록 막는 회귀 방지용이다. 위 EV-003의 stash 실행에서 `1 passed`로 확인했다
- GREEN: `python -m pytest -q tests/test_integration.py tests/test_jobs.py` · cwd `.` · exit 0 · `20 passed`
- FAST: `python -m pytest -v` · cwd `.` · exit 0 · `159 passed` (그룹 경계, 커밋 전 작업공간 · 기준 커밋 `ffeaead`)
- source/test fingerprint: src/claude_pool/pool.py@25b4a895396c, tests/test_jobs.py@5bd2cbba9528

### EV-005
- origin: execute-dev
- acceptance: [AC-009, AC-010]
- tasks: [task-004]
- method: tdd
- target: tests/test_ask_script.py::test_prints_the_answer_and_exits_zero, ::test_reports_the_failure_classification_and_exits_nonzero, ::test_without_a_prompt_it_prints_usage_and_exits_two, ::test_module_documents_how_to_run_it
- RED: `python -m pytest -q tests/test_ask_script.py` · cwd `.` · exit 1 · `FileNotFoundError: ... scripts\ask.py` (런처 부재)
- GREEN: `python -m pytest -q tests/test_ask_script.py` · cwd `.` · exit 0 · `4 passed`
- 비고: 실제 데몬·실제 CLI를 띄우지 않도록 클라이언트를 stub으로 주입해 검증했다
- FAST: `python -m pytest -v` · cwd `.` · exit 0 · `159 passed` (그룹 경계, 커밋 전 작업공간 · 기준 커밋 `ffeaead`)
- source/test fingerprint: scripts/ask.py@5a580d4de58e, tests/test_ask_script.py@b5065385417e

### EV-006
- origin: execute-dev
- acceptance: [AC-011]
- tasks: [task-005]
- method: static
- target: `README.md`(유휴 축소 절, 런처 절), `CLAUDE.md`(반드시 지켜야 할 것 2항목)
- RED: N/A — 문서 변경
- GREEN: `grep -c "유휴 축소\|claude-pool-ask" README.md` · cwd `.` · 3건. `grep -n "축소의 하한\|워커가 나가 있으면" CLAUDE.md` · 2건. `git diff --check` · 정리 후 출력 없음
- FAST: `python -m pytest -v` · cwd `.` · exit 0 · `159 passed` (그룹 경계, 커밋 전 작업공간 · 기준 커밋 `ffeaead`)
- source/test fingerprint: README.md@d7ad9a4c9df9, CLAUDE.md@38b8496377ec

### EV-007
- origin: execute-dev
- acceptance: [AC-012]
- tasks: [task-006]
- method: static
- target: `tests/` 전체의 `claude_cmd` 주입과 데몬 기동 경로
- RED: N/A — 기존 규칙(테스트는 실제 CLI를 부르지 않는다)의 유지 확인
- GREEN: `grep -rn "claude_cmd=" tests/` · cwd `.` · 모든 주입이 가짜 CLI(`FAKE_CLI`), 없는 실행 파일(`MISSING_BINARY`), 또는 스폰하지 않는 검증용 값이다. `grep -rn "run_daemon\|ClaudePoolClient(" tests/` · 데몬을 띄우는 곳은 기존 `tests/test_client.py`뿐이며 가짜 CLI 설정을 쓴다. 이번에 추가한 `tests/test_ask_script.py`는 클라이언트를 stub으로 대체한다
- FAST: `python -m pytest -v` · cwd `.` · exit 0 · `159 passed` (그룹 경계, 커밋 전 작업공간 · 기준 커밋 `ffeaead`)
- source/test fingerprint: tests/test_ask_script.py@b5065385417e, tests/test_pool.py@6c4a77edc34a, tests/test_integration.py@8f3b3bda8ae4, tests/test_jobs.py@5bd2cbba9528

### EV-008
- origin: execute-dev
- acceptance: [AC-013]
- tasks: [task-006]
- method: baseline
- target: 전체 테스트 스위트
- RED: N/A — 전체 회귀 확인
- GREEN: `python -m pytest -v` · cwd `.` · exit 0 · `159 passed in 24.02s` (변경 전 기준선 `146 passed`)
- FAST: `python -m pytest -v` · cwd `.` · exit 0 · `159 passed` (그룹 경계, 커밋 전 작업공간 · 기준 커밋 `ffeaead`)
- source/test fingerprint: src/claude_pool/config.py@7ac8bbcc50ac, src/claude_pool/pool.py@25b4a895396c, scripts/ask.py@5a580d4de58e, tests/test_config.py@4663c51681f2, tests/test_pool.py@6c4a77edc34a, tests/test_integration.py@8f3b3bda8ae4, tests/test_jobs.py@5bd2cbba9528, tests/test_ask_script.py@b5065385417e, README.md@d7ad9a4c9df9, CLAUDE.md@38b8496377ec

---
description: 요청이 없는 동안 예열 워커를 0까지 줄이고, 데몬이 없을 때도 바로 쓸 수 있는 런처를 제공한다 — GitHub 이슈 #2
status: approved
revision: 2
plan: docs/plans/2026-09-18-idle-scale-to-zero/plan-index.md
origin: brain
architecture:
  - ../../architecture/design/00-overview.md
  - ../../architecture/design/01-project-structure.md
  - ../../architecture/design/02-external-dependencies.md
  - ../../architecture/design/04-testing-strategy.md
  - ../../architecture/design/05-coding-conventions.md
  - ../../architecture/design/07-development-patterns.md
  - ../../architecture/design/15-non-functional-requirements.md
  - ../../architecture/as-built/15-non-functional-requirements.md
  - ../../architecture/as-built/10-data-flow.md
---

# 유휴 시 워커를 0까지 줄이기

- 출처: [GitHub 이슈 #2](https://github.com/HojinJava/claude_code_cli_local_gateway/issues/2)
- 관련 spec: [워커 풀과 워커 수명주기](../2026-09-17-spec-worker-pool/2026-09-17-spec-worker-pool.md)(`origin: migration`)가 현재 축소 정책을 역작성해 두었다. 이 spec이 그 정책의 하한을 바꾼다.

## 배경과 해결할 문제

풀은 `min_workers`(기본 4) 아래로 줄지 않는다. 축소 루프는 `min_workers`를 넘는 idle 워커만 죽인다(`pool.py:205`). 그래서 요청이 하루 종일 없어도 워커 4개가 대기한다. `~/.claude/rules/common/local-llm-gateway.md`에 기록된 실측값으로 idle 워커 1개당 메모리 약 236MB(Working Set)와 CPU 코어 약 2.5%를 쓰므로, 기본값에서 상시 약 1.5GB와 0.1코어가 나간다.

2026-09-18 확인: 2026-09-17 08:18에 뜬 데몬이 하루가 지나도록 워커 4개를 붙든 채 떠 있었고, 그 사이 요청은 거의 없었다. 오래 떠 있는 프로세스는 editable 설치의 옛 코드를 계속 돌리고, `claude` 실행 파일 교체도 방해한다.

## 확정한 결정 (2026-09-18 사용자 합의)

- **데몬은 종료하지 않는다.** 유휴 시 워커만 0까지 줄인다. 포트가 계속 열려 있어 `curl` 사용자와 다른 호출자에게 영향이 없다.
- **기본 활성이고 기준은 60초**다. 예열 이점보다 방치 비용을 줄이는 쪽을 택했다.
- **런처를 추가한다.** 데몬이 아예 없을 때(재부팅 직후 등)를 위해, 저장소의 `scripts/ask.py`와 그것을 부르는 전역 `.cmd`를 둔다.
- **재예열은 점진적이다** (revision 2, 2026-09-18 사용자 확인). 구현 중 확인한 사실: 현재 `release`는 반납 1건당 워커를 1개만 보충한다(`pool.py:190-198`). revision 1의 AC-003은 이 동작을 "`min_workers`까지 복구"로 잘못 적었다. 드문 호출 하나가 워커 여러 개를 띄우고 60초 뒤 다시 죽이는 낭비를 피하려고 현재 동작을 계약으로 확정했다.

## 범위

- 유휴가 지속되면 idle 워커를 **`min_workers` 아래, 0까지** 줄인다.
- 유휴 판정 기준 시간을 환경변수로 설정한다. `0`이면 비활성이며 지금 동작(하한 `min_workers` 유지)이 된다.
- 처리 중인 요청이나 job이 있으면 줄이지 않는다.
- 요청이 다시 오면 기존 경로 그대로 온디맨드 스폰하고, 처리 뒤 기존 `release` 동작대로 1개씩 보충한다.
- `scripts/ask.py`: 데몬이 없으면 띄우고 프롬프트를 보내 결과를 표준 출력으로 낸다. 실패는 `kind`·`retryable`을 함께 알리고 종료 코드를 0이 아닌 값으로 둔다.
- README·`CLAUDE.md`에 새 정책과 런처 사용법을 적는다.

## 비범위

- 데몬 자체의 유휴 종료. 이번에는 하지 않는다.
- `/health`·`GET /`·OpenAPI에 새 필드 추가. 축소 상태는 기존 `idle`·`total`·`busy`로 드러난다.
- HTTP 계약 변경(`kind` 6종, 상태코드, 응답 본문 키).
- 워커 1회용 정책, stream-json 프로토콜, `runner.execute` 단일 경로, 자동 재시도 없음 정책.
- 전역 `.cmd` 파일의 버전 관리. 저장소 밖(`~/.local/bin`)에 두고 README에 내용만 적는다.
- `min_workers`·`max_workers` 검증 추가(이슈 #1 spec의 열린 항목으로 남아 있다).

## 동작 규칙

축소 루프가 도는 시점마다 다음을 본다.

| 조건 | 결과 |
|---|---|
| 유휴 기준 시간이 `0` | 기존 동작. idle 워커 중 `min_workers` 초과분만, 그것도 `idle_timeout_sec`를 넘긴 것만 종료 |
| 마지막 요청 종료 이후 경과 ≤ 기준 시간 | 기존 동작과 같다 |
| 마지막 요청 종료 이후 경과 > 기준 시간이고, 진행 중 요청이 없음 | idle 워커를 **전부** 종료한다(`min_workers` 무시) |
| 진행 중 요청이 하나라도 있음 | 축소하지 않는다 |

- "진행 중 요청"은 워커를 쥐고 있는 모든 작업을 뜻한다. `/generate`와 `/jobs`가 같은 `runner.execute`를 쓰므로 실행 중 job도 여기에 포함된다.
- "마지막 요청 종료 시각"은 풀이 워커를 반납받은 시점으로 정한다. 세부 위치는 design에서 정한다.
- 축소 뒤 빈 풀은 비정상이 아니다. `/health`의 `healthy`는 `idle_alive == idle`이라 빈 풀에서 참이 된다(현재 동작 유지).

## 사용자 관찰 동작과 수용 기준

- **AC-001** 기준 시간이 지나도록 요청이 없으면 `/health`의 `idle`과 `total`이 `0`이 된다. `min_workers`가 0보다 커도 그렇다.
- **AC-002** 워커가 0인 상태에서 `POST /generate`를 보내면 정상 응답(200)을 받는다. 데몬은 그때 워커를 띄운다.
- **AC-003** 요청을 처리한 뒤에는 예열이 다시 시작된다. 반납 1건당 워커 1개를 보충하므로(현재 `release` 동작), 요청이 이어지면 `min_workers`까지 회복된다.
- **AC-004** 처리 중인 요청이 있는 동안에는 축소가 일어나지 않는다. 그 요청은 끊기지 않고 정상 응답을 받는다.
- **AC-005** 실행 중인 `/jobs` job이 있는 동안에도 축소가 일어나지 않고, job은 정상 종료 상태가 된다.
- **AC-006** 기준 시간을 `0`으로 두면 지금 동작 그대로다. 유휴가 아무리 길어도 `idle`은 `min_workers` 아래로 내려가지 않는다.
- **AC-007** 기준 시간은 환경변수로 설정하며 기본값은 60초다. 다른 설정과 같은 방식으로 `PoolConfig`에서 읽는다.
- **AC-008** 축소가 일어난 뒤에도 `/health`의 `healthy`는 `true`이고 `last_error`는 축소 때문에 채워지지 않는다.
- **AC-009** `python scripts/ask.py "프롬프트"`는 데몬이 없으면 띄운 뒤 응답 텍스트를 표준 출력에 찍고 종료 코드 0으로 끝난다.
- **AC-010** 요청이 실패하면 `scripts/ask.py`는 `kind`와 `retryable`을 사람이 읽을 수 있게 표준 오류에 적고 0이 아닌 종료 코드로 끝난다.
- **AC-011** README에 유휴 축소 정책(기준 시간·기본값·비활성 방법), 축소 시 관찰되는 `/health` 값, 런처 사용법과 전역 `.cmd` 내용이 적혀 있다. `CLAUDE.md`에는 축소 하한이 `min_workers`가 아니라는 사실과 처리 중에는 줄이지 않는다는 규칙이 적혀 있다.
- **AC-012** 테스트는 실제 `claude` CLI를 호출하지 않는다. 가짜 CLI로만 검증한다.
- **AC-013** `pytest -v` 전체가 통과한다.

## 기존 구조와 바뀌는 책임

| 파일 | 현재 책임 | 바뀌는 책임 |
|---|---|---|
| `src/claude_pool/config.py` | 설정 13개 로드·검증 | 유휴 축소 기준 시간 설정 추가 |
| `src/claude_pool/pool.py` | 축소 루프가 `min_workers` 초과분만 종료 | 마지막 반납 시각을 기록하고, 유휴가 기준을 넘고 진행 중 작업이 없으면 idle 전부 종료 |
| `scripts/ask.py` | 없음 | 새 런처. 데몬 자동 기동 후 프롬프트 1건 전송, 결과·실패 출력 |
| `tests/test_pool.py`, `tests/test_integration.py` | 축소·오토스케일 검증 | 0까지 축소, 처리 중 비축소, 재예열 검증 추가 |
| `README.md`, `CLAUDE.md` | 예열 정책 설명 | 유휴 축소 정책·런처 안내 |

## 아키텍처 참조

- [design/15-non-functional-requirements.md](../../architecture/design/15-non-functional-requirements.md) — 유휴 축소 규칙·설정·제한값(설계 본문)
- [design/07-development-patterns.md](../../architecture/design/07-development-patterns.md) — 축소 판정을 풀 안에 두는 작성 규칙
- [design/04-testing-strategy.md](../../architecture/design/04-testing-strategy.md) — AC별 검증 방법
- [design/00-overview.md](../../architecture/design/00-overview.md), [design/01-project-structure.md](../../architecture/design/01-project-structure.md), [design/02-external-dependencies.md](../../architecture/design/02-external-dependencies.md), [design/05-coding-conventions.md](../../architecture/design/05-coding-conventions.md) — 필수 코어
- 현재 구조: [as-built/15-non-functional-requirements.md](../../architecture/as-built/15-non-functional-requirements.md), [as-built/10-data-flow.md](../../architecture/as-built/10-data-flow.md)

## 위험·테스트·문서 영향

- **예열 이점 축소:** 60초 넘게 쉬었다가 보내는 첫 요청은 CLI 부팅 비용(약 1초)을 낸다. 이 프로젝트의 목적과 상충하는 면이 있으나, 사용자가 방치 비용을 더 무겁게 보고 선택했다. 기준 시간을 늘리거나 `0`으로 끄면 되돌릴 수 있다.
- **경쟁 조건:** 축소를 시작한 직후 요청이 올 수 있다. 축소는 idle 워커만 대상으로 하고 배포된 워커는 건드리지 않으므로 진행 중 요청이 끊기지는 않는다. 다만 축소와 획득이 같은 락 안에서 판정되어야 한다.
- **잦은 스폰:** 60초 간격으로 드문드문 호출하면 매번 새로 띄운다. 기준 시간 조정으로 대응한다.
- **테스트:** 짧은 기준 시간으로 가짜 CLI를 써서 검증한다. 실제 CLI·실제 데몬은 쓰지 않는다.
- **문서:** as-built 문서는 구현 뒤 sync가 갱신한다.

## 열린 질문과 확정 결정

확정 결정은 위 "확정한 결정" 절에 있다. 추가로 이번 spec에서 정한 것은 다음과 같다.

- `/health`에 새 필드를 넣지 않는다. 축소 여부는 기존 값으로 읽을 수 있다.
- 전역 `.cmd`는 저장소 밖에 두고 README에 내용을 적는다.

열린 질문: 없음.

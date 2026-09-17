---
description: claude-pool 아키텍처 문서 공통 색인 — 사후(as-built) 실측 문서 16종의 역할·적용 영역·근거 spec·실측 기준과 미작성 프로파일 문서 사유
tags: [architecture]
profiles: [web-backend]
---

# claude-pool 아키텍처 색인

## 역할

- 이 저장소의 아키텍처 문서는 **사후 아키텍처(`as-built/`)만 있다.** 사전 설계 문서(`design/`)는 존재하지 않는다. 따라서 설계의 미반영·부분 반영·반영 완료를 대조할 사전 짝이 없으며, 아래 문서는 모두 기존 코드 실측으로 작성한 현재 구조 기록이다.
- 작성 경위: migration 최초 전체 온보딩. 실측 기준 commit `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`(branch `master`).
- 적용 프로파일: `web-backend` — aiohttp 서버 진입점(`web.TCPSite`)과 라우트·미들웨어·핸들러가 있는 로컬 HTTP 게이트웨이 데몬. 코어 `00`~`07`과 프로파일 문서 `08`~`15`를 둔다.
- 실측 문서화는 기능의 정상 동작이나 보안 통제 효과를 검증한 결과가 아니다.
- 기능 수정 전 파일 탐색은 [01-project-structure의 File Responsibility Map](as-built/01-project-structure.md#file-responsibility-map)에서 시작한다.

## 근거 spec

| spec | 다루는 영역 |
|---|---|
| [워커 풀과 워커 수명주기](../spec/2026-09-17-spec-worker-pool/2026-09-17-spec-worker-pool.md) | `worker.py`, `pool.py`, `winjob.py`, 가짜 CLI |
| [HTTP 게이트웨이 데몬 API](../spec/2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md) | `server.py`, `runner.py`, `jobs.py`, `errors.py`, `apidocs.py`, `config.py`, `daemon.py` |
| [클라이언트와 운영·조사 스크립트](../spec/2026-09-17-spec-client-ops/2026-09-17-spec-client-ops.md) | `client.py`, `scripts/*.py` |

spec은 참고 연결이며 as-built 문서의 구현 사실 근거는 코드다.

## 사후 아키텍처 문서

설계 반영 상태 열: 사전 설계 문서가 없으므로 모든 행이 `해당 없음(design 없음)`이다.

| 번호 | 주제 | 문서 | 역할 | 적용 영역 | 근거 spec | 실측 기준 | 설계 반영 상태 |
|---|---|---|---|---|---|---|---|
| 00 | overview | [00-overview.md](as-built/00-overview.md) | 실제 진입점·실행 경로, 요청 1건 런타임 플로우 | 전체 | [worker-pool](../spec/2026-09-17-spec-worker-pool/2026-09-17-spec-worker-pool.md), [gateway-api](../spec/2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md), [client-ops](../spec/2026-09-17-spec-client-ops/2026-09-17-spec-client-ops.md) | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 01 | project-structure | [01-project-structure.md](as-built/01-project-structure.md) | 실제 폴더·진입점, File Responsibility Map(34개 파일) | 저장소 전체(사용자 문서 제외) | 3개 spec 전부 | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 02 | external-dependencies | [02-external-dependencies.md](as-built/02-external-dependencies.md) | 매니페스트 패키지·버전 제약, lockfile 부재, 외부 실행 의존 | `pyproject.toml`, import, CLI·OS 도구 | 3개 spec 전부 | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 03 | configuration | [03-configuration.md](as-built/03-configuration.md) | 환경변수·폴백·검증·주입, pytest·빌드 설정 | `config.py`, `pyproject.toml` | [gateway-api](../spec/2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md) | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 04 | testing-strategy | [04-testing-strategy.md](as-built/04-testing-strategy.md) | 테스트 구성·가짜 CLI 경계·실행 방법 | `tests/`, 수동 스크립트 경계 | 3개 spec 전부 | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 05 | coding-conventions | [05-coding-conventions.md](as-built/05-coding-conventions.md) | 도구 설정 부재와 관찰 관례 | 전체 Python 파일 | — | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 06 | build-and-run | [06-build-and-run.md](as-built/06-build-and-run.md) | 확인된 설치·실행·종료·복구 절차와 출처 | 데몬·클라이언트·`daemon_ctl` | [gateway-api](../spec/2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md), [client-ops](../spec/2026-09-17-spec-client-ops/2026-09-17-spec-client-ops.md) | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 07 | development-patterns | [07-development-patterns.md](as-built/07-development-patterns.md) | 2회 이상 반복된 구현 형태·확장 경로·이탈 지점 | `src/`, `tests/` | 3개 spec 전부 | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 08 | system-context | [08-system-context.md](as-built/08-system-context.md) | 호출자·`claude` CLI·Job Object·파일시스템·OS 도구 관계 | 데몬 경계, 클라이언트 | [worker-pool](../spec/2026-09-17-spec-worker-pool/2026-09-17-spec-worker-pool.md), [client-ops](../spec/2026-09-17-spec-client-ops/2026-09-17-spec-client-ops.md) | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 09 | component-architecture | [09-component-architecture.md](as-built/09-component-architecture.md) | 모듈 구성·의존 방향·조립 위치 | `src/claude_pool/` | [gateway-api](../spec/2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md), [worker-pool](../spec/2026-09-17-spec-worker-pool/2026-09-17-spec-worker-pool.md) | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 10 | data-flow | [10-data-flow.md](as-built/10-data-flow.md) | 미들웨어 순서, 동기·백그라운드 경로, 워커 획득·반납, 기동·종료 순서 | `server.py`→`runner.py`→`pool.py`/`worker.py`, `jobs.py`, `daemon.py` | [gateway-api](../spec/2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md), [worker-pool](../spec/2026-09-17-spec-worker-pool/2026-09-17-spec-worker-pool.md) | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 11 | api-contract | [11-api-contract.md](as-built/11-api-contract.md) | 라우트·JSON 키·상태코드·헤더, 자기 문서 생성과 `/docs` HTML 이스케이프 | `server.py`, `jobs.py`, `apidocs.py` | [gateway-api](../spec/2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md) | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 12 | security-auth | [12-security-auth.md](as-built/12-security-auth.md) | 인증 부재, loopback·Host 가드, job ID, 워커 플래그 적용 지점 | `config.py`, `server.py`, `jobs.py`, `worker.py` | [gateway-api](../spec/2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md), [worker-pool](../spec/2026-09-17-spec-worker-pool/2026-09-17-spec-worker-pool.md) | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 13 | error-policy | [13-error-policy.md](as-built/13-error-policy.md) | 예외 처리 지점, kind↔HTTP 매핑, 응답 구현, `FAILURE_KINDS` 관계 | `errors.py`, `runner.py`, `server.py`, `jobs.py`, `client.py` | [gateway-api](../spec/2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md), [client-ops](../spec/2026-09-17-spec-client-ops/2026-09-17-spec-client-ops.md) | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 14 | observability-logging | [14-observability-logging.md](as-built/14-observability-logging.md) | `/health` 구성, 오류 상태 기록, 로깅 미사용 | `pool.py`, `server.py`, `runner.py` | [worker-pool](../spec/2026-09-17-spec-worker-pool/2026-09-17-spec-worker-pool.md), [gateway-api](../spec/2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md) | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |
| 15 | non-functional-requirements | [15-non-functional-requirements.md](as-built/15-non-functional-requirements.md) | 워커·타임아웃·job 보관 제한값, 측정 근거 확인 상태 | `config.py`, `pool.py`, `jobs.py`, `client.py`, `daemon_ctl.py` | 3개 spec 전부 | `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` | 해당 없음(design 없음) |

## 미작성 프로파일 문서

`web-backend` 프로파일의 조건부·해당 주제 중 작성하지 않은 문서와 사유. 조건 미해당 문서의 생략은 누락이 아니다.

| slug | 사유 |
|---|---|
| `database` | DB·ORM·마이그레이션이 없다. 상태는 프로세스 메모리(`WorkerPool`, `JobStore`)에만 있고 디스크에는 pid 파일만 쓴다 |
| `view-architecture` | 템플릿 엔진 기반 서버 렌더링 뷰가 없다. 자체 문서 HTML 1개(`GET /docs`, `apidocs.render_html`)는 [11-api-contract](as-built/11-api-contract.md#자기-문서)에서 다룬다 |
| `view-page-catalog` | 서버 렌더링 뷰 계층이 없고 단독 진입 HTML 페이지는 1개로 15개 임계치 미만이다 |

## 실측 반영 범위

- 반영 범위: 기준 commit `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`의 추적 파일 중 `README.md`·`CLAUDE.md`를 제외한 34개 파일 전체.
- 이후 코드 변경분은 이 색인과 as-built 문서에 반영되지 않았다. 최신성은 각 문서의 `실측 근거` 절의 기준 commit으로 판단한다.

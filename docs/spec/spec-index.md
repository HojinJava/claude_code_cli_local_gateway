---
description: claude-pool spec 색인 — 기존 코드에서 역추론한 migration spec 3개와 분석 범위·검증 기록
tags: [spec]
---

# Spec 색인

| spec | 상태 | revision | origin | plan | 다루는 영역 |
|---|---|---|---|---|---|
| [워커 풀과 워커 수명주기](2026-09-17-spec-worker-pool/2026-09-17-spec-worker-pool.md) | implemented | 1 | migration | 없음 | `worker.py`, `pool.py`, `winjob.py` — 예열 워커 스폰, 1회용 정책, 오토스케일, 종료 드레인, `/health` stats |
| [HTTP 게이트웨이 데몬 API](2026-09-17-spec-gateway-api/2026-09-17-spec-gateway-api.md) | implemented | 1 | migration | 없음 | `server.py`, `runner.py`, `jobs.py`, `errors.py`, `apidocs.py`, `config.py`, `daemon.py` — 라우트 계약, Host 가드, 실패 분류, 백그라운드 job, 자기 문서, 데몬 조립 |
| [클라이언트와 운영·조사 스크립트](2026-09-17-spec-client-ops/2026-09-17-spec-client-ops.md) | implemented | 1 | migration | 없음 | `client.py`, `scripts/daemon_ctl.py`, `scripts/bench_cold_vs_warm.py`, `scripts/investigate_stream_json_timeout.py` |
| [구조화된 값으로 워커 실패 분류하기](2026-09-17-spec-structured-failure-classification/2026-09-17-spec-structured-failure-classification.md) | approved | 1 | brain | [plan](../plans/2026-09-17-structured-failure-classification/plan-index.md) | 이슈 #1 — `result.api_error_status`·`assistant.error`로 `rate_limited`·`not_authenticated`·`worker_failed` 분류, 문구 정규식 제거. 선행: gateway-api spec |

migration spec 3개는 plan이 없으며, 변경하려면 `brain`에서 요구를 다시 구체화해야 make-plans의 계획 대상이 된다. 관련 구조 문서는 [architecture.md](../architecture/architecture.md)에서 찾는다.

## Migration 검증 기록

### 분석 기준

- 분석 커밋 앵커: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42` (branch `master`, 시작 시 작업공간 clean)
- 분석 영역: 저장소 전체 최초 온보딩
- 실행일: 2026-09-17

### 분석 범위와 누락 확인

- 실제 소스 집합: `git ls-tree -r --name-only -z 821f6e9c83edc2b2f11434cc00e52c106f6f7b42`의 36개 경로에서 의도적 제외 2개를 뺀 34개(`.gitignore`, `pyproject.toml`, `scripts/*.py` 3개, `src/claude_pool/*.py` 12개, `tests/**/*.py` 17개).
- 의도적 제외: `README.md`, `CLAUDE.md` — 사용자 문서이며 manifest·빌드가 제품 입력으로 참조하지 않는다(`pyproject.toml`에 `readme` 키 없음).
- 파일 책임표 대조: [01-project-structure의 File Responsibility Map](../architecture/as-built/01-project-structure.md#file-responsibility-map) 34행의 경로 집합과 실제 소스 집합을 스크립트로 비교했다. 커버 34, 누락 0, 초과 0.
- spec 역작성 범위: 34개 중 기능·요구를 담은 파일은 세 spec 중 하나 이상이 다룬다. 이름이 spec 본문에 나오지 않는 파일은 `.gitignore`, 빈 `src/claude_pool/__init__.py`, 빈 `tests/__init__.py`, 빈 `tests/fixtures/__init__.py` 4개다. 모두 기능·요구가 없는 설정·패키지 표지 파일이라 spec 역작성 누락으로 보지 않으며, 책임은 파일 책임표에 기록돼 있다. 파일 책임표의 커버는 구조 조사 범위이고 spec 작성·동작 검증 완료를 뜻하지 않는다.

### §2.5 검증 범위

1. **교차 대조(문서만):** spec 3개, 색인, as-built 16개를 fact sheet 기반 18개 축(환경변수·폴백, Host 가드 범위, 실패 분류·Retry-After, job 직렬화, 라우트·상태코드, 워커 argv·Job Object, 기동·종료 순서, 제한값, 의존성, 테스트 구성, 클라이언트 기본값, `/health` 키 등)으로 대조했다. 모순 3건을 찾아 정정했다: `daemon_ctl stop`의 종료 대상 조건(06·12 문서가 pid 파일 폴백 경로 누락), `_finish` 소속 클래스(07 문서의 `Job._finish` → `JobStore._finish`), `client.py` import 목록(`from __future__` 누락).
2. **표적 코드 대조:**
   - spec: 수용 기준 124개(worker-pool 40, gateway-api 48, client-ops 36)의 근거 인용을 전수 대조했다. 본문 값(숫자·키·상태코드·환경변수·플래그·메시지) 약 350건을 전수 대조했다. 커밋 해시 13개에 걸친 이력 주장 약 40건을 `git show`로 확인했다. 정정 8건: 커밋 순서 표현, AC-029 근거 테스트 교체, 저장소 밖 fact sheet 인용 6곳을 코드 인용으로 교체, 삭제 문서의 복원 커밋, `timeout_sec` falsy 조건, 주석 줄 번호, `/docs` 이스케이프 범위(숫자 값은 그대로 삽입), AC-027 취소 대기 범위.
   - as-built: 인용 약 700건, `11`·`03`·`13`·`02`·`15`의 표 값과 책임표 34행 전부, 테스트 함수 수 115, mermaid 흐름 5개, 패턴 문서의 반복 위치를 대조했다. 교차 대조 지적분을 포함해 정정한 내용: `runner.execute`에서 기록과 반납의 실행 순서(00·10·01), `JobStore._finish`, 테스트의 `WorkerPool` 직접 생성 범위, docstring·print 서술 범위, 조사 스크립트 docstring, `daemon_ctl stop` 폴백, 테스트 종료 방식과 `claude_cmd` 주입 표현.
   - 이력 주장 중 확인 실패로 `추정:` 강등한 것은 없다. 코드·커밋으로 확정 가능했던 추정 7건은 `확인된 사실:`로 바꿨다.
3. **기계 검사:** 모든 docs의 `path:line` 인용 1,087건이 앵커 tree의 파일 길이 안에 있다. 상대 링크·앵커 깨짐 0. spec frontmatter(`description`·`status: implemented`·`origin: migration`), as-built frontmatter(`tags`·`status: as-built`), 색인 frontmatter(`tags`·`description`·`profiles`)를 확인했다. `docs/qa/**`·`docs/architecture/design/`을 만들지 않았고 source·test·설정 파일 변경이 없다.
4. **미대조 범위:** aiohttp·stdlib 라이브러리 동작(`Host` 헤더가 없을 때의 `request.host`, 본문 크기 기본 한도, 연결 끊김 시 핸들러 취소, `ipaddress`의 IPv4-mapped 처리)은 저장소 코드로 확정할 수 없어 문서에 `미확인`으로 남겼다. `05`·`08`·`09`·`12`·`14` 문서의 설명 문장은 인용 전수 대조 외에 표본으로 확인했다. 테스트 통과 여부·런타임 동작·성능 수치는 확인하지 않았다(migration은 동작을 판정하지 않는다).
5. **미해결 모순:** 없음.

### §2.6 추정 확인

- 사용자에게 물은 3건의 답을 `사용자 확인(2026-09-17 migration):` 출처로 spec에 기록했다. 세 답 모두 코드 사실과 모순되지 않는다.
  - 종결 job에 대한 `DELETE`는 현재처럼 반환만 하고 reap에 맡기는 것이 의도한 계약이다.
  - 비 Windows(Linux/macOS)도 공식 지원 대상이다.
  - 설정값·`timeout_sec` 범위 검증 부재는 의도한 선택이 아니다.
- 나머지 구현 세부 의도 추정 12건은 사용자 선택에 따라 각 spec의 열린 질문에 `미답 — 사람이 나중에 spec 직접 갱신, 자동 반영 없음`으로 남겼다.

### Architecture Gate

- 판정: required — 최초 온보딩이며 architecture 색인·사후 문서·파일 책임표가 없었다.
- 범위·실측: 저장소 전체, `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`, 소스 34개 파일. 프로파일 `web-backend`.
- 결과: PASS. 사용자 승인 범위(코어 00~07, 프로파일 08~15, 색인, `docs/product.md`, 루트 안내서, master 문서 체크포인트 1개)대로 처리했다. 루트 안내서: 최초 문서화이고 `AGENTS.md`·AGENTS 참조가 없어 발동했다. 번들 `update-root-guides.mjs`로 `AGENTS.md`를 생성하고 기존 `CLAUDE.md` 끝에 `@AGENTS.md` 참조만 추가했으며(기존 49줄 보존), `--check` 멱등 검증을 통과했다.

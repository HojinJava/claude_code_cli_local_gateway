---
description: claude-pool 사전 프로젝트 구조 — 이슈 #1 변경의 예정 수정 경로(기존 구조 유지)
tags: [architecture]
status: design
---

# 01. 프로젝트 구조 (design)

- 근거 spec: [구조화된 값으로 워커 실패 분류하기](../../spec/2026-09-17-spec-structured-failure-classification/2026-09-17-spec-structured-failure-classification.md)
- **예정 구조**: 디렉터리·모듈 구성은 현재 구조를 그대로 유지한다(기본값 적용: 기존 배치 우선). 현재 구조와 파일 책임은 [as-built/01-project-structure](../as-built/01-project-structure.md#file-responsibility-map)가 정본이다.

## 이번 변경이 책임을 바꾸는 예정 경로

새 파일·새 모듈은 만들지 않는다.

| 경로 | 예정 책임 변화 |
|---|---|
| `src/claude_pool/worker.py` | stdout에서 결과 줄을 exit code보다 먼저 찾고, `api_error_status`·최상위 `assistant.error`를 추가로 반환 |
| `src/claude_pool/errors.py` | 문구 정규식 대신 구조화된 값 분류 함수와 상수 |
| `src/claude_pool/runner.py` | `WorkerError` → `worker_failed`, `is_error` 결과 → 구조화된 값 분류 호출 |
| `src/claude_pool/apidocs.py` | `FAILURE_KINDS` 의미 문구 |
| `tests/fixtures/fake_claude_cli.py` | 실측 출력 모양과 구조화된 값·exit code 옵션 |
| `tests/` 관련 파일 | 새 판정 기대값 |
| `CLAUDE.md`, `README.md` | 새 판정 설명 |

배치 원칙: 구현은 `src/claude_pool/`, 검증은 `tests/`, 가짜 CLI는 `tests/fixtures/`에 둔다(기존 배치).

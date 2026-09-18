---
description: claude-pool 사전 외부 의존성 — 이슈 #1 변경은 새 패키지 의존성을 도입하지 않는다
tags: [architecture]
status: design
---

# 02. 외부 의존성 (design)

- 근거 spec: [구조화된 값으로 워커 실패 분류하기](../../spec/2026-09-17-spec-structured-failure-classification/2026-09-17-spec-structured-failure-classification.md)
- 기본값 적용: 추가 외부 의존성을 도입하지 않고 기존 의존성과 표준 라이브러리만 쓴다. 현재 설치 패키지는 [as-built/02-external-dependencies](../as-built/02-external-dependencies.md)가 정본이다.

## 이번 변경의 의존 관계

- 파이썬 패키지: 추가·변경 없음. `errors.py`는 정규식(`re`)을 더 쓰지 않게 된다.
- 외부 실행 의존: `claude` CLI의 stream-json 출력 필드에 새로 의존한다.
  - `result.api_error_status`(성공 시 `null`), 최상위 `assistant` 줄의 `error`(CLI SDK 스키마 enum).
  - 실측 버전은 Claude Code 2.1.274다. 인증 실패 모양만 실측했고 429·529 출력은 미실측이다.
  - 필드가 없거나 값이 바뀌면 분류는 `worker_failed`로 떨어진다(추정 kind를 만들지 않는다).

## 이슈 #2 — 의존 관계

- 근거 spec: [유휴 시 워커를 0까지 줄이기](../../spec/2026-09-18-spec-idle-scale-to-zero/2026-09-18-spec-idle-scale-to-zero.md)
- 새 패키지를 도입하지 않는다. 축소 판정은 표준 라이브러리(`asyncio`, `time`)만 쓴다.
- 런처 `scripts/ask.py`는 저장소 안의 `claude_pool.client`만 쓴다. 이 클라이언트는 stdlib만 의존하므로 런처에도 새 의존성이 없다.

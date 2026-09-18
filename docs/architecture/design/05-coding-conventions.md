---
description: claude-pool 사전 코딩 규칙 — 이슈 #1 변경에 적용할 기존 관례
tags: [architecture]
status: design
---

# 05. 코딩 규칙 (design)

- 근거 spec: [구조화된 값으로 워커 실패 분류하기](../../spec/2026-09-17-spec-structured-failure-classification/2026-09-17-spec-structured-failure-classification.md)
- 기본값 적용: 기존 관례를 유지한다. 린터·포매터 설정은 없으며 새 도구를 도입하지 않는다. 현재 관례는 [as-built/05-coding-conventions](../as-built/05-coding-conventions.md)가 정본이다.

## 이번 변경에 적용할 규칙

- `src/` 모듈의 첫 import는 `from __future__ import annotations`다(기존 관례).
- 판정에 쓰는 숫자·문자열 집합은 `UPPER_SNAKE_CASE` 이름의 `frozenset` 상수로 둔다.
- 설계 의도는 "왜"를 설명하는 주석으로 남긴다(기존 주석 스타일). 미실측 사실(429·529 출력)은 주석에 명시한다.
- UTF-8을 쓰고 줄바꿈은 기존 파일 형식을 따른다.

## 이슈 #2 — 적용할 규칙

- 근거 spec: [유휴 시 워커를 0까지 줄이기](../../spec/2026-09-18-spec-idle-scale-to-zero/2026-09-18-spec-idle-scale-to-zero.md)
- 기존 관례를 그대로 따른다. 새 설정 이름은 `UPPER_SNAKE_CASE` 환경변수와 `snake_case` 필드로 둔다.
- 시간 비교는 기존 축소 루프와 같이 `time.monotonic()`을 쓴다. 벽시계(`time.time()`)는 job 보관에만 쓰는 현재 구분을 유지한다.
- 런처 스크립트는 `scripts/`의 기존 스크립트처럼 모듈 docstring에 용도와 실행법을 적는다.

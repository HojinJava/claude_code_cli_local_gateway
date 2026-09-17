---
description: claude-pool 사전 개발 패턴 — 이슈 #1 분류 로직의 작성 방식(값 추출과 판정 분리)
tags: [architecture]
status: design
---

# 07. 개발 패턴 (design)

- 근거 spec: [구조화된 값으로 워커 실패 분류하기](../../spec/2026-09-17-spec-structured-failure-classification/2026-09-17-spec-structured-failure-classification.md)
- 적용 범위: 워커 실패 분류 경로(`worker.py`, `runner.py`, `errors.py`). 그 밖의 작성 방식은 기존 방식을 유지한다([as-built/07-development-patterns](../as-built/07-development-patterns.md)).

## 채택 방식: 값 추출과 분류 판정의 분리

기존 프로젝트 방식을 따른다. 워커는 프로세스 입출력을, `runner`는 전송 방식과 무관한 `Outcome`을, `errors`는 `Failure` 값 생성을 맡는다. 이는 web-backend 프로파일의 기본 추천(요청·응답 변환은 진입부, 규칙은 HTTP에 의존하지 않음)과도 맞다.

- `Worker.run`은 stdout에서 **값만 추출**한다(`api_error_status`, `assistant.error`). 판정하지 않는다.
- `errors`의 분류 함수는 **구조화된 값만 입력으로 받는 순수 함수**다. 문구·HTTP·aiohttp에 의존하지 않는다.
- `runner.execute`는 두 경계를 잇는다. `WorkerError`는 `worker_failed`로, `is_error` 결과는 분류 함수로 보낸다.
- 선택 이유: 분류를 순수 함수로 두면 표의 각 행을 프로세스 없이 파라미터 테스트할 수 있고, `FAILURE_KINDS`와의 일치 검사도 같은 함수를 쓸 수 있다.
- 제약: 새 클래스 계층·전략 객체·설정 스위치를 만들지 않는다. 표 하나를 if/else로 표현한다.

설계 예시(실제 이름은 구현에서 확정한다):

```python
# 설계 예시
def classify_result(api_error_status: int | None, error: str | None) -> Failure:
    if api_error_status is not None:
        if api_error_status in RATE_LIMIT_STATUSES:
            return RATE_LIMITED
        if api_error_status in AUTH_STATUSES:
            return NOT_AUTHENTICATED
        return WORKER_FAILED
    if error in RATE_LIMIT_ERRORS:
        return RATE_LIMITED
    if error in AUTH_ERRORS:
        return NOT_AUTHENTICATED
    return WORKER_FAILED
```

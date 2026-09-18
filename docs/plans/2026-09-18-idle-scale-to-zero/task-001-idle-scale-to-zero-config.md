---
task: 001
status: done
risk: low
---

# task-001 유휴 축소 기준 시간 설정

## 목표

유휴 축소 기준 시간을 `PoolConfig`에 추가한다. 기본 60초이고 `0`이면 비활성이다.

## 의존성

없음.

## 설계 입력

[design/15-non-functional-requirements.md — 목표: 유휴 시 자원을 0으로](../../architecture/design/15-non-functional-requirements.md#목표-유휴-시-자원을-0으로), [design/05-coding-conventions.md — 이슈 #2](../../architecture/design/05-coding-conventions.md#이슈-2--적용할-규칙)

## 파일 책임

- `src/claude_pool/config.py`: 필드 `idle_scale_to_zero_sec: float = 60.0`을 추가하고, `from_env`에서 `CLAUDE_POOL_IDLE_SCALE_TO_ZERO_SEC`를 읽는다. 기존 시간 설정과 같은 형태(`float(os.environ.get(...))`)로 둔다. 새 검증 규칙은 추가하지 않는다(값 범위 검증은 이번 범위 밖).
- `tests/test_config.py`: 기본값과 환경변수 반영을 확인한다.

## 완료 기준

- 구현: 위 필드·환경변수. 기존 설정 동작은 그대로다.
- 검증: RED → GREEN, `pytest tests/test_config.py`.
- 담당 AC: AC-007.

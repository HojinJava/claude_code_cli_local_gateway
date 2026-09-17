---
task: 004
status: pending
risk: low
---

# task-004 주석과 사용자 문서 갱신

## 목표

`errors.py` 머리 주석, `CLAUDE.md`, `README.md`가 새 판정과 실측 결과를 설명하게 한다.

## 의존성

task-003.

## 설계 입력

[design/13-error-policy.md — 미확정 사항](../../architecture/design/13-error-policy.md#미확정-사항), [분류 규칙](../../architecture/design/13-error-policy.md#분류-규칙-판단-순서가-우선순위)

## 파일 책임

- `src/claude_pool/errors.py`: 머리 주석의 "CLI는 모든 실패를 같은 모양으로 낸다"를 실측 결과로 교체. 입력 필드, 판단 순서, 429·529 출력 미실측을 적는다(코드 동작 변경 없음).
- `CLAUDE.md`: 핵심 아키텍처의 `errors.py` 설명을 구조화된 값 분류로 수정. 문구 정규식을 되살리지 말라는 규칙과 결과 줄이 exit code보다 우선한다는 사실을 "반드시 지켜야 할 것"에 추가.
- `README.md`: "실패를 어떻게 알려주나" 절의 문구 매칭 설명을 구조화된 값 분류로 교체. 실측 CLI 버전 2.1.274와 "429·529 실제 출력은 미실측"을 적는다.

## 완료 기준

- 구현: 세 문서가 spec 분류 규칙과 일치.
- 검증: static — 문구·버전 표기 대조, `git diff --check`.
- 담당 AC: AC-014.

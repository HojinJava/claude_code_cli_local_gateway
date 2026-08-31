# CLAUDE.md

이 파일은 이 리포에서 작업하는 Claude Code에게 주는 프로젝트 지침입니다.

## 프로젝트 개요

`claude-pool`은 Claude Code CLI(`claude`)를 로컬 LLM처럼 쓰기 위한 HTTP 게이트웨이입니다. `claude -p` 워커 프로세스를 미리 띄워놓고 대기시켜서, 매 요청마다 CLI 부팅 비용을 새로 치르지 않고도 여러 곳에서 동시에(병렬로) 호출할 수 있게 하면서, 요청마다 완전히 독립된 워커가 처리하도록(독립 테넌트) 만들었습니다.

## 핵심 아키텍처

- `src/claude_pool/worker.py` — `claude -p` 프로세스 1개를 감싸는 1회용 래퍼. 요청 하나 처리하면 폐기된다.
- `src/claude_pool/pool.py` — `WorkerPool`. `min_workers`~`max_workers` 사이에서 오토스케일링(큐잉 발생 시 증가, idle 지속 시 감소).
- `src/claude_pool/server.py` — aiohttp 서버 (`POST /generate`, `GET /health`).
- `src/claude_pool/daemon.py` — 데몬 엔트리포인트, 위 셋을 조립.
- `src/claude_pool/client.py` — 의존성 없는(stdlib `urllib`만 사용) 클라이언트, 데몬 자동 기동.
- `src/claude_pool/config.py` — `PoolConfig` (환경변수로 설정, `__post_init__`에서 host가 loopback인지 검증).
- `src/claude_pool/errors.py` — 워커 실패 메시지를 `rate_limited`/`not_authenticated`/`worker_failed`로 분류. HTTP 상태·`retryable`·`Retry-After`가 여기서 결정된다.
- `src/claude_pool/runner.py` — `execute()`. 프롬프트 하나를 워커에 태우고 `Outcome`을 돌려준다. 동기(`/generate`)와 백그라운드(`/jobs`)가 공유한다.
- `src/claude_pool/jobs.py` — `JobStore`. 백그라운드 job 실행·보관·취소. 제출 시점에 만료된 job을 reap한다.
- `src/claude_pool/apidocs.py` — 데몬 자기 문서 (`GET /`, `GET /docs`, `GET /openapi.json`). 살아있는 `PoolConfig`에서 생성한다.
- `src/claude_pool/winjob.py` — Windows Job Object 래퍼. `WorkerPool`이 생성한 job에 모든 워커를 묶어서, 데몬이 어떻게 죽든(정상 종료든 크래시든) OS가 워커 프로세스를 정리하게 한다.

## 반드시 지켜야 할 것

- **워커는 `stream-json` 프로토콜로만 실행한다** (`--input-format stream-json --output-format stream-json --verbose`). `--input-format text`는 실제 CLI가 stdin을 약 3초만 기다리다 포기하는 버그가 있어서 예열 풀 설계와 안 맞는다 — 되돌리지 말 것.
- **테스트는 절대 실제 `claude` CLI를 호출하지 않는다.** `tests/fixtures/fake_claude_cli.py`(가짜 CLI)를 상대로만 테스트한다. 실제 CLI를 부르는 건 비용이 들고 인증이 필요해서, README의 "실제 claude CLI를 대상으로 한 수동 스모크 테스트" 절차로만 확인한다.
- **인증 계층을 추가하지 않는다.** `127.0.0.1`(loopback) 바인딩만으로 보호한다. `--bare` 플래그는 절대 쓰지 않는다 (API 키만 지원해서 구독 인증이 깨진다).
- **`model`은 요청별로 override하지 않는다.** 데몬 하나당 모델 하나로 고정한다 (`PoolConfig.model`). 다른 모델이 필요하면 다른 포트로 데몬을 하나 더 띄운다.
- **워커는 1회용이다.** 절대 재사용하지 않는다 — 컨텍스트 격리(독립 테넌트)가 이 프로젝트의 핵심 요구사항이다.
- **`/generate`와 `/health`는 `Host` 헤더가 loopback 리터럴일 때만 응답한다** (`server.require_loopback_host`). loopback 바인딩만으로는 DNS rebinding을 못 막는다 — 인증 계층을 안 쓰는 대신 이 미들웨어가 그 자리를 대신하므로 제거하지 말 것.
- **데몬은 실패한 요청을 자동 재시도하지 않는다.** 재시도는 구독 쿼터를 쓰는 행위라서, 분류 결과(`kind`/`retryable`/`Retry-After`)만 내려주고 판단은 호출자에게 맡긴다.
- **`/health`는 카운터가 아니라 liveness를 보고해야 한다.** `idle`(카운터)과 `idle_alive`(실제 생존)를 둘 다 노출하는 이유는, 예열해둔 `claude`가 전부 죽어도 카운터만 보면 정상으로 보이기 때문이다.
- **`Worker.is_alive()`는 보증이 아니라 best-effort 필터다.** `returncode`는 asyncio가 자식을 수확한 뒤에야 세팅되므로, 방금 죽은 워커는 살아있다고 보고되고 그대로 배포된다. 실제 오류는 `run()`이 exit code와 stderr로 드러낸다.
- **`apidocs.FAILURE_KINDS`는 `errors.classify`와 항상 일치해야 한다.** 분류 규칙을 바꾸면 이 표도 같이 고칠 것 — `tests/test_apidocs.py`가 둘의 어긋남을 잡는다.
- **`/docs` HTML은 자체 완결이어야 한다.** CDN에서 뭘 불러오지 말 것 (오프라인 머신에서도 떠야 하고, 로컬 전용 도구가 외부로 나갈 이유가 없다).
- **워커를 쓰는 모든 경로는 `runner.execute()`를 거쳐야 한다.** 여기에만 `release_in_background` 호출이 있고, 그게 취소된 호출자와 고아 `claude` 프로세스 사이의 유일한 방어선이다. `/generate`와 `/jobs`가 워커를 다르게 다루면 안 된다.
- **데몬 종료 시 `JobStore.shutdown()`이 `pool.stop()`보다 먼저 와야 한다.** job을 취소해야 워커가 풀로 반납되고, 그 다음에야 풀이 전부 정리할 수 있다.
- **모든 워커는 `winjob`의 kill-on-close job에 할당돼야 한다.** `Worker`를 새로 스폰하는 코드를 추가할 때 `job` 인자를 빠뜨리지 말 것 — 이게 데몬 크래시 시 고아 프로세스를 막는 유일한 안전장치다.

## 개발 명령어

```bash
pip install -e ".[dev]"       # 설치
pytest -v                     # 전체 테스트 (가짜 CLI 기반, 비용 없음)
python -m claude_pool.daemon  # 데몬 실행
```

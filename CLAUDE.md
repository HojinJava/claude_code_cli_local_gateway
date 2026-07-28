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

## 반드시 지켜야 할 것

- **워커는 `stream-json` 프로토콜로만 실행한다** (`--input-format stream-json --output-format stream-json --verbose`). `--input-format text`는 실제 CLI가 stdin을 약 3초만 기다리다 포기하는 버그가 있어서 예열 풀 설계와 안 맞는다 — 되돌리지 말 것.
- **테스트는 절대 실제 `claude` CLI를 호출하지 않는다.** `tests/fixtures/fake_claude_cli.py`(가짜 CLI)를 상대로만 테스트한다. 실제 CLI를 부르는 건 비용이 들고 인증이 필요해서, README의 "실제 claude CLI를 대상으로 한 수동 스모크 테스트" 절차로만 확인한다.
- **인증 계층을 추가하지 않는다.** `127.0.0.1`(loopback) 바인딩만으로 보호한다. `--bare` 플래그는 절대 쓰지 않는다 (API 키만 지원해서 구독 인증이 깨진다).
- **`model`은 요청별로 override하지 않는다.** 데몬 하나당 모델 하나로 고정한다 (`PoolConfig.model`). 다른 모델이 필요하면 다른 포트로 데몬을 하나 더 띄운다.
- **워커는 1회용이다.** 절대 재사용하지 않는다 — 컨텍스트 격리(독립 테넌트)가 이 프로젝트의 핵심 요구사항이다.

## 개발 명령어

```bash
pip install -e ".[dev]"       # 설치
pytest -v                     # 전체 테스트 (가짜 CLI 기반, 비용 없음)
python -m claude_pool.daemon  # 데몬 실행
```

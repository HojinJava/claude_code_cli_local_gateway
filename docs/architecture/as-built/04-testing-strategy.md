---
description: claude-pool의 실제 테스트 구성·위치·가짜 claude CLI 주입 방식·실행 방법과 실제 CLI를 부르는 수동 스크립트의 경계
tags: [architecture]
status: as-built
---

# 04. 테스트 전략 (as-built)

## 구성과 위치

- 테스트는 모두 `tests/` 아래 pytest 모듈이다. 파일별 대상은 [01-project-structure](01-project-structure.md#테스트-tests) 책임표를 본다.
- 테스트 함수 수(정적 집계, `def test_`/`async def test_` 기준, parametrize 전개 전): `test_apidocs` 14, `test_ask_script` 4, `test_client` 16, `test_config` 13, `test_daemon` 4, `test_errors` 4, `test_host_guard` 4, `test_integration` 3, `test_jobs` 17, `test_pool` 18, `test_server` 15, `test_winjob` 3, `test_worker` 9, `fixtures/test_fake_claude_cli` 4 — 합계 128.
- 커버리지 측정 설정(`pytest-cov`, `.coveragerc`, `[tool.coverage]`)은 저장소에 없다. `.gitignore`에 `.coverage`가 있을 뿐이다(`.gitignore:9`).
- CI 설정(`.github/workflows` 등)은 없다.

## 테스트 계층 (코드에서 확인한 형태)

| 계층 | 대상 | 방식 | 대표 파일 |
|---|---|---|---|
| 순수 함수 단위 | 분류·설정 검증·Host 헤더 파싱·문서 생성 | 프로세스·네트워크 없이 직접 호출 | `tests/test_errors.py`, `tests/test_config.py`, `tests/test_host_guard.py:29-42`, `tests/test_apidocs.py:95-126` |
| 서브프로세스 단위 | `Worker`, `WorkerPool`, `JobStore` | 가짜 CLI를 실제 자식 프로세스로 스폰 | `tests/test_worker.py`, `tests/test_pool.py`, `tests/test_jobs.py:42-147` |
| HTTP 인프로세스 | 라우트·미들웨어 | `pytest-aiohttp`의 `aiohttp_client(create_app(pool))` | `tests/test_server.py:24-29`, `tests/test_jobs.py:150-233`, `tests/test_apidocs.py:25-29` |
| 실제 TCP 데몬 | `run_daemon` 조립·종료·pid 파일 | `asyncio.ensure_future(run_daemon(config))` + `aiohttp.ClientSession`, 대부분 태스크 cancel로 종료(기동 실패 테스트 `tests/test_daemon.py:131-143`은 `run_daemon`의 예외를 기다림) | `tests/test_daemon.py:28-143` |
| 클라이언트-데몬 | `ClaudePoolClient` | 백그라운드 스레드에서 `asyncio.run(run_daemon(config))` 후 동기 클라이언트로 호출 | `tests/test_client.py:17-43` |
| 통합 | 동시성·오토스케일 | 인프로세스 앱에 동시 요청, 풀 내부 상태 확인 | `tests/test_integration.py` |
| 스크립트 단위 | `scripts/ask.py` 런처 | `importlib.util.spec_from_file_location`으로 스크립트를 모듈로 로드하고 `ClaudePoolClient`를 stub 클래스로 monkeypatch — 데몬도 워커도 띄우지 않는다 | `tests/test_ask_script.py:16-20`, `tests/test_ask_script.py:23-32` |
| OS 통합(Windows 한정) | Job Object | `pytestmark = skipif(sys.platform != "win32")`, `test_pool.py:323` 개별 skipif | `tests/test_winjob.py`, `tests/test_pool.py:323-358` |

## 가짜 CLI 경계

- 모든 워커 경로 테스트는 실제 `claude` 대신 [`tests/fixtures/fake_claude_cli.py`](../../../tests/fixtures/fake_claude_cli.py)를 `PoolConfig.claude_cmd = [sys.executable, str(FAKE_CLI), "--fake-mode", ...]`로 주입한다(예: `tests/test_server.py:18`, `tests/test_pool.py:21`, `tests/test_daemon.py:35`, `tests/test_client.py:31`).
- 가짜 CLI 동작(`fake_claude_cli.py:16-48`): 알 수 없는 인자는 `parse_known_args`로 무시 → stdin을 EOF까지 읽음 → `--fake-delay-sec`만큼 대기 → `crash`면 stderr 출력 후 exit 1, 아니면 `{"type":"system","subtype":"init"}` 줄과 `{"type":"result", ...}` 줄 출력. `error` 모드는 `is_error: true`와 `--fake-error-text`(기본 `"simulated error"`)를 싣는다.
- 가짜 CLI 자체의 계약은 `tests/fixtures/test_fake_claude_cli.py`가 subprocess로 확인한다.
- 스폰 실패는 존재하지 않는 실행 파일 `["claude-pool-no-such-binary-xyz"]`로 재현한다(`tests/test_pool.py:13`, `tests/test_server.py:81`, `tests/test_daemon.py:139`).
- 실패 분류의 HTTP 경로는 가짜 CLI의 `--fake-error-text`로 실제 CLI와 유사한 문구를 주입해 확인한다(예: `tests/test_server.py:138-189`).
- 자동 기동은 실제 데몬 프로세스를 띄우지 않고 `claude_pool.client.subprocess.Popen`을 monkeypatch해 argv·env만 확인한다(`tests/test_client.py:62-76`).
- 런처 `scripts/ask.py`도 실제 데몬을 띄우지 않는다. 테스트가 로드한 모듈의 `ClaudePoolClient` 이름 자체를 stub 클래스로 바꿔(`monkeypatch.setattr(ask, "ClaudePoolClient", StubClient)`, `tests/test_ask_script.py:38`) 출력·종료 코드·실패 분류 표시만 확인한다. 모듈 docstring도 같은 이유를 적는다(`tests/test_ask_script.py:1-6`).
- 테스트 코드에서 실제 `claude` 실행 파일 이름으로 워커를 스폰하는 경로는 없다(스폰하는 테스트의 `claude_cmd` 주입은 가짜 CLI 또는 없는 실행 파일이고, `tests/test_config.py`의 다른 값들은 스폰하지 않는 검증용이다). 단 `PoolConfig()` 기본값(`["claude"]`)을 확인하는 `tests/test_config.py:6-13`은 스폰하지 않는다.

## 테스트가 기대는 내부 접근·타이밍

- 초과분 축소 루프 검증은 `pool._idle`·`pool._total`에 만료된 `Worker`를 직접 넣는다(`tests/test_integration.py:79-84`, `tests/test_pool.py:186-193`).
- 유휴 축소(0까지) 검증은 내부 상태를 직접 조작하지 않고, 짧은 `idle_scale_to_zero_sec`(0.1~0.15초)과 긴 `idle_timeout_sec`(10초)를 함께 준 설정으로 초과분 규칙과 구분한다(`tests/test_pool.py:106-115`, `tests/test_jobs.py:238-246`, `tests/test_integration.py:95-103`).
- 일부 테스트는 짧은 `asyncio.sleep`과 작은 `idle_timeout_sec`/`scale_down_interval_sec`/`idle_scale_to_zero_sec`에 기댄다(예: `tests/test_pool.py:22-23`, `tests/test_pool.py:122`, `tests/test_integration.py:65`, `tests/test_integration.py:86`, `tests/test_integration.py:108`).
- 풀 teardown은 `conftest.make_pool` fixture가 `stop()`한다(`tests/conftest.py:16-29`). `tests/test_pool.py:290-320`의 두 테스트는 `WorkerPool`을 직접 만들고 본문에서 `stop()`한다. Windows 전용 테스트(`tests/test_pool.py:323-358`)도 직접 만들며 `stop()` 대신 `pool._job.Close()`와 워커 `kill()`로 정리한다.

## 실행 방법

- 테스트 러너는 pytest이며 설정은 `pyproject.toml:20-25`에 있다([03-configuration](03-configuration.md#pytest-설정)). dev 의존성은 `dev` extras로 선언돼 있다(`pyproject.toml:10-15`).
- 구체 명령 `pip install -e ".[dev]"`, `pytest -v`는 사용자 문서(`README.md`, `CLAUDE.md`) 기재 명령이다. 이번 실측에서 실행하지 않았다.
- `pythonpath` 설정이 없으므로 `claude_pool` import는 패키지 설치를 전제로 한다.

## 실제 CLI를 부르는 수동 스크립트의 경계

| 스크립트 | 실제 CLI 호출 | 테스트 여부 |
|---|---|---|
| `scripts/bench_cold_vs_warm.py` | `claude -p --input-format text --output-format json ... --model haiku`를 cold·예열 각 10회 스폰(`bench_cold_vs_warm.py:14-28`, `bench_cold_vs_warm.py:68-79`) | `tests/`에서 import·호출 없음 |
| `scripts/investigate_stream_json_timeout.py` | `claude -p --input-format stream-json --output-format stream-json --verbose ... --model haiku`를 15초 지연 후 입력(`investigate_stream_json_timeout.py:16-26`, `investigate_stream_json_timeout.py:74-77`) | `tests/`에서 import·호출 없음 |
| `scripts/daemon_ctl.py` | 직접 호출 없음. `start`는 데몬을 기동하므로 설정된 `claude_cmd`(기본 실제 `claude`)로 워커가 스폰된다 | `tests/`에서 import·호출 없음. 관련 pid 파일 동작은 `tests/test_daemon.py:100-143`이 데몬 쪽에서 확인 |
| `scripts/ask.py` | 직접 호출 없음. 클라이언트 자동 기동으로 데몬이 뜨면 설정된 `claude_cmd`(기본 실제 `claude`)로 워커가 스폰된다 | `tests/test_ask_script.py`가 파일 경로로 로드하되 `ClaudePoolClient`를 stub으로 대체해 데몬·CLI를 부르지 않는다 |

- 두 조사 스크립트는 인증된 CLI와 구독 쿼터를 사용한다. `bench_cold_vs_warm.py` docstring은 수동 실행을 명시하고(`bench_cold_vs_warm.py:4-5`), `bench_cold_vs_warm.py` docstring은 최저가 모델을 쓴다고 적고(모델은 상수 `MODEL = "haiku"`, `bench_cold_vs_warm.py:15`), `investigate_stream_json_timeout.py` docstring은 haiku를 쓴다고 적는다(`investigate_stream_json_timeout.py:6`).
- 두 조사 스크립트의 실행 결과 수치는 추적 파일에 없다(`미확인`).

## 실측 근거

절마다 기준 시점이 다르다.

### 이번 갱신 기준 — `7cc905fc828abeb790f3e8d46de469e7021ed137`

- 갱신한 절: 「구성과 위치」의 함수 수, 「테스트 계층」의 스크립트 단위 행과 이동한 줄 번호, 「가짜 CLI 경계」의 런처 stub 항목, 「테스트가 기대는 내부 접근·타이밍」, 「실제 CLI를 부르는 수동 스크립트의 경계」의 `scripts/ask.py` 행.
- 확인한 소스: `tests/**/*.py` 18개 전부(`tests/test_ask_script.py` 신규 포함), [`scripts/ask.py`](../../../scripts/ask.py)
- 확인 범위: 테스트 본문·fixture 정적 읽기와 함수 수 정적 집계(`^(async )?def test_` 기준). **테스트를 실행하지 않았으므로 통과 여부·소요 시간·커버리지는 기록하지 않는다.**

### 이전 기준 — `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`

- 위에 적지 않은 나머지 절(「구성과 위치」의 커버리지·CI 설정 부재, 「가짜 CLI 경계」의 나머지 항목, 조사 스크립트 2개 행)은 이 commit 기준이며 이번에 다시 확인하지 않았다.
- 당시 확인한 소스: `tests/**/*.py` 17개 전부, [pyproject.toml](../../../pyproject.toml), [.gitignore](../../../.gitignore), `scripts/*.py` 3개
- 미확인: 테스트 통과 여부, 커버리지 수치, 비 Windows 환경에서의 skip 결과, 조사 스크립트 실측값.

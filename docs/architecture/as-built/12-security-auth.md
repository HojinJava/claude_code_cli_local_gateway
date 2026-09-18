---
description: claude-pool의 인증 계층 부재, loopback 바인딩 강제, Host 헤더 미들웨어, job ID 생성, 워커 CLI 플래그, 프로세스 정리·pid 검증 등 신뢰 경계 관련 코드의 적용 지점
tags: [architecture]
status: as-built
---

# 12. 보안·인증 (as-built)

이 문서는 신뢰 경계와 관련된 코드가 **어디에 어떻게 적용돼 있는지**를 기록한다. 각 통제의 효과(우회 불가능성 등)는 검증하지 않았다.

## 인증·인가

- 인증·인가 계층이 없다. 토큰·세션·API 키·헤더 인증을 검사하는 코드가 `src/`에 없고, 모든 라우트가 인증 없이 핸들러로 진입한다(`src/claude_pool/server.py:51-70`).
- 설계 의도는 주석에 기록돼 있다: API에 인증이 없으므로 원격에서 닿지 않아야 한다(`src/claude_pool/config.py:42-43`), 인증 계층 없이 DNS rebinding을 막는다(`server.py:30-38`).
- 사용자·역할·권한 모델은 없다. job 조회·취소도 호출자를 구분하지 않는다(`server.py:139-157`).

## 통제 적용 지점

| 통제 | 적용 지점 | 동작(코드 기준) |
|---|---|---|
| loopback 바인딩 강제 | `PoolConfig.__post_init__` `config.py:44-49` | `host`가 `"localhost"`이거나 `ipaddress.ip_address(host).is_loopback`이 아니면 `ValueError`. 생성자·`from_env()` 모두 거친다. 바인딩은 이 값으로만 한다(`daemon.py:36`) |
| Host 헤더 검사 | 미들웨어 `require_loopback_host` `server.py:28-48`, 등록 `server.py:52` | `request.host`에서 `hostname_from_host_header`(`server.py:15-25`)로 포트·IPv6 괄호를 떼고 `is_loopback_host`(`config.py:12-18`)로 판정. 아니면 403 `{"error", "kind": "forbidden_host", "retryable": false}`. 앱 미들웨어라 등록된 9개 라우트 전부에 적용 |
| job ID | `JobStore.submit` `jobs.py:92-95` | `secrets.token_urlsafe(12)`. 주석: 인증이 없으므로 다른 로컬 프로세스가 열거하지 못하게 순차 id를 쓰지 않음 |
| 전체 프롬프트 비보관 | `jobs.py:30-32`, `jobs.py:96`, `jobs.py:100` | `Job`에는 앞 80자만 `prompt_preview`로 저장, 전체는 태스크 인자로만 전달. 목록 응답(`GET /jobs`)에 preview가 노출된다(`server.py:148-150`) |
| 워커 CLI 플래그 | `Worker._build_argv` `worker.py:34-46` | `-p`, `--input-format stream-json`, `--output-format stream-json`, `--verbose`, `--no-session-persistence`, `--tools ""`, `--strict-mcp-config`, `--safe-mode`, `--model <config.model>`. `--bare`는 없다. 각 플래그가 CLI에서 갖는 효과는 이 저장소에서 확인하지 않았다 |
| 워커 argv 구성 방식 | `worker.py:49-56`, `config.py:50-59` | `asyncio.create_subprocess_exec`(셸 미경유)에 리스트 argv 전달. 프롬프트는 argv가 아니라 stdin JSON으로 전달(`worker.py:79-86`). `claude_cmd`는 문자열 리스트만 허용 |
| 워커 격리(1회용) | `pool.py:185-192` | 반납 시 무조건 kill, idle로 되돌리지 않음. `--no-session-persistence` 플래그와 함께 요청 간 CLI 세션을 재사용하지 않는 구조 |
| 워커 작업 디렉터리 | `worker.py:54` | `cwd = config.scratch_dir` |
| 콘솔 창 억제 | `worker.py:20`, `worker.py:55` | Windows에서 `CREATE_NO_WINDOW` |
| 고아 프로세스 정리 | `pool.py:25`, `worker.py:61`, `winjob.py:20-41` | Windows에서 kill-on-close Job Object에 모든 워커 할당. 비 Windows는 no-op |
| 자동 재시도 없음(쿼터 소모 제어) | `runner.py:37-67` | 획득·실행 각 1회, 실패는 분류만 해서 반환 |
| pid 검증 후 종료 | `scripts/daemon_ctl.py:47-57` | pid 파일의 pid 명령줄에 `claude_pool.daemon`이 포함되면 종료 대상. pid 파일로 못 찾고 포트가 응답하면 명령줄 후보가 정확히 1개일 때만 그 pid를 대상으로 삼는다(포트 대응 미확인). 후보가 0개이거나 여럿이면 추측하지 않고 수동 명령 출력(`daemon_ctl.py:139-150`) |
| `/docs` 출력 이스케이프 | `apidocs.py:327-390` | 상세 지점은 [11-api-contract](11-api-contract.md#자기-문서) |

## 시크릿 취급

- 저장소 코드·설정에 시크릿 값이나 시크릿 주입 설정(환경변수 키 포함)이 없다. `CLAUDE_POOL_*` 환경변수는 모두 비시크릿 운영 설정이다(`config.py:63-101`).
- `claude` CLI 인증 정보는 데몬이 읽거나 전달하지 않는다. 워커는 데몬 프로세스 환경을 상속해 사용자가 로그인한 CLI를 실행한다(`create_subprocess_exec`에 `env` 인자 없음, `worker.py:49-56`).
- 워커 stderr는 `WorkerError` 메시지에 포함돼(`worker.py:92-96`) 실패 응답 `error`와 `/health`의 `last_error`로 노출될 수 있다(`server.py:103`, `runner.py:74`, `pool.py:248`). stderr 내용의 마스킹 코드는 없다.

## 네트워크 노출 관련 기타 사실

- CORS 헤더 설정, CSRF 토큰, 요청 속도 제한 코드는 없다.
- TLS 설정은 없다(평문 HTTP, `web.TCPSite`, `daemon.py:36`).
- 클라이언트는 `host` 인자를 검증하지 않는다(`client.py:36-45`). 자동 기동된 데몬은 전달받은 `CLAUDE_POOL_HOST`를 `PoolConfig` 검증에 넘긴다(`client.py:61`).

## 테스트 위치

| 대상 | 테스트 |
|---|---|
| loopback host 허용·거부 | `tests/test_config.py:28-42` |
| Host 헤더 파싱·403·허용 | `tests/test_host_guard.py` |
| job·문서 라우트의 가드 적용 | `tests/test_jobs.py:229-232`, `tests/test_apidocs.py:89-92` |
| job id 비순차성 | `tests/test_jobs.py:53-56` |
| `claude_cmd` 리스트 검증 | `tests/test_config.py:55-71` |
| Job Object 정리 | `tests/test_winjob.py`, `tests/test_pool.py:260-295` |

테스트는 실행하지 않았다.

## 실측 근거

- 기준 commit: `821f6e9c83edc2b2f11434cc00e52c106f6f7b42`
- 확인한 소스: [config.py](../../../src/claude_pool/config.py), [server.py](../../../src/claude_pool/server.py), [jobs.py](../../../src/claude_pool/jobs.py), [worker.py](../../../src/claude_pool/worker.py), [pool.py](../../../src/claude_pool/pool.py), [winjob.py](../../../src/claude_pool/winjob.py), [runner.py](../../../src/claude_pool/runner.py), [daemon.py](../../../src/claude_pool/daemon.py), [client.py](../../../src/claude_pool/client.py), [apidocs.py](../../../src/claude_pool/apidocs.py), [daemon_ctl.py](../../../scripts/daemon_ctl.py), 위 테스트 파일
- 확인 범위: 통제 코드의 적용 위치 정적 확인. 공격 시나리오 재현·통제 효과 검증은 수행하지 않았다.
- 미확인: `claude` CLI 플래그(`--tools ""`, `--strict-mcp-config`, `--safe-mode`, `--no-session-persistence`)의 실제 효과, `Host` 헤더가 없을 때 aiohttp `request.host` 값, 동일 머신의 다른 프로세스·사용자에 대한 노출 범위.

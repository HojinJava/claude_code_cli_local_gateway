# claude-pool

Claude Code CLI(`claude`)를 로컬 LLM처럼 쓰기 위한 HTTP 게이트웨이입니다. `claude -p` 워커 프로세스를 미리 띄워놓고 대기시켜서, 매 요청마다 CLI 부팅 비용을 새로 치르지 않고도 여러 곳에서 동시에 호출할 수 있게 해줍니다.

## 왜 만들었나

Claude Code 구독형 계정도 API 토큰처럼 코드에서 호출해서 쓰기 위해 만들었습니다. 별도 API 키 없이, 이미 인증된 구독 계정을 그대로 로컬 HTTP 엔드포인트로 노출해서 원하는 곳에서 프롬프트를 넣고 텍스트 응답을 받을 수 있게 합니다.

## 아키텍처

이 프로젝트의 아키텍처는 두 가지 목표를 위해 만들어졌습니다: **병렬 처리**(여러 곳에서 동시에 호출해도 감당할 수 있어야 함)와 **독립 테넌트**(요청 간에 컨텍스트가 섞이면 안 됨).

### 병렬 처리 — 워커 풀 + 오토스케일링

```mermaid
flowchart TB
    A["Python 프로세스 A"]
    B["Python 프로세스 B"]
    C["Python 프로세스 C"]

    A -- HTTP --> Server
    B -- HTTP --> Server
    C -- HTTP --> Server

    subgraph Daemon["claude-pool daemon (127.0.0.1 전용)"]
        Server["aiohttp<br/>POST /generate, GET /health"]
        Pool["WorkerPool<br/>min_workers ~ max_workers"]
        Server --> Pool
    end

    Pool --> W1["worker 1<br/>IDLE (stdin 대기중)"]
    Pool --> W2["worker 2<br/>IDLE"]
    Pool --> W3["worker N<br/>..."]
```

`claude -p` 프로세스를 미리 여러 개 띄워놓고 대기시켜서(pre-warm), 요청이 오면 그중 하나에게 넘겨주는 방식입니다.

- 매 요청마다 새 프로세스를 부팅하는 비용 없이 여러 요청을 동시에 처리합니다.
- 요청이 몰려서 idle 워커가 바닥나면(`acquire()`에서 큐잉 발생) 자동으로 워커를 늘리고(`max_workers`까지), 한가해지면 일정 시간(`idle_timeout_sec`) 이상 안 쓰인 워커를 정리해서 `min_workers`까지 줄이는 오토스케일링이 있습니다.
- 취소된 요청, 스폰 실패, 데몬 종료 등 예외 상황에서도 워커 프로세스가 좀비로 남지 않도록 정리합니다.

### 독립 테넌트 — 1회용 워커 + stream-json

```mermaid
sequenceDiagram
    participant C as 호출자
    participant D as Daemon (HTTP)
    participant P as WorkerPool
    participant W as Worker (claude -p)

    C->>D: POST /generate {prompt}
    D->>P: acquire()
    alt idle 워커 있음
        P-->>D: idle 워커 반환
    else idle 워커 없음
        P->>P: 백그라운드로 워커 1개 추가 예열
        P-->>D: 예열되는 대로 반환 (그동안 대기)
    end
    D->>W: stdin에 프롬프트 기록 + EOF
    W-->>D: stream-json 결과 라인
    D->>P: release(worker) — 워커는 폐기, 필요시 보충
    D-->>C: {"text": "...", "duration_ms": N}
```

각 워커는 딱 한 번의 요청만 처리하고 폐기됩니다. 다음 요청은 항상 새 워커가 받기 때문에 이전 요청의 대화 내용이 섞여 들어갈 수 없습니다.

이 설계에서 가장 까다로웠던 부분은 워커를 미리 띄워놓고 요청이 올 때까지 오래 대기시켜야 한다는 점이었습니다. `claude -p --input-format text`는 stdin 입력이 약 3초 안에 안 들어오면 포기하고 에러를 내는데, 이러면 "미리 띄워놓고 나중에 먹인다"는 전제 자체가 깨집니다. 조사 결과 `--input-format stream-json --output-format stream-json --verbose` 모드는 이 타임아웃이 없다는 걸 확인해서, 워커는 이 프로토콜로 stdin을 통해 프롬프트를 받고 stdout의 stream-json 라인 중 `"type":"result"`인 라인에서 응답을 추출합니다.

### 그 외

- **인증 없음, 로컬 전용**: `127.0.0.1`(loopback)에만 바인딩합니다 — `CLAUDE_POOL_HOST`를 loopback이 아닌 주소로 바꾸려 하면 시작 시점에 에러가 납니다.
- **모델은 데몬당 하나로 고정**: 예열 워커는 프로세스 시작 시점에 `--model`을 고정해서 뜨기 때문에, 요청별로 다른 모델을 요청하는 건 지원하지 않습니다. 다른 모델이 필요하면 다른 포트로 데몬을 하나 더 띄우면 됩니다.

## 시작하기

### 설치

```bash
git clone https://github.com/HojinJava/claude_code_cli_local_gateway.git
cd claude_code_cli_local_gateway
pip install -e ".[dev]"
```

Python 3.11 이상, 그리고 로컬에 인증된 `claude` CLI가 PATH에 있어야 합니다 (API 키 불필요 — 구독 인증을 그대로 사용).

### 데몬 실행

```bash
python -m claude_pool.daemon
```

기본값은 `min_workers=4`, `max_workers=30`, `model=sonnet`, `127.0.0.1:8756`입니다. 환경변수로 바꿀 수 있습니다:

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `CLAUDE_POOL_MIN_WORKERS` | 4 | 항상 유지할 예열 워커 최소 개수 |
| `CLAUDE_POOL_MAX_WORKERS` | 30 | 오토스케일링 상한 |
| `CLAUDE_POOL_MODEL` | sonnet | 데몬당 고정 모델 (요청별 override 불가) |
| `CLAUDE_POOL_HOST` | 127.0.0.1 | loopback 주소만 허용 (그 외는 시작 시점 에러) |
| `CLAUDE_POOL_PORT` | 8756 | |
| `CLAUDE_POOL_TIMEOUT_SEC` | 120.0 | 요청 하나당 기본 타임아웃 |
| `CLAUDE_POOL_ACQUIRE_TIMEOUT_SEC` | 60.0 | 워커를 못 구했을 때 최대 대기 시간 |
| `CLAUDE_POOL_IDLE_TIMEOUT_SEC` | 60.0 | 이 시간 이상 안 쓰인 idle 워커 정리 |
| `CLAUDE_POOL_SCALE_DOWN_INTERVAL_SEC` | 30.0 | 스케일다운 점검 주기 |

### Python에서 호출하기

```python
from claude_pool.client import ClaudePoolClient

client = ClaudePoolClient()  # 데몬이 안 떠 있으면 자동으로 띄움
text = client.generate("reply with the single word PONG")
print(text)  # "PONG"

print(client.health())
# {"min_workers": 4, "max_workers": 30, "total": 4, "idle": 4, "busy": 0}
```

### curl로 직접 호출

```bash
curl -X POST http://127.0.0.1:8756/generate \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"reply with the single word PONG\"}"
```

## 테스트

전체 자동화 테스트는 실제 `claude` CLI를 호출하지 않고, `tests/fixtures/fake_claude_cli.py`(stream-json 프로토콜을 흉내내는 작은 파이썬 스크립트)를 상대로 돕니다. 비용 없이 빠르게 돌아갑니다.

```bash
pip install -e ".[dev]"
pytest -v
```

실제 `claude` CLI를 대상으로 한 수동 스모크 테스트(비용 발생, 자동화 안 됨)는 데몬을 직접 띄우고 확인합니다:

```bash
python -m claude_pool.daemon &

curl http://127.0.0.1:8756/health

curl -X POST http://127.0.0.1:8756/generate \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"reply with the single word PONG\"}"
```

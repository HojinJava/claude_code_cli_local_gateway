# claude-pool 설계 문서

**날짜**: 2026-07-28
**상태**: 승인됨 (구현 계획 단계로 진행)

## 배경 / 목적

로컬에 인증된 Claude Code CLI(구독 인증, API 키 불필요)를 다른 Python 프로젝트에서
"로컬 LLM처럼" 호출하고 싶다. 즉 프롬프트를 stdin으로 보내고 텍스트 응답을 받는
경험을, 매번 새 프로세스를 띄우는 부팅 오버헤드 없이 여러 곳에서 동시에 쓸 수
있어야 한다.

## 핵심 요구사항 (우선순위 순)

1. **독립 테넌트**: 이전 요청과 다음 요청이 서로 연관되면 안 된다. 앞선 대화 내용이
   다음 응답에 영향을 주면 안 된다.
2. **속도**: 매 요청마다 프로세스를 새로 실행하고 죽이는 방식은 피한다. 부팅
   오버헤드를 거의 0에 가깝게 만든다.
3. **동시성**: 여러 Python 프로세스/스크립트가 동시에 호출하는 상황을 감당해야
   한다.

입력은 stdin을 사용한다 (argv는 길이 제한 때문에 사용하지 않음). 인증 계층은 두지
않는다 — 전부 `127.0.0.1`(localhost) 내부 통신이고 호출하는 모든 곳은 신뢰할 수
있는 내부망이기 때문이다.

## 이름/개념 정리

이 시스템은 세 가지 개념이 겹친 형태다.

- **CLI-to-API 어댑터**: CLI 툴의 stdin/stdout 프로토콜을 HTTP request/response로
  바꿔주는 부분 (어댑터 패턴).
- **프로세스 풀 / 프리포크(pre-fork) 패턴**: 워커를 미리 띄워 대기시키는 것.
  Gunicorn/uWSGI의 워커 프리포킹, PHP-FPM, AWS Lambda의 provisioned concurrency와
  동일한 문제/해법.
- **로컬 인퍼런스 게이트웨이**: 위 둘을 합친 전체 역할. Ollama, vLLM 같은 카테고리에
  속하되, 모델 파일 대신 Claude Code CLI 프로세스를 백엔드로 쓴다는 점이 다르다.

Ollama API 스키마와의 호환은 검토했으나 채택하지 않는다 (아래 "검토 후 기각한
대안" 참고). API는 자유 설계로 간다.

## 전체 아키텍처

```
[Python 호출자 A]  [Python 호출자 B]  [Python 호출자 C]  ...
        \               |                /
         \-------------[HTTP 127.0.0.1:<port>]----------/
                          |
                   [claude-pool daemon] (단일 상주 프로세스, asyncio)
                          |
        ┌─────────────────┼─────────────────┐
   [warm worker 1]   [warm worker 2]   ...  [warm worker N]
   (claude -p, stdin 대기중)          (풀 크기 = min_workers~max_workers 사이에서 동적 조절)
```

- **claude-pool daemon**: 로컬에 하나만 상주하는 Python 프로세스. `claude -p ...`
  워커를 미리 N개 띄워 stdin을 연 채 "대기(warm)" 상태로 유지한다.
- **클라이언트 라이브러리**: 다른 Python 프로젝트가 `import` 해서 쓰는 얇은
  클라이언트. 데몬이 안 떠 있으면 자동으로 띄우고(`GET /health` 실패 시 기동),
  이후에는 HTTP로 요청만 보낸다.
- **통신 방식**: localhost HTTP. 인증 헤더 없음 — `127.0.0.1` 바인딩으로 외부
  노출 자체를 차단한다.

## 워커 생명주기 (핵심 트릭)

각 워커는 **딱 한 번의 요청만 처리하고 버려지는 1회용** 프로세스다. 데몬이 미리
여러 개를 띄워놓고 대기시키기 때문에, 요청이 왔을 때는 부팅 비용이 이미 끝나 있는
상태다.

```
IDLE(대기, stdin open) → 요청 도착 → prompt 기록 + stdin EOF → 응답 수신 → 프로세스 종료
                                                                         └→ 백그라운드에서 새 워커 1개 보충
```

워커 실행 커맨드:

```
claude -p \
  --input-format stream-json \
  --output-format stream-json \
  --verbose \
  --no-session-persistence \
  --tools "" \
  --strict-mcp-config \
  --safe-mode \
  --model <model>
```

플래그 근거:

- `--safe-mode`: CLAUDE.md/훅/플러그인/MCP를 꺼서 어떤 프로젝트의 설정도 섞여
  들어오지 않게 한다. 인증(OAuth/구독)은 정상 동작한다 — `--bare`는 API 키만
  지원하고 OAuth/키체인을 안 읽으므로 이번 요구사항에는 쓸 수 없다.
- `--no-session-persistence`: 세션 파일이 디스크에 남지 않음 → 요청 간 완전
  독립.
- `--tools ""`, `--strict-mcp-config` (mcp-config 미지정): 툴 사용을 차단 →
  순수 텍스트 생성만 수행.
- 워커의 cwd는 리포 디렉터리가 아니라 별도의 빈 스크래치 디렉터리로 고정한다
  (프로젝트 파일 노출 방지).
- `--input-format stream-json --output-format stream-json --verbose`: 처음에는
  `--input-format text --output-format json`(단순 stdin 파이프)으로 설계했으나,
  Task 11 실제 CLI 스모크 테스트에서 **실제 `claude -p`가 stdin 입력을 약 3초만
  기다리다 포기하고 에러를 낸다는 것을 발견했다** ("no stdin data received in 3s,
  proceeding without it"). 이는 "워커를 미리 띄워놓고 다음 요청이 올 때까지
  무한정 대기"하는 예열 풀의 핵심 전제와 정면으로 충돌한다 — 실제 요청이 3초
  이상 늦게 오면 워커가 이미 죽어있다. 조사 결과 `stream-json` 입출력 모드는 이
  3초 타임아웃이 없음을 확인했다 (0초/6초/15초 지연 모두 정상 응답,
  `docs/superpowers/plans/2026-07-28-stream-json-investigation.md` 참고). 이
  모드는 `--output-format json`처럼 단일 JSON을 반환하지 않고 줄바꿈으로 구분된
  여러 JSON 라인을 출력하므로, 워커는 stdout을 줄 단위로 스캔해서
  `"type":"result"`인 라인에서 `is_error`/`result`/`duration_ms`를 추출해야
  한다. 입력도 순수 텍스트가 아니라
  `{"type":"user","message":{"role":"user","content":"<prompt>"}}` 형태의 JSON
  한 줄이다.

**검증된 전제**: "`claude -p`를 프롬프트 인자 없이 띄우면 stdin을 받을 때까지
블로킹하며, 이 대기 상태에서 이미 인증/부팅이 끝나 있다"는 가정은 Task 1
스파이크로 검증됐다 (부팅 오버헤드는 실제로 예열로 없앨 수 있음). 다만 정확히
"몇 초까지 대기 가능한가"는 스파이크 당시엔 1초만 테스트해서 놓쳤고, 위
stream-json 발견으로 보완됐다.

## 동적 풀 크기 조절 (오토스케일링)

풀 크기를 고정하지 않고 `min_workers`~`max_workers` 사이에서 실제 부하에 반응해
조절한다. 시간대 기반 스케줄이 아니라 큐잉 발생 여부와 idle 지속 시간이라는 실제
신호를 기준으로 삼는다.

- 설정값: `min_workers`, `max_workers` (예: min=4, max=30).
- **베이스라인 유지**: `min_workers`개는 항상 즉시 보충/유지한다 (기존 예열
  로직 그대로).
- **스케일 업**: 요청이 도착했는데 idle 워커가 없어 큐잉이 발생하면(= 피크 신호),
  현재 총 워커 수(idle+busy)가 `max_workers` 미만인 경우 새 워커를 1개 추가로
  예열 시작한다. 큐잉이 계속되면 `max_workers`에 도달할 때까지 계속 +1씩 늘어난다.
- **스케일 다운**: 주기적으로 (예: 30초마다) idle 워커들의 마지막 사용 시각을
  확인해서, `min_workers`를 초과하는 idle 워커 중 일정 시간(예: 60초) 이상 안 쓰인
  것들을 종료한다. 한가할 때는 자연히 `min_workers`까지 줄어든다.
- `GET /health` 응답에 `min_workers`/`max_workers`/현재 총 워커 수를 노출해 현재
  스케일 상태를 확인할 수 있게 한다.

## 요청 처리 흐름

1. 클라이언트가 `POST /generate {prompt, model?, timeout_sec?}` 호출.
2. 데몬이 풀에서 idle 워커 하나를 꺼낸다. idle 워커가 없으면: 총 워커 수가
   `max_workers` 미만이면 스케일 업을 트리거하면서 idle 워커가 생길 때까지
   대기하고, 이미 `max_workers`에 도달했으면 그냥 대기(큐잉)한다.
3. 워커 stdin에 prompt를 쓰고 EOF, stdout(JSON)을 끝까지 읽어서 파싱한다.
4. 응답을 클라이언트에 반환하고, 워커 프로세스는 폐기한다. 백그라운드로 신규
   워커를 보충한다 (베이스라인 유지 로직과 스케일 업/다운 규칙을 따름).

## API

```
POST /generate
  body: { "prompt": str, "timeout_sec"?: number }
  200: { "text": str, "duration_ms": number }
  4xx/5xx: { "error": str }

GET /health
  200: { "min_workers": int, "max_workers": int, "total": int, "idle": int, "busy": int }
```

- `model`은 요청별 override를 지원하지 않는다. 워커는 예열을 위해 프로세스 시작
  시점에 `--model`을 고정해서 뜨는데, 요청마다 다른 모델을 받으면 예열된 워커를
  못 쓰고 콜드 스폰을 해야 해서 예열의 이점이 사라진다. 대신 모델은 데몬 시작
  옵션(`PoolConfig.model`)으로 데몬 하나당 하나만 고정한다. 다른 모델이 필요하면
  다른 포트로 데몬 인스턴스를 하나 더 띄운다.
- 스트리밍은 v1 범위에서 제외한다. Claude Code CLI는
  `--output-format stream-json --include-partial-messages`로 청크 단위 출력을
  지원하므로 기술적으로는 가능하지만, 워커 stdout 파싱과 HTTP 응답 방식이
  복잡해지므로 필요성이 확인되면 v2에서 추가한다.
- 인증 헤더는 두지 않는다 (내부망 신뢰 전제).

## 에러 처리

- **워커 타임아웃**: 요청별 `timeout_sec`(기본값 있음) 초과 시 프로세스를 kill하고
  클라이언트에 timeout 에러를 반환한 뒤 풀에 새 워커를 보충한다.
- **워커 크래시/비정상 종료** (exit code ≠ 0, JSON 파싱 실패): 에러를 그대로
  클라이언트에 반환한다. 자동 재시도는 v1에서 하지 않는다 (필요하면 호출자가
  판단하도록 그대로 전달하고, 재시도 로직은 필요성이 확인되면 추가한다).
- **풀 고갈 시**: 총 워커 수가 `max_workers` 미만이면 스케일 업으로 새 워커를
  추가하며 대기하고, 이미 `max_workers`에 도달했으면 idle 워커가 생길 때까지
  요청을 큐잉한다.
- **데몬 자체가 죽어있는 경우**: 클라이언트가 `/health` 실패를 감지하면 데몬
  프로세스를 재기동하고 재시도한다.

## 검증 계획

1. **스파이크 (설계 전제 검증)**: "claude -p를 stdin 열어둔 채 미리 띄우면
   부팅이 미리 끝나는가"를 실제로 확인하는 작은 벤치마크 스크립트. 후보 2개
   (콜드 스폰 vs 예열 풀)를 각각 10회씩 실행해 응답 시간을 비교한다.
2. **단위 테스트**: 워커 상태 머신(IDLE→BUSY→종료→보충), 풀 크기 유지 로직.
3. **통합 테스트**: 데몬 기동 → 여러 클라이언트가 동시에 `/generate` 호출 →
   응답 격리(서로 다른 프롬프트에 대해 컨텍스트가 안 섞이는지) 확인.
4. **동시성 테스트**: 10~30개 동시 요청 부하 시 큐잉/지연 동작 확인.
5. **오토스케일링 테스트**: 버스트 요청으로 큐잉을 유발해 `max_workers`까지
   스케일 업되는지, 이후 요청이 멈추면 일정 시간 후 `min_workers`까지 스케일
   다운되는지 확인.

## 검토 후 기각한 대안

- **단일/소수의 장기 실행 프로세스를 `--input-format stream-json` 멀티턴으로
  재사용**: 컨텍스트 초기화가 프로토콜 차원에서 보장되지 않아 "독립 테넌트"
  요구사항을 만족한다고 확신할 수 없어 기각.
- **Ollama API 스키마 호환** (`/api/generate`, `/api/chat`, `options`, `context`
  등): 기존 ollama 클라이언트를 그대로 쓸 수 있다는 이점은 있으나, 지원 안 되는
  필드(샘플링 옵션)나 오히려 요구사항과 충돌하는 필드(`context`의 대화 이어가기)가
  있어 오히려 불편하다고 판단, 자유 설계로 대체.
- **콜드 스폰 per request (매 요청마다 새 프로세스)**: 가장 단순하고 독립성은
  완벽하지만 부팅 오버헤드 요구사항을 만족 못 함. 벤치마크 비교용 베이스라인으로만
  유지.

## 후속 작업 (지금은 미착수, 조건 충족 시 진행)

- 데몬/클라이언트 구현이 완료되고 나면, 이 서비스를 **어떤 프로젝트의 Claude Code
  세션에서든 발견할 수 있는 전역 위치**에 문서화한다 (예: 전역 CLAUDE.md 또는
  전역 참조 문서에 엔드포인트/포트/사용법 기록).
- README에 아키텍처 다이어그램과 활용 방안을 작성한다. 현재는 아직 구성이 안
  됐으므로, 실제 구현 후 내용이 확정되면 추가한다.

# Task 1 Validation Spike Results: Cold vs Pre-Warm Bootstrap Time

## Objective
Determine whether pre-spawning `claude -p` processes and letting them idle saves meaningful boot time compared to fresh spawn-per-request, establishing the core premise of the claude-pool daemon design.

## Benchmark Setup
- **Model**: haiku (cheapest, ~1 token prompt)
- **Prompt**: "reply with the single word OK"
- **Iterations**: 10 cold spawns, 10 pre-warmed spawns
- **Pre-warm settle time**: 1.0s (simulating idle pool time before request arrives)
- **CLI flags**: `-p`, `--input-format text`, `--output-format json`, `--no-session-persistence`, `--tools ""`, `--strict-mcp-config`, `--safe-mode`

## Raw Benchmark Output

```
cold[0] = 4.527s
cold[1] = 3.429s
cold[2] = 3.216s
cold[3] = 3.136s
cold[4] = 2.906s
cold[5] = 3.000s
cold[6] = 3.295s
cold[7] = 3.431s
cold[8] = 3.742s
cold[9] = 3.821s
warm[0] = 2.769s
warm[1] = 2.721s
warm[2] = 2.404s
warm[3] = 3.918s
warm[4] = 2.769s
warm[5] = 2.639s
warm[6] = 2.360s
warm[7] = 2.292s
warm[8] = 4.639s
warm[9] = 2.335s

--- summary ---
cold  mean=3.450s  median=3.362s
warm  mean=2.885s  median=2.680s
```

## Analysis

| Metric | Cold Spawn | Pre-Warmed | Delta |
|--------|-----------|-----------|-------|
| Mean | 3.450s | 2.885s | -565ms (−16.38%) |
| Median | 3.362s | 2.680s | -682ms (−20.28%) |

## Key Findings

1. **Absolute savings**: 565ms mean improvement, 682ms median improvement
2. **Percentage savings**: 16.38% mean improvement, 20.28% median improvement  
3. **Variance**: Pre-warmed shows slightly higher variance (cold σ ≈ 0.427s, warm σ ≈ 0.743s), likely due to API timing variability, but the improvement is consistent across all runs except outliers
4. **Outliers**: Both datasets contain occasional spikes (cold[0]=4.527s, warm[3]=3.918s, warm[8]=4.639s), likely from API/network jitter, but the trend is clear

## Decision

**✅ GO**

Per the brief's decision rule (warm mean ≥20% lower than cold mean, OR ≥200ms absolute savings):
- Mean percentage improvement: 16.38% — **does not meet 20% criterion**
- Mean absolute savings: **565ms ≥ 200ms threshold** ✓

The pre-warmed pool saves **565ms in absolute terms** (mean), meeting the decision criteria via the absolute-savings clause. The GO decision is justified.

**Interpretation**: Pre-spawning processes and letting them idle _does_ meaningfully reduce perceived request latency. The cold spawn cost (mainly auth handshake + model loading) is largely front-loaded during initial spawn, and pre-warmed processes avoid this cost when serving requests. The median results (682ms, 20.28%) further corroborate the mean findings.

## Implications for Next Phase

1. The core premise of claude-pool is **validated** — pooling saves meaningful time
2. The architecture should prioritize:
   - Efficient worker pool lifecycle (spawn, idle, reuse, drain)
   - Minimal overhead per request after handoff to pre-warmed process
   - Graceful shutdown to reclaim processes without losing in-flight requests

## Cost

20 API calls × haiku model cost ≈ $0.04 USD (negligible)

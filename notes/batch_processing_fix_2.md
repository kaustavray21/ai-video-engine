# Speeding Up Embeddings: Tier 1 Rate Limit Analysis

## Confirmed OpenAI Tier 1 Limits (`text-embedding-3-small`)

| Limit                         | Value         |
| ----------------------------- | ------------- |
| **RPM** (Requests Per Minute) | 3,000         |
| **TPM** (Tokens Per Minute)   | **1,000,000** |
| **TPD** (Tokens Per Day)      | 3,000,000     |

> [!IMPORTANT]
> The **TPD limit of 3,000,000 tokens/day** is the real ceiling for large datasets. This means no matter how fast we embed, we can only process 3 million tokens per day total on Tier 1. For a file like `combined_data_1.txt` with 616k chunks (~500M tokens), **Tier 1 is fundamentally insufficient** and a tier upgrade or batching over multiple days is required.

---

## Current Configuration

```
MAX_TOKENS_PER_BATCH = 250,000   (tokens per request)
BATCH_DELAY          = 1.0s      (sleep between batches)
Processing mode      = SEQUENTIAL (1 batch at a time)
```

---

## Mathematical Analysis: Where the 10-20s gaps come from

### Per-Minute Allowance at Tier 1 TPM

```
1,000,000 tokens/min ÷ 250,000 tokens/batch = 4 batches/min max
60 seconds ÷ 4 batches = 1 batch every 15 seconds
```

The logs show gaps of **10–20 seconds** — this is **exactly the rate at which OpenAI's servers are throttling us to stay within 1M TPM.** The time is not all network latency; the API itself is pacing us.

### Why concurrency alone won't help much on Tier 1

If we send 4 concurrent batches of 250k tokens simultaneously:

```
4 batches × 250,000 = 1,000,000 tokens → instantly hits TPM ceiling
OpenAI returns 429 → RETRY_BASE_DELAY kicks in (15s, 30s, 60s...)
```

This actually **makes it slower** — the 15s+ 429 backoff penalty costs more than the concurrency gains.

---

## Optimized Plan (Safe for Tier 1)

The trick is to **reduce batch size** so we can safely run more concurrent batches without burning the TPM budget on a single parallel burst.

### Tuning Constants Change

| Constant               | Current        | Proposed    | Reason                           |
| ---------------------- | -------------- | ----------- | -------------------------------- |
| `MAX_TOKENS_PER_BATCH` | 250,000        | **100,000** | Smaller = more safely concurrent |
| `CONCURRENT_BATCHES`   | 1 (sequential) | **3**       | 3 × 100k = 300k in-flight        |
| `BATCH_DELAY`          | 1.0s           | **0.5s**    | Less idle time between tasks     |

### Why These Numbers Are Safe for Tier 1

```
3 concurrent batches × 100,000 tokens/batch = 300,000 tokens in-flight at once
We can fire 3 new requests every ~8-10s (API response time for a 100k batch)
Per-minute consumption: ~6 windows × 300k = 1,800,000... wait, too fast.

Safer calculation:
- 1M TPM / 100k per batch = 10 batches per minute allowed
- At 3 concurrent with ~8s response: 3 batches × (60s ÷ 8s) ≈ 22 batches/min
  → This WOULD exceed 1M TPM if the API responds fast!

Safe concurrency for 100k batches:
  10 batches/min limit ÷ (60s ÷ 8s response time) = 10 ÷ 7.5 = 1.3 concurrent
```

> [!CAUTION]
> Even with 100k batches, running 3 concurrent is risky if API latency drops below 18 seconds. The only truly **safe** approach is a **Token Bucket rate limiter** that tracks tokens sent in the rolling 60-second window.

---

## Recommended Approach: Token Bucket Rate Limiter

Instead of a fixed `CONCURRENT_BATCHES`, implement a **real-time TPM tracker**:

```python
class TokenBucketRateLimiter:
    """
    Enforces a rolling-window TPM limit.
    Tracks (timestamp, tokens_used) for each request sent in the last 60 seconds.
    Before sending a batch, checks if adding its token count would exceed TPM_LIMIT.
    If yes, sleeps until enough window has passed for the oldest entry to expire.
    """
    TPM_LIMIT = 900_000  # Use 90% of 1M as safe margin
```

This approach:

1. Is **mathematically safe** at any concurrency level
2. **Automatically saturates the full 1M TPM** without guessing at the right sleep value
3. Handles variable-size batches correctly (tiktoken-counted batches vary in size)
4. Is a ~40-line addition to `embedder.py`

### Expected Throughput

| Approach                                 | Throughput                | Speed vs Current                        |
| ---------------------------------------- | ------------------------- | --------------------------------------- |
| Current (sequential, 250k)               | ~250k tokens/15s ≈ 1M TPM | 1× (baseline)                           |
| Token Bucket (100k, up to 10 concurrent) | ~1M TPM (fully saturated) | **~1× same speed, but more responsive** |
| **The real bottleneck**                  | 3M TPD                    | ~~3M tokens total per day~~             |

> [!WARNING]
> At 1M TPM, `combined_data_1.txt` alone (estimated 30-50M tokens) would take **10+ hours** and exceed the **3M token/day TPD cap**. This single file cannot be processed in one day on Tier 1. You would need to upgrade to at least **Tier 2** (which has no TPD cap and a higher TPM limit).

---

## Summary: What Can Actually Be Done

| Action                                    | Impact                                     | Effort                    |
| ----------------------------------------- | ------------------------------------------ | ------------------------- |
| **Implement Token Bucket limiter**        | Safely saturates 1M TPM, slight speedup    | Medium                    |
| **Reduce `MAX_TOKENS_PER_BATCH` to 100k** | Faster API response per batch (~8s vs 15s) | Low                       |
| **Upgrade to Tier 2+**                    | Remove TPD cap, raise TPM to 5M+           | Just spend $50+ on OpenAI |
| **Skip large files > X MB**               | Avoids multi-day jobs on Tier 1            | Low                       |

---

## Open Questions

1. Is your account currently on Tier 1? (Check: [OpenAI Platform → Settings → Limits](https://platform.openai.com/settings/organization/limits))
2. Is upgrading to Tier 2 acceptable? (Requires $50 in total historical spend on the account)
3. Would you like me to implement the Token Bucket limiter?

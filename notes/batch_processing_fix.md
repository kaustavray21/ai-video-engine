# Fix OpenAI Embeddings Token Overflow — Exact Counting + Auto-Split Retry

## Problem

Every single embedding request for CSV/numeric data is hitting OpenAI's hard limit:
`Invalid 'input': maximum request size is 300000 tokens per request.`

The root cause is the heuristic `CHARS_PER_TOKEN = 2.5` in [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py) used by `_plan_batches()` to estimate token counts.

### Log Evidence — Two Distinct Failure Patterns

| File                  | Chars | Chunks  | Batches Planned               | Outcome                                              |
| --------------------- | ----- | ------- | ----------------------------- | ---------------------------------------------------- |
| `combined_data_1.txt` | 495M  | 616,376 | 13 segments × 80 batches each | **All 13 segments failed** — batch 1 always blows up |
| `links.csv`           | 542K  | 679     | **2 batches**                 | **Failed on batch 1**                                |
| `creditcard.csv`      | —     | 284,807 | —                             | Succeeded earlier (less token-dense)                 |
| `customer_churn.csv`  | —     | 1,186   | —                             | ✓ Succeeded                                          |

> [!CAUTION]
> The `links.csv` case is the smoking gun. Only **679 chunks** in **2 batches**, yet batch 1 (≈625 chunks) still exceeds 300k tokens. This proves the heuristic is fundamentally broken for dense numeric/ID data — not just for large files.

### Why the Heuristic Fails

The batch planner estimates: `est_tokens = len(chunk) / 2.5 ≈ 400 tokens/chunk`, so it packs **625 chunks** into batch 1 (625 × 400 = 250k estimated tokens).

But dense CSV data like `1488844,3,2005-09-06` tokenizes at ~1.0–1.3 chars/token, giving **~770 tokens/chunk**. Actual batch 1 payload: **625 × 770 ≈ 481,250 tokens** — 1.6× over the limit.

---

## Proposed Changes

Two-layer defense: **exact token counting** (prevention) + **auto-split on 400** (safety net).

### Layer 1 — Exact Token Counting via tiktoken

#### [MODIFY] [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py)

**Change `_plan_batches()`** to use `tiktoken.encode_batch()` for exact token counts instead of the `CHARS_PER_TOKEN` heuristic.

- `tiktoken` is already in [requirements.txt](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/requirements.txt) (`tiktoken==0.7.0`)
- `encode_batch()` uses a Rust backend — tokenizing 50k chunks takes <100ms
- Remove the now-unused `CHARS_PER_TOKEN` constant

```python
def _plan_batches(self, chunks: List[str]) -> List[Tuple[int, int]]:
    import tiktoken
    try:
        enc = tiktoken.encoding_for_model(EMBED_MODEL)
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")

    # Exact token counts — Rust-parallel, <100ms for 50k chunks
    token_counts = [len(t) for t in enc.encode_batch(chunks, disallowed_special=())]

    batches = []
    i = 0
    while i < len(chunks):
        batch_tokens = 0
        batch_count = 0
        j = i
        while j < len(chunks) and batch_count < MAX_BATCH_INPUTS:
            if batch_tokens + token_counts[j] > MAX_TOKENS_PER_BATCH and batch_count > 0:
                break
            batch_tokens += token_counts[j]
            batch_count += 1
            j += 1
        batches.append((i, j))
        i = j
    return batches
```

---

### Layer 2 — Auto-Split Retry on 400 Errors

#### [MODIFY] [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py)

**Change `_embed_batch()`** to catch `400 "maximum request size"` errors and recursively split the batch in half and retry both halves. This is a safety net in case tiktoken's count diverges from OpenAI's internal tokenizer.

```python
elif resp.status == 400:
    body = await resp.text()
    if 'maximum request size' in body and len(texts) > 1:
        mid = len(texts) // 2
        logger.warning(
            f'[Embedder] Batch {batch_num} too large ({len(texts)} inputs), '
            f'splitting in half and retrying'
        )
        left = await self._embed_batch(session, texts[:mid], batch_num, total_batches)
        await asyncio.sleep(BATCH_DELAY)
        right = await self._embed_batch(session, texts[mid:], batch_num, total_batches)
        return left + right
    raise RuntimeError(f'OpenAI embeddings API error {resp.status}: {body}')
```

This handles edge cases where:

- tiktoken version drifts from OpenAI's server-side tokenizer
- A single chunk contains unexpectedly dense content (e.g. base64 encoded data)

---

## Summary of Changes

| File                                                                                                                    | What Changes                                                      |
| ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py) | `_plan_batches()`: replace heuristic with tiktoken exact counting |
| [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py) | `_embed_batch()`: add 400-error auto-split retry                  |
| [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py) | Remove unused `CHARS_PER_TOKEN` constant                          |

No changes needed in `study_material_processor.py` — the segmentation logic is fine; it's the per-batch token estimation that's broken.

---

## Verification Plan

### Automated Tests

1. Restart Celery worker
2. Retry the failed SM — the pending/failed files (including `links.csv` and `combined_data_1.txt`) should now process
3. **What to look for in logs**:
   - Batch counts should be **higher** than before (more, smaller batches for dense data)
   - `links.csv` (679 chunks): expect ~4–6 batches instead of 2
   - `combined_data_1.txt` segments: expect ~150+ batches per segment instead of 80
   - Zero `400 maximum request size` errors
   - If auto-split triggers: `Batch N too large, splitting in half and retrying`

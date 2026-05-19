# Batch Processing Speed Optimization — Final Plan

## Log Verification Summary

Analyzed [ai_video_engine_2026-05-17_21-12-45.log](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/logs/ai_video_engine_2026-05-17_21-12-45.log) (123KB, 1195 lines):

```
LOG FINDINGS
============
429 rate limit errors:     0 (ZERO — the 9s delay is far too conservative)
Network errors:            1 (Connection reset by peer, batch 62 — retried OK)
SoftTimeLimitExceeded:     2 (creditcard.csv at batch 660/713, combined_data_1.txt at batch 1/1541)
Actual batch interval:     ~12-13s (9.0s delay + 3-4s API round-trip)

File timings from logs:
  city_temperature.csv:    52,749 chunks → 132 batches → 30 min ✓ completed
  OnlineRetail.csv:        57,028 chunks → 143 batches → 33 min ✓ completed
  ratings.csv:             29,956 chunks → 75 batches  → 16 min ✓ completed
  creditcard.csv:         284,807 chunks → 713 batches → 14h (timeout at 660/713) ✗
  combined_data_1.txt:    616,376 chunks → 1541 batches → killed immediately ✗
```

---

## Proposed Fixes (3 total)

---

### Fix 1 — Token-Budget-Aware Dynamic Batch Size (MED effort, HIGH impact)

- **File**: [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py)
- **Lines 29-37** (constants) and **149-169** (`_embed_all` method)

#### The Problem with a Fixed BATCH_SIZE=2048

CSV/numerical data tokenizes much more densely than English text:

| Content Type        | Chars/Chunk | Tokens/Chunk | 2048 × Tokens | Safe?                        |
| ------------------- | ----------- | ------------ | ------------- | ---------------------------- |
| English text        | 1000        | ~250         | ~512k         | ✅                           |
| CSV (mixed)         | 1000        | ~400         | ~820k         | ⚠️                           |
| CSV (dense numbers) | 1000        | ~600-700     | ~1.2-1.4M     | ❌ Exceeds per-request limit |

OpenAI has an undocumented ~300k-500k token per-request ceiling for embeddings. The current code already notes this concern at line 32.

#### Solution: Dynamic batch sizing with a token budget

Replace the fixed `BATCH_SIZE` with a `MAX_TOKENS_PER_BATCH` budget. Before each batch, estimate the token count and pack as many chunks as fit.

**New constants:**

```python
# ── Tuning constants ──────────────────────────────────────────────────────────
OPENAI_EMBED_URL  = "https://api.openai.com/v1/embeddings"
EMBED_MODEL       = "text-embedding-3-small"
MAX_BATCH_INPUTS  = 2048       # OpenAI hard cap on array length
MAX_TOKENS_PER_BATCH = 250_000 # stay safely under ~300k per-request token ceiling
BATCH_DELAY       = 1.0        # seconds between batches (adaptive: 429 retry self-regulates)
WINDOW_SIZE       = 10_000     # process this many chunks at a time (memory safety)
MAX_RETRIES       = 5          # 429 retry attempts
RETRY_BASE_DELAY  = 15         # seconds for first retry, doubles each attempt
CHARS_PER_TOKEN   = 2.5        # conservative estimate (English ≈ 4, CSV/numbers ≈ 1.5-2.5)
# ─────────────────────────────────────────────────────────────────────────────
```

**New `_embed_all` method** with dynamic batch sizing:

```python
async def _embed_all(self, chunks: List[str]) -> List[List[float]]:
    """
    Embed all chunks with token-budget-aware dynamic batching.
    Each batch is sized to stay under MAX_TOKENS_PER_BATCH tokens
    AND MAX_BATCH_INPUTS inputs (OpenAI hard cap = 2048).
    """
    all_vectors: List[List[float]] = []
    total_chunks = len(chunks)
    batches = self._plan_batches(chunks)
    total_batches = len(batches)

    async with aiohttp.ClientSession() as session:
        for batch_num, (b_start, b_end) in enumerate(batches, start=1):
            batch = chunks[b_start:b_end]

            vectors = await self._embed_batch(session, batch, batch_num, total_batches)
            all_vectors.extend(vectors)

            # Rate-limit guard: pause before the next batch
            if batch_num < total_batches:
                await asyncio.sleep(BATCH_DELAY)

    return all_vectors

def _plan_batches(self, chunks: List[str]) -> List[Tuple[int, int]]:
    """
    Plan batch boundaries so each batch stays under both
    MAX_BATCH_INPUTS and MAX_TOKENS_PER_BATCH.
    """
    batches = []
    i = 0
    while i < len(chunks):
        batch_tokens = 0
        batch_count = 0
        j = i
        while j < len(chunks) and batch_count < MAX_BATCH_INPUTS:
            est_tokens = max(1, int(len(chunks[j]) / CHARS_PER_TOKEN))
            if batch_tokens + est_tokens > MAX_TOKENS_PER_BATCH and batch_count > 0:
                break
            batch_tokens += est_tokens
            batch_count += 1
            j += 1
        batches.append((i, j))
        i = j
    return batches
```

**Impact by content type:**

| Content Type                      | Effective Batch Size | Batches for creditcard.csv (284k chunks) |
| --------------------------------- | -------------------- | ---------------------------------------- |
| English text (250 tok/chunk)      | ~1000 inputs         | ~285 batches                             |
| CSV mixed (400 tok/chunk)         | ~625 inputs          | ~456 batches                             |
| CSV dense numbers (600 tok/chunk) | ~416 inputs          | ~685 batches                             |

This automatically adapts — English text gets large batches for speed, dense CSV gets smaller batches for safety.

---

### Fix 2 — Reduce BATCH_DELAY 9.0 → 1.0s (LOW effort, HIGH impact)

- **File**: [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py)
- **Line 33**

Already included in Fix 1 constants above. The 9s delay is confirmed unnecessary by the zero-429 log evidence. The existing 5-retry exponential backoff provides adaptive protection.

---

### Fix 3 — Split large files into segments (MED effort, CRITICAL)

- **File**: [study_material_processor.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/study_material_processor.py)
- **Lines 226-236** (Phase 2, embedding call)

#### Why This Is Needed

Even with dynamic batching, a file with 616k chunks at ~3s/batch still takes:

- Best case (English, ~1000/batch): 617 batches × 3s = **31 min** — tight but OK
- Worst case (CSV, ~400/batch): 1541 batches × 3s = **77 min** — risky with 4h time limit when processing 136 files

By splitting into segments with their own vectorstores and merging, we get:

- Progress checkpointing (if timeout hits, we keep completed segments)
- Predictable per-segment time (~2-3 min each)
- Memory safety (don't hold 600k embeddings in RAM simultaneously)

#### Changes

Add `MAX_CHUNKS_PER_SEGMENT = 50_000` constant and a new `_embed_with_segmentation` method:

```python
MAX_CHUNKS_PER_SEGMENT = 50_000  # ~50-125 batches per segment depending on content

def _embed_with_segmentation(self, text: str, save_path: str, metadata: dict):
    """
    Embed text with automatic segmentation for very large files.
    If chunks > MAX_CHUNKS_PER_SEGMENT, split into segments,
    embed each, then merge into one per-file vectorstore.
    """
    from apps.core.services.embedder import EmbedResult

    # Pre-chunk to check size
    chunks = self.embedder.text_splitter.split_text(text)
    total_chunks = len(chunks)

    if total_chunks <= MAX_CHUNKS_PER_SEGMENT:
        # Small enough — single-shot
        return self.embedder.create_vectorstore(text, save_path, metadata)

    logger.info(
        f'[Processor] Large file: {total_chunks:,} chunks → '
        f'splitting into segments of {MAX_CHUNKS_PER_SEGMENT:,}'
    )

    embeddings = OpenAIEmbeddings(
        openai_api_key=self.openai_api_key,
        model='text-embedding-3-small',
    )
    merged_vs = None
    segment_count = 0
    total_embedded = 0

    for seg_start in range(0, total_chunks, MAX_CHUNKS_PER_SEGMENT):
        segment_count += 1
        seg_chunks = chunks[seg_start: seg_start + MAX_CHUNKS_PER_SEGMENT]
        seg_text = '\n\n'.join(seg_chunks)

        seg_path = f'{save_path}.seg{segment_count}'

        result = self.embedder.create_vectorstore(
            transcript_text=seg_text,
            save_path=seg_path,
            metadata=metadata,
        )

        if not result.success:
            logger.warning(f'[Processor] Segment {segment_count} failed: {result.error}')
            continue

        total_embedded += result.chunk_count

        # Load and merge
        try:
            vs = FAISS.load_local(seg_path, embeddings, allow_dangerous_deserialization=True)
            if merged_vs is None:
                merged_vs = vs
            else:
                merged_vs.merge_from(vs)
        except Exception as exc:
            logger.warning(f'[Processor] Could not load segment {segment_count}: {exc}')
        finally:
            if os.path.exists(seg_path):
                shutil.rmtree(seg_path)

        logger.info(
            f'[Processor] Segment {segment_count}: {len(seg_chunks):,} chunks '
            f'({total_embedded:,}/{total_chunks:,} total)'
        )

    if merged_vs is None:
        return EmbedResult(success=False, error='All segments failed to embed')

    os.makedirs(save_path, exist_ok=True)
    merged_vs.save_local(save_path)
    logger.info(f'[Processor] Merged {segment_count} segments → {total_embedded:,} chunks')

    return EmbedResult(
        success=True,
        vectorstore_path=save_path,
        chunk_count=total_embedded,
    )
```

Then replace the `create_vectorstore` call in `_phase2_process_files` (line 226):

```diff
-                embed_result = self.embedder.create_vectorstore(
+                embed_result = self._embed_with_segmentation(
-                    transcript_text=conv.text,
+                    text=conv.text,
                     save_path=vs_path,
                     metadata={...},
                 )
```

---

## Expected Speedup

```
EXPECTED SPEEDUP (all 3 fixes)
================================

creditcard.csv (284,807 chunks, dense CSV ≈ 600 tok/chunk):
  BEFORE: 713 batches × 13s  = ~2.6 hours → timeout ✗
  AFTER:  6 segments × ~685 batches total ÷ ~416/batch × 3s = ~34 min ✓
  Speedup: ~4.5x

city_temperature.csv (52,749 chunks, CSV ≈ 400 tok/chunk):
  BEFORE: 132 batches × 13s  = 30 min
  AFTER:  ~85 batches × 3s   = ~4.3 min
  Speedup: ~7x

combined_data_1.txt (616,376 chunks):
  BEFORE: 1541 batches × 13s = 5.6 hours → timeout ✗
  AFTER:  13 segments × ~120 batches each × 3s = ~78 min ✓
  Speedup: from impossible → completes

Overall: ~5-30x faster depending on content type
```

---

## Changes Summary

| File                                                                                                                                                    | Fix                                         | What Changes                                                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py)                                 | Fix 1+2: Dynamic batch size + reduced delay | Replace constants (lines 29-37), rewrite `_embed_all` (lines 149-169), add `_plan_batches` method |
| [study_material_processor.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/study_material_processor.py) | Fix 3: Segmented embedding                  | Add `_embed_with_segmentation` method (~55 lines), change 1 call site (line 226)                  |

> [!IMPORTANT]
> **Shall I apply these changes?** Reply:
>
> - `apply all` — apply all 3 fixes
> - `apply fix N` — apply specific fix(es)
> - `skip fix N` — skip a fix

## Verification Plan

1. Restart Celery: `celery -A config worker --loglevel=info`
2. Reset & retry SM id=4: `python reset_stuck_sm.py -i 4`, then trigger retry
3. **What to look for in logs**:
   - Dynamic batch sizes: `Batch 1/85 → 625 embeddings` (CSV) vs `Batch 1/26 → 1000 embeddings` (text)
   - Batch interval ~2-3s instead of ~12-13s
   - Large files show segmentation: `Large file: 284,807 chunks → splitting into segments of 50,000`
   - Segment progress: `Segment 1: 50,000 chunks (50,000/284,807 total)`
   - No `SoftTimeLimitExceeded`
   - If 429s appear, they'll be handled: `429 rate limit on batch N, retrying in 15s…`

# Batch Embedding Optimization for Study Material Processor

## Problem

The current embedder sends **one chunk at a time** to the OpenAI API via `FAISS.from_texts()`. For large files like `tags.csv` (20,162 chunks) or `book_tags.csv` (19,567 chunks), this means:

- **~20,000+ individual API calls per file** → hit rate limits (429 errors)
- **~10 minutes per huge file** → combined time blows past the 30-min soft limit

## What the Batch Processing Document Recommends

For a 16GB / 4 CPU / OpenAI API setup:

| Strategy                                        | Benefit                                                           |
| ----------------------------------------------- | ----------------------------------------------------------------- |
| Batch size 2048                                 | Reduces API calls by 100x (OpenAI allows max 2048 inputs/request) |
| Async concurrency (20 parallel requests)        | Overlaps network I/O                                              |
| Memory windowing (process 10k chunks at a time) | Prevents RAM exhaustion                                           |
| 429 auto-retry with backoff                     | Handles rate limit errors gracefully                              |

**Result:** 20,162 chunks → 10 API calls → ~2–4 minutes instead of ~10 minutes.

## Proposed Changes

### MODIFY [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py)

Replace the single-shot `FAISS.from_texts()` call with an async batched embedder that:

1. Splits chunks into batches of **2048** (OpenAI max)
2. Fires up to **20 concurrent async requests** via `aiohttp`
3. Processes chunks in **windows of 10,000** to stay memory-safe
4. Retries on **HTTP 429** with exponential backoff
5. Assembles the resulting FAISS index from pre-computed embeddings

The `Embedder.create_vectorstore()` method signature stays **identical** — no changes needed in the processor or anywhere else that calls it.

### No Changes Needed Elsewhere

- `study_material_processor.py` — calls `embedder.create_vectorstore()` unchanged
- `study_material_tasks.py` — no change
- `file_converter.py` — no change

## New Dependency

`aiohttp` — for async HTTP requests to the OpenAI embeddings API.

> [!IMPORTANT]
> Need to install: `pip install aiohttp`

## Verification Plan

1. Restart Celery worker and trigger retry on study material id=4
2. Check logs — should see `Embedding batch X/Y` lines instead of one-at-a-time chunk logs
3. Confirm vectorstore is saved correctly and query still returns results
# Batch Embedding Optimization for Study Material Processor

## Problem

The current embedder sends **one chunk at a time** to the OpenAI API via `FAISS.from_texts()`. For large files like `tags.csv` (20,162 chunks) or `book_tags.csv` (19,567 chunks), this means:
- **~20,000+ individual API calls per file** → hit rate limits (429 errors)
- **~10 minutes per huge file** → combined time blows past the 30-min soft limit

## What the Batch Processing Document Recommends

For a 16GB / 4 CPU / OpenAI API setup:

| Strategy | Benefit |
|---|---|
| Batch size 2048 | Reduces API calls by 100x (OpenAI allows max 2048 inputs/request) |
| Async concurrency (20 parallel requests) | Overlaps network I/O |
| Memory windowing (process 10k chunks at a time) | Prevents RAM exhaustion |
| 429 auto-retry with backoff | Handles rate limit errors gracefully |

**Result:** 20,162 chunks → 10 API calls → ~2–4 minutes instead of ~10 minutes.

## Proposed Changes

### MODIFY [embedder.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/embedder.py)

Replace the single-shot `FAISS.from_texts()` call with an async batched embedder that:
1. Splits chunks into batches of **2048** (OpenAI max)
2. Fires up to **20 concurrent async requests** via `aiohttp`
3. Processes chunks in **windows of 10,000** to stay memory-safe
4. Retries on **HTTP 429** with exponential backoff
5. Assembles the resulting FAISS index from pre-computed embeddings

The `Embedder.create_vectorstore()` method signature stays **identical** — no changes needed in the processor or anywhere else that calls it.

### No Changes Needed Elsewhere

- `study_material_processor.py` — calls `embedder.create_vectorstore()` unchanged  
- `study_material_tasks.py` — no change
- `file_converter.py` — no change

## New Dependency

`aiohttp` — for async HTTP requests to the OpenAI embeddings API.

> [!IMPORTANT]
> Need to install: `pip install aiohttp`

## Verification Plan

1. Restart Celery worker and trigger retry on study material id=4
2. Check logs — should see `Embedding batch X/Y` lines instead of one-at-a-time chunk logs
3. Confirm vectorstore is saved correctly and query still returns results

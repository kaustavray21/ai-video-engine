# Walkthrough: Course Vectorstore Metadata Fallback

## Overview

We resolved an issue where RAG queries spanning a complete course vectorstore returned empty source metadata for video transcript chunks, which confused the LLM and resulted in strict "no context found" answers.

## Changes Made

- **[MODIFY] `vectorstore.py`**:
  - Implemented `_get_doc_metadata()` inside `VectorStoreManager`. This method dynamically inspects raw chunk metadata. If `source_file` is missing (as is standard for video chunks), but `video_title` is present, it injects robust fallbacks:
    - `source_file = video_title`
    - `file_type = 'video_transcript'`
    - `chunk_role = 'single'`
  - Replaced all explicit `doc.metadata` calls with `self._get_doc_metadata(doc)` across:
    - Unique source tracking (for boosting `k` on overview queries)
    - Metadata filtering logic
    - BM25 candidate slot capping (`MAX_BM25_PER_FILE`)
    - Context formatting (`[Source: ..., Type: ...]`)
    - API response JSON population (`retrieved_sources`)
    - Guaranteed file representation in `_get_one_chunk_per_file`

## Verification

- We queried the `http://127.0.0.1:8000/api/query/course/` endpoint for course 10 using the query `"Summarize all topics"`.
- The overview `k`-boost mechanism correctly engaged because `unique_files` correctly counted the dynamic video titles in the docstore.
- The payload successfully returned 27 contextually rich, metadata-annotated chunks, resolving the previous issue where only 6 unannotated chunks were sent.
- Video chunks were visibly tagged, for example: `"source_file": "Problems with RNN", "file_type": "video_transcript"`.

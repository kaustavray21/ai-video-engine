# RAG Plan: Ensuring Full File Coverage In Overview Queries

## Problem Analysis

From the `current.toon` eval results, three queries were run against `tesst1` (SM ID 8), which contains **5+ files** including `.pptx`, `.csv`, `.pdf`, `.sql`, `.svg`, `.py` etc.

### Observed failures:

| Query                                                               | Problem                                                                                        |
| ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| "What are the topics or files in this course?"                      | ✅ Correct — 20 chunks retrieved, 3 files mentioned. But `.sql`, `.svg`, `.py` are **missing** |
| "summarize the contents of live_video_pipeline_vulnerabilities.svg" | ❌ Answer: "context does not contain..." — `.svg` chunks were **never retrieved**              |
| "summarize the contents of process_live_videos.py"                  | ❌ Same — `.py` file chunks were **never surfaced**                                            |

### Root Cause

**1. Semantic relevance bias** — FAISS + BM25 retrieval is similarity-based. Files like `.svg` (very short, no real text) and `.py` (code, not natural language) produce **dense, semantically similar embeddings** to nothing in the query. They lose to the `.pptx` and `.csv` which have many more chunks and semantically richer text.

**2. Volume imbalance** — The `.pptx` has 21+ chunks, `.csv` has 200+ chunks. Together they dominate the top-k slots. A single `.sql` has maybe 15 chunks, `.svg` may have 0–2 chunks (since SVG text extraction is near-empty).

**3. Overview boost is k-limited to 20** — Even with k=20, the large files (`.pptx` = 16 slots, `.csv` = 4 slots) monopolize the results, leaving no room for `.svg`, `.py`, or `.sql`.

**4. Per-file query also fails for `.svg`** — If the file produced near-zero text content after conversion, its vectorstore will have 0 or near-0 chunks, making it un-queryable by design.

---

## Solution: Two-Track Fix

### Track 1 — Guaranteed File Coverage In Overview Queries (Retrieval Fix)

Instead of relying purely on semantic retrieval for overview queries, implement a **"guaranteed 1-slot-per-file"** strategy:

- When `is_overview` is detected, collect **1 representative chunk per unique source file** from the vectorstore (just scan the docstore, pick the first/best chunk per file).
- Combine these guaranteed slots with the normal top-k results (deduped).
- This ensures every file that has _any_ content gets represented in the LLM context.

### Track 2 — File Metadata Index For Listing (No-Retrieval Fix)

For pure "what files are in this study material?" questions, the answer should come from the **database** (`StudyMaterialFile` table), not the vectorstore. The vectorstore is the wrong tool for listing files — it's for content retrieval.

- Add a **file manifest injection**: when an overview question is asked, prepend the list of `StudyMaterialFile.original_name` + `file_type` + `status` from the DB into the context.
- The LLM will always list all files even if they have 0 vectorstore chunks.

### Track 3 — Rich Ingestion Headers For All Code File Types (Ingestion Fix)

Every code/config file now gets a `[File Summary]` header injected at ingest time via `_read_code()` + `_extract_code_symbols()`. This makes **every file queryable by filename, language, and key structural symbols** even if it only produces 1–2 chunks.

| Extension Group                       | What is extracted                                   |
| ------------------------------------- | --------------------------------------------------- |
| `.py`                                 | AST: function names, class names                    |
| `.js/.ts/.jsx/.tsx/.vue/.svelte`      | regex: classes, function/var names, exports         |
| `.java/.cs/.swift/.kt/.php/.rb/.dart` | regex: classes, interfaces, methods                 |
| `.go`                                 | regex: struct names, function names                 |
| `.rs`                                 | regex: structs, enums, functions                    |
| `.c/.cpp/.h`                          | regex: structs, function signatures                 |
| `.sql`                                | regex: CREATE TABLE, VIEW, PROCEDURE/FUNCTION names |
| `.sh/.bash/.zsh`                      | regex: shell function names                         |
| `.html`                               | regex: `<title>`, `<h1-3>` headings                 |
| `.css/.scss/.sass`                    | regex: CSS selectors (count + sample)               |
| `.json`                               | JSON parse: top-level keys                          |
| `.yaml/.yml`                          | regex: top-level YAML keys                          |
| `.xml`                                | regex: element tag names                            |
| `.graphql/.gql`                       | regex: type names, query/mutation names             |
| `.dockerfile`                         | regex: FROM base image, instruction types           |

For **SVG** files: always inject `[File Summary] SVG graphic file: X.svg. Diagram title or topic: X` — the filename stem becomes the topic even for near-empty SVGs.

> ⚠️ Track 3 only applies to **newly processed / re-retried** SMs. Existing vectorstores need a retry to benefit.

---

## Proposed Changes

---

### Component 1: VectorStoreManager (Core Fix)

#### [MODIFY] [vectorstore.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/vectorstore.py)

**`query()` method changes:**

1. For `is_overview` queries: after loading the vectorstore, run `_get_one_chunk_per_file()` to get guaranteed slots.
2. Merge guaranteed slots into `final_docs` (prepend, then dedup by source_file so large files don't dominate).
3. Cap total context size (guaranteed + top-k combined) to avoid token overflow.

**New method `_get_one_chunk_per_file()`:**

```python
def _get_one_chunk_per_file(self, vectorstore) -> list:
    """Return one representative chunk per unique source_file."""
    seen = {}
    for doc in vectorstore.docstore._dict.values():
        sf = (doc.metadata or {}).get('source_file', '')
        if sf and sf not in seen:
            seen[sf] = doc
    return list(seen.values())
```

---

### Component 2: Study Material Query API View (Manifest Injection)

#### [MODIFY] [study_material_views.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/api/views/study_material_views.py)

In `StudyMaterialQueryAPI.post()`, before calling `vsm.query()`:

- Detect if question is an overview question (same `OVERVIEW_PATTERNS` check).
- If yes, fetch all `StudyMaterialFile` objects for this SM and pass `file_manifest` list to the query.

In `VectorStoreManager.query()`:

- Accept optional `file_manifest: list[str]` param.
- If provided, prepend a synthetic context block: `[File Manifest]\nThis study material contains the following files:\n- file1.pptx\n- file2.csv\n- file3.svg\n...`

This guarantees the LLM always knows all files exist, even if their chunks aren't retrieved.

---

### Component 3: File Converter (Ingestion Quality)

#### [MODIFY] [file_converter.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/file_converter.py)

- `.svg` conversion: extract `<title>`, `<desc>`, and all text nodes. If result is empty/very short, create a fallback chunk: `"This file is an SVG image named {filename}. It appears to be a diagram or graphic."`
- `.py` conversion: inject a "File Summary" header chunk listing all top-level function/class names (using `ast` module), so queries like "summarize process_live_videos.py" can match on the filename.

---

## Overview of Changes

```
OVERVIEW_PATTERNS detection →
  1. Inject file manifest from DB into context (always correct)
  2. Guarantee 1 chunk per file from vectorstore (always represented)
  3. Merge with top-k, dedup by source_file → LLM sees all files
```

---

## Open Questions

> [!IMPORTANT]
> **Q: Token budget for large SMs** — If a SM has 20+ files, injecting 1 chunk per file + file manifest could exceed the LLM's context window. Should we cap guaranteed slots at e.g. 15 files, and show a "(+N more files)" note? Recommend: **yes, cap at 15 guaranteed slots**.

> [!NOTE]
> **SVG files** will likely always return "no content" since SVGs are graphics, not text. The fix is to ensure the filename itself is stored as a queryable chunk so the system at least acknowledges the file exists. Should we skip SVGs entirely at ingest (mark as `skipped`) and only list them in the manifest?

---

## Verification Plan

Run the same 3 eval queries from `current.toon` against SM 8 after the changes:

1. **"What are the topics or files in this course?"** — Should now list ALL files including `.sql`, `.svg`, `.py`.
2. **"summarize the contents of live_video_pipeline_vulnerabilities.svg"** — Should answer with filename-based context + note it's a graphic.
3. **"summarize the contents of process_live_videos.py"** — Should list function names from the injected summary chunk.

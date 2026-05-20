# RAG Improvement Plan — v2

## ai_video_engine · TOON KB + modality-aware architecture

> **For Claude:** This document is the single source of truth for implementing RAG improvements.
> Every section is written so you can act on it directly without asking the user for clarification.
> Sections marked **[CONSTRAINT]** must never be violated. Sections marked **[DECISION]** record
> a choice already made — do not re-open them. When you begin a phase, read the entire phase
> first, then execute changes in the exact file order given in Section 5.

---

## 0. How To Use This Plan (Claude-Specific Instructions)

1. **Never modify source files before the user types `apply phase N`.** This document is planning only until then.
2. **Read the target file before editing it.** Do not write from memory.
3. **After each file change, verify** by running the verification step listed in Section 5 before moving to the next file.
4. **If a file on disk contradicts this plan**, trust the file and note the mismatch in your response. Do not silently apply the plan over a conflicting implementation.
5. **Do not add new pip dependencies** without listing them explicitly in the phase notes and appending them to `requirements.txt`.
6. **Do not remove** existing retry, checkpointing, async embedding, TokenBucketRateLimiter, or merged-vectorstore behavior. These are **[CONSTRAINT]** items.
7. **Phases are independent.** Phase 2 can be started before Phase 1 only if the specific item in Phase 2 has no dependency note pointing to Phase 1.

---

## 1. Current State From Knowledge Base

### Architecture Summary (from TOON KB)

- **Five FAISS vectorstore types** exist in the project:
  - `video_vectorstores/<video_id>/` — per-video transcript embeddings
  - `course_vectorstores/<course_id>/` — aggregated from per-video FAISS via `CourseAggregator`
  - `individual_vectorstores/` — per-file SM vectorstores built during `StudyMaterialProcessor.run()`
  - `complete_vectorstores/<sm_id>/` — merged SM vectorstore (all files in one ZIP merged)
  - `course.merged_vectorstore_path` — course + study material merged vectorstore built by `StudyMaterialMerger`

- **Ingestion chain:** `FileConverter` (30+ format → raw text) → `Embedder` (`RecursiveCharacterTextSplitter` → async `aiohttp` OpenAI embeddings → FAISS save)

- **Embedder** (`apps/core/services/embedder.py`, 401 lines): async sequential mega-batches via `aiohttp`, `OpenAIRateLimiter` (dual TPM+RPM rolling-window), `MAX_BATCH_INPUTS=2048`, `MAX_TOKENS_PER_BATCH=280_000`, `TPM_LIMIT=980_000`, `RPM_LIMIT=2_800`, `tiktoken` exact token counting, `MAX_RETRIES=5`. Sequential dispatch (no concurrency). Production-tested (upd_012, upd_019). **[CONSTRAINT: do not rewrite this layer.]**

- **Retrieval / QA** (`apps/core/services/vectorstore.py`): `VectorStoreManager`, FAISS `similarity_search`, GPT-4o-mini via `ChatOpenAI`, single `QA_PROMPT` `PromptTemplate`.

- **Study material pipeline:** ZIP upload → `ZipExtractor` → `FileConverter` → `Embedder` → FAISS. Per-file `StudyMaterialFile` model tracks status/error/vectorstore path. Retry skips completed files (upd_014).

- **CourseQueryAPI** returns `vectorstore_used` and supports `include_study_materials` toggle (upd_015).

- **Celery:** `process_study_material` + `retry_study_material` use `SoftTimeLimitExceeded`, lazy imports, registered explicitly in `config/celery.py` (upd_022). **[CONSTRAINT: do not alter task registration or time-limit handling.]**

- **Logging:** `TimedRotatingFileHandler`, midnight rotation, 10 backups (upd_021). Already in place — no change needed.

### **[DECISION]** What the new architecture requirements change

The user has specified that the current single-path `FileConverter → RecursiveCharacterTextSplitter` pipeline must be replaced with a **modality-aware ingestion pipeline** with four distinct paths:

| Modality                                         | Current handler                                   | Required new handler                                                                                    |
| ------------------------------------------------ | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Documents / Presentations (PDF, DOCX, PPTX)      | `pdfplumber`, `python-docx`, `python-pptx`        | VLM-generated description **for images inside docs** + `unstructured` layout-aware parsing **for text** |
| Images (JPG, PNG, SVG direct uploads)            | `pytesseract` OCR                                 | GPT-4o vision call → descriptive text summary → embed the summary                                       |
| Structured data (XLSX, CSV, JSON, ODS)           | flat text dump                                    | Serialize rows as key-value pairs or Markdown tables                                                    |
| Code & markup (.py, .js, .ts, .html, .xml, etc.) | UTF-8 read, then `RecursiveCharacterTextSplitter` | AST-based function/class boundary chunking                                                              |

In addition:

- Every chunk must carry **enriched metadata** (7 fields — see Section 4.3).
- **Parent-child indexing** must be used for code and dense documents.
- **Hybrid search** (BM25 + dense FAISS via RRF) is required as a Phase 2 target for exact-match use cases.
- **Self-querying retriever** (LLM metadata router before vector search) is a Phase 3 target.

### Recently Completed Work — [CONSTRAINT: Do Not Re-implement]

| ID               | Completed work                                                          |
| ---------------- | ----------------------------------------------------------------------- |
| upd_012, upd_019 | Async batched Embedder with TokenBucketRateLimiter                      |
| upd_014          | `retry_study_material` with per-file checkpoint skip                    |
| upd_015          | `include_study_materials` toggle + `vectorstore_used` in CourseQueryAPI |
| upd_022          | Celery SM task autodiscovery                                            |
| upd_021          | Timed log rotation                                                      |
| upd_010          | `StudyMaterialFile` per-file tracking model                             |
| upd_013          | `StudyMaterialFilesAPI` + `StudyMaterialRetryAPI`                       |
| upd_020          | Multipart upload support in ApiTesterView                               |

---

## 2. Verified Architecture

| Flow                   | Entry Point                                               | Main Files                                                                                                 | Vectorstore Used                                      | Notes                                              |
| ---------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | -------------------------------------------------- |
| Video ingestion        | `process_video_task`                                      | `processing.py` → `downloader.py` / `vimeo_transcript.py` → `transcriber.py` → `embedder.py`               | `video_vectorstores/<video_id>/`                      | Vimeo captions first; Whisper fallback             |
| Course VS rebuild      | `rebuild_course_vectorstore_task`                         | `processing.py` → `aggregator.py` → `embedder.py`                                                          | `course_vectorstores/<course_id>/`                    | Merges per-video FAISS                             |
| Video query            | `POST /query/video/`                                      | `query_views.VideoQueryAPI` → `VectorStoreManager`                                                         | `video_vectorstores/<video_id>/`                      | GPT-4o-mini + `QA_PROMPT`                          |
| Course query (no SM)   | `POST /query/course/`                                     | `query_views.CourseQueryAPI` → `VectorStoreManager`                                                        | `course_vectorstores/<course_id>/`                    | `include_study_materials=false` or no merged VS    |
| Course query (with SM) | `POST /query/course/`                                     | `query_views.CourseQueryAPI` → `VectorStoreManager`                                                        | `course.merged_vectorstore_path`                      | `include_study_materials=true` + merged VS present |
| SM ingestion           | `POST /study-materials/upload/`                           | `study_material_views` → Celery → `StudyMaterialProcessor` → `ZipExtractor` → `FileConverter` → `Embedder` | `individual_vectorstores/` + `complete_vectorstores/` | Per-file checkpointing                             |
| SM query               | `POST /study-materials/<pk>/query/`                       | `study_material_views.StudyMaterialQueryAPI` → `VectorStoreManager`                                        | `complete_vectorstores/<sm_id>/`                      | GPT-4o-mini                                        |
| Merged VS build        | `POST /study-materials/<pk>/merge-to-course/<course_id>/` | `StudyMaterialMergeAPI` → `StudyMaterialMerger.build()`                                                    | Writes `course.merged_vectorstore_path`               | Loads both FAISS, calls `merge_from()`             |
| SM retry               | `POST /study-materials/<pk>/retry/`                       | `StudyMaterialRetryAPI` → `retry_study_material` (Celery)                                                  | Resumes from checkpoint                               | Skips completed `StudyMaterialFile` records        |

---

## 3. Gaps And Risks

| Area                           | Current Behavior                                                             | Gap / Risk                                                                                          | Evidence                                                                              | Priority     |
| ------------------------------ | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------ |
| Single-path ingestion          | All file types go through `FileConverter` → `RecursiveCharacterTextSplitter` | No modality awareness; images OCR'd noisily; tables flattened; code split mid-function              | `kb_map`: `file_converter.py` 218 lines, one converter; `embedder.py` single splitter | **Critical** |
| Image ingestion quality        | `pytesseract` OCR on JPG/PNG                                                 | OCR fails on diagrams, charts, screenshots; embeds noise not meaning                                | `kb_map`: `file_converter.py` imports `pytesseract`                                   | **Critical** |
| Structured data chunking       | Flat text dump of XLSX/CSV                                                   | Table rows split across chunks; cell relationships destroyed; key-value queries fail                | `kb_map`: `file_converter.py` handles XLSX via `openpyxl`                             | High         |
| Code chunking                  | `RecursiveCharacterTextSplitter` on source files                             | Functions/classes split mid-body; imports separated from their usage                                | `kb_map`: `file_converter.py` reads code as UTF-8                                     | High         |
| Chunk metadata absent          | Raw text only in FAISS Documents                                             | No source attribution, page/slide/function name; citation impossible; metadata filtering impossible | `kb_map`: `embedder.py` no metadata fields in exports                                 | High         |
| QA prompt groundedness         | Single `QA_PROMPT` in `vectorstore.py`                                       | No grounding instruction, no citation format, no source-type separation, no refusal behavior        | `kb_map`: `vectorstore.py` exports `QA_PROMPT` — content unverified                   | High         |
| Dense-only retrieval           | FAISS cosine similarity                                                      | Exact-match queries (variable names, IDs, credentials, formula names) miss; no keyword path         | Architecture                                                                          | Medium       |
| No self-querying router        | All queries hit all chunks                                                   | Queries about config files search transcript chunks; no metadata pre-filter before embedding        | Architecture                                                                          | Medium       |
| top-k not configurable         | Default LangChain k=4                                                        | No tuning; may under-retrieve for merged vectorstores                                               | `kb_map`: `vectorstore.py` — no k constant visible                                    | Medium       |
| Similarity scores not surfaced | `vectorstore_used` returned but no per-chunk scores                          | Cannot diagnose retrieval quality; no score threshold enforcement                                   | upd_015 only added path field                                                         | Medium       |
| No parent-child indexing       | Flat chunk list                                                              | Dense documents return child snippets with no surrounding context; LLM answer is thin               | Architecture                                                                          | Medium       |
| Empty VS handling              | Unverified                                                                   | Missing or corrupt FAISS directory may 500 or silently return empty answer                          | `kb_map`: `vectorstore.py` 159 lines, no guard in exports                             | High         |
| Merged VS staleness            | Manual re-merge only                                                         | No signal to user that SM was updated after last merge                                              | `kb_map`: `StudyMaterialMergeAPI` is explicit POST                                    | Low          |
| Token usage not logged         | Not tracked per query                                                        | Cannot identify expensive queries or cost-optimise                                                  | `kb_map`: `vectorstore.py` uses `ChatOpenAI` — no usage tracking visible              | Low          |
| No RAG eval harness            | Ad-hoc production testing only                                               | Cannot detect regressions after changes                                                             | upd_025/026 are docs only                                                             | Medium       |
| Error fields not serialized    | `StudyMaterialFile.error` exists                                             | Operators cannot see failure reasons via API; must use Django admin                                 | upd_010 added model field; serializer status unclear                                  | Medium       |

---

## 4. Architecture For The New Pipeline

### 4.1 Modality Router — Where It Lives

A new service `apps/core/services/modality_router.py` will sit between `FileConverter` and `Embedder`.
It receives a `FileEntry` (already produced by `ZipExtractor`) and the converted text from `FileConverter`,
examines `file_extension`, and dispatches to one of four specialist handlers.

**Call chain after this change:**

```
ZipExtractor → FileConverter (raw text) → ModalityRouter
                                                ├── DocumentHandler    (PDF, DOCX, PPTX, RTF, ODT, ODP)
                                                ├── ImageHandler       (JPG, PNG, SVG)
                                                ├── StructuredHandler  (XLSX, XLS, CSV, JSON, ODS)
                                                └── CodeHandler        (all code + markup extensions)
                                                        ↓
                                              EnrichedChunkList (chunks + metadata dicts)
                                                        ↓
                                              Embedder.embed_chunks(chunks, metadata)  ← new method signature
```

The `Embedder` already handles async batching, rate limiting, and FAISS saving.
**Only its input interface changes** — it will accept pre-split chunks with metadata attached,
rather than raw text to split internally. The async/aiohttp/TokenBucket internals are untouched.

**[CONSTRAINT]:** The `Embedder`'s async batch loop, `OpenAIRateLimiter`, sequential dispatch,
`MAX_BATCH_INPUTS`, `MAX_TOKENS_PER_BATCH`, `TPM_LIMIT`, `RPM_LIMIT`, `MAX_RETRIES`, and `BATCH_DELAY` must not be changed.

---

### 4.2 Four Modality Handlers

#### Handler A — DocumentHandler (PDF, DOCX, PPTX, RTF, ODT, ODP)

**Parsing:** Keep existing `FileConverter` text extraction (pdfplumber, python-docx, python-pptx).
Do not add `unstructured` or `LlamaParse` as new dependencies — they carry heavy transitive deps
that conflict with the existing OCR stack. Instead, extract **section structure** from the existing
parsers:

- **PDF via pdfplumber:** extract text page-by-page; record `page_number` per chunk.
- **DOCX via python-docx:** iterate paragraphs; detect headings by `paragraph.style.name`
  (e.g. `"Heading 1"`, `"Heading 2"`); record the most recent heading as `header_context`.
- **PPTX via python-pptx:** iterate slides; record `slide_number` per chunk.

**Chunking:** Paragraph-boundary chunking. Split on `\n\n` first (paragraph breaks), then apply
`RecursiveCharacterTextSplitter` with `chunk_size=1200, chunk_overlap=180` only if a paragraph
exceeds the limit. This preserves paragraph integrity for prose.

**Parent-child:** For PDFs and DOCX only — create a **parent chunk** (full page or full section
under a heading) and **child chunks** (400-token pieces of that parent). Store both in FAISS.
Parent chunks use metadata key `chunk_role: "parent"`; children use `chunk_role: "child"` with
`parent_chunk_id` linking back. During retrieval, when a child chunk is matched, the
`VectorStoreManager` will fetch the parent chunk by its `parent_chunk_id` metadata filter and
pass the parent text to the LLM instead.

#### Handler B — ImageHandler (JPG, JPEG, PNG, SVG)

**[DECISION]:** Replace `pytesseract` OCR with a GPT-4o vision call during ingestion.
OCR is kept as a fallback only if the GPT-4o call fails.

**Processing steps:**

1. Base64-encode the image file from disk.
2. Call `openai.OpenAI().chat.completions.create()` with model `gpt-4o`, passing the image as
   `image_url: { url: "data:image/<ext>;base64,<b64>" }` and a structured prompt:

   ```
   Describe this image in full detail for a search index.
   Include: all visible text (verbatim), chart labels and values,
   diagram component names and relationships, table contents,
   code snippets if present, and a one-sentence summary.
   Format: plain text, no markdown.
   ```

3. Store the GPT-4o description as the chunk text.
4. Metadata: `file_type: "image"`, `file_extension`, `source_file`, `vision_generated: true`.
5. No further splitting — one image → one chunk (descriptions are typically 200–600 tokens).

**Fallback:** If GPT-4o vision call fails (rate limit, network, non-image content), fall back to
`pytesseract` with the existing cleanup (Phase 1.4 from v1 plan — still applies here).

**SVG:** Parse XML with `lxml`, extract all `<text>` and `<title>` nodes as plain text.
If the SVG contains no text nodes, treat it as an image and apply the GPT-4o path.

**Cost note:** GPT-4o vision input is ~$0.01–$0.03 per image at 1024px. Gate behind
`IMAGE_VLM_ENABLED` setting (default `True`). When `False`, fall back to pytesseract.

#### Handler C — StructuredHandler (XLSX, XLS, CSV, JSON, ODS)

**[DECISION]:** Never apply `RecursiveCharacterTextSplitter` to structured data. Convert to
semantic units first.

- **XLSX / XLS / ODS:** For each sheet, serialize every row as:
  `"[SheetName] RowN: ColHeader1=Value1 | ColHeader2=Value2 | ..."`
  Group rows into chunks of 20 rows each (approximately 500–800 tokens per chunk).
  Metadata: `sheet_name`, `row_range` (e.g. `"1-20"`).

- **CSV:** Same row serialization as XLSX. No sheet name. Metadata: `row_range`.

- **JSON:** If top-level is an array, serialize each element as a key-value string.
  If top-level is an object, serialize each top-level key as a separate chunk.
  Metadata: `json_path` (e.g. `"root[0]"`, `"root.users"`).

**No parent-child** for structured data — row groups are already the right granularity.

#### Handler D — CodeHandler (.py, .js, .ts, .jsx, .tsx, .vue, .svelte, .html, .css, .scss, .sass, .java, .go, .rs, .cpp, .c, .h, .cs, .swift, .kt, .php, .rb, .dart, .sh, .bash, .zsh, .dockerfile, .makefile, .mk, .sql, .graphql, .gql, .xml, .yaml, .yml, .toml, .env)

**[DECISION]:** Use AST-based chunking for languages where AST parsing is cheap and reliable
in Python without additional compiled dependencies. For other languages, use line-count chunking
at logical boundaries.

**AST group (Python only — standard library `ast` module):**

- Parse the file with `ast.parse()`.
- Extract top-level nodes: `ast.FunctionDef`, `ast.AsyncFunctionDef`, `ast.ClassDef`.
- Each node becomes one chunk: the source lines from `node.lineno` to `node.end_lineno`.
- Module-level statements (imports, constants, top-level assignments) are grouped into an
  "imports + globals" chunk prepended to each function/class chunk during retrieval context
  (stored as a `module_globals` chunk with `chunk_role: "globals"`).
- Metadata: `function_name` or `class_name`, `start_line`, `end_line`.

**Line-boundary group (JS, TS, JSX, TSX, Java, Go, Rust, C/C++, C#, Swift, Kotlin, PHP, Ruby, Dart):**

- Split on blank lines between top-level constructs (heuristic: lines starting with known
  declaration keywords: `function`, `class`, `def`, `fn`, `func`, `public`, `private`, `export`).
- Fall back to `RecursiveCharacterTextSplitter` with `chunk_size=600, chunk_overlap=80` if no
  declaration boundaries found.
- Metadata: `start_line`, `end_line`.

**Config / markup group (HTML, XML, YAML, TOML, JSON, ENV, SQL, GraphQL, Makefile, Dockerfile, Shell):**

- Read as UTF-8 text.
- Split at top-level structure boundaries:
  - HTML/XML: split at top-level tags (direct children of `<body>` or root).
  - YAML/TOML: split at top-level key blocks.
  - SQL: split at statement boundaries (`;`).
  - Shell/Makefile/Dockerfile: split at function or target definitions.
  - ENV: each line is one chunk (one key-value pair per chunk).
- Metadata: `tag_name` (HTML/XML), `key_name` (YAML/TOML/ENV), `statement_index` (SQL).

**Parent-child for code:** Each function/class chunk is the **child**. Its **parent** is the
file-level chunk (all imports + class/function signatures without bodies, ~100 tokens). When a
child chunk is matched, retrieve its parent for LLM context.

---

### 4.3 Mandatory Metadata Fields Per Chunk

Every chunk produced by any handler **must** carry these metadata fields before being passed to `Embedder`.
The `Embedder` will attach them as `Document.metadata` in the FAISS `Document` object.

| Field               | Type        | Source                                         | Example                                                                                          |
| ------------------- | ----------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `source_file`       | str         | `FileEntry.filename`                           | `"lecture_notes.pdf"`                                                                            |
| `file_extension`    | str         | `FileEntry.extension`                          | `".pdf"`                                                                                         |
| `file_type`         | str         | Handler classification                         | `"document"`, `"image"`, `"structured"`, `"code"`, `"config"`, `"presentation"`, `"spreadsheet"` |
| `chunk_index`       | int         | Sequence within file                           | `0`, `1`, `2` …                                                                                  |
| `chunk_role`        | str         | `"child"`, `"parent"`, `"globals"`, `"single"` | `"child"`                                                                                        |
| `parent_chunk_id`   | str or null | Parent chunk's `source_file:chunk_index`       | `"lecture_notes.pdf:0"`                                                                          |
| `header_context`    | str or null | Most recent heading (DOCX/PPTX/HTML)           | `"Chapter 3: Neural Networks"`                                                                   |
| `page_number`       | int or null | PDF page, PPTX slide                           | `4`                                                                                              |
| `sheet_name`        | str or null | XLSX/ODS sheet                                 | `"Q2 Revenue"`                                                                                   |
| `row_range`         | str or null | XLSX/CSV row range                             | `"21-40"`                                                                                        |
| `function_name`     | str or null | Python/JS AST                                  | `"process_video_task"`                                                                           |
| `class_name`        | str or null | Python/JS AST                                  | `"VectorStoreManager"`                                                                           |
| `start_line`        | int or null | Code handlers                                  | `42`                                                                                             |
| `end_line`          | int or null | Code handlers                                  | `89`                                                                                             |
| `vision_generated`  | bool        | ImageHandler                                   | `true` / `false`                                                                                 |
| `date_modified`     | str (ISO)   | `os.path.getmtime` on source file              | `"2026-05-18T12:00:00Z"`                                                                         |
| `study_material_id` | str or null | `StudyMaterial.pk`                             | `"sm_42"`                                                                                        |
| `course_id`         | str or null | Attached course pk when merging                | `"course_7"`                                                                                     |

**[CONSTRAINT]:** These fields must be present on every chunk. Null is acceptable for fields
that do not apply (e.g. `page_number` is null for a `.py` file). An absent field is a bug.

---

### 4.4 Hybrid Search — BM25 + Dense FAISS via RRF

**[DECISION]:** Implement in Phase 2. The dense FAISS path is preserved exactly. BM25 is added
as a parallel index stored alongside FAISS.

**At ingestion:** After saving the FAISS index, serialize a `bm25_index.pkl` file in the same
vectorstore directory using `rank_bm25.BM25Okapi`. Store the corpus (list of tokenized chunk
texts) and the corresponding chunk metadata list.

**At retrieval:** `VectorStoreManager.query()` will:

1. Run FAISS `similarity_search_with_score(query, k=VECTORSTORE_TOP_K * 2)` → dense results.
2. Run BM25 `get_scores(tokenized_query)` → sparse results.
3. Merge via Reciprocal Rank Fusion:
   `rrf_score(doc) = 1/(k + dense_rank) + 1/(k + sparse_rank)` where `k=60` (standard RRF constant).
4. Return top `VECTORSTORE_TOP_K` chunks by RRF score.
5. If `bm25_index.pkl` does not exist (vectorstore predates Phase 2), fall back to dense-only search.
   Log a `WARNING` with the vectorstore path so the operator knows it needs rebuilding.

**New dependency:** `rank-bm25` → add to `requirements.txt`.

---

### 4.5 Self-Querying Retriever (Phase 3)

Before hitting the vectorstore, a lightweight LLM call routes the query by generating a metadata filter.

**Implemented as** a new method `VectorStoreManager.route_query(question: str) -> dict` that calls
GPT-4o-mini with a structured prompt:

```
Given the user question below, output a JSON object with these optional filter fields:
- file_type: one of ["document", "image", "structured", "code", "config", "presentation", "spreadsheet"] or null
- file_extension: a specific extension like ".py" or ".env" or null
- function_name: if the question is about a specific function, its name, or null

Output only valid JSON. No explanation.

Question: {question}
```

The returned JSON is used as a FAISS metadata filter in `similarity_search_with_score()`.
Gate behind `SELF_QUERY_ROUTING_ENABLED` setting (default `False`). If the LLM returns invalid
JSON or all-null fields, skip filtering and run a full search.

---

## 5. Exact File-Level Plan

> Execute in this exact order within each phase. Read each file before editing it.

### Phase 1 — Modality-Aware Ingestion (Foundation)

Dependencies: None. Must complete before Phase 2.

| #    | File                                                      | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Why                                                                      | New deps                                                       | Risk                                                                         | Verification                                                                                                                                                |
| ---- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.1  | `apps/core/services/modality_router.py`                   | **Create new file.** `ModalityRouter` class with `route(file_entry, converted_text) -> List[EnrichedChunk]`. `EnrichedChunk = dataclass(text: str, metadata: dict)`. Dispatch to DocumentHandler, ImageHandler, StructuredHandler, CodeHandler based on `file_entry.extension`.                                                                                                                                                                                                                                      | Single dispatch point; keeps `file_converter.py` and `embedder.py` clean | None                                                           | Low — new file                                                               | Import in Django shell; call `ModalityRouter().route(mock_file_entry, "test text")` and confirm output type                                                 |
| 1.2  | `apps/core/services/modality_router.py`                   | **Add DocumentHandler** inside same file (inner class or module-level function). Paragraph-split + section heading detection for DOCX/PPTX. Page-split for PDF. Parent-child chunk generation.                                                                                                                                                                                                                                                                                                                       | Document structure preservation                                          | None                                                           | Low                                                                          | Run against a test DOCX; confirm `header_context` and `page_number` in chunk metadata                                                                       |
| 1.3  | `apps/core/services/modality_router.py`                   | **Add ImageHandler** inside same file. GPT-4o base64 vision call → description text. `pytesseract` fallback. SVG lxml text extraction. Gate behind `IMAGE_VLM_ENABLED` setting.                                                                                                                                                                                                                                                                                                                                      | Replace noisy OCR with semantic image descriptions                       | None (uses existing `openai` package + `lxml` already in deps) | Medium — adds OpenAI vision cost. Test with `IMAGE_VLM_ENABLED=False` first. | Upload a PNG; confirm `vision_generated: true` and meaningful description in returned chunk text                                                            |
| 1.4  | `apps/core/services/modality_router.py`                   | **Add StructuredHandler** inside same file. Row serialization for XLSX/CSV. Key-value chunking for JSON.                                                                                                                                                                                                                                                                                                                                                                                                             | Tabular data integrity                                                   | None                                                           | Low                                                                          | Run against a 3-column CSV; confirm row serialization in chunk text                                                                                         |
| 1.5  | `apps/core/services/modality_router.py`                   | **Add CodeHandler** inside same file. Python AST-based chunking via `ast` stdlib. Line-boundary heuristic for other languages. Config/markup group. Parent-child for Python.                                                                                                                                                                                                                                                                                                                                         | Code split at logical boundaries                                         | None                                                           | Low                                                                          | Parse a `.py` file; confirm each chunk is a complete function/class; confirm `function_name` in metadata                                                    |
| 1.6  | `apps/core/services/embedder.py`                          | **Add `embed_chunks(chunks: List[EnrichedChunk], vectorstore_path: str) -> EmbedResult` method** alongside existing `create_vectorstore()`. Accepts pre-split chunks with per-chunk metadata dicts; skips internal `RecursiveCharacterTextSplitter` for this path. Calls existing async batch loop (`_embed_all`) unchanged. Attaches per-chunk metadata to `Document` objects before FAISS save. Existing `create_vectorstore()` method stays intact for video/transcript path.                                        | Preserve existing async infrastructure; add metadata-aware path          | None                                                           | Low — additive method only                                                   | Django shell: call `embed_chunks([EnrichedChunk("test", {"source_file": "x.py", ...})], "/tmp/test_vs")`; load FAISS; confirm `docstore._dict` has metadata |
| 1.7  | `apps/core/services/study_material_processor.py` (478 lines) | **Replace `_embed_with_segmentation()` path with `ModalityRouter → Embedder.embed_chunks()` call.** Import `ModalityRouter`. After `FileConverter` produces text, pass `file_entry + text` to `ModalityRouter.route()`, then pass resulting `EnrichedChunk` list to `Embedder.embed_chunks()`. `_embed_with_segmentation()` is updated to accept and use `EnrichedChunk` list instead of raw text. The segmentation logic (split into segments of `MAX_CHUNKS_PER_SEGMENT`, merge FAISS indexes) is preserved. Preserve per-file `StudyMaterialFile` status/error update logic exactly. | Wire the new pipeline into SM processing                                 | None                                                           | Medium — core pipeline change. Verify retry behavior unchanged.              | Upload a ZIP with PDF + XLSX + .py file. Confirm each `StudyMaterialFile` completes. Confirm chunks have metadata via Django shell FAISS inspection.        |
| 1.8  | `apps/core/services/file_converter.py`                    | **Post-OCR cleanup** (from v1 plan, still required): after `pytesseract` output, collapse repeated whitespace (`re.sub(r'\s+', ' ')`), strip non-printable chars (`re.sub(r'[^\x20-\x7E\n]', '')`), strip isolated single-character lines.                                                                                                                                                                                                                                                                           | Reduce OCR fallback noise                                                | None                                                           | Low                                                                          | Before/after text diff on an image file via Django shell                                                                                                    |
| 1.9  | `apps/core/services/vectorstore.py`                       | **Rewrite `QA_PROMPT`** for groundedness, source citation, and source-type separation. New prompt must instruct the model to: (a) answer only from provided context, (b) cite `source_file` from metadata when available, (c) state "The provided context does not contain information about this topic." when context is insufficient, (d) if context contains both `file_type: "video_transcript"` and study material chunks, separate the answer into "**From video:**" and "**From study materials:**" sections. | Highest-impact single change for answer quality                          | None                                                           | Low — prompt only                                                            | Test: query with out-of-context question → confirm refusal phrase. Test: query merged VS → confirm section separation.                                      |
| 1.10 | `apps/core/services/vectorstore.py`                       | **Add empty-vectorstore guard.** Before `FAISS.load_local()`, check `os.path.exists(vectorstore_path)` and that `index.faiss` exists inside it. Return a `QueryResult` with `answer="Vectorstore not found."`, `error="missing_vectorstore"`, and log at `ERROR` level.                                                                                                                                                                                                                                              | Prevent silent 500 errors                                                | None                                                           | None                                                                         | Delete a vectorstore directory; query it; confirm clean error response                                                                                      |
| 1.11 | `config/settings.py`                                      | **Add constants:** `VECTORSTORE_TOP_K = 6`, `VECTORSTORE_SCORE_THRESHOLD = None`, `QUERY_REWRITE_ENABLED = False`, `SELF_QUERY_ROUTING_ENABLED = False`, `IMAGE_VLM_ENABLED = True`                                                                                                                                                                                                                                                                                                                                  | Central config for all new retrieval behavior                            | None                                                           | None                                                                         | `python manage.py shell` → `from django.conf import settings; print(settings.VECTORSTORE_TOP_K)`                                                            |
| 1.12 | `apps/core/api/serializers/study_material_serializers.py` | **ALREADY COMPLETE.** `error` is in `StudyMaterialFileSerializer.fields` (line 24) and `error_log` is in `StudyMaterialSerializer.fields` (line 38). No change needed.                                                                                                                                                                                                                                                                                                                                                | Already done                                                             | None                                                           | None                                                                         | Already verified                                                                                                                                            |

---

### Phase 2 — Retrieval Quality

Dependencies: Phase 1 must be complete (metadata must exist in FAISS for filtering to work).

| #   | File                                          | Change                                                                                                                                                                                                                                                                                                                                                          | Why                                                     | New deps                                | Risk                                                                      | Verification                                                                                       |
| --- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 2.1 | `apps/core/services/embedder.py`              | **In `embed_chunks()`, also build and save `bm25_index.pkl`** alongside FAISS. Use `rank_bm25.BM25Okapi` on tokenized chunk texts. Serialize with `pickle`.                                                                                                                                                                                                     | Hybrid search requires BM25 at ingestion time           | `rank-bm25` → add to `requirements.txt` | Low — additive save step                                                  | After SM processing, confirm `bm25_index.pkl` exists in vectorstore directory                      |
| 2.2 | `apps/core/services/vectorstore.py`           | **Switch from `similarity_search()` to `similarity_search_with_score()`.** Use `VECTORSTORE_TOP_K * 2` for initial FAISS retrieval (over-fetch for RRF). Implement RRF merge with BM25 (`bm25_index.pkl` if present). Return final top `VECTORSTORE_TOP_K` results. Fall back to dense-only if `bm25_index.pkl` missing (log `WARNING`).                        | Hybrid search for exact-match recall                    | None                                    | Medium — changes retrieval output order; verify existing tests still pass | Query with an exact keyword that appears in a `.env` chunk; confirm it surfaces in results         |
| 2.3 | `apps/core/services/vectorstore.py`           | **Parent-child retrieval.** After RRF ranking, for any result with `chunk_role: "child"`, load its parent chunk by running a second `similarity_search()` filtered by `source_file == result.metadata["source_file"]` and `chunk_role == "parent"`. Replace the child text with parent text in the LLM context, but keep child metadata in `retrieved_sources`. | Pass surrounding context to LLM                         | None                                    | Medium — adds a second FAISS call per matched child chunk                 | Query a PDF; confirm `retrieved_sources` shows child metadata but LLM context contains parent text |
| 2.4 | `apps/core/services/vectorstore.py`           | **Surface `retrieved_sources` and `retrieved_chunk_count` in `QueryResult` dataclass.** `retrieved_sources: List[dict]` — each dict contains `source_file`, `file_type`, `chunk_index`, `chunk_role`, `score`, `header_context`, `page_number`, `function_name`.                                                                                                | Source transparency                                     | None                                    | Low — additive field                                                      | Inspect `QueryResult` in Django shell after a query                                                |
| 2.5 | `apps/core/api/views/query_views.py`          | **Return `retrieved_sources` and `retrieved_chunk_count`** in both `VideoQueryAPI` and `CourseQueryAPI` responses. Add optional `filter_source_file` request param passed to `VectorStoreManager`.                                                                                                                                                              | Source transparency in API; file-scoped queries         | None                                    | Low — additive                                                            | Call `POST /query/course/`; confirm `retrieved_sources` in JSON                                    |
| 2.6 | `apps/core/api/views/study_material_views.py` | **Return `retrieved_sources` and `retrieved_chunk_count`** in `StudyMaterialQueryAPI`. Add optional `filter_file_type` and `filter_source_file` params.                                                                                                                                                                                                         | Source transparency; allow "only search slides" queries | None                                    | Low — additive                                                            | Call `POST /study-materials/<pk>/query/`; confirm `retrieved_sources`                              |
| 2.7 | `requirements.txt`                            | **Add `rank-bm25`.**                                                                                                                                                                                                                                                                                                                                            | Required for BM25 hybrid search                         | `rank-bm25`                             | Low                                                                       | `pip install rank-bm25 --break-system-packages` and confirm import                                 |

---

### Phase 3 — Observability, Routing, and Evaluation

Dependencies: Phase 1 required. Phase 2 recommended but not strictly required for items 3.1–3.3.

| #   | File                                              | Change                                                                                                                                                                                                                                                                                                                                                                     | Why                                           | New deps | Risk                                                  | Verification                                                                                                  |
| --- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- | -------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| 3.1 | `apps/core/services/vectorstore.py`               | **Per-query retrieval logging.** After each query, log at `INFO`: `vectorstore_path`, `top_k`, `retrieved_chunk_count`, `top_score`, `model_name`, `latency_ms`. Log at `WARNING` if all scores are below `VECTORSTORE_SCORE_THRESHOLD` (when set).                                                                                                                        | Retrieval observability                       | None     | None                                                  | Run query; `grep INFO` in rotating log file                                                                   |
| 3.2 | `apps/core/services/vectorstore.py`               | **Token usage logging.** After `ChatOpenAI` call, extract `response.response_metadata["token_usage"]` (LangChain 0.2+). Log `prompt_tokens`, `completion_tokens`, `total_tokens` at `INFO`. If key absent, fall back to `tiktoken` estimate on prompt string.                                                                                                              | Cost tracking per query                       | None     | Low                                                   | Run query; confirm token fields in log                                                                        |
| 3.3 | `apps/core/services/vectorstore.py`               | **Query rewriting (when `QUERY_REWRITE_ENABLED=True`).** Before embedding the question, call GPT-4o-mini with: `"Rewrite the following search question to be more specific and retrieve relevant technical content. Output only the rewritten question.\n\nQuestion: {question}"`. Use rewritten question for FAISS/BM25 retrieval. Pass original question to `QA_PROMPT`. | Improve embedding of short/vague questions    | None     | Low — gated behind setting                            | Set `QUERY_REWRITE_ENABLED=True`; query with "explain this"; confirm rewritten question in logs               |
| 3.4 | `apps/core/services/vectorstore.py`               | **Self-querying router (when `SELF_QUERY_ROUTING_ENABLED=True`).** Implement `route_query()` as described in Section 4.5. Apply returned metadata filter to FAISS `similarity_search_with_score`. Skip filter if LLM returns invalid JSON or all-null.                                                                                                                     | Metadata-filtered retrieval for typed queries | None     | Medium — LLM-in-loop; adds latency. Gated by setting. | Enable setting; ask "what are the database credentials"; confirm `file_type: "config"` filter applied in logs |
| 3.5 | `dashboard/src/components/StudyMaterialsView.tsx` | **Add `retrieved_sources` panel** below query answer. For each source: show `source_file` (bold), `file_type` badge, `score` (2 decimal places), `header_context` or `function_name` if present, `page_number` if present. Collapsible section.                                                                                                                            | User-visible source attribution               | None     | Low                                                   | Run query in dashboard; expand sources panel                                                                  |
| 3.6 | `dashboard/src/components/StudyMaterialsView.tsx` | **Add per-file error tooltip.** In the files table, when a file has status `failed`, show a `⚠` icon with the `error` field as tooltip text.                                                                                                                                                                                                                               | Operator visibility without Django admin      | None     | None                                                  | Force a file failure; open dashboard files list; confirm tooltip                                              |
| 3.7 | `notes/rag_eval/test_questions.json`              | **Create** with 3 question sets: (a) 5 video transcript questions with `expected_source_type: "video_transcript"`, (b) 5 document questions with `expected_file_extension`, (c) 5 code questions with `expected_function_name`. Each entry: `{question, vectorstore_type, expected_source_file, expected_source_type, should_refuse: bool}`.                               | Regression test baseline                      | None     | None                                                  | JSON lints; entries are human-readable                                                                        |
| 3.8 | `notes/rag_eval/eval_runner.py`                   | **Create** standalone Django management script. For each test question: call the relevant query API locally, check `retrieved_sources` contains `expected_source_file`, check `answer` non-empty if `should_refuse=false`, check `answer` contains refusal phrase if `should_refuse=true`. Print PASS/FAIL per case.                                                       | Automated RAG regression                      | None     | None                                                  | Run against dev instance; all baseline cases should PASS                                                      |
| 3.9 | `notes/rag_eval/regression_cases.json`            | **Create** with known-bad cases: missing vectorstore path, empty FAISS index, ZIP with all-failed files, `include_study_materials=true` with no merged VS, query with no matching metadata filter. Each entry: `{case_id, description, expected_error_or_fallback}`.                                                                                                       | Regression coverage for edge cases            | None     | None                                                  | Cases are documentation; run manually                                                                         |

---

## 6. API And UI Changes

| Endpoint / UI                             | Proposed Change                                                                                            | Backward Compatible?             | Notes      |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------- | ---------- |
| `POST /query/video/`                      | Add `retrieved_sources` (list), `retrieved_chunk_count` (int)                                              | Yes — additive                   | Phase 2.5  |
| `POST /query/course/`                     | Add `retrieved_sources`, `retrieved_chunk_count`; optional `filter_source_file` param                      | Yes — additive                   | Phase 2.5  |
| `POST /study-materials/<pk>/query/`       | Add `retrieved_sources`, `retrieved_chunk_count`; optional `filter_file_type`, `filter_source_file` params | Yes — additive                   | Phase 2.6  |
| `GET /study-materials/<pk>/files/`        | Ensure `error` field present in `StudyMaterialFileSerializer`                                              | Yes — model field already exists | Phase 1.12 |
| `GET /study-materials/<id>/status/`       | Add `error_log` to `StudyMaterialSerializer`                                                               | Yes — additive                   | Phase 1.12 |
| `StudyMaterialsView.tsx` — query response | Add collapsible `retrieved_sources` panel                                                                  | Yes — display only               | Phase 3.5  |
| `StudyMaterialsView.tsx` — files table    | Add `⚠` error tooltip on failed files                                                                      | Yes — display only               | Phase 3.6  |

---

## 7. Testing Checklist

### Phase 1 — Required Before Marking Complete

- [ ] Upload a ZIP containing: 1 PDF (multi-page), 1 DOCX (with headings), 1 PPTX (3+ slides), 1 XLSX (2 sheets), 1 CSV, 1 `.py` file, 1 `.js` file, 1 PNG image
- [ ] For each file above, confirm the corresponding `StudyMaterialFile` record completes with status `completed` and a non-zero `chunk_count`
- [ ] Open the FAISS vectorstore in Django shell (`FAISS.load_local(path, embeddings)`), inspect 3 random docs, confirm all 7 mandatory metadata fields are present and non-null where applicable
- [ ] Query the SM directly; confirm `answer` cites `source_file` from metadata
- [ ] Submit a question whose answer is not in any vectorstore; confirm response contains `"The provided context does not contain information about this topic."`
- [ ] Submit a question answered by both a video transcript chunk and a study material chunk (use merged VS); confirm answer has "**From video:**" and "**From study materials:**" sections
- [ ] Delete a vectorstore directory; query it; confirm response is `{"answer": "Vectorstore not found.", "error": "missing_vectorstore"}` with HTTP 200 (not 500)
- [ ] Force a file failure in a ZIP (include an unreadable binary); confirm the failed `StudyMaterialFile` has a non-empty `error` field via `GET /study-materials/<pk>/files/`
- [ ] Retry the above SM; confirm the failed file is retried and all already-completed files are skipped
- [ ] Confirm `IMAGE_VLM_ENABLED=False` falls back to `pytesseract` without error

### Phase 2 — Required Before Marking Complete

- [ ] After processing a SM, confirm `bm25_index.pkl` exists in the vectorstore directory
- [ ] Query with an exact keyword from a `.env` file chunk; confirm it appears in `retrieved_sources`
- [ ] Query a PDF SM; confirm `retrieved_sources` shows child chunk metadata but LLM answer text draws from the parent context
- [ ] Call `POST /query/course/` and confirm `retrieved_sources` is present in JSON with `score`, `source_file`, `file_type` per entry
- [ ] Call with `filter_source_file=specific_file.pdf`; confirm only chunks from that file appear in `retrieved_sources`
- [ ] Load a vectorstore that predates Phase 2 (no `bm25_index.pkl`); query it; confirm graceful dense-only fallback and `WARNING` log entry

### Phase 3 — Required Before Marking Complete

- [ ] Run a query; `grep INFO` in rotating log; confirm `vectorstore_path`, `top_k`, `retrieved_chunk_count`, `top_score`, `latency_ms`, `prompt_tokens`, `completion_tokens` all present
- [ ] Set `QUERY_REWRITE_ENABLED=True`; submit a 2-word query; confirm rewritten question in logs
- [ ] Set `SELF_QUERY_ROUTING_ENABLED=True`; query "what are the database credentials?"; confirm `file_type: "config"` filter in logs
- [ ] Open dashboard StudyMaterialsView; run a query; confirm sources panel appears and is collapsible
- [ ] Force a file failure; open dashboard files table; confirm `⚠` icon with error tooltip
- [ ] Run `notes/rag_eval/eval_runner.py`; confirm all baseline test cases PASS

---

## 8. Dependency Changes Summary

| Package     | Phase   | Reason                              | Install command                                 |
| ----------- | ------- | ----------------------------------- | ----------------------------------------------- |
| `rank-bm25` | Phase 2 | BM25 sparse index for hybrid search | `pip install rank-bm25 --break-system-packages` |

All other changes use existing dependencies already in `requirements.txt`:
`openai` (vision calls), `ast` (stdlib), `lxml` (already listed for SVG), `pickle` (stdlib),
`tiktoken` (already used in embedder), `pytesseract` + `Pillow` (already listed).

---

## 9. Approval Gate

**No source files have been modified. This is a planning document only.**

### Files to be created (new)

- `apps/core/services/modality_router.py`
- `notes/rag_eval/test_questions.json`
- `notes/rag_eval/eval_runner.py`
- `notes/rag_eval/regression_cases.json`

### Files to be modified

**Phase 1:**
`apps/core/services/embedder.py` · `apps/core/services/study_material_processor.py` · `apps/core/services/file_converter.py` · `apps/core/services/vectorstore.py` · `config/settings.py` · `apps/core/api/serializers/study_material_serializers.py`

**Phase 2:**
`apps/core/services/embedder.py` · `apps/core/services/vectorstore.py` · `apps/core/api/views/query_views.py` · `apps/core/api/views/study_material_views.py` · `requirements.txt`

**Phase 3:**
`apps/core/services/vectorstore.py` · `dashboard/src/components/StudyMaterialsView.tsx`

### Files explicitly not modified

`config/celery.py` · `apps/core/tasks/study_material_tasks.py` · `apps/core/tasks/processing.py` · `apps/core/models/*` · `apps/core/services/aggregator.py` · `apps/core/services/zip_extractor.py`

---

**Shall I apply this plan? Reply `apply phase 1`, `apply phase 2`, `apply phase 3`, or `revise plan`.**

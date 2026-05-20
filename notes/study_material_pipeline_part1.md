# Study Material Pipeline — Part 1: Architecture & Services
> **Last updated:** 2026-05-19 — Reflects the fully working, production-tested implementation.

---

## What Was Solved

| Problem | Solution |
|---|---|
| Celery 40-min hard timeout on large zips | Per-file `StudyMaterialFile` checkpointing — retry skips completed files |
| OpenAI `400 Bad Request` on oversized batches | `tiktoken` exact token counting + auto-split retry in `_embed_batch()` |
| Token-per-minute rate limit exhaustion | `OpenAIRateLimiter` dual rolling-window (TPM + RPM) with lock-released sleeps |
| 50k+ chunk files too large for one embedding call | `_embed_with_segmentation()` — splits into 50k-chunk segments, merges FAISS |
| Log file growing unbounded | `_CustomTimedRotatingFileHandler` — daily rotation, 10-day backup, renamed files |

---

## Storage Architecture

```
media/
├── course_vectorstores/
│   └── {course_id}_{course_slug}/                        ← ORIGINAL (never touched)
│       ├── index.faiss
│       ├── index.pkl
│       └── {cid}_{cslug}_{smid}_{smslug}.vectorstore/   ← MERGED (delete+rebuild on SM replace)
│           ├── index.faiss
│           └── index.pkl
│
├── study_materials/{sm_slug}/
│   └── text/{original_filename}.txt                      ← converted text (kept; raw files deleted)
│
└── study_materials_vectorstore/
    ├── complete_vectorstores/
    │   └── {sm_id}_{sm_slug}_vectorstore/                ← merged SM VS (all files combined)
    │       ├── index.faiss
    │       └── index.pkl
    └── individual_vectorstores/
        └── {sm_id}_{stem}_vectorstore/                   ← per-file VS (one per extracted file)
            ├── index.faiss
            └── index.pkl
```

> [!NOTE]
> `{sm_slug}` and `{stem}` are produced by `re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_')`.
> Per-file vectorstores are prefixed with `{sm_id}_` to prevent collisions when two SMs share a filename.

**Path examples (SM id=3, name="Week 1 Notes", Course id=5, "Python Bootcamp"):**
- Text file: `study_materials/Week_1_Notes/text/notes.txt`
- Per-file VS: `study_materials_vectorstore/individual_vectorstores/3_notes_vectorstore/`
- Full SM VS: `study_materials_vectorstore/complete_vectorstores/3_Week_1_Notes_vectorstore/`
- Course+SM merged VS: `course_vectorstores/5_Python_Bootcamp/5_Python_Bootcamp_3_Week_1_Notes.vectorstore/`

---

## 1 — Data Models

### `apps/core/models/study_material.py`

```python
class StudyMaterial(models.Model):
    STATUS_PENDING    = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED  = 'completed'
    STATUS_FAILED     = 'failed'

    name                 = models.CharField(max_length=255, unique=True)
    description          = models.TextField(blank=True, default='')
    file_path            = models.CharField(max_length=500, blank=True, default='')
    status               = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    files_count          = models.IntegerField(default=0)
    processed_files      = models.IntegerField(default=0)   # incremented atomically via F()
    vectorstore_location = models.CharField(max_length=500, blank=True, default='')
    # ^ relative path to complete_vectorstores/{sm_id}_{slug}_vectorstore/
    error_log            = models.TextField(blank=True, default='')
    created_at           = models.DateTimeField(auto_now_add=True)
    attached_to_courses  = models.ManyToManyField('Course', blank=True)

    class Meta:
        ordering = ['-created_at']
```

### `apps/core/models/study_material_file.py`

```python
class StudyMaterialFile(models.Model):
    STATUS_PENDING    = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED  = 'completed'
    STATUS_FAILED     = 'failed'
    STATUS_SKIPPED    = 'skipped'

    study_material   = models.ForeignKey(StudyMaterial, on_delete=models.CASCADE, related_name='files')
    original_name    = models.CharField(max_length=500)    # e.g. "notes.pdf"
    relative_path    = models.CharField(max_length=1000)   # e.g. "lectures/week1/notes.pdf"
    file_type        = models.CharField(max_length=20, blank=True, default='')  # e.g. ".pdf"
    file_size        = models.BigIntegerField(default=0)
    text_path        = models.CharField(max_length=500, blank=True, default='')  # relative .txt path
    vectorstore_path = models.CharField(max_length=500, blank=True, default='')  # relative VS path
    chunk_count      = models.IntegerField(default=0)
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error            = models.TextField(blank=True, default='')
    created_at       = models.DateTimeField(auto_now_add=True)
    processed_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['study_material', 'status'])]
```

### `apps/core/models/course.py` — Study-material fields

```python
# Study material attachment
study_material          = models.JSONField(null=True, blank=True)
# e.g. {"id": 3, "name": "Week 1 Notes", "description": "..."}

merged_vectorstore_path = models.CharField(max_length=500, blank=True, default='')
# relative: course_vectorstores/{cid}_{cslug}/{cid}_{cslug}_{smid}_{smslug}.vectorstore

study_materials_history = models.JSONField(default=list, blank=True)
# audit log of replaced SMs
```

---

## 2 — Zip Extractor Service

### `apps/core/services/zip_extractor.py`

```python
@dataclass
class FileEntry:
    abs_path:      str
    relative_path: str   # path inside zip (sanitised)
    ext:           str   # lowercase extension e.g. ".pdf"
    size:          int   # bytes

class ZipExtractor:
    def extract(self, zip_path: str, extract_dir: str) -> List[FileEntry]: ...
    def _extract_recursive(self, zip_path, extract_dir, entries, prefix): ...
    @staticmethod
    def _sanitise(path: str) -> str | None: ...
```

**Key behaviours:**
- Nested `.zip` members are extracted recursively, deleted after recursion.
- `_sanitise()` strips any `../` components (path traversal protection).
- Returns a flat `List[FileEntry]` regardless of archive depth.
- Directories (`member.endswith('/')`) are created but not yielded as entries.

---

## 3 — File Converter Service

### `apps/core/services/file_converter.py`

All library imports are inline (inside each `_convert_*` method) — no guarding at module level needed; `ImportError` surfaces as a `ConversionResult(success=False, error=...)`.

```python
@dataclass
class ConversionResult:
    success: bool
    text:    str   = ''
    error:   str   = ''
    skipped: bool  = False
```

**Supported formats:**

| Category | Extensions | Library |
|---|---|---|
| PDF | `.pdf` | `pdfplumber` |
| Word | `.docx`, `.doc` | `python-docx` |
| PowerPoint | `.pptx`, `.ppt` | `python-pptx` |
| Plain text / Markdown | `.txt`, `.md` | built-in |
| RTF | `.rtf` | `striprtf` |
| Excel | `.xlsx` | `openpyxl` (read_only=True, data_only=True) |
| Excel legacy | `.xls` | `xlrd` |
| CSV | `.csv` | built-in `csv` |
| ODS | `.ods` | `odfpy` |
| ODP | `.odp` | `odfpy` |
| Code / Config | `.py .js .ts .jsx .tsx .vue .svelte .html .css .scss .sass .java .go .rs .cpp .c .h .cs .swift .kt .php .rb .dart .json .yaml .yml .toml .xml .env .sh .bash .zsh .dockerfile .makefile .mk .graphql .gql .sql` | built-in (UTF-8) |
| Image OCR | `.jpg`, `.jpeg`, `.png` | `Pillow` + `pytesseract` (blank → placeholder) |
| SVG | `.svg` | `lxml.etree` (text nodes only) |
| **Skipped** | `.mp4 .mp3 .mov .avi .zip` | — `skipped=True` |
| **Skipped** | anything else | — `skipped=True` |

**Logging pattern:**
```
INFO  [FileConverter] .pdf  → extracted 4,821 chars from notes.pdf
INFO  [FileConverter] .xlsx → skipped
WARN  [FileConverter] .docx → failed for report.docx: <error>
```

---

## 4 — Embedder Service

### `apps/core/services/embedder.py`

**Model:** `text-embedding-3-small`

**Tuning constants (current working values):**

```python
EMBED_MODEL           = "text-embedding-3-small"
MAX_BATCH_INPUTS      = 2048       # OpenAI hard cap on array length
MAX_TOKENS_PER_BATCH  = 280_000    # stay safely under OpenAI's 300k per-request cap
BATCH_DELAY           = 0.5        # seconds between sequential batches
MAX_RETRIES           = 5          # 429 retry attempts
RETRY_BASE_DELAY      = 15         # seconds for first retry; doubles each attempt
TPM_LIMIT             = 980_000    # 98% of Tier 1 1M TPM
RPM_LIMIT             = 2_800      # 93% of Tier 1 3,000 RPM
```

**`OpenAIRateLimiter` — dual rolling-window (TPM + RPM):**
- Two logs: `_token_log: List[(ts, count)]` for TPM, `_req_log: List[ts]` for RPM.
- `asyncio.Lock` is **released before every `asyncio.sleep()`** — no convoy effect.
- Each waiter independently re-checks budget after waking.

**`Embedder.create_vectorstore(transcript_text, save_path, metadata=None) → EmbedResult`:**
1. `text_splitter.split_text(text)` → `chunks`
2. `asyncio.run(_embed_all(chunks))` → `vectors` (list of float lists)
3. `FAISS.from_embeddings(text_embedding_pairs, embedding=self.embeddings, metadatas=...)`
4. `vectorstore.save_local(save_path)`

**`_plan_batches(chunks)` — tiktoken exact counting:**
```python
# Uses enc.encode_batch(chunks, disallowed_special=()) — parallel Rust path, < 100ms for 50k chunks
# Builds batches keeping both MAX_BATCH_INPUTS and MAX_TOKENS_PER_BATCH constraints
```

**`_embed_batch()` — retry & auto-split:**
- `429` → exponential backoff (`RETRY_BASE_DELAY * 2^(attempt-1)`)
- `400` with `'maximum request size'` or `'max_tokens_per_request'` → split batch in half, recurse

**`EmbedResult` dataclass:**
```python
@dataclass
class EmbedResult:
    success:          bool
    vectorstore_path: str = ''
    chunk_count:      int = 0
    error:            str = ''
```

**`Embedder` constructor params (working defaults):**
```python
Embedder(
    openai_api_key = settings.OPENAI_API_KEY,
    chunk_size     = 1000,
    chunk_overlap  = 200,
)
# text_splitter separators: ['\n\n', '\n', '. ', ' ', '']
```

---

## 5 — Study Material Processor

### `apps/core/services/study_material_processor.py`

**Segmentation constant:**
```python
MAX_CHUNKS_PER_SEGMENT = 50_000
# Files producing more chunks than this are split into segments, each embedded
# separately, then merged via FAISS.merge_from().
```

**Entry point:**
```python
class StudyMaterialProcessor:
    def __init__(self, openai_api_key: str = ''):
        # Falls back to settings.OPENAI_API_KEY
        self.extractor = ZipExtractor()
        self.converter = FileConverter()
        self.embedder  = Embedder(openai_api_key=self.openai_api_key)

    def run(self, study_material: StudyMaterial) -> ProcessResult: ...
```

**4-phase pipeline:**

```
PHASE 1 — DISCOVERY  (only if sm.status == 'pending')
  ZipExtractor.extract(zip_path, raw_dir)  →  List[FileEntry]
  StudyMaterialFile.objects.bulk_create(smf_objects)   ← atomic transaction
  SM: files_count=N, processed_files=0, status='processing'
  Logging: "[Processor] Discovered N files → N StudyMaterialFile records created"

PHASE 2 — PER-FILE  (resumable — only processes status IN ('pending','failed'))
  For each SMF ordered by created_at:
    a. smf.status = 'processing'
    b. FileConverter.convert(FileEntry) → ConversionResult
    c. If conv.skipped  → smf.status='skipped'; continue
    d. If not conv.success → raise ValueError(conv.error)
    e. Write text → study_materials/{slug}/text/{stem}.txt
       (counter suffix added if name collision: {stem}_1.txt, {stem}_2.txt, …)
    f. _embed_with_segmentation(text, vs_path, metadata) → EmbedResult
    g. smf: text_path, vectorstore_path, chunk_count, status='completed', processed_at
    h. SM: processed_files += 1  (atomic F() update)
    On SoftTimeLimitExceeded → re-raise (let Celery task handle checkpointing)
    On other exception → smf.status='failed', log WARNING, continue

PHASE 3 — MERGE  (all completed SMFs with vectorstore_path set)
  Iteratively FAISS.merge_from() per-file VSs
  Atomic save: write to {vs_path}.tmp → rename to final path (overwrites old if exists)
  Save → study_materials_vectorstore/complete_vectorstores/{sm_id}_{slug}_vectorstore/
  SM: status='completed', vectorstore_location=vs_relative

PHASE 4 — CLEANUP
  Delete original zip (sm.file_path)
  Delete each raw extracted file (smf.relative_path inside raw_dir)
  os.walk raw_dir bottom-up: rmdir empty subdirs (text/ dir is preserved)
```

**`_embed_with_segmentation(text, save_path, metadata)` — large-file handling:**
```python
chunks = embedder.text_splitter.split_text(text)
if len(chunks) <= MAX_CHUNKS_PER_SEGMENT:
    return embedder.create_vectorstore(text, save_path, metadata)

# Large: iterate segments of MAX_CHUNKS_PER_SEGMENT chunks
for seg_start in range(0, total, MAX_CHUNKS_PER_SEGMENT):
    seg_text = '\n\n'.join(chunks[seg_start:seg_start+MAX_CHUNKS_PER_SEGMENT])
    result = embedder.create_vectorstore(seg_text, seg_path, metadata)
    vs = FAISS.load_local(seg_path, embeddings, allow_dangerous_deserialization=True)
    merged_vs.merge_from(vs)
    shutil.rmtree(seg_path)   # clean up segment

merged_vs.save_local(save_path)
```

**`ProcessResult` dataclass:**
```python
@dataclass
class ProcessResult:
    success:              bool
    study_material_id:    int = 0
    files_count:          int = 0
    processed_files:      int = 0
    vectorstore_location: str = ''
    error:                str = ''
```

---

## 6 — Study Material Merger

### `apps/core/services/study_material_merger.py`

```python
@dataclass
class MergeResult:
    success:         bool
    merged_path:     str = ''    # absolute
    merged_relative: str = ''    # relative to MEDIA_ROOT
    error:           str = ''

class StudyMaterialMerger:
    def __init__(self, openai_api_key: str = ''):
        self.embeddings = OpenAIEmbeddings(openai_api_key=...)

    @staticmethod
    def _slugify(text) -> str:
        return re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_')

    # Path helpers
    @staticmethod
    def get_merged_vs_path(course, sm) -> str:       # absolute
    @staticmethod
    def get_merged_vs_relative(course, sm) -> str:   # relative to MEDIA_ROOT
    @staticmethod
    def get_course_vs_abs(course) -> str:            # handles both abs + relative stored paths

    def build(self, course, sm) -> MergeResult:
        # 1. FAISS.load_local(course_vs_path)
        # 2. FAISS.load_local(sm.vectorstore_location)
        # 3. course_vs.merge_from(sm_vs)
        # 4. Atomic save: tempfile.mkdtemp() → save_local(temp) → rename(temp, final_path)
        # 5. Return MergeResult

    def replace(self, course, sm) -> MergeResult:
        # shutil.rmtree(course.merged_vectorstore_path) if exists
        # self.build(course, sm)
```

> [!IMPORTANT]
> The original `course.vectorstore_path` (video-only index) is **never modified**.
> The merged vectorstore is saved as a sibling folder inside `course_vectorstores/{cid}_{cslug}/`.

**Folder naming:**
```
course_vectorstores/
└── {course.id}_{course_slug}/
    ├── index.faiss                                          ← original (video-only), untouched
    ├── index.pkl
    └── {cid}_{cslug}_{smid}_{smslug}.vectorstore/          ← merged (course + SM)
        ├── index.faiss
        └── index.pkl
```

---

## File Map

```
apps/core/
├── models/
│   ├── study_material.py          STATUS constants + 6 fields + attached_to_courses M2M
│   ├── study_material_file.py     5 STATUS constants + 10 fields + composite index
│   ├── course.py                  study_material (JSON), merged_vectorstore_path, study_materials_history
│   └── __init__.py                exports StudyMaterial, StudyMaterialFile, Course, Video, Job, ApiLog
└── services/
    ├── zip_extractor.py           FileEntry dataclass + ZipExtractor (recursive, path-sanitised)
    ├── file_converter.py          ConversionResult + FileConverter (30+ formats, inline imports)
    ├── embedder.py                OpenAIRateLimiter + Embedder (tiktoken, async batching, auto-split)
    ├── study_material_processor.py  StudyMaterialProcessor (4-phase, segmentation, resumable)
    └── study_material_merger.py   StudyMaterialMerger (build / replace, atomic save)
```

---

## Required pip Packages

```bash
pip install pdfplumber python-pptx openpyxl xlrd python-docx striprtf odfpy \
            Pillow pytesseract lxml tiktoken aiohttp \
            langchain langchain-community langchain-openai faiss-cpu
```

> [!WARNING]
> `pytesseract` requires the system `tesseract-ocr` binary: `sudo apt install tesseract-ocr`
> Without it, image files produce a placeholder `[Image: filename.jpg]` rather than erroring.

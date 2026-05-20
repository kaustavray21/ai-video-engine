# Study Material Pipeline — Part 2: Tasks, APIs, Logging & Data Flow
> **Last updated:** 2026-05-19 — Reflects the fully working, production-tested implementation.

---

## 6 — Celery Task

### `apps/core/tasks/study_material_tasks.py`

**Current time limits (production values):**

```python
@shared_task(bind=True, soft_time_limit=14400, time_limit=15000, max_retries=0)
def process_study_material(self, study_material_id: int):
    """
    Resumable pipeline — skips already-completed files on retry.
    Delegates entirely to StudyMaterialProcessor.run(sm).
    """
    sm = StudyMaterial.objects.get(pk=study_material_id)
    processor = StudyMaterialProcessor()   # picks up settings.OPENAI_API_KEY
    result = processor.run(sm)
    return {
        'status': 'completed' if result.success else 'failed',
        'study_material_id': study_material_id,
        'files_count': result.files_count,
        'processed_files': result.processed_files,
        'vectorstore_location': result.vectorstore_location,
        'error': result.error,
    }

    # SoftTimeLimitExceeded handler:
    #   SM.status → 'failed', error_log → 'Soft time limit exceeded — retry to resume'
    #   Return {'status': 'failed', 'error': 'soft_time_limit_exceeded'}

    # Other exception handler:
    #   SM.status → 'failed', error_log → str(exc)
    #   Re-raise (Celery marks task as FAILURE)


@shared_task
def retry_study_material(study_material_id: int):
    """Re-queue failed SM — resumes from last checkpoint (skips completed files)."""
    StudyMaterial.objects.filter(pk=study_material_id).update(
        status=StudyMaterial.STATUS_PROCESSING,
        error_log='',
    )
    process_study_material.delay(study_material_id)
    return {'status': 'queued', 'study_material_id': study_material_id}
```

> [!IMPORTANT]
> `soft_time_limit=14400` (4 hours) and `time_limit=15000` (4h 10m) — tuned for large study material zips.
> The default `CELERY_TASK_SOFT_TIME_LIMIT = 1800` in `settings.py` only applies to **video** tasks.
> Per-task decorator values override the global setting.

> [!NOTE]
> `max_retries=0` — Celery auto-retry is disabled. Manual retry is done via the `/retry/` endpoint which calls `retry_study_material.delay(id)`. The processor's Phase 2 skips `status='completed'` files automatically.

**Celery worker settings (config/settings.py):**
```python
CELERY_BROKER_URL               = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND           = 'redis://localhost:6379/0'
CELERY_WORKER_CONCURRENCY       = 4
CELERY_WORKER_PREFETCH_MULTIPLIER = 1   # CRITICAL: prevents double-prefetch RAM spike
CELERY_WORKER_MAX_TASKS_PER_CHILD = 10  # recycle workers to reclaim FAISS/numpy leaks
CELERY_TASK_SOFT_TIME_LIMIT     = 1800  # global default (video tasks)
CELERY_TASK_TIME_LIMIT          = 2400  # global default (video tasks)
```

**Starting the worker:**
```bash
celery -A config worker --loglevel=info
```

---

## 7 — API Views

### `apps/core/api/views/study_material_views.py`

| Class | Method | Endpoint | Description |
|---|---|---|---|
| `StudyMaterialListAPI` | GET | `/api/study-materials/` | All SMs with file summary |
| `StudyMaterialUploadAPI` | POST | `/api/study-materials/upload/` | Save zip → create SM → dispatch Celery task |
| `StudyMaterialStatusAPI` | GET | `/api/study-materials/<pk>/status/` | SM status + per-file summary |
| `StudyMaterialFilesAPI` | GET | `/api/study-materials/<pk>/files/` | All `StudyMaterialFile` records for SM |
| `StudyMaterialQueryAPI` | POST | `/api/study-materials/<pk>/query/` | RAG against full SM vectorstore |
| `StudyMaterialRetryAPI` | POST | `/api/study-materials/<pk>/retry/` | Re-queue failed SM (resumes from checkpoint) |
| `StudyMaterialMergeAPI` | POST | `/api/study-materials/<pk>/merge-to-course/<course_id>/` | Merge SM VS into course VS |

**Upload request (multipart/form-data):**
```
POST /api/study-materials/upload/
Content-Type: multipart/form-data

name        = "Week 1 Notes"
description = "Lecture slides and exercises"
zip_file    = @/path/to/materials.zip
```

**`StudyMaterialStatusAPI` response:**
```json
{
  "id": 3,
  "name": "Week 1 Notes",
  "status": "processing",
  "files_count": 14,
  "processed_files": 9,
  "vectorstore_location": "",
  "created_at": "2026-05-16T14:21:29Z",
  "attached_courses": [{"id": 5, "title": "Python Bootcamp"}],
  "file_summary": {
    "completed": 9,
    "pending": 3,
    "failed": 1,
    "skipped": 1
  }
}
```

**Merge endpoint logic:**

| Scenario | Action | Saved to Course |
|---|---|---|
| `course.study_material == null` | `Merger.build()` | `study_material=JSON`, `merged_vectorstore_path=relative` |
| Same SM id as current | No-op | `{"message": "Already merged"}` |
| Different SM id | `Merger.replace()` → delete old folder, build new; append old to `study_materials_history` | Updated fields |

> [!IMPORTANT]
> Merge endpoint validates `sm.status == 'completed'` before proceeding.
> Course's original `vectorstore_path` is never touched by any merge operation.

---

## 8 — URL Registration

### `apps/core/api/urls.py`

```python
from apps.core.api.views.study_material_views import (
    StudyMaterialUploadAPI, StudyMaterialStatusAPI, StudyMaterialListAPI,
    StudyMaterialMergeAPI, StudyMaterialQueryAPI,
    StudyMaterialFilesAPI, StudyMaterialRetryAPI,
)

# ── Study Materials ──
path('study-materials/',                                          StudyMaterialListAPI.as_view(),  name='study_material_list'),
path('study-materials/upload/',                                   StudyMaterialUploadAPI.as_view(), name='study_material_upload'),
path('study-materials/<int:pk>/status/',                          StudyMaterialStatusAPI.as_view(), name='study_material_status'),
path('study-materials/<int:pk>/files/',                           StudyMaterialFilesAPI.as_view(),  name='study_material_files'),
path('study-materials/<int:pk>/query/',                           StudyMaterialQueryAPI.as_view(),  name='study_material_query'),
path('study-materials/<int:pk>/retry/',                           StudyMaterialRetryAPI.as_view(),  name='study_material_retry'),
path('study-materials/<int:pk>/merge-to-course/<int:course_id>/', StudyMaterialMergeAPI.as_view(),  name='study_material_merge'),
```

**Course query with study material:**
```python
# query_views.py — CourseQueryAPI
# include_study_materials=true  → uses course.merged_vectorstore_path (merged index)
# include_study_materials=false → uses course.vectorstore_path         (video-only)
```

---

## 9 — Logging Configuration

### `config/settings.py` — Logging

**Daily rotating log files** — rotated at midnight, 10 days retained:

```python
from logging.handlers import TimedRotatingFileHandler

LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_filename = LOGS_DIR / 'ai_video_engine.log'

def _log_namer(default_name):
    """Rename rotated logs: ai_video_engine.log.2026-05-17 → ai_video_engine_2026-05-17.log"""
    parts = default_name.rsplit('.log.', 1)
    if len(parts) == 2:
        return f'{parts[0]}_{parts[1]}.log'
    return default_name

class _CustomTimedRotatingFileHandler(TimedRotatingFileHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.namer = _log_namer

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} [{name}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'config.settings._CustomTimedRotatingFileHandler',
            'filename': str(log_filename),
            'when': 'midnight',
            'interval': 1,
            'backupCount': 10,
            'encoding': 'utf-8',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'apps.core': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
```

**Log file naming:**
```
logs/
├── ai_video_engine.log            ← today's active log
├── ai_video_engine_2026-05-18.log ← yesterday's rotated log
├── ai_video_engine_2026-05-17.log
└── ...
```

**Log level strategy:**

| Level | Where | Example |
|---|---|---|
| `INFO` | Task start/done, phase transitions, per-file success, rate limiter sleeps | `[Processor] [3/14] ✓ notes.pdf → 42 chunks` |
| `WARNING` | File conversion failure (pipeline continues), 429 retries, segment failures | `[Embedder] 429 rate limit on batch 5, retrying in 30s…` |
| `ERROR` | SM not found, unrecoverable task error | `[Task] StudyMaterial id=99 not found` |
| `DEBUG` | Per-chunk details, path resolution, FileConverter skip detail | `[FileConverter] report.mp4 — skipped (binary/archive)` |

**Sample complete pipeline log:**
```
INFO  [apps.core.tasks.study_material_tasks]            [Task] START process_study_material id=3
INFO  [apps.core.services.study_material_processor]     [Processor] Phase 1: Discovery for SM "Week 1 Notes" (id=3)
INFO  [apps.core.services.study_material_processor]     [ZipExtractor] Extracting: test3.zip → .../study_materials/Week_1_Notes/
INFO  [apps.core.services.study_material_processor]     [ZipExtractor] Discovered 14 files
INFO  [apps.core.services.study_material_processor]     [Processor] Discovered 14 files → 14 StudyMaterialFile records created
INFO  [apps.core.services.study_material_processor]     [Processor] Phase 2: Per-file processing for SM "Week 1 Notes"
INFO  [apps.core.services.file_converter]               [FileConverter] .pdf → extracted 4,821 chars from notes.pdf
INFO  [apps.core.services.embedder]                     Split transcript into 42 chunks
INFO  [apps.core.services.embedder]                     [Embedder] Planned 1 sequential batches for 42 chunks
INFO  [apps.core.services.embedder]                     [Embedder] Batch 1/1 → 42 embeddings
INFO  [apps.core.services.embedder]                     Vectorstore saved: .../individual_vectorstores/3_notes_vectorstore (42 chunks)
INFO  [apps.core.services.study_material_processor]     [Processor] [1/14] ✓ notes.pdf → 42 chunks
WARN  [apps.core.services.study_material_processor]     [Processor] [2/14] ✗ data.mp4: skipped
INFO  [apps.core.services.study_material_processor]     [Processor] Phase 3: Merging file vectorstores for SM "Week 1 Notes"
INFO  [apps.core.services.study_material_processor]     [Processor] Phase 3: Merged 13 file vectorstores → .../complete_vectorstores/3_Week_1_Notes_vectorstore
INFO  [apps.core.services.study_material_processor]     [Processor] Phase 4: Cleanup for SM "Week 1 Notes"
INFO  [apps.core.services.study_material_processor]     [Processor] DONE SM "Week 1 Notes": 13/14 files, VS at study_materials_vectorstore/...
INFO  [apps.core.tasks.study_material_tasks]            [Task] DONE process_study_material id=3 — 13/14 files, VS at ...
```

---

## 10 — Complete Data Flow

```
POST /api/study-materials/upload/
  │
  ├─ Validate: name (unique), zip_file required
  ├─ Save zip → media/study_materials/{slug}/  (or temp path in file_path field)
  ├─ Create StudyMaterial(status='pending', file_path=zip_abs_path)
  └─ process_study_material.delay(sm.id)
          │
          ▼
  [CELERY WORKER — soft_time_limit=14400s]
  │
  ├─ PHASE 1: DISCOVERY  (only if sm.status == 'pending')
  │    ZipExtractor.extract(zip_path, raw_dir)
  │    (nested .zip → recurse; ../paths → sanitised out)
  │    StudyMaterialFile.objects.bulk_create([...])    ← atomic transaction
  │    SM: files_count=N, processed_files=0, status='processing'
  │
  ├─ PHASE 2: PER-FILE  (resumable — queryset filtered to 'pending'|'failed' only)
  │    For each SMF:
  │      FileConverter.convert(FileEntry) → ConversionResult
  │      Write text → study_materials/{slug}/text/{stem}.txt
  │      _embed_with_segmentation(text, vs_path, metadata):
  │        if chunks ≤ 50k → Embedder.create_vectorstore() directly
  │        if chunks > 50k → split into 50k segments, embed each, FAISS.merge_from()
  │      SMF: status='completed', vectorstore_path, chunk_count, processed_at
  │      SM: processed_files += 1  (atomic F() update — safe for concurrent reads)
  │      On SoftTimeLimitExceeded → re-raise (Celery handler marks SM failed, keeps checkpoint)
  │      On other error → SMF.status='failed', continue
  │
  ├─ PHASE 3: MERGE
  │    Load all completed SMF.vectorstore_path entries
  │    FAISS.merge_from() iteratively
  │    Atomic save: write to {vs_path}.tmp → os.rename(tmp, final)
  │    → study_materials_vectorstore/complete_vectorstores/{sm_id}_{slug}_vectorstore/
  │    SM: status='completed', vectorstore_location=vs_relative
  │
  └─ PHASE 4: CLEANUP
       os.remove(sm.file_path)                     ← original zip
       os.remove(raw_dir/{smf.relative_path})      ← all raw extracted files
       os.rmdir empty subdirs in raw_dir           ← cleanup (text/ dir preserved)


POST /api/study-materials/<pk>/retry/
  │
  ├─ SM.status → 'processing', error_log → ''
  └─ process_study_material.delay(sm.id)
       Phase 1 skipped (sm.status != 'pending')
       Phase 2 skips status='completed' files — only 'pending'/'failed' re-processed


POST /api/study-materials/<pk>/merge-to-course/<cid>/
  │
  ├─ Validate: SM status == 'completed'
  ├─ Check course.study_material:
  │    null           → Merger.build(course, sm)
  │    same SM id     → {"message": "Already merged"}  (no-op)
  │    different SM   → Merger.replace(course, sm)
  │                     (rmtree old merged folder, build new, append old to history)
  ├─ StudyMaterialMerger.build():
  │    FAISS.load_local(course.vectorstore_path)      ← video-only, untouched
  │    FAISS.load_local(sm.vectorstore_location)      ← full SM VS
  │    course_vs.merge_from(sm_vs)
  │    tempfile.mkdtemp() → save_local(tmp) → os.rename(tmp, final_path)  ← atomic
  │    → course_vectorstores/{cid}_{cslug}/{cid}_{cslug}_{smid}_{smslug}.vectorstore/
  └─ Course: study_material=JSON, merged_vectorstore_path=relative


POST /api/query/course/  {"question": "...", "include_study_materials": true}
  └─ VectorStoreManager.query(course.merged_vectorstore_path)   ← merged index

POST /api/query/course/  {"question": "...", "include_study_materials": false}
  └─ VectorStoreManager.query(course.vectorstore_path)          ← video-only index

POST /api/study-materials/<pk>/query/  {"question": "..."}
  └─ VectorStoreManager.query(sm.vectorstore_location)          ← full SM merged index
```

---

## 11 — Complete File Map

```
apps/core/
├── models/
│   ├── study_material.py          StudyMaterial model (STATUS_* constants, 8 fields)
│   ├── study_material_file.py     StudyMaterialFile model (STATUS_* constants, 10 fields, DB index)
│   ├── course.py                  Course model (study_material JSON, merged_vectorstore_path, history)
│   ├── video.py
│   ├── job.py
│   ├── api_log.py
│   └── __init__.py                exports all models
├── migrations/
│   └── 0001_...  through  0009_...  (auto-generated)
├── services/
│   ├── zip_extractor.py           FileEntry + ZipExtractor (recursive, path-sanitised)
│   ├── file_converter.py          ConversionResult + FileConverter (30+ formats, inline imports)
│   ├── embedder.py                OpenAIRateLimiter + EmbedResult + Embedder (tiktoken, async, auto-split)
│   ├── study_material_processor.py  StudyMaterialProcessor (4-phase, segmented embedding, resumable)
│   ├── study_material_merger.py   MergeResult + StudyMaterialMerger (build/replace, atomic save)
│   ├── aggregator.py              course-level vectorstore builder (video pipeline)
│   ├── downloader.py              Vimeo downloader
│   ├── transcriber.py             Whisper transcription
│   ├── vectorstore.py             VectorStoreManager (load/query)
│   └── vimeo_transcript.py        Vimeo caption fast-path
├── tasks/
│   ├── processing.py              video pipeline task
│   └── study_material_tasks.py   process_study_material + retry_study_material
└── api/
    ├── urls.py                    7 SM endpoints + all other routes
    ├── serializers/
    │   ├── study_material_serializers.py  Upload, Query, List, File serializers
    │   └── ...
    └── views/
        ├── study_material_views.py  7 view classes
        ├── query_views.py           CourseQueryAPI (include_study_materials flag)
        └── ...

config/
├── settings.py    _CustomTimedRotatingFileHandler + LOGGING + Celery settings
├── celery.py      Celery app configuration
└── urls.py        includes apps.core.api.urls under /api/
```

---

## 12 — Verification Checklist

### Setup

```bash
# 1. Install dependencies
pip install pdfplumber python-pptx openpyxl xlrd python-docx striprtf odfpy \
            Pillow pytesseract lxml tiktoken aiohttp \
            langchain langchain-community langchain-openai faiss-cpu

# 2. System dependency for OCR
sudo apt install tesseract-ocr

# 3. Migrations
python manage.py makemigrations
python manage.py migrate

# 4. Start services
python manage.py rundev          # or runserver
celery -A config worker --loglevel=info
```

### Functional tests

```bash
# Upload
curl -X POST http://localhost:8000/api/study-materials/upload/ \
  -F "name=Test SM" \
  -F "description=Test upload" \
  -F "zip_file=@/path/to/test.zip"

# Watch progress (poll until status=completed)
curl http://localhost:8000/api/study-materials/<id>/status/

# Per-file breakdown
curl http://localhost:8000/api/study-materials/<id>/files/

# Query the SM
curl -X POST http://localhost:8000/api/study-materials/<id>/query/ \
  -H "Content-Type: application/json" \
  -d '{"question": "summarise the key topics"}'

# Merge into course
curl -X POST http://localhost:8000/api/study-materials/<id>/merge-to-course/<course_id>/

# Query course with SM
curl -X POST http://localhost:8000/api/query/course/ \
  -H "Content-Type: application/json" \
  -d '{"course_id": <cid>, "question": "...", "include_study_materials": true}'

# Retry a failed SM
curl -X POST http://localhost:8000/api/study-materials/<id>/retry/
```

### What to verify on disk after `completed`

```
media/
├── study_materials/{slug}/text/           ← *.txt files, one per processed file
│   (no raw extracted files, no zip)
├── study_materials_vectorstore/
│   ├── individual_vectorstores/
│   │   └── {sm_id}_{stem}_vectorstore/   ← one per completed SMF
│   └── complete_vectorstores/
│       └── {sm_id}_{slug}_vectorstore/   ← single merged SM VS
└── course_vectorstores/{cid}_{cslug}/
    ├── index.faiss                        ← ORIGINAL mtime unchanged
    └── {cid}_{cslug}_{smid}_{smslug}.vectorstore/   ← merged (after merge endpoint)
```

### Resumability test

```bash
# Kill worker mid-processing
# Check: some SMFs have status='completed', some 'pending'/'failed'
# Restart worker and retry:
curl -X POST http://localhost:8000/api/study-materials/<id>/retry/
# Verify: already-completed files are NOT re-embedded (processed_files doesn't reset)
```

# Study Material Pipeline — Part 2: Tasks, APIs, Logging & Data Flow

---

## 6 — Celery Task (Refactored for Checkpointing)

### [MODIFY] `apps/core/tasks/study_material_tasks.py`

The single monolithic task is replaced with a **resumable** approach:

```python
@shared_task(bind=True, soft_time_limit=1800, time_limit=2400)
def process_study_material(self, study_material_id: int):
    """
    Resumable pipeline — skips already-completed files on retry.
    Phase 1: Discovery (if SM still 'pending')
    Phase 2: Per-file processing (only pending/failed files)
    Phase 3: Merge all completed file VSs → full SM VS
    Phase 4: Cleanup
    """
    logger.info(f'[Task] START process_study_material id={study_material_id}')
    try:
        StudyMaterialProcessor(study_material_id).run()
        logger.info(f'[Task] DONE process_study_material id={study_material_id}')
    except SoftTimeLimitExceeded:
        # Mark SM as failed but keep completed StudyMaterialFiles intact
        StudyMaterial.objects.filter(pk=study_material_id).update(
            status='failed',
            error_log='Soft time limit exceeded — retry to resume from last checkpoint'
        )
        logger.warning(f'[Task] Soft time limit exceeded for SM id={study_material_id}')
    except Exception as exc:
        StudyMaterial.objects.filter(pk=study_material_id).update(
            status='failed', error_log=str(exc)
        )
        logger.exception(f'[Task] FAILED process_study_material id={study_material_id}: {exc}')
        raise


@shared_task
def retry_study_material(study_material_id: int):
    """Re-queue a failed SM — resumes from last completed file checkpoint."""
    StudyMaterial.objects.filter(pk=study_material_id).update(status='processing', error_log='')
    process_study_material.delay(study_material_id)
```

> [!IMPORTANT]
> **Why this solves the 40-min timeout:** `StudyMaterialFile` records are saved to DB after each file completes. A retry skips all `status='completed'` files and resumes from the first `pending`/`failed` one. Large zips like `test3` can be re-queued without re-processing anything already done.

---

## 7 — API Views

### [MODIFY] `apps/core/api/views/study_material_views.py`

| Class | Endpoint | Description |
|---|---|---|
| `StudyMaterialUploadAPI` | `POST /api/study-materials/upload/` | Save zip → create SM record → dispatch Celery task |
| `StudyMaterialStatusAPI` | `GET /api/study-materials/<id>/status/` | Full status: SM fields + per-file summary |
| `StudyMaterialListAPI` | `GET /api/study-materials/` | All SMs with `attached_courses_count` |
| `StudyMaterialMergeAPI` | `POST /api/study-materials/<id>/merge-to-course/<cid>/` | Merge SM VS into course VS |
| `StudyMaterialQueryAPI` | `POST /api/study-materials/<id>/query/` | RAG against full SM vectorstore |
| `StudyMaterialFilesAPI` | `GET /api/study-materials/<id>/files/` | List all `StudyMaterialFile` records |
| `StudyMaterialRetryAPI` | `POST /api/study-materials/<id>/retry/` | Re-queue failed SM (resumes from checkpoint) |

**`StudyMaterialStatusAPI` response shape:**
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

### [MODIFY] `apps/core/api/views/query_views.py` — `CourseQueryAPI`

```
include_study_materials=true  → use course.merged_vectorstore_path  (fast, merged index)
include_study_materials=false → use course.vectorstore_path          (original, video-only)
```

---

## 8 — Merge Endpoint Logic

`StudyMaterialMergeAPI` validates SM `status == 'completed'`, then:

| Scenario | Action | Response |
|---|---|---|
| `course.study_material == null` | `Merger.build()` → set `merged_vectorstore_path` + `study_material` | `{study_material, replaced: null, path}` |
| Same SM id | No-op | `{message: "Already merged"}` |
| Different SM | `Merger.replace()` → delete old folder, build new; append old to history | `{study_material, replaced: old, path}` |

---

## 9 — Serializers

### [NEW] `apps/core/api/serializers/study_material_serializers.py`

- `StudyMaterialUploadSerializer` — `name`, `description`, `zip_file` (FileField)
- `StudyMaterialQuerySerializer` — `question`
- `StudyMaterialSerializer` — all SM fields + `attached_courses_count` + `file_summary`
- `StudyMaterialFileSerializer` — all `StudyMaterialFile` fields

### [MODIFY] `CourseQuerySerializer`
Add: `include_study_materials = serializers.BooleanField(default=True, required=False)`

---

## 10 — URL Registration

### [MODIFY] `apps/core/api/urls.py`

```python
# ── Study Materials ──
path('study-materials/',                                          StudyMaterialListAPI.as_view(),  name='sm_list'),
path('study-materials/upload/',                                   StudyMaterialUploadAPI.as_view(), name='sm_upload'),
path('study-materials/<int:pk>/status/',                          StudyMaterialStatusAPI.as_view(), name='sm_status'),
path('study-materials/<int:pk>/files/',                           StudyMaterialFilesAPI.as_view(),  name='sm_files'),
path('study-materials/<int:pk>/query/',                           StudyMaterialQueryAPI.as_view(),  name='sm_query'),
path('study-materials/<int:pk>/retry/',                           StudyMaterialRetryAPI.as_view(),  name='sm_retry'),
path('study-materials/<int:pk>/merge-to-course/<int:course_id>/', StudyMaterialMergeAPI.as_view(),  name='sm_merge'),
```

---

## 11 — Structured Logging Strategy

Every service uses `logger = logging.getLogger(__name__)`.

| Level | Where | Example |
|---|---|---|
| `INFO` | Task start/done, phase transitions, each file success | `[Processor] [3/14] ✓ notes.pdf → 42 chunks` |
| `WARNING` | File conversion fail (pipeline continues), OCR blank | `[FileConverter] .xlsx skipped — openpyxl not installed` |
| `ERROR` | Unrecoverable: vectorstore save fail, merge fail | `[Merger] Failed to save merged VS: disk full` |
| `DEBUG` | Per-chunk details, internal path resolution | `[ZipExtractor] Resolved member path` |

**Sample log output:**
```
INFO  [tasks.study_material_tasks]       [Task] START process_study_material id=1
INFO  [services.study_material_processor] [Processor] Phase 1: Discovery
INFO  [services.zip_extractor]            [ZipExtractor] Extracting: test1.zip
INFO  [services.zip_extractor]            [ZipExtractor] Found nested zip: resources.zip
INFO  [services.study_material_processor] [Processor] Discovered 14 files → 14 StudyMaterialFile records created
INFO  [services.study_material_processor] [Processor] Phase 2: Per-file processing
INFO  [services.study_material_processor] [Processor] [1/14] ✓ notes.pdf → 42 chunks
WARN  [services.study_material_processor] [Processor] [2/14] ✗ data.xlsx → openpyxl not installed
INFO  [services.study_material_processor] [Processor] Phase 3: Merging 13/14 file vectorstores
INFO  [services.study_material_processor] [Processor] Phase 4: Cleanup
INFO  [tasks.study_material_tasks]       [Task] DONE process_study_material id=1
```

---

## 12 — Complete File Map

```
apps/core/
├── models/
│   ├── study_material.py           [MODIFY — processed_files, error_log]
│   ├── study_material_file.py      [NEW — per-file model]
│   ├── course.py                   [MODIFY — study_material, merged_vs_path, history]
│   └── __init__.py                 [MODIFY — export StudyMaterialFile]
├── migrations/
│   └── 0XXX_study_material_v2.py   [NEW]
├── services/
│   ├── zip_extractor.py             [NEW]
│   ├── file_converter.py            [MODIFY — guarded imports + logging]
│   ├── study_material_processor.py  [MODIFY — per-file VS pipeline + phases]
│   └── study_material_merger.py     [NEW]
├── tasks/
│   └── study_material_tasks.py      [MODIFY — resumable + retry task]
└── api/
    ├── urls.py                      [MODIFY — 7 new patterns]
    ├── serializers/
    │   └── study_material_serializers.py  [MODIFY — add FileSerializer]
    └── views/
        ├── study_material_views.py  [MODIFY — add FilesAPI, RetryAPI]
        └── query_views.py           [MODIFY — include_study_materials]
```

---

## Full Data Flow

```
POST /api/study-materials/upload/
  │
  ├─ Save zip → media/study_materials/{name}/
  ├─ Create StudyMaterial (status=pending)
  └─ Dispatch process_study_material.delay(id)
          │
          ▼
  [CELERY TASK]
  │
  ├─ PHASE 1: DISCOVERY
  │    ZipExtractor.extract() → flat list[FileEntry]
  │    (nested zips recursed, subfolders walked at any depth)
  │    Create StudyMaterialFile record per discovered file
  │    SM: files_count=N, status='processing'
  │
  ├─ PHASE 2: PER-FILE QUEUE  (resumable — skips completed files on retry)
  │    For each pending StudyMaterialFile:
  │      FileConverter → text → study_materials/{name}/text/{filename}.txt
  │      Embedder → FAISS → study_materials_vectorstore/individual_vectorstores/{sm_id}_{filename}_vectorstore/
  │      Update StudyMaterialFile: status=completed, vectorstore_path, chunk_count
  │      SM: processed_files += 1
  │
  ├─ PHASE 3: SM MERGE
  │    Load all completed StudyMaterialFile.vectorstore_path entries
  │    FAISS.merge_from() iteratively across all per-file vectorstores
  │    Save → study_materials_vectorstore/complete_vectorstores/{sm_id}_{sm_name}_vectorstore/
  │    SM: status='completed', vectorstore_location=...
  │
  └─ PHASE 4: CLEANUP
       Delete original zip + all raw extracted files
       Keep: study_materials/{name}/text/*.txt
       Keep: study_materials_vectorstore/individual_vectorstores/{sm_id}_*_vectorstore/
       Keep: study_materials_vectorstore/complete_vectorstores/{sm_id}_{sm_name}_vectorstore/


POST /api/study-materials/<id>/merge-to-course/<cid>/
  │
  ├─ Validate SM status == 'completed'
  ├─ StudyMaterialMerger.build() or .replace()
  │    Load course_vectorstores/{cid}_{cslug}/index.faiss   (original, untouched)
  │    Load study_materials_vectorstore/complete_vectorstores/{smid}_{smname}_vectorstore/
  │    FAISS.merge_from()
  │    Atomic save → course_vectorstores/{cid}_{cslug}/{cid}_{cslug}_{smid}_{smslug}.vectorstore/
  └─ Update Course: study_material JSON, merged_vectorstore_path


POST /api/query/course/  { include_study_materials: true }
  └─ VectorStoreManager.query(course.merged_vectorstore_path)   ← merged index (fast)

POST /api/query/course/  { include_study_materials: false }
  └─ VectorStoreManager.query(course.vectorstore_path)          ← video-only index

POST /api/study-materials/<id>/query/
  └─ VectorStoreManager.query(sm.vectorstore_location)          ← full SM merged index
```

---

## Verification Plan

### Automated
1. `python manage.py makemigrations && python manage.py migrate`
2. `pip install pdfplumber python-pptx openpyxl`
3. Upload zip with: nested zip (PDF), subfolder (.py + .jsx), .png, .csv
4. `GET /api/study-materials/<id>/status/` → watch `processed_files` increment
5. `GET /api/study-materials/<id>/files/` → verify per-file records with `status`, `vectorstore_path`
6. After `completed`: verify `files_count` matches discovered files
7. Verify per-file VSs at \`study_materials_vectorstore/individual_vectorstores/{sm_id}_{filename}_vectorstore/\`
8. Verify merged SM VS at \`study_materials_vectorstore/complete_vectorstores/{sm_id}_{sm_name}_vectorstore/\`
9. `POST /study-materials/<id>/query/` → verify `sources` contain varied file types
10. `POST /study-materials/<id>/merge-to-course/<cid>/`
11. Verify `course_vectorstores/{cid}_{slug}/{cid}_{slug}_{smid}_{smslug}.vectorstore/` exists
12. Verify original `course_vectorstores/{cid}_{slug}/index.faiss` **mtime unchanged**
13. `POST /query/course/` with `include_study_materials: true` → references SM content
14. `POST /query/course/` with `include_study_materials: false` → video chunks only
15. Kill task mid-process, re-queue → verify already-completed files are skipped

### Manual
- `study_materials/{name}/` contains **only** `text/` dir (no vectorstores, no raw files)
- `study_materials_vectorstore/` contains:
  - `individual_vectorstores/{sm_id}_{filename}_vectorstore/` — one per processed file
  - `complete_vectorstores/{sm_id}_{sm_name}_vectorstore/` — merged (created in Phase 3)
- `Course.merged_vectorstore_path` matches actual subfolder inside `course_vectorstores/{cid}_{slug}/`

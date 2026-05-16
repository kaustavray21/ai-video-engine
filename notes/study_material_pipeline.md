# Study Material Pipeline — Implementation Plan

## Overview

Add a full **Study Material** feature to the existing AI Video Engine Django project. Users upload a `.zip` of study files, which gets **recursively extracted**, converted to text, and embedded into a **dedicated standalone FAISS vectorstore**.

When a study material is attached to a course, a **new merged vectorstore** is created by combining the course's existing vectorstore with the study material's vectorstore. This merged index lives in its own isolated folder — **the original course vectorstore is never modified**. Replacing or updating the study material simply deletes the old merged folder and rebuilds it.

> [!NOTE]
> **Celery is confirmed** — `config/celery.py` already configured with `autodiscover_tasks(['apps.core.tasks'])`. New task auto-discovered with no config changes.

---

## Storage Architecture

```
media/
├── course_vectorstores/
│   └── {course_id}_{course_slug}/                              ← original course vectorstore (videos only, NEVER touched)
│       ├── index.faiss
│       ├── index.pkl
│       └── {course_id}_{course_slug}_{sm_id}_{sm_name}.vectorstore/  ← merged vectorstore (created on merge, deleted+rebuilt on SM replace)
│           ├── index.faiss
│           └── index.pkl
│
├── study_materials/{name}/
│   ├── text/{original_filename}.txt        ← converted text files, flat naming (kept permanently)
│   └── (raw extracted files deleted)
│
└── study_materials_vectorstore/
    └── {sm_id}_{name}.vectorstore/         ← standalone SM vectorstore (kept permanently)
        ├── index.faiss
        └── index.pkl
```

**Path examples:**

- Course `"Python Bootcamp"` (id=5): `course_vectorstores/5_Python_Bootcamp/`
- SM `"Week 1 Notes"` (id=3) merged with course: `course_vectorstores/5_Python_Bootcamp/5_Python_Bootcamp_3_Week_1_Notes.vectorstore/`
- SM standalone vectorstore: `study_materials_vectorstore/3_Week_1_Notes.vectorstore/`
- Text file from `lectures/week1/notes.pdf`: `study_materials/Week_1_Notes/text/notes.txt`

---

## Proposed Changes

### 1 — Data Model

#### [NEW] `apps/core/models/study_material.py`

| Field                  | Type                                    | Notes                                                     |
| ---------------------- | --------------------------------------- | --------------------------------------------------------- |
| `name`                 | `CharField(unique=True)`                | Used as directory slug                                    |
| `description`          | `TextField(blank=True)`                 | Optional                                                  |
| `file_path`            | `CharField`                             | `media/study_materials/{name}/`                           |
| `status`               | `CharField` choices                     | `pending \| processing \| completed \| failed`            |
| `files_count`          | `IntegerField(default=0)`               | Non-skipped files only                                    |
| `vectorstore_location` | `CharField`                             | `study_materials_vectorstore/{sm_id}_{name}.vectorstore/` |
| `created_at`           | `DateTimeField(auto_now_add=True)`      |                                                           |
| `attached_to_courses`  | `ManyToManyField('Course', blank=True)` | Which courses have a merged vectorstore for this SM       |

#### [MODIFY] `apps/core/models/course.py`

Add three fields:

```python
# Currently attached study material metadata
study_material = models.JSONField(null=True, blank=True)
# e.g. {"id": 3, "name": "Week 1 Notes", "description": "..."}

# Path to merged (course + SM) vectorstore — relative to MEDIA_ROOT
# e.g. "course_vectorstores/5_Python_Bootcamp/5_Python_Bootcamp_3_Week_1_Notes.vectorstore"
merged_vectorstore_path = models.CharField(max_length=500, blank=True, default='')

# History of replaced study materials (audit log)
study_materials_history = models.JSONField(default=list, blank=True)
```

#### [MODIFY] `apps/core/models/__init__.py`

Export `StudyMaterial`.

#### [NEW] Migration

Auto-generated for both model changes.

---

### 2 — Recursive Extraction Service

#### [NEW] `apps/core/services/zip_extractor.py`

A `ZipExtractor` that recursively extracts a zip archive:

- Walks all members with `zipfile.ZipFile`
- When a member is itself a `.zip` → extracts into a matching subdirectory, then **recurses**
- Preserves original subfolder structure for all non-zip files
- Sanitises paths against directory traversal (`../`) attacks
- Returns flat `list[FileEntry(abs_path, relative_path, ext, size)]`

```python
# Example input zip:
# lectures/week1/notes.pdf
# resources.zip           ← nested zip
#   └── slides.pptx
# images/diagram.png

# → Extracted flat list:
# FileEntry(".../lectures/week1/notes.pdf",  "lectures/week1/notes.pdf")
# FileEntry(".../resources/slides.pptx",     "resources/slides.pptx")
# FileEntry(".../images/diagram.png",         "images/diagram.png")
```

---

### 3 — File-to-Text Conversion Service

#### [NEW] `apps/core/services/file_converter.py`

Converts 30+ file types to plain text. Returns `ConversionResult(success, text, error, skipped: bool)`.

**Documents:** `.pdf`, `.doc`, `.docx`, `.txt`, `.md`, `.rtf`, `.ppt`, `.pptx`, `.odp`

**Spreadsheets:** `.xls`, `.xlsx`, `.csv`, `.ods`

**Code / Config / Data** _(UTF-8 direct read)_:
`.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.vue`, `.svelte`,
`.html`, `.css`, `.scss`, `.sass`,
`.java`, `.go`, `.rs`, `.cpp`, `.c`, `.h`, `.cs`, `.swift`, `.kt`, `.php`, `.rb`, `.dart`,
`.json`, `.yaml`, `.yml`, `.toml`, `.xml`, `.env`, `.sh`, `.bash`, `.zsh`,
`Dockerfile`, `.dockerfile`, `.makefile`, `.mk`, `.graphql`, `.gql`, `.sql`

**Images:**

- `.jpg`, `.jpeg`, `.png` → `pytesseract` OCR; fallback to `"[Image: {filename}]"` on failure
- `.svg` → XML parse, extract text nodes + `<title>` / `<desc>`

**Skipped:** `.mp4`, `.mp3`, `.mov`, `.avi`, `.zip`

---

### 4 — Study Material Processing Service

#### [NEW] `apps/core/services/study_material_processor.py`

1. **Recursive extract** → `ZipExtractor.extract()` → flat `list[FileEntry]`
2. **Convert** → `FileConverter.convert(entry)` per file; save to `media/study_materials/{name}/text/{original_filename}.txt` (flat, deduplicated by filename)
3. **Embed** → `Embedder.create_vectorstore()` with per-chunk metadata: `{original_name, type, size, chunk_index}`
4. **Save standalone vectorstore** → `study_materials_vectorstore/{sm_id}_{name}.vectorstore/` _(permanent, for direct queries)_
5. **Update model** → `status=completed`, `files_count`, `vectorstore_location`
6. **Cleanup** → delete original `.zip` + raw extracted files; keep `text/` folder

---

### 5 — Study Material Merge Service

#### [NEW] `apps/core/services/study_material_merger.py`

Handles building and replacing the merged vectorstore. Key methods:

```python
class StudyMaterialMerger:

    @staticmethod
    def _slugify(text: str) -> str:
        """Filesystem-safe slug: replace non-alphanumeric with underscore."""
        return re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_')

    @staticmethod
    def get_merged_vs_path(course, study_material) -> str:
        """
        Absolute path for the merged vectorstore.
        Pattern: media/course_vectorstores/{course_id}_{course_slug}/{course_id}_{course_slug}_{sm_id}_{sm_slug}.vectorstore/
        """
        course_slug = StudyMaterialMerger._slugify(course.title)
        sm_slug     = StudyMaterialMerger._slugify(study_material.name)
        folder_name = f'{course.id}_{course_slug}_{study_material.id}_{sm_slug}.vectorstore'
        return os.path.join(
            str(settings.MEDIA_ROOT),
            'course_vectorstores',
            f'{course.id}_{course_slug}',   # same dir as original course vectorstore
            folder_name,
        )

    @staticmethod
    def get_merged_vs_relative(course, study_material) -> str:
        """Relative path (to MEDIA_ROOT) — stored in Course.merged_vectorstore_path."""
        course_slug = StudyMaterialMerger._slugify(course.title)
        sm_slug     = StudyMaterialMerger._slugify(study_material.name)
        folder_name = f'{course.id}_{course_slug}_{study_material.id}_{sm_slug}.vectorstore'
        return os.path.join(
            'course_vectorstores',
            f'{course.id}_{course_slug}',
            folder_name,
        )

    def build(self, course, study_material) -> MergeResult:
        """
        1. Load course vectorstore (original, video-only) from course.vectorstore_path
        2. Load SM standalone vectorstore from study_material.vectorstore_location
        3. FAISS.merge_from() → combined index
        4. Atomic save to merged path (temp → rename)
        5. Return MergeResult(success, merged_path, merged_relative)
        """

    def replace(self, course, study_material) -> MergeResult:
        """
        1. shutil.rmtree(abs(course.merged_vectorstore_path))  ← delete old merged folder
        2. Call self.build(course, study_material)
        """
```

**Path example:**

```
Course: "Python Bootcamp" (id=5)
SM:     "Week 1 Notes"   (id=3)

Original course VS:  course_vectorstores/5_Python_Bootcamp/
                         ├── index.faiss
                         └── index.pkl

Merged VS:           course_vectorstores/5_Python_Bootcamp/5_Python_Bootcamp_3_Week_1_Notes.vectorstore/
                         ├── index.faiss
                         └── index.pkl

SM standalone:       study_materials_vectorstore/3_Week_1_Notes.vectorstore/
                         ├── index.faiss
                         └── index.pkl
```

---

### 6 — Celery Task

#### [NEW] `apps/core/tasks/study_material_tasks.py`

```python
@shared_task(bind=True)
def process_study_material(self, study_material_id: int):
    ...
```

- Calls `StudyMaterialProcessor.run(study_material_id)`
- On exception: sets `status = failed`, logs full traceback
- Auto-discovered — no changes to `config/celery.py`

---

### 7 — API Views

#### [NEW] `apps/core/api/views/study_material_views.py`

| Class                    | Endpoint                                                      | Description                                                         |
| ------------------------ | ------------------------------------------------------------- | ------------------------------------------------------------------- |
| `StudyMaterialUploadAPI` | `POST /api/study-materials/upload/`                           | Save zip, dispatch Celery task, return `{id, status: "processing"}` |
| `StudyMaterialStatusAPI` | `GET /api/study-materials/<id>/status/`                       | Return all fields                                                   |
| `StudyMaterialListAPI`   | `GET /api/study-materials/`                                   | List all with `attached_courses_count`                              |
| `StudyMaterialMergeAPI`  | `POST /api/study-materials/<id>/merge-to-course/<course_id>/` | Create/replace merged vectorstore                                   |
| `StudyMaterialQueryAPI`  | `POST /api/study-materials/<id>/query/`                       | RAG against standalone SM vectorstore                               |

#### [MODIFY] `apps/core/api/views/query_views.py` — `CourseQueryAPI`

Add `include_study_materials: bool` (default `true`):

```
include_study_materials=true  → use course.merged_vectorstore_path  (fast, merged index)
include_study_materials=false → use course.vectorstore_path          (original, video-only)
```

Both paths use the existing `VectorStoreManager.query()` — just different paths passed in.

---

### 8 — Merge Endpoint Logic

`StudyMaterialMergeAPI` steps:

| Scenario                        | Action                                                                                                                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `course.study_material == null` | `StudyMaterialMerger.build(course, sm)` → set `merged_vectorstore_path`, `study_material`                                                                                       |
| Same SM `id` already merged     | Return `{message: "Already merged"}`                                                                                                                                            |
| Different SM already merged     | `StudyMaterialMerger.replace(course, sm)` → deletes old merged folder, builds new → update `study_material`, `merged_vectorstore_path`, append old to `study_materials_history` |

After successful merge, update Course with `update_fields`:

```python
['study_material', 'merged_vectorstore_path', 'study_materials_history']
```

And `StudyMaterial.attached_to_courses.add(course)`.

**Response:**

```json
{
  "study_material": {"id": 3, "name": "Week 1 Notes"},
  "replaced": {"id": 1, "name": "Old Notes"} | null,
  "merged_vectorstore_path": "course_vectorstores/5_Python_Bootcamp/5_Python_Bootcamp_3_Week_1_Notes.vectorstore"
}
```

---

### 9 — Serializers

#### [NEW] `apps/core/api/serializers/study_material_serializers.py`

- `StudyMaterialUploadSerializer` — `name`, `description`, `zip_file`
- `StudyMaterialQuerySerializer` — `question`
- `StudyMaterialSerializer` — all fields + `attached_courses_count`

#### [MODIFY] `CourseQuerySerializer`

Add: `include_study_materials = serializers.BooleanField(default=True, required=False)`

---

### 10 — URL Registration

#### [MODIFY] `apps/core/api/urls.py`

```python
# ── Study Materials ──
path('study-materials/', StudyMaterialListAPI.as_view(), name='study_material_list'),
path('study-materials/upload/', StudyMaterialUploadAPI.as_view(), name='study_material_upload'),
path('study-materials/<int:pk>/status/', StudyMaterialStatusAPI.as_view(), name='study_material_status'),
path('study-materials/<int:pk>/query/', StudyMaterialQueryAPI.as_view(), name='study_material_query'),
path('study-materials/<int:pk>/merge-to-course/<int:course_id>/', StudyMaterialMergeAPI.as_view(), name='study_material_merge'),
```

---

### 11 — Dependencies

#### [MODIFY] `requirements.txt`

| Package       | Purpose         |
| ------------- | --------------- |
| `pdfplumber`  | PDF extraction  |
| `python-docx` | DOCX            |
| `python-pptx` | PPTX            |
| `openpyxl`    | XLSX            |
| `xlrd`        | XLS (legacy)    |
| `striprtf`    | RTF             |
| `odfpy`       | ODS / ODP       |
| `pytesseract` | JPEG / PNG OCR  |
| `Pillow`      | Image loading   |
| `lxml`        | SVG XML parsing |

> [!NOTE]
> `pytesseract` requires system package `tesseract-ocr`. OCR is best-effort — skipped with warning if binary not found.

---

## Complete File Map

```
apps/core/
├── models/
│   ├── study_material.py               [NEW]
│   ├── course.py                       [MODIFY — study_material, merged_vectorstore_path, history]
│   └── __init__.py                     [MODIFY — export StudyMaterial]
├── migrations/
│   └── 0XXX_add_study_material.py      [NEW]
├── services/
│   ├── zip_extractor.py                [NEW — recursive unzip]
│   ├── file_converter.py               [NEW — 30+ formats → text]
│   ├── study_material_processor.py     [NEW — upload pipeline]
│   └── study_material_merger.py        [NEW — merge/replace merged vectorstore]
├── tasks/
│   └── study_material_tasks.py         [NEW — Celery task]
└── api/
    ├── urls.py                         [MODIFY — 5 new patterns]
    ├── serializers/
    │   └── study_material_serializers.py  [NEW]
    └── views/
        ├── study_material_views.py     [NEW — 5 views]
        └── query_views.py              [MODIFY — include_study_materials param]
```

---

## Full Data Flow

```
┌─────────────────────────────────────────────────────────┐
│  UPLOAD & PROCESS                                       │
│                                                         │
│  POST /api/study-materials/upload/                      │
│    → ZipExtractor (recursive, nested zips + folders)    │
│    → FileConverter (30+ formats, OCR for images)        │
│    → Embedder → FAISS                                   │
│    → study_materials_vectorstore/{sm_id}_{name}.vectorstore/  │
│      (standalone, permanent)                            │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│  MERGE TO COURSE                                        │
│                                                         │
│  POST /api/study-materials/<id>/merge-to-course/<cid>/  │
│    → Load course_vectorstores/{id}_{slug}/  (original)  │
│    → Load study_materials_vectorstore/{sm_id}_{name}.vectorstore/  │
│    → FAISS.merge_from()                                             │
│    → Save to:                                                        │
│      course_vectorstores/{id}_{slug}/                               │
│        {id}_{slug}_{sm_id}_{sm_name}.vectorstore/   (new subfolder) │
│      (original index.faiss / index.pkl untouched)                   │
│                                                                      │
│  On SM replace:                                                      │
│    → shutil.rmtree(old .vectorstore subfolder)                      │
│    → rebuild new .vectorstore subfolder with new SM                 │
└──────────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│  QUERY                                                  │
│                                                         │
│  POST /api/query/course/                                │
│    include_study_materials=true                         │
│      → query merged_vectorstore_path  (fast)            │
│    include_study_materials=false                        │
│      → query original vectorstore_path (video-only)     │
│                                                         │
│  POST /api/study-materials/<id>/query/                  │
│      → query standalone SM vectorstore                  │
└─────────────────────────────────────────────────────────┘
```

---

## Verification Plan

### Automated

1. `python manage.py makemigrations && python manage.py migrate`
2. Upload a `.zip` with: nested zip (PDF), subfolder (`.py` + `.jsx`), `.png`, `.csv`
3. Poll status → `completed`; check `files_count` includes nested files
4. `POST /study-materials/{id}/query/` → verify `sources` span multiple file types
5. `POST /study-materials/{id}/merge-to-course/{cid}/` → check `merged_vectorstore_path` set on course
6. Verify `course_vectorstores/{id}_{slug}/{id}_{slug}_{sm_id}_{sm_name}.vectorstore/index.faiss` exists on disk
7. Verify `course_vectorstores/{id}_{slug}/index.faiss` is **unchanged** (same mtime)
8. `POST /query/course/` with `include_study_materials: true` → answer references SM content
9. `POST /query/course/` with `include_study_materials: false` → answer from video only
10. Merge a _different_ SM → verify old merged folder deleted, new one created

### Manual

- Check `media/study_materials/{name}/text/` contains flat `.txt` files (original filenames)
- Verify cleanup: original zip + raw extracted files gone, only `text/` remains
- Confirm `Course.merged_vectorstore_path` matches the `{id}_{slug}/{id}_{slug}_{sm_id}_{sm_name}.vectorstore` folder on disk

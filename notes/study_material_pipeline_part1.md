# Study Material Pipeline — Implementation Plan (Part 1: Architecture & Services)

## Key Observations from Logs

> [!IMPORTANT]
> **Celery time limit exceeded** — `test3` hit the 40-min hard cap. Per-file individual vectorstores + `StudyMaterialFile` checkpointing directly solves this: progress is saved per-file, not all-or-nothing.

> [!WARNING]
> **Packages not installed in venv** — `pdfplumber`, `openpyxl`, `python-pptx` missing. Run `pip install pdfplumber python-pptx openpyxl` in the venv before testing again.

---

## Storage Architecture

```
media/
├── course_vectorstores/
│   └── {course_id}_{course_slug}/                          ← original (NEVER touched)
│       ├── index.faiss
│       ├── index.pkl
│       └── {cid}_{cslug}_{smid}_{smslug}.vectorstore/     ← merged (delete+rebuild on SM replace)
│           ├── index.faiss
│           └── index.pkl
│
├── study_materials/{sm_name}/
│   └── text/{original_filename}.txt                    ← converted text (kept, raw files deleted)
│
└── study_materials_vectorstore/
    ├── complete_vectorstores/
    │   └── {sm_id}_{sm_name}_vectorstore/              ← merged SM vectorstore (all files combined)
    │       ├── index.faiss
    │       └── index.pkl
    └── individual_vectorstores/
        └── {sm_id}_{original_filename}_vectorstore/    ← per-file vectorstore (one per file)
            ├── index.faiss
            └── index.pkl
```

> [!NOTE]
> Per-file vectorstores are prefixed with `{sm_id}_` to prevent filename collisions when two study materials contain files with the same name (e.g., both have `notes.pdf`).

**Path examples (SM id=3, name="Week 1 Notes", Course id=5, "Python Bootcamp"):**
- Text file: `study_materials/Week_1_Notes/text/notes.txt`
- Per-file VS: `study_materials_vectorstore/individual_vectorstores/3_notes_vectorstore/`
- Full SM VS: `study_materials_vectorstore/complete_vectorstores/3_Week_1_Notes_vectorstore/`
- Course+SM merged VS: `course_vectorstores/5_Python_Bootcamp/5_Python_Bootcamp_3_Week_1_Notes.vectorstore/`

---

## 1 — Data Models

### [MODIFY] `apps/core/models/study_material.py`

```python
class StudyMaterial(models.Model):
    STATUS = ['pending', 'processing', 'completed', 'failed']

    name                 = models.CharField(max_length=255, unique=True)
    description          = models.TextField(blank=True, default='')
    file_path            = models.CharField(max_length=500, blank=True)  # media/study_materials/{name}/
    status               = models.CharField(max_length=20, default='pending')
    files_count          = models.IntegerField(default=0)   # total discovered (non-skipped)
    processed_files      = models.IntegerField(default=0)   # per-file VSs built so far
    vectorstore_location = models.CharField(max_length=500, blank=True)  # full merged SM VS
    created_at           = models.DateTimeField(auto_now_add=True)
    attached_to_courses  = models.ManyToManyField('Course', blank=True)
    error_log            = models.TextField(blank=True)     # last pipeline error
```

### [NEW] `apps/core/models/study_material_file.py`

Tracks every file discovered inside the uploaded zip:

```python
class StudyMaterialFile(models.Model):
    STATUS = ['pending', 'processing', 'completed', 'failed', 'skipped']

    study_material   = models.ForeignKey(StudyMaterial, on_delete=models.CASCADE,
                                         related_name='files')
    original_name    = models.CharField(max_length=500)     # e.g. "notes.pdf"
    relative_path    = models.CharField(max_length=1000)    # e.g. "lectures/week1/notes.pdf"
    file_type        = models.CharField(max_length=20)      # e.g. ".pdf"
    file_size        = models.BigIntegerField(default=0)    # bytes
    text_path        = models.CharField(max_length=500, blank=True)  # .txt file path (relative)
    vectorstore_path = models.CharField(max_length=500, blank=True)  # per-file VS path (relative)
    chunk_count      = models.IntegerField(default=0)
    status           = models.CharField(max_length=20, default='pending')
    error            = models.TextField(blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    processed_at     = models.DateTimeField(null=True, blank=True)
```

### [MODIFY] `apps/core/models/course.py`

Add three fields:
```python
study_material          = models.JSONField(null=True, blank=True)
# e.g. {"id": 3, "name": "Week 1 Notes", "description": "..."}

merged_vectorstore_path = models.CharField(max_length=500, blank=True, default='')
# e.g. "course_vectorstores/5_Python_Bootcamp/5_Python_Bootcamp_3_Week_1_Notes.vectorstore"

study_materials_history = models.JSONField(default=list, blank=True)
```

### [MODIFY] `apps/core/models/__init__.py`
Export `StudyMaterial`, `StudyMaterialFile`.

### [NEW] Migration
Auto-generated for all model changes.

---

## 2 — Recursive Extraction Service

### [NEW] `apps/core/services/zip_extractor.py`

```python
# Pipeline:
# 1. Open zip at zip_path
# 2. For each member:
#    - If member is a .zip → extract to subdir, recurse
#    - Otherwise → extract to dest_dir, yield FileEntry
# 3. Returns flat list[FileEntry(abs_path, relative_path, ext, size)]
# Sanitises paths: strips any "../" components
```

Logging:
```
[ZipExtractor] Extracting: my_upload.zip → media/study_materials/Week_1_Notes/
[ZipExtractor] Found nested zip: resources.zip → recursing into resources/
[ZipExtractor] Discovered 14 files total (2 nested zips expanded)
```

---

## 3 — File Converter Service

### [EXISTING/MODIFY] `apps/core/services/file_converter.py`

Already partially implemented. Fix outstanding issues:
- `pdfplumber` import guarded: `try: import pdfplumber except ImportError: pdfplumber = None`
- Same guard for `pptx`, `openpyxl`, `docx`, `striprtf`, `odfpy`
- Each converter logs at INFO on success, WARNING on failure/skip

**Supported formats:**

| Category | Extensions |
|---|---|
| Documents | `.pdf`, `.doc`, `.docx`, `.txt`, `.md`, `.rtf`, `.ppt`, `.pptx`, `.odp` |
| Spreadsheets | `.xls`, `.xlsx`, `.csv`, `.ods` |
| Code/Config | `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.vue`, `.svelte`, `.html`, `.css`, `.scss`, `.sass`, `.java`, `.go`, `.rs`, `.cpp`, `.c`, `.h`, `.cs`, `.swift`, `.kt`, `.php`, `.rb`, `.dart`, `.json`, `.yaml`, `.yml`, `.toml`, `.xml`, `.env`, `.sh`, `.bash`, `.zsh`, `Dockerfile`, `.graphql`, `.sql` |
| Images | `.jpg`, `.jpeg`, `.png` (OCR), `.svg` (XML text nodes) |
| Skipped | `.mp4`, `.mp3`, `.mov`, `.avi`, `.zip` |

Returns `ConversionResult(success, text, error, skipped: bool)`.

Logging:
```
[FileConverter] .pdf  → extracted 4,821 chars from notes.pdf
[FileConverter] .xlsx → failed (openpyxl not installed), skipping
[FileConverter] .jpg  → OCR returned blank, using placeholder
```

---

## 4 — Study Material Processor (Refactored)

### [MODIFY] `apps/core/services/study_material_processor.py`

**New pipeline — per-file vectorstore approach:**

```
PHASE 1 — DISCOVERY (fast, synchronous within task)
  1. ZipExtractor.extract(zip_path, dest_dir) → list[FileEntry]
  2. Create StudyMaterialFile record for every FileEntry
  3. Update StudyMaterial: files_count=len(entries), status='processing'
  4. Log: "[Processor] Discovered N files for SM '{name}'"

PHASE 2 — PER-FILE PROCESSING (sequential queue)
  For each StudyMaterialFile in status='pending':
    a. Mark file status = 'processing'
    b. FileConverter.convert(file_entry) → text
    c. Save text → study_materials/{name}/text/{original_filename}.txt
       Update file.text_path
     d. vs_path = study_materials_vectorstore/individual_vectorstores/{sm_id}_{original_filename}_vectorstore/
        Embedder.create_vectorstore(text, save_path=vs_path)
    e. Update StudyMaterialFile:
         vectorstore_path=vs_path, chunk_count, status='completed', processed_at=now()
    f. StudyMaterial.processed_files += 1  (atomic update)
    g. Log: "[Processor] [{i}/{N}] ✓ {filename} → {chunks} chunks"
    On error:
    h. StudyMaterialFile.status = 'failed', error = str(e)
    i. Log WARNING: "[Processor] [{i}/{N}] ✗ {filename}: {error}"
    j. Continue to next file (do not abort pipeline)

PHASE 3 — MERGE INTO FULL SM VECTORSTORE
  1. Load all completed StudyMaterialFile vectorstores
  2. FAISS.merge_from() iteratively → combined index
   3. Save → study_materials_vectorstore/complete_vectorstores/{sm_id}_{sm_name}_vectorstore/
  4. Update StudyMaterial: vectorstore_location, status='completed'
  5. Log: "[Processor] Merged {M}/{N} file vectorstores → full SM vectorstore"

PHASE 4 — CLEANUP
  1. Delete original zip
  2. Delete raw extracted files (keep text/ folder in study_materials/{name}/)
  3. Log: "[Processor] Cleanup complete"
```

---

## 5 — Study Material Merger Service

### [NEW] `apps/core/services/study_material_merger.py`

```python
class StudyMaterialMerger:

    @staticmethod
    def _slug(text: str) -> str:
        return re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_')

    @staticmethod
    def get_merged_vs_path(course, sm) -> str:
        cslug = StudyMaterialMerger._slug(course.title)
        sslug = StudyMaterialMerger._slug(sm.name)
        folder = f'{course.id}_{cslug}_{sm.id}_{sslug}.vectorstore'
        return os.path.join(settings.MEDIA_ROOT, 'course_vectorstores',
                            f'{course.id}_{cslug}', folder)

    @staticmethod
    def get_merged_vs_relative(course, sm) -> str:
        cslug = StudyMaterialMerger._slug(course.title)
        sslug = StudyMaterialMerger._slug(sm.name)
        folder = f'{course.id}_{cslug}_{sm.id}_{sslug}.vectorstore'
        return os.path.join('course_vectorstores', f'{course.id}_{cslug}', folder)

    def build(self, course, sm) -> MergeResult:
        # 1. Load course.vectorstore_path (original, video-only)
        # 2. Load sm.vectorstore_location (full SM merged vectorstore)
        # 3. FAISS.merge_from()
        # 4. Atomic save (temp → rename) to get_merged_vs_path()
        # 5. Return MergeResult(success, merged_path, merged_relative)

    def replace(self, course, sm) -> MergeResult:
        # 1. shutil.rmtree(abs(course.merged_vectorstore_path))
        # 2. self.build(course, sm)
```

Logging:
```
[Merger] Building merged VS: "Python Bootcamp" + "Week 1 Notes"
[Merger] Loaded course VS: 18,432 vectors
[Merger] Loaded SM VS: 3,201 vectors
[Merger] Merged → 21,633 vectors total
[Merger] Saved → course_vectorstores/5_Python_Bootcamp/5_Python_Bootcamp_3_Week_1_Notes.vectorstore/
```

---

## File Map (Part 1 scope)

```
apps/core/
├── models/
│   ├── study_material.py           [MODIFY — add processed_files, error_log]
│   ├── study_material_file.py      [NEW — per-file tracking model]
│   ├── course.py                   [MODIFY — study_material, merged_vectorstore_path, history]
│   └── __init__.py                 [MODIFY — export StudyMaterialFile]
├── migrations/
│   └── 0XXX_study_material_v2.py   [NEW]
└── services/
    ├── zip_extractor.py             [NEW — recursive unzip]
    ├── file_converter.py            [MODIFY — guard imports, add logging]
    ├── study_material_processor.py  [MODIFY — per-file VS pipeline]
    └── study_material_merger.py     [NEW — course+SM merge]
```

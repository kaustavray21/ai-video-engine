# Study Material Feature — Changes Summary

## Backend Changes

### New Models

| File | Description |
|---|---|
| `apps/core/models/study_material.py` | `StudyMaterial` model — name, description, file_path, status (pending/processing/completed/failed), files_count, vectorstore_location, created_at, attached_to_courses (M2M to Course) |

### Modified Models

| File | Change |
|---|---|
| `apps/core/models/course.py` | Added 3 fields: `study_material` (JSONField), `merged_vectorstore_path` (CharField), `study_materials_history` (JSONField) |
| `apps/core/models/__init__.py` | Export `StudyMaterial` |

### New Services

| File | Description |
|---|---|
| `apps/core/services/zip_extractor.py` | `ZipExtractor` — recursive zip extraction with path traversal protection, returns `list[FileEntry]` |
| `apps/core/services/file_converter.py` | `FileConverter` — converts 30+ formats to text (PDF, DOCX, PPTX, XLSX, CSV, ODS, ODP, RTF, code files, images via OCR, SVG) |
| `apps/core/services/study_material_processor.py` | `StudyMaterialProcessor` — orchestrates pipeline: extract → convert → chunk → embed → save FAISS vectorstore → cleanup |
| `apps/core/services/study_material_merger.py` | `StudyMaterialMerger` — `build()`/`replace()` merged vectorstore using `FAISS.merge_from()` with atomic save |

### New Celery Task

| File | Task Name | Description |
|---|---|---|
| `apps/core/tasks/study_material_tasks.py` | `process_study_material` | Async processing of uploaded study material zip |

### New API Views

| Endpoint | View Class | Description |
|---|---|---|
| `POST /api/study-materials/upload/` | `StudyMaterialUploadAPI` | Upload zip, dispatch Celery task |
| `GET /api/study-materials/<id>/status/` | `StudyMaterialStatusAPI` | Poll processing status |
| `GET /api/study-materials/` | `StudyMaterialListAPI` | List all with `attached_courses_count` |
| `POST /api/study-materials/<id>/query/` | `StudyMaterialQueryAPI` | RAG against standalone SM vectorstore |
| `POST /api/study-materials/<id>/merge-to-course/<course_id>/` | `StudyMaterialMergeAPI` | Create/replace merged vectorstore |

### Modified API Views

| View | Change |
|---|---|
| `CourseQueryAPI` | Added `include_study_materials` param — routes to `merged_vectorstore_path` (true) or `vectorstore_path` (false) |

### New Serializers

| Serializer | Fields |
|---|---|
| `StudyMaterialUploadSerializer` | name, description, zip_file |
| `StudyMaterialQuerySerializer` | question |
| `StudyMaterialSerializer` | All model fields + attached_courses_count |

### Modified Serializers

| Serializer | Change |
|---|---|
| `CourseQuerySerializer` | Added `include_study_materials` (BooleanField, default=true) |

### Dependencies Added

| Package | Purpose |
|---|---|
| `pdfplumber` | PDF text extraction |
| `python-docx` | DOCX conversion |
| `python-pptx` | PPTX conversion |
| `openpyxl` | XLSX conversion |
| `xlrd` | XLS (legacy) conversion |
| `striprtf` | RTF conversion |
| `odfpy` | ODS/ODP conversion |
| `pytesseract` | Image OCR (JPG/PNG) |
| `Pillow` | Image loading |
| `lxml` | SVG XML parsing |

## Storage Architecture

```
media/
├── course_vectorstores/
│   └── {course_id}_{course_slug}/
│       ├── index.faiss                              ← original (video-only, NEVER touched)
│       ├── index.pkl
│       └── {course_id}_{course_slug}_{sm_id}_{sm_name}.vectorstore/  ← merged (replaced on SM update)
│           ├── index.faiss
│           └── index.pkl
├── study_materials/{name}/
│   └── text/{original_filename}.txt                 ← converted text (kept permanently)
└── study_materials_vectorstore/
    ├── complete_vectorstores/
    │   └── {sm_id}_{sm_name}_vectorstore/           ← standalone SM vectorstore (kept permanently)
    │       ├── index.faiss
    │       └── index.pkl
    └── individual_vectorstores/
        └── {sm_id}_{filename}_vectorstore/           ← per-file vectorstore (one per file)
            ├── index.faiss
            └── index.pkl
```

## Database Migration

- `core.0005_course_merged_vectorstore_path_course_study_material_and_more` — adds 3 fields to Course + creates StudyMaterial table

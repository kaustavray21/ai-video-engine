# Study Material API Endpoints

Base URL: `/api/`

---

## Upload Study Material

```
POST /api/study-materials/upload/
```

Upload a `.zip` archive of study files. Dispatches async Celery task for recursive extraction, text conversion, and vector embedding.

**Request** (multipart/form-data):

| Field        | Type   | Required | Description            |
| ------------ | ------ | -------- | ---------------------- |
| `name`       | string | yes      | Unique name / slug     |
| `description`| string | no       | Optional description   |
| `zip_file`   | file   | yes      | `.zip` archive of files |

**Response** `201 Created`:

```json
{
  "id": 1,
  "name": "Week 1 Notes",
  "status": "pending"
}
```

---

## List Study Materials

```
GET /api/study-materials/
```

List all study materials with attached course count and file status summary.

**Response** `200 OK`:

```json
[
  {
    "id": 1,
    "name": "Week 1 Notes",
    "description": "...",
    "file_path": "study_materials/Week_1_Notes/",
    "status": "completed",
    "files_count": 12,
    "processed_files": 12,
    "vectorstore_location": "study_materials_vectorstore/complete_vectorstores/1_Week_1_Notes_vectorstore/",
    "error_log": "",
    "attached_courses_count": 1,
    "file_summary": {
      "completed": 10,
      "pending": 0,
      "processing": 0,
      "failed": 1,
      "skipped": 1
    },
    "created_at": "2025-01-15T10:30:00Z"
  }
]
```

Possible statuses: `pending | processing | completed | failed`

---

## Get Study Material Status

```
GET /api/study-materials/<id>/status/
```

Poll processing status, all metadata fields, and per-file details.

**Response** `200 OK`:

```json
{
  "id": 1,
  "name": "Week 1 Notes",
  "description": "...",
  "file_path": "study_materials/Week_1_Notes/",
  "status": "completed",
  "files_count": 12,
  "processed_files": 12,
  "vectorstore_location": "study_materials_vectorstore/complete_vectorstores/1_Week_1_Notes_vectorstore/",
  "error_log": "",
  "attached_courses_count": 1,
  "file_summary": {
    "completed": 10,
    "pending": 0,
    "processing": 0,
    "failed": 1,
    "skipped": 1
  },
  "created_at": "2025-01-15T10:30:00Z",
  "files": [
    {
      "file_id": 1,
      "original_name": "intro.pdf",
      "file_type": ".pdf",
      "status": "completed",
      "chunk_count": 42,
      "error": ""
    },
    {
      "file_id": 2,
      "original_name": "hw1.py",
      "file_type": ".py",
      "status": "failed",
      "chunk_count": 0,
      "error": "Unsupported file encoding"
    }
  ]
}
```

---

## List Study Material Files

```
GET /api/study-materials/<id>/files/
```

List all individual files within a study material with full metadata.

**Response** `200 OK`:

```json
{
  "study_material_id": 1,
  "study_material_name": "Week 1 Notes",
  "total_files": 12,
  "files": [
    {
      "id": 1,
      "original_name": "intro.pdf",
      "relative_path": "lectures/week1/intro.pdf",
      "file_type": ".pdf",
      "file_size": 1024000,
      "text_path": "study_materials/Week_1_Notes/text/intro.txt",
      "vectorstore_path": "study_materials_vectorstore/individual_vectorstores/1_intro_vectorstore/",
      "chunk_count": 42,
      "status": "completed",
      "error": "",
      "created_at": "2025-01-15T10:30:00Z",
      "processed_at": "2025-01-15T10:31:00Z"
    }
  ]
}
```

---

## Query Study Material

```
POST /api/study-materials/<id>/query/
```

RAG query against the standalone study material vectorstore (no course context).

**Request** (JSON):

```json
{
  "question": "What is covered in week 1?",
  "filter_source_file": "lectures/week1/intro.pdf",
  "filter_file_type": ".pdf"
}
```

| Field               | Type   | Required | Description |
| ------------------- | ------ | -------- | ----------- |
| `question`           | string | yes      | Max 2000 chars |
| `filter_source_file` | string | no       | Filter by relative source path |
| `filter_file_type`   | string | no       | Filter by file extension (e.g. `.pdf`) |

**Response** `200 OK`:

```json
{
  "status": "success",
  "answer": "Week 1 covers Python fundamentals including variables, loops, and functions.",
  "study_material_id": 1,
  "study_material_name": "Week 1 Notes",
  "question": "What is covered in week 1?",
  "source_chunks": [
    {
      "original_name": "lectures/week1/intro.pdf",
      "type": ".pdf",
      "chunk_index": 0,
      "score": 0.92
    },
    {
      "original_name": "exercises/hw1.py",
      "type": ".py",
      "chunk_index": 2,
      "score": 0.78
    }
  ],
  "retrieved_sources": 2,
  "retrieved_chunk_count": 2
}
```

---

## Query Study Material File

```
POST /api/study-materials/files/<file_id>/query/
```

RAG query against a single file's vectorstore within a study material.

**Request** (JSON):

```json
{
  "question": "What is the time complexity of this algorithm?"
}
```

**Response** `200 OK`:

```json
{
  "status": "success",
  "answer": "The algorithm has O(n log n) time complexity.",
  "file_id": 1,
  "file_name": "intro.pdf",
  "file_type": ".pdf",
  "study_material_id": 1,
  "study_material_name": "Week 1 Notes",
  "question": "What is the time complexity of this algorithm?",
  "source_chunks": [...],
  "retrieved_sources": 1,
  "retrieved_chunk_count": 3
}
```

---

## Retry Failed Study Material

```
POST /api/study-materials/<id>/retry/
```

Retry processing a failed study material. Dispatches a Celery task to re-process only the failed files.

**Precondition**: Study material status must be `failed`.

**Response** `200 OK`:

```json
{
  "id": 1,
  "name": "Week 1 Notes",
  "status": "queued_for_retry",
  "processed_files": 8,
  "files_count": 12
}
```

---

## Merge Study Material to Course

```
POST /api/study-materials/<id>/merge-to-course/<course_id>/
```

Merge study material's standalone vectorstore into a course. Creates a new merged vectorstore subfolder alongside the original course vectorstore. Original course vectorstore is never modified.

**Logic by scenario:**

| Scenario | Action |
|---|---|
| No SM attached to course | `build()` — create merged vectorstore, set `merged_vectorstore_path` on course |
| Same SM `id` already merged | Return `{"message": "Already merged"}` |
| Different SM already merged | `replace()` — delete old merged folder, build new one, append old to history |

**Precondition**: Study material status must be `completed`.

**Response** `200 OK`:

```json
{
  "study_material": {
    "id": 3,
    "name": "Week 1 Notes"
  },
  "replaced": {
    "id": 1,
    "name": "Old Notes"
  },
  "merged_vectorstore_path": "course_vectorstores/5_Python_Bootcamp/5_Python_Bootcamp_3_Week_1_Notes.vectorstore"
}
```

If no replacement occurred, `"replaced"` is `null`.

---

## Course Query (with Study Material Support)

```
POST /api/query/course/
```

Queries either the merged (course + study material) vectorstore or the original video-only vectorstore.

**Request** (JSON):

```json
{
  "course_id": 5,
  "question": "What topics are covered?",
  "include_study_materials": true
}
```

| Parameter | Default | Behavior |
|---|---|---|
| `include_study_materials=true` | default | Queries `course.merged_vectorstore_path` (course + SM merged index) |
| `include_study_materials=false` | — | Queries `course.vectorstore_path` (original video-only index) |

---

## Storage Layout

```
media/
├── course_vectorstores/
│   └── {course_id}_{course_slug}/
│       ├── index.faiss                              ← original (video-only, NEVER touched)
│       ├── index.pkl
│       └── {course_id}_{course_slug}_{sm_id}_{sm_name}.vectorstore/  ← merged (replaced on SM update)
│           ├── index.faiss
│           └── index.pkl
│
├── study_materials/{name}/
│   └── text/{original_filename}.txt                 ← converted text (kept permanently)
│
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

---

## Summary of All Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| `POST`   | `/api/study-materials/upload/` | Upload zip and start processing |
| `GET`    | `/api/study-materials/` | List all study materials |
| `GET`    | `/api/study-materials/<id>/status/` | Get status + per-file details |
| `GET`    | `/api/study-materials/<id>/files/` | List individual files with metadata |
| `POST`   | `/api/study-materials/<id>/query/` | Query the standalone vectorstore |
| `POST`   | `/api/study-materials/files/<file_id>/query/` | Query a single file's vectorstore |
| `POST`   | `/api/study-materials/<id>/retry/` | Retry processing (must be failed) |
| `POST`   | `/api/study-materials/<id>/merge-to-course/<course_id>/` | Merge into a course |
| `POST`   | `/api/query/course/` | Course query (optionally including SM) |

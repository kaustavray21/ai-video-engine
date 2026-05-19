# Study Material API Endpoints

Base URL: `/api/`

---

## Upload Study Material

```
POST /api/study-materials/upload/
```

Upload a `.zip` archive of study files. Dispatches async Celery task for recursive extraction, text conversion, and vector embedding.

**Request** (multipart/form-data):

| Field       | Type   | Required | Description            |
| ----------- | ------ | -------- | ---------------------- |
| `name`      | string | yes      | Unique name / slug     |
| `description` | string | no    | Optional description   |
| `zip_file`  | file   | yes      | `.zip` archive of files |

**Response** `201 Created`:

```json
{
  "id": 1,
  "name": "Week 1 Notes",
  "status": "processing"
}
```

---

## Get Study Material Status

```
GET /api/study-materials/<id>/status/
```

Poll processing status and all metadata fields.

**Response** `200 OK`:

```json
{
  "id": 1,
  "name": "Week 1 Notes",
  "description": "...",
  "status": "completed",
  "files_count": 12,
  "vectorstore_location": "study_materials_vectorstore/complete_vectorstores/1_Week_1_Notes_vectorstore/",
  "attached_courses_count": 1,
  "created_at": "2025-01-15T10:30:00Z"
}
```

Possible statuses: `pending | processing | completed | failed`

---

## List Study Materials

```
GET /api/study-materials/
```

List all study materials with attached course count.

**Response** `200 OK`:

```json
[
  {
    "id": 1,
    "name": "Week 1 Notes",
    "description": "...",
    "status": "completed",
    "files_count": 12,
    "vectorstore_location": "study_materials_vectorstore/complete_vectorstores/1_Week_1_Notes_vectorstore/",
    "attached_courses_count": 1,
    "created_at": "2025-01-15T10:30:00Z"
  }
]
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
  "question": "What is covered in week 1?"
}
```

**Response** `200 OK`:

```json
{
  "answer": "Week 1 covers Python fundamentals including variables, loops, and functions.",
  "sources": [
    {
      "original_name": "lectures/week1/intro.pdf",
      "type": "pdf",
      "chunk_index": 0
    },
    {
      "original_name": "exercises/hw1.py",
      "type": "py",
      "chunk_index": 2
    }
  ]
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

**Modified** — now accepts `include_study_materials` parameter.

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

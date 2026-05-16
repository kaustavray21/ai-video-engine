# Vimeo Transcript Fast Path + Vectorstore Dedup Refactor

Me look at big project plan. Me adapt for this small `ai_video_engine`. Two big hunts:

1. **Vimeo Transcript Fast Path** — ask Vimeo "you have captions?" → if yes, grab text, skip download/audio/whisper → go straight to vectorstore. Save time. Save money.
2. **Vectorstore Dedup + Global Storage** — same vimeo video in two courses? No copy folder. Just point. One folder per unique video on disk.

---

## Current State of Branch `16-May-non-temporal-version`

| Thing                      | Status                                                                        |
| -------------------------- | ----------------------------------------------------------------------------- |
| `VimeoTranscriptService`   | ❌ NOT EXIST — reference code in `architecture refactoring plan/` folder only |
| Pipeline (`processing.py`) | ✅ Full slow path: download → audio → whisper → embed                         |
| `Video` model              | ❌ Missing: `transcript_source`, `vimeo_caption_language`                     |
| `ProcessingJob` model      | ❌ Missing: `REUSED` status, `processing_path` field                          |
| Vectorstore paths          | ❌ Keyed by DB video ID: `course_{id}/vectorstore/video_{id}`                 |
| Dedup check                | ❌ No cross-course check at all                                               |

---

## Current Disk Layout

```
media/
├── course_5/vectorstore/video_21/   ← DB video ID in folder name
├── course_5/vectorstore/video_22/
├── course_5/vectorstore/course_complete/
├── course_8/vectorstore/video_41/
├── course_8/vectorstore/course_complete/
└── live_videos/                     ← downloaded .mp4 files (cleaned after processing)
```

---

## Feature 1: Vimeo Transcript Fast Path

### What it do

Before downloading whole MP4, ask Vimeo API: "you have captions on this video?" If yes → grab VTT text → parse to plain text → jump straight to embedding step. Skip Steps 1-3. **Saves ~2-3 minutes per video.**

### Flow

```
process_video_task(job_id)
  ├── job.mark_started()
  │
  ├── [NEW] Step 0: Try Vimeo Transcript ──────────────────┐
  │   service = VimeoTranscriptService(vimeo_token)         │
  │   result = service.fetch_transcript(vimeo_video_id)     │
  │   if result['success']:                                  │
  │       → skip Steps 1-3                                   │
  │       → jump to Step 4 (embedding) with transcript text │
  │       → set video.transcript_source = 'vimeo_captions'  │
  │   else:                                                  │
  │       → log "falling back to full pipeline"             │
  │       → continue Steps 1-5 as normal                    │
  └─────────────────────────────────────────────────────────┘
```

---

### Proposed Changes — Feature 1

---

#### [NEW] [vimeo_transcript.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/vimeo_transcript.py)

Copy and adapt `VimeoTranscriptService` from the reference `architecture refactoring plan/vimeo_transcript_service.py`. Standalone service, only needs `requests` + `django.conf.settings`.

**What it do:**

- `VimeoTranscriptService(vimeo_token)` → init
- `.fetch_transcript(vimeo_video_id)` → calls Vimeo API `/videos/{id}/texttracks` → downloads VTT → parses → returns:

```python
{
    'success': True,
    'transcript_text': '...',      # plain text for embeddings
    'transcript_path': '/abs/path/to/file.txt',
    'language': 'en-x-autogen',
    'line_count': 435,
}
```

---

#### [MODIFY] [video.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/models/video.py)

Add 2 new fields (both optional, `blank=True` — safe migration, no data loss):

```python
# After 'vectorstore_created' field (line ~69)

transcript_source = models.CharField(
    max_length=20,
    choices=[
        ('vimeo_captions', 'Vimeo Captions (VTT)'),
        ('whisper',        'Whisper Transcription'),
    ],
    blank=True, default='',
    help_text="How transcript was obtained"
)
vimeo_caption_language = models.CharField(
    max_length=20, blank=True, default='',
    help_text="Language code of Vimeo caption track"
)
```

---

#### [MODIFY] [job.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/models/job.py)

Add `processing_path` field to track which route was taken:

```python
# After 'processing_details' field (line ~60)

processing_path = models.CharField(
    max_length=20,
    choices=[
        ('vimeo_transcript', 'Fast Path — Vimeo Captions'),
        ('full_pipeline',    'Full Pipeline — Download + Whisper'),
        ('reused',           'Reused — Vectorstore Already Existed'),
    ],
    blank=True, default='',
    help_text="Which processing route was taken"
)
```

---

#### [MODIFY] [processing.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/tasks/processing.py)

Insert **Step 0** (fast path) at top of pipeline, before Step 1 download. Two surgical cuts:

**Cut 1** — Add import at top:

```python
from apps.core.services.vimeo_transcript import VimeoTranscriptService
```

**Cut 2** — Insert before Step 1 (after `job.mark_started()`):

```python
# ── Step 0: Try Vimeo transcript fast path ──────────────────
job.update_progress(3, 'checking_vimeo_captions')
try:
    vts = VimeoTranscriptService(vimeo_token=vimeo_token)
    vt_result = vts.fetch_transcript(video.vimeo_video_id)
except Exception as e:
    logger.warning(f'Vimeo transcript check failed: {e}')
    vt_result = {'success': False}

if vt_result.get('success'):
    logger.info(f'✅ Vimeo transcript found! Skipping download/audio/whisper.')
    # Jump straight to Step 4 with the Vimeo transcript
    transcript_text = vt_result['transcript_text']
    video.transcript_path = os.path.relpath(vt_result['transcript_path'], media_root)
    video.transcript_source = 'vimeo_captions'
    video.vimeo_caption_language = vt_result.get('language', '')
    video.save(update_fields=['transcript_path', 'transcript_source', 'vimeo_caption_language'])
    job.update_progress(60, 'vimeo_transcript_obtained')

    # → continue to Step 4 (embedding) using transcript_text
    # (restructure pipeline so Step 4+ uses transcript_text variable)
else:
    logger.info(f'Vimeo captions not available. Full pipeline.')
    transcript_text = None  # will be set by Step 3
# ── End Step 0 ─────────────────────────────────────────────

if transcript_text is None:
    # Steps 1-3 run only when fast path missed
    ...existing download/audio/transcribe code...
    transcript_text = tx_result.transcript

# Step 4+ runs always, using transcript_text from either path
```

**Existing Steps 1-5 become the fallback path.** Step 4 (embedding) and Step 5 (cleanup) run for both paths. Only difference: fast path has no .mp4/.wav to clean up.

Also update job completion to record `processing_path`:

```python
job.processing_path = 'vimeo_transcript' if video.transcript_source == 'vimeo_captions' else 'full_pipeline'
```

---

## Feature 2: Vectorstore Dedup + Global Storage

### Problem

Same Vimeo video in Course A and Course B → pipeline runs twice. Two full downloads, two Whisper calls, two OpenAI embedding calls. Disk has two copies of same vectorstore.

### Solution: Two-Layer Fix

**Layer 1 — Global vectorstore folder (keyed by vimeo_video_id)**

```
media/
├── video_vectorstores/             ← NEW: one folder per unique Vimeo video
│   ├── 1022483822/
│   │   ├── index.faiss
│   │   └── index.pkl
│   └── 1022483889/
│       ├── index.faiss
│       └── index.pkl
│
└── course_vectorstores/            ← NEW: one folder per course
    ├── 5_my_course_name/
    │   ├── index.faiss
    │   └── index.pkl
    └── 8_16_May_course/
        ├── index.faiss
        └── index.pkl
```

**Layer 2 — "REUSED" status (pointer, not copy)**

When same video added to second course:

1. Check: does `media/video_vectorstores/{vimeo_video_id}/` exist on disk?
2. **Yes** → just set `video.vectorstore_path` to point there → mark job `REUSED` → done. Zero file ops.
3. **No** → full pipeline (or fast path from Feature 1)

---

### Proposed Changes — Feature 2

---

#### [MODIFY] [job.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/models/job.py)

Add `REUSED` to `STATUS_CHOICES` and a `mark_reused()` helper:

```python
STATUS_CHOICES = [
    ('SCHEDULED', 'Scheduled'),
    ('IN_PROGRESS', 'In Progress'),
    ('COMPLETED', 'Completed'),
    ('FAILED', 'Failed'),
    ('ABORTED', 'Aborted'),
    ('REUSED', 'Reused — Vectorstore Already Existed'),  # ← NEW
]
```

```python
def mark_reused(self, source_info: str):
    """Mark job as reused — vectorstore already existed on disk."""
    self.status = 'REUSED'
    self.progress = 100
    self.completed_at = timezone.now()
    self.processing_path = 'reused'
    self.processing_details = {
        'reuse_reason': 'vectorstore_exists_on_disk',
        'source': source_info,
    }
    self.save(update_fields=[
        'status', 'progress', 'completed_at',
        'processing_path', 'processing_details',
    ])
    # Mark parent video as ready
    self.video.vectorstore_created = True
    self.video.status = 'ready'
    self.video.save(update_fields=['vectorstore_created', 'status'])
    self.video.course.update_statistics()
```

---

#### [MODIFY] [processing.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/tasks/processing.py)

**Change 1 — New vectorstore save path** (Step 4):

```python
# BEFORE (line ~116-121):
vs_save_path = os.path.join(
    media_root, f'course_{course.id}', 'vectorstore', f'video_{video.id}',
)

# AFTER:
vs_save_path = os.path.join(
    media_root, 'video_vectorstores', video.vimeo_video_id,
)
```

**Change 2 — Dedup check** (insert after `job.mark_started()`, before Step 0):

```python
# ── DEDUP: Check if vectorstore already exists for this vimeo_video_id ──
shared_path = os.path.join('video_vectorstores', video.vimeo_video_id)
shared_abs = os.path.join(media_root, shared_path)

if os.path.isdir(shared_abs) and os.path.exists(os.path.join(shared_abs, 'index.faiss')):
    logger.info(
        f'[DEDUP] Vectorstore exists at {shared_abs}. '
        f'Pointing instead of reprocessing.'
    )
    video.vectorstore_path = shared_path
    video.vectorstore_created = True
    video.status = 'ready'
    video.save(update_fields=['vectorstore_path', 'vectorstore_created', 'status'])

    job.mark_reused(source_info=f'disk:{shared_path}')

    # Still rebuild course vectorstore
    rebuild_course_vectorstore_task.apply_async(args=[course.id], countdown=60)
    logger.info(f'✅ Job {job_id} completed via REUSED path')
    return
# ── END DEDUP ───────────────────────────────────────────────
```

---

#### [MODIFY] [aggregator.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/aggregator.py)

Change course vectorstore path from `course_{id}/vectorstore/course_complete` to `course_vectorstores/{id}_{slug}`:

```python
import re

@staticmethod
def _make_course_slug(course) -> str:
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', course.title).strip('_')[:50]
    return f"{course.id}_{slug}"

@staticmethod
def get_course_vs_path(course) -> str:
    slug = CourseAggregator._make_course_slug(course)
    return os.path.join(str(settings.MEDIA_ROOT), 'course_vectorstores', slug)

@staticmethod
def get_course_vs_relative(course) -> str:
    slug = CourseAggregator._make_course_slug(course)
    return os.path.join('course_vectorstores', slug)
```

No other changes needed in aggregator — `_resolve_video_vs_path()` already reads from `video.vectorstore_path` which will now hold `video_vectorstores/{vimeo_id}`.

---

#### [NEW] [migrate_vectorstores.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/management/commands/migrate_vectorstores.py)

Django management command. Run once to move existing vectorstores from old layout to new layout.

```bash
python manage.py migrate_vectorstores --dry-run    # preview
python manage.py migrate_vectorstores              # do it
```

**What it do:**

| Phase           | Action                                                                                                            |
| --------------- | ----------------------------------------------------------------------------------------------------------------- |
| 1. Scan         | Walk `media/course_*/vectorstore/video_*` → map DB video ID to vimeo_video_id                                     |
| 2. Move videos  | `shutil.move(old, media/video_vectorstores/{vimeo_id})` — dedup on disk (first wins, rest just update DB pointer) |
| 3. Move courses | `shutil.move(course_complete, media/course_vectorstores/{id}_{slug})`                                             |
| 4. Cleanup      | Delete empty old `course_*/vectorstore/` directories                                                              |
| 5. Update DB    | Set new paths on `Video.vectorstore_path` and `Course.vectorstore_path`                                           |

Writes manifest JSON to `media/migration_manifest.json` for audit trail.

Status values for manifest entries:
| Status | Meaning |
|---|---|
| `moved` | Folder physically moved, DB updated |
| `dedup_pointer` | Folder already at destination (another video moved it), DB pointer updated only |
| `skipped_missing` | Folder not found on disk |
| `error` | Something broke — logged, migration continues |

---

## What NOT Touch

| File             | Reason                                                        |
| ---------------- | ------------------------------------------------------------- |
| `settings.py`    | `VIMEO_TOKEN` already configured                              |
| `downloader.py`  | Unchanged — becomes fallback path                             |
| `transcriber.py` | Unchanged — becomes fallback path                             |
| `embedder.py`    | Unchanged — just receives different `save_path`               |
| `vectorstore.py` | Unchanged — reads path from DB, resolves against `MEDIA_ROOT` |

---

## Migration Required

```bash
python manage.py makemigrations core   # new fields on Video + ProcessingJob
python manage.py migrate
```

> [!NOTE]
> All new fields are `blank=True, default=''`. Existing rows get empty string. Zero data loss. Migration is instant.

---

## Execution Order

```
1. Add model fields (video.py, job.py)         → makemigrations + migrate
2. Add VimeoTranscriptService                   → new file
3. Modify processing.py                         → dedup check + fast path + new vectorstore paths
4. Modify aggregator.py                         → new course vectorstore paths
5. Run migrate_vectorstores management command  → move existing files on disk
6. Test end-to-end
```

> [!IMPORTANT]
> Steps 1-4 are code changes. Step 5 is a one-time data migration of files on disk. Step 5 should happen AFTER code is deployed so new paths are understood by the application.

---

## Open Questions

> [!IMPORTANT]
> **Transcript file handling on REUSED path**: When same vimeo video appears in Course B and vectorstore already exists, should we also grab the transcript from Vimeo for Course B's `transcript_path`? Or just leave it empty since we already have the vectorstore? The vectorstore is sufficient for Q&A, but having the transcript stored is useful for audit/display.

> [!WARNING]
> **Existing data on disk**: You currently have vectorstores in `course_5/`, `course_6/`, `course_7/`, `course_8/`. The migration script will move all of them. After migration, old `course_*/vectorstore/` directories will be deleted. **Make sure to back up `media/` before running.**

---

## Verification Plan

### Automated

```bash
python manage.py makemigrations --check    # clean migration state
python manage.py migrate                    # apply
python manage.py migrate_vectorstores --dry-run   # preview moves
python manage.py migrate_vectorstores              # execute
```

### Manual Testing

**Test 1 — Fast path (Vimeo captions exist):**

- Add a video that has captions on Vimeo
- Watch logs for: `✅ Vimeo transcript found! Skipping download/audio/whisper.`
- Confirm vectorstore saved to `media/video_vectorstores/{vimeo_id}/`
- Confirm `video.transcript_source == 'vimeo_captions'`

**Test 2 — Fallback (no captions):**

- Add a video with no Vimeo captions
- Watch logs for: `Vimeo captions not available. Full pipeline.`
- Confirm full download → whisper → embed pipeline runs
- Confirm `video.transcript_source == 'whisper'`

**Test 3 — REUSED path (same video, different course):**

- Add same Vimeo video to a second course
- Watch logs for: `[DEDUP] Vectorstore exists at... Pointing instead of reprocessing.`
- Confirm job status = `REUSED`
- Confirm no new files created on disk
- Confirm course vectorstore rebuilt with merged index

**Test 4 — Disk verification after migration:**

```bash
ls media/video_vectorstores/       # one folder per unique vimeo_video_id
ls media/course_vectorstores/      # one folder per course
find media -name 'course_*' -type d -path '*/vectorstore'  # should be empty/gone
```

### Log Markers

```
[VimeoTranscript] ✅ Saved 435 cues to ...
✅ Vimeo transcript found! Skipping download/audio/whisper.
[DEDUP] Vectorstore exists at ... Pointing instead of reprocessing.
✅ Job N completed via REUSED path
```

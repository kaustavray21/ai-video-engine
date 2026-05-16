# Walkthrough: Vimeo Fast Path + Vectorstore Dedup

## What Changed

### New Files

| File                                                                                                                                                                                            | Purpose                                                                                    |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| [vimeo_transcript.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/vimeo_transcript.py)                                                         | `VimeoTranscriptService` — fetches captions from Vimeo API, parses VTT, returns plain text |
| [migrate_vectorstores.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/management/commands/migrate_vectorstores.py)                                      | One-time management command to move vectorstores from old to new layout                    |
| [0004_processingjob_processing_path_and_more.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/migrations/0004_processingjob_processing_path_and_more.py) | Django migration for new model fields                                                      |

### Modified Files

| File                                                                                                                        | Changes                                                                |
| --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| [video.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/models/video.py)             | Added `transcript_source`, `vimeo_caption_language` fields             |
| [job.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/models/job.py)                 | Added `REUSED` status, `processing_path` field, `mark_reused()` method |
| [processing.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/tasks/processing.py)    | Added dedup check, Vimeo fast path, global vectorstore paths           |
| [aggregator.py](file:///home/ricky/VScode/projects/python/Django/testings/ai_video_engine/apps/core/services/aggregator.py) | Changed course vectorstore paths to `course_vectorstores/{id}_{slug}`  |

## Pipeline Flow (After)

```
process_video_task(job_id)
  │
  ├── DEDUP check: video_vectorstores/{vimeo_id}/ exists?
  │   └── YES → point DB, mark REUSED, rebuild course VS → return
  │
  ├── Step 0: Try Vimeo captions
  │   └── SUCCESS → grab text, set transcript_source='vimeo_captions'
  │   └── FAIL → continue to full pipeline
  │
  ├── Steps 1-3 (only if Step 0 failed):
  │   ├── Download MP4 from Vimeo
  │   ├── Extract audio (ffmpeg)
  │   └── Transcribe (Whisper API), set transcript_source='whisper'
  │
  ├── Step 4: Create FAISS vectorstore → video_vectorstores/{vimeo_id}/
  ├── Step 5: Cleanup .mp4/.wav
  └── Step 6: Mark complete, queue course VS rebuild
```

## New Disk Layout

```
media/
├── video_vectorstores/           ← one per unique Vimeo video
│   ├── 1022483822/
│   └── 1022483878/
├── course_vectorstores/          ← one per course
│   ├── 5_Gen_AI_COURSE/
│   └── 8_16_May_course/
└── live_videos/                  ← temp downloads (cleaned after processing)
```

## Verification Results

- `python manage.py makemigrations --check` → **No changes detected** ✅
- `python manage.py check` → **0 issues** ✅
- `python manage.py migrate_vectorstores --dry-run` → **19 videos, 4 courses detected** ✅
  - Dedup detected: video_36 and video_21 share vimeo_id `1022483822` (will be deduped on real run)

## Next Steps

1. **Run the actual migration** (when ready):
   ```bash
   python manage.py migrate_vectorstores
   ```
2. **Test with Celery worker** — add a video and watch logs for fast path or dedup
3. **Test REUSED path** — add same vimeo video to a second course

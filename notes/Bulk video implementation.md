# Bulk Add Videos to Course API

Add a new endpoint that accepts multiple Vimeo URLs at once for a single course, validates each one, creates Video + ProcessingJob records, and dispatches Celery tasks for all of them in one request.

## Proposed Changes

### Backend — Serializer

#### [MODIFY] [video_serializers.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/api/serializers/video_serializers.py)

Add a new `BulkVideoCreateSerializer`:
```python
class BulkVideoCreateSerializer(serializers.Serializer):
    course_id = serializers.IntegerField()
    video_urls = serializers.ListField(
        child=serializers.URLField(),
        min_length=1,
        max_length=50,  # safety cap
    )
```

---

### Backend — View

#### [MODIFY] [video_views.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/api/views/video_views.py)

Add `BulkVideoCreateAPI` view that:
1. Validates the payload via `BulkVideoCreateSerializer`
2. Looks up the course (404 if not found)
3. Loops through each URL:
   - Cleans it, extracts Vimeo ID
   - Skips duplicates and invalid URLs (tracks them in a `skipped` list)
   - Creates `Video` + `ProcessingJob` records
   - Dispatches `process_video_task` via `send_task`
4. Updates course statistics once at the end
5. Returns a summary response:
```json
{
  "message": "3 video(s) added, 1 skipped",
  "added": [
    {"video_id": 5, "vimeo_id": "671720300", "job_id": 7},
    {"video_id": 6, "vimeo_id": "817678028", "job_id": 8},
    {"video_id": 7, "vimeo_id": "123456789", "job_id": 9}
  ],
  "skipped": [
    {"url": "https://vimeo.com/671720300", "reason": "duplicate"}
  ]
}
```

---

### Backend — URL Routing

#### [MODIFY] [urls.py](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/apps/core/api/urls.py)

Add under `# ── Video Management ──`:
```python
path('videos/bulk/', BulkVideoCreateAPI.as_view(), name='video_bulk_create'),
```

---

### Frontend — Endpoint Config

#### [MODIFY] [endpoints.ts](file:///home/ricky/VScode/projects/python/Django/testings%20and%20implementation/ai_video_engine/dashboard/src/constants/endpoints.ts)

Add new entry to `API_ENDPOINTS`:
```typescript
{
  method: 'POST',
  path: '/videos/bulk/',
  label: 'Bulk Add Videos',
  bodyHint: '{\n  "course_id": 1,\n  "video_urls": [\n    "https://vimeo.com/...",\n    "https://vimeo.com/..."\n  ]\n}'
}
```

## Open Questions

> [!IMPORTANT]
> Should there be a maximum cap on how many URLs can be submitted at once? I've defaulted to **50** in the serializer. Let me know if you want a different limit.

## Verification Plan

### Automated Tests
- Hit `POST /api/videos/bulk/` from the API Tester with a mix of valid, duplicate, and invalid URLs
- Confirm the response separates `added` vs `skipped` correctly
- Confirm Celery worker picks up all dispatched jobs

### Manual Verification
- Check `Video Status` endpoint for each newly created video
- Confirm course statistics update after bulk add

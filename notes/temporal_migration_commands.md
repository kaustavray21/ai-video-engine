# Temporal Cloud Migration — Commands to Run

> All commands must be run from the project root:
> `cd "/home/ricky/VScode/projects/python/Django/testings and implementation/ai_video_engine"`
>
> Make sure your virtualenv is activated first:
> `source venv/bin/activate`

---

## Step 1 — Install the Temporal Python SDK

```bash
pip install temporalio
```

**Why:** The entire migration depends on `temporalio` — all new files (`activities.py`, `workflows.py`, `client.py`, `worker.py`) import from it. Without this package, nothing will import or run.

---

## Step 2 — Verify existing dependencies are installed

```bash
pip show openai langchain-community langchain-openai faiss-cpu requests
```

**Why:** The Temporal activities call your existing services (downloader, transcriber, embedder, aggregator) which depend on these packages. This command confirms they're all present. If any shows "not found", install it with `pip install <package-name>`.

---

## Step 3 — Syntax-check all new and modified files

```bash
python -c "
import ast
files = [
    'apps/core/temporal/__init__.py',
    'apps/core/temporal/activities.py',
    'apps/core/temporal/workflows.py',
    'apps/core/temporal/client.py',
    'apps/core/temporal/worker.py',
    'apps/core/management/commands/run_temporal_worker.py',
    'config/settings.py',
    'config/celery.py',
    'apps/core/api/views/video_views.py',
]
for f in files:
    ast.parse(open(f).read())
    print(f'OK: {f}')
print('All files syntax OK')
"
```

**Why:** Catches any syntax errors before you try to run anything. This checks every file that was created or modified during the migration.

---

## Step 4 — Confirm Celery dispatch calls are removed from views

```bash
grep -n "current_app.send_task" apps/core/api/views/video_views.py
```

**Why:** This should produce **no output**. All three `current_app.send_task(...)` calls in `VideoCreateAPI`, `BulkVideoCreateAPI`, and `VideoDeleteAPI` have been replaced with Temporal workflow dispatch calls. If you see any matches, the migration is incomplete.

---

## Step 5 — Confirm Celery task code is still intact (not deleted)

```bash
grep -n "def process_video_task\|def rebuild_course_vectorstore_task" apps/core/tasks/processing.py
```

**Why:** Should output both function definitions. The Celery code is intentionally **kept** as a reference and fallback — only the _dispatch calls_ in the views were changed. The tasks themselves are untouched.

---

## Step 6 — Verify Temporal imports resolve correctly

```bash
python -c "
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
import django; django.setup()
from apps.core.temporal.activities import download_video, extract_and_transcribe, create_embeddings, cleanup_media_files, rebuild_course_vectorstore, mark_job_complete
from apps.core.temporal.workflows import VideoProcessingWorkflow, CourseRebuildWorkflow
from apps.core.temporal.client import get_client, start_video_workflow, start_course_rebuild
print('All Temporal imports OK')
"
```

**Why:** This proves that all new modules can be imported into a Django context without circular import errors or missing symbols. If this fails, there is a wiring issue in the code.

---

## Step 7 — Confirm Django management command is registered

```bash
python manage.py help | grep temporal
```

**Why:** Should show `run_temporal_worker` in the output, confirming Django discovered the new management command. If it doesn't appear, check that `apps/core/management/commands/run_temporal_worker.py` exists and `apps/core/management/__init__.py` exists.

---

## Step 8 — Smoke-test Temporal Cloud connection

```bash
python test_temporal_connection.py
```

**Why:** This temporary script connects to your Temporal Cloud instance using the credentials from `.env` and runs a simple workflow query to prove auth works. Expected output:

```
Endpoint : quickstart-kaustavr-acb569e7.o6j79.tmprl.cloud:7233
Namespace: quickstart-kaustavr-acb569e7
TLS      : True
API key  : set
Connecting...
Connected OK
Workflow query OK (found 0 recent workflows)
SUCCESS — Temporal Cloud connection is working.
```

> [!WARNING]
> If you see `UNAUTHENTICATED`, check `TEMPORAL_API_KEY` in `.env`.
> If you see `ssl.SSLError` or `UNAVAILABLE`, ensure `TEMPORAL_TLS=True` in `.env`.
> If you see `Namespace not found`, verify `TEMPORAL_NAMESPACE` matches the subdomain of your endpoint.

---

## Step 9 — Delete the smoke test script

```bash
rm test_temporal_connection.py
```

**Why:** It's a one-time diagnostic script. No need to keep it in the repo.

---

## Step 10 — Start the Temporal worker (Terminal 1)

```bash
python manage.py run_temporal_worker
```

Or alternatively:

```bash
python -m apps.core.temporal.worker
```

**Why:** This starts the Temporal worker process that polls the `video-processing` task queue on Temporal Cloud. When a Django view dispatches a workflow, Temporal Cloud routes it to this worker for execution. This replaces `celery -A config worker ...`.

Expected output:
```
Starting Temporal worker
  Endpoint  : quickstart-kaustavr-acb569e7.o6j79.tmprl.cloud:7233
  Namespace : quickstart-kaustavr-acb569e7
  Task queue: video-processing
  Concurrency: 4

Connected to Temporal Cloud.
Worker running. Press Ctrl+C to stop.
```

> [!IMPORTANT]
> Leave this running in its own terminal. Open a **new** terminal for the next steps.

---

## Step 11 — Start Django dev server (Terminal 2)

```bash
python manage.py runserver
```

**Why:** The Django server handles API requests. When you POST to `/api/videos/`, it now dispatches a Temporal workflow instead of a Celery task.

---

## Step 12 — Test the full pipeline (Terminal 3)

### 12a. Create a test course (if you don't have one):

```bash
curl -s -X POST http://localhost:8000/api/courses/ \
  -H "Content-Type: application/json" \
  -d '{"title": "Temporal Test Course", "description": "Testing Temporal migration"}' | python -m json.tool
```

### 12b. Add a video (use a real Vimeo URL from your account):

```bash
curl -s -X POST http://localhost:8000/api/videos/ \
  -H "Content-Type: application/json" \
  -d '{"course_id": <COURSE_ID>, "video_url": "https://vimeo.com/<YOUR_VIDEO_ID>"}' | python -m json.tool
```

### 12c. Monitor progress:

```bash
curl -s -X POST http://localhost:8000/api/videos/status/ \
  -H "Content-Type: application/json" \
  -d '{"id": <VIDEO_ID>}' | python -m json.tool
```

**Why:** End-to-end verification that the Django view → Temporal Cloud → Worker → services pipeline works correctly. The video should progress through: `downloading → transcribing → embedding → ready`.

### 12d. Check Temporal Cloud UI:

Open [https://cloud.temporal.io/](https://cloud.temporal.io/) → navigate to your namespace → Workflows. You should see a `VideoProcessingWorkflow` execution in "Running" or "Completed" state.

---

## Step 13 — Verify file structure

```bash
find apps/core/temporal/ -type f -name "*.py" | sort
find apps/core/management/commands/ -name "run_temporal_worker.py"
```

**Why:** Final sanity check. Expected output:

```
apps/core/temporal/__init__.py
apps/core/temporal/activities.py
apps/core/temporal/client.py
apps/core/temporal/worker.py
apps/core/temporal/workflows.py
apps/core/management/commands/run_temporal_worker.py
```

---

## Summary of What Changed

| File | Change |
|---|---|
| `.env` | Added `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE`, `TEMPORAL_TLS` |
| `config/settings.py` | Added `TEMPORAL_*` settings block after Celery config |
| `config/celery.py` | `worker_ready` handler disabled with early `return` (code preserved) |
| `apps/core/tasks/processing.py` | **Untouched** — kept as reference |
| `apps/core/temporal/__init__.py` | **NEW** — package init |
| `apps/core/temporal/activities.py` | **NEW** — 6 Temporal activities wrapping existing services |
| `apps/core/temporal/workflows.py` | **NEW** — `VideoProcessingWorkflow` + `CourseRebuildWorkflow` |
| `apps/core/temporal/client.py` | **NEW** — Temporal Cloud client factory + sync dispatch helpers |
| `apps/core/temporal/worker.py` | **NEW** — Worker entry point |
| `apps/core/api/views/video_views.py` | 3 Celery `send_task()` calls replaced with Temporal dispatches |
| `apps/core/management/commands/run_temporal_worker.py` | **NEW** — `python manage.py run_temporal_worker` |

---

## Troubleshooting

| Error | Likely Cause | Fix |
|---|---|---|
| `ssl.SSLError` or `UNAVAILABLE` | TLS misconfigured | Ensure `TEMPORAL_TLS=True` in `.env` |
| `UNAUTHENTICATED` | Wrong or missing API key | Check `TEMPORAL_API_KEY` in `.env` |
| `Namespace not found` | Wrong namespace string | Must match subdomain of your endpoint exactly |
| `Activity not registered` | Worker started without new activity | Restart worker after adding activities |
| `Non-determinism error` | I/O in workflow code | Move offending code into an activity |
| `Heartbeat timeout` | Long activity not heartbeating | Add `activity.heartbeat()` calls every few minutes |
| `django.core.exceptions.AppRegistryNotReady` | `django.setup()` missing in activity | Each activity must call `django.setup()` |

---

## Running in Production

```bash
# Start the Temporal worker (replaces: celery -A config worker)
python manage.py run_temporal_worker --concurrency 4

# Django server (unchanged)
python manage.py runserver

# Monitor workflows:
# https://cloud.temporal.io/ → your namespace → Workflows
```

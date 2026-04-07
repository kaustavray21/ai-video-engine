# Temporal Cloud Migration Plan
## AI Video Engine — Celery → Temporal Cloud

> **How to use this file**: Feed it to Claude Code in your terminal.
> Run `claude` in your project root (`new/`) and paste this document or reference it with:
> `claude "Follow the plan in temporal_migration_plan.md step by step"`
>
> Claude Code will read your existing files, create new ones, and modify existing ones.
> Work through each phase in order. Do not skip phases.

---

## Project Context

**Root directory**: `new/` (the extracted project folder)

**Stack**:
- Django 4.x + Django REST Framework
- MySQL database
- Celery + Redis (kept intact, not deleted — just no longer invoked for video processing)
- Temporal Cloud (added alongside Celery)
- OpenAI Whisper + GPT-4o-mini
- FAISS vectorstores (LangChain)
- React/TypeScript dashboard (unchanged)

**Temporal Cloud environment variables** (already in `.env`):
```
TEMPORAL_ENDPOINT="quickstart-kaustavr-acb569e7.o6j79.tmprl.cloud:7233"
TEMPORAL_NAMESPACE="quickstart-kaustavr-acb569e7"
TEMPORAL_API_KEY="<your-api-key>"
```

> Note: The namespace is the subdomain portion of the endpoint before `.o6j79.tmprl.cloud`.
> Claude Code should read these from `.env` via `python-dotenv` — never hardcode them.

---

## Phase 0 — Read and understand the codebase

**Tell Claude Code:**

```
Read and understand the following files before making any changes:

1. config/settings.py          — Django settings, env vars, Celery config
2. config/celery.py            — Current Celery app and worker_ready signal
3. config/urls.py              — URL routing
4. apps/core/tasks/processing.py     — The two Celery tasks being replaced
5. apps/core/services/downloader.py  — VimeoDownloader service
6. apps/core/services/transcriber.py — Transcriber service (audio + Whisper)
7. apps/core/services/embedder.py    — Embedder service (FAISS creation)
8. apps/core/services/aggregator.py  — CourseAggregator service
9. apps/core/services/vectorstore.py — VectorStoreManager service
10. apps/core/models/video.py        — Video model
11. apps/core/models/job.py          — ProcessingJob model
12. apps/core/models/course.py       — Course model
13. apps/core/api/views/video_views.py — VideoCreateAPI, BulkVideoCreateAPI, VideoDeleteAPI
14. apps/core/api/urls.py            — API URL routing

Confirm you have read all files before proceeding.
```

---

## Phase 1 — Install dependencies and update settings

### 1.1 Install Python packages

**Tell Claude Code:**

```
Run the following command to install the Temporal Python SDK:

    pip install temporalio

Also confirm these are already installed (they should be from requirements):
    pip show openai langchain-community langchain-openai faiss-cpu requests

Do NOT uninstall celery or redis — the Celery code is being kept intact.
```

### 1.2 Add Temporal config to `config/settings.py`

**Tell Claude Code:**

```
Add the following Temporal configuration block to config/settings.py,
directly after the CELERY configuration block (around line 120).
Read the existing CELERY block first to find the exact insertion point.

Add this block:

# ---------------------------------------------------------------------------
# Temporal Cloud
# ---------------------------------------------------------------------------

TEMPORAL_ENDPOINT = os.environ.get('TEMPORAL_ENDPOINT', 'localhost:7233')
TEMPORAL_NAMESPACE = os.environ.get('TEMPORAL_NAMESPACE', 'default')
TEMPORAL_API_KEY = os.environ.get('TEMPORAL_API_KEY', '')
TEMPORAL_TASK_QUEUE = os.environ.get('TEMPORAL_TASK_QUEUE', 'video-processing')

# TLS is required for Temporal Cloud (api-key auth uses mTLS transport).
# Set to False only when connecting to a local dev server without TLS.
TEMPORAL_TLS = os.environ.get('TEMPORAL_TLS', 'True').lower() in ('true', '1', 'yes')
```

### 1.3 Add Temporal vars to `.env`

**Tell Claude Code:**

```
Open the .env file (it exists at the project root new/).
Add these lines if they are not already present.
Do NOT overwrite existing values:

TEMPORAL_NAMESPACE="quickstart-kaustavr-acb569e7"
TEMPORAL_API_KEY="<paste your actual API key here>"
TEMPORAL_TASK_QUEUE="video-processing"
TEMPORAL_TLS="True"

Leave TEMPORAL_ENDPOINT as-is (already present).
After editing, confirm the file contains all four TEMPORAL_ variables.
```

---

## Phase 2 — Create the Temporal package structure

**Tell Claude Code:**

```
Create the following directory structure inside apps/core/:

    apps/core/temporal/
        __init__.py
        client.py
        activities.py
        workflows.py
        worker.py

Create each file as an empty Python file first (just a module docstring),
then we will fill them in the steps below.
Confirm the directory and all five files exist before continuing.
```

---

## Phase 3 — Implement activities (`apps/core/temporal/activities.py`)

**Tell Claude Code:**

```
Replace the contents of apps/core/temporal/activities.py with the full
implementation below. Read the existing service files in apps/core/services/
before writing — the activities are thin wrappers around those services.

The activities must:
- Call activity.heartbeat() during long-running operations so Temporal Cloud
  knows the worker is alive and can reschedule on crash.
- Call django.setup() at the top of each activity (workers run outside
  Django's normal request cycle).
- Update ProcessingJob progress and Video.status in the DB at each step.
- Use dataclasses for all inputs and outputs (required for Temporal serialization).
- NEVER import from apps.core.temporal.workflows (no circular imports).

Write the full file:

```python
"""
Temporal activities for the AI Video Engine processing pipeline.

Each activity maps to one pipeline step:
  1. download_video          — Vimeo API download
  2. extract_and_transcribe  — ffmpeg audio extraction + OpenAI Whisper
  3. create_embeddings       — Text chunking + FAISS vectorstore creation
  4. cleanup_media_files     — Delete .mp4 and .wav files
  5. rebuild_course_vectorstore — Merge per-video FAISS indexes into course index
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

import django
from temporalio import activity

logger = logging.getLogger(__name__)


# ─── Input / Output dataclasses ───────────────────────────────────────────────
# Use dataclasses, not dicts — Temporal serializes these to JSON automatically.

@dataclass
class DownloadInput:
    job_id: int
    vimeo_video_id: str
    video_url: str
    video_id: int
    media_root: str

@dataclass
class DownloadOutput:
    video_file: str
    audio_path_placeholder: str   # derived: same path with .wav extension
    title: str
    description: str
    duration: int
    filesize: int
    metadata: dict = field(default_factory=dict)

@dataclass
class TranscribeInput:
    job_id: int
    video_file: str
    media_root: str

@dataclass
class TranscribeOutput:
    transcript: str
    transcript_file: str
    segment_count: int
    audio_path: str              # absolute path to .wav (for cleanup)

@dataclass
class EmbedInput:
    job_id: int
    video_id: int
    course_id: int
    video_title: str
    transcript: str
    media_root: str

@dataclass
class EmbedOutput:
    vectorstore_abs_path: str
    vectorstore_rel_path: str
    chunk_count: int

@dataclass
class CleanupInput:
    video_file: str
    audio_path: str

@dataclass
class RebuildCourseInput:
    course_id: int


# ─── Activities ────────────────────────────────────────────────────────────────

@activity.defn
async def download_video(inp: DownloadInput) -> DownloadOutput:
    """Download Vimeo video via REST API. Updates Video and ProcessingJob in DB."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from apps.core.models import ProcessingJob, Video
    from apps.core.services.downloader import VimeoDownloader
    from django.conf import settings

    job = ProcessingJob.objects.select_related('video__course').get(id=inp.job_id)
    video = job.video

    job.update_progress(5, 'downloading')
    video.status = 'downloading'
    video.save(update_fields=['status'])

    activity.heartbeat('starting_download')

    output_dir = os.path.join(inp.media_root, 'live_videos')
    downloader = VimeoDownloader(
        vimeo_token=settings.VIMEO_TOKEN,
        output_dir=output_dir,
    )

    result = downloader.download(inp.vimeo_video_id)
    if not result.success:
        raise Exception(f'Download failed: {result.error}')

    activity.heartbeat('download_complete')

    video.local_path = os.path.relpath(result.video_file, inp.media_root)
    video.title = result.title or video.title
    video.description = result.description or ''
    video.duration_seconds = result.duration
    video.metadata = result.metadata or {}
    video.save(update_fields=[
        'local_path', 'title', 'description', 'duration_seconds', 'metadata',
    ])
    job.update_progress(25, 'download_complete')

    audio_placeholder = os.path.splitext(result.video_file)[0] + '.wav'

    return DownloadOutput(
        video_file=result.video_file,
        audio_path_placeholder=audio_placeholder,
        title=result.title,
        description=result.description,
        duration=result.duration,
        filesize=result.filesize,
        metadata=result.metadata or {},
    )


@activity.defn
async def extract_and_transcribe(inp: TranscribeInput) -> TranscribeOutput:
    """
    Extract audio from video with ffmpeg, then transcribe with OpenAI Whisper.
    Combined into one activity so the .wav file stays on the same worker process
    that created it — avoids cross-worker file path issues.
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from apps.core.models import ProcessingJob, Video
    from apps.core.services.transcriber import Transcriber
    from django.conf import settings

    job = ProcessingJob.objects.select_related('video').get(id=inp.job_id)
    video = job.video

    transcriber = Transcriber(openai_api_key=settings.OPENAI_API_KEY)

    # ── Audio extraction ──
    activity.heartbeat('extracting_audio')
    job.update_progress(30, 'transcribing')
    video.status = 'transcribing'
    video.save(update_fields=['status'])

    audio_path = transcriber.extract_audio(inp.video_file)
    if not audio_path:
        raise Exception('Audio extraction failed — check ffmpeg is installed')

    video.audio_path = os.path.relpath(audio_path, inp.media_root)
    video.save(update_fields=['audio_path'])
    job.update_progress(40, 'audio_extracted')

    # ── Transcription ──
    activity.heartbeat('transcribing')
    job.update_progress(45, 'transcribing')

    tx_result = transcriber.transcribe(audio_path)
    if not tx_result.success:
        raise Exception(f'Transcription failed: {tx_result.error}')

    video.transcript_path = os.path.relpath(tx_result.transcript_file, inp.media_root)
    video.save(update_fields=['transcript_path'])
    job.update_progress(60, 'transcription_complete')

    activity.heartbeat('transcription_complete')

    return TranscribeOutput(
        transcript=tx_result.transcript,
        transcript_file=tx_result.transcript_file,
        segment_count=tx_result.segment_count,
        audio_path=audio_path,
    )


@activity.defn
async def create_embeddings(inp: EmbedInput) -> EmbedOutput:
    """Chunk transcript text and build a per-video FAISS vectorstore."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from apps.core.models import ProcessingJob, Video
    from apps.core.services.embedder import Embedder
    from django.conf import settings

    job = ProcessingJob.objects.select_related('video').get(id=inp.job_id)
    video = job.video

    video.status = 'embedding'
    video.save(update_fields=['status'])
    job.update_progress(65, 'embedding')

    activity.heartbeat('creating_embeddings')

    embedder = Embedder(openai_api_key=settings.OPENAI_API_KEY)
    vs_save_path = os.path.join(
        inp.media_root,
        f'course_{inp.course_id}',
        'vectorstore',
        f'video_{inp.video_id}',
    )

    result = embedder.create_vectorstore(
        transcript_text=inp.transcript,
        save_path=vs_save_path,
        metadata={
            'video_id': inp.video_id,
            'course_id': inp.course_id,
            'video_title': inp.video_title,
        },
    )
    if not result.success:
        raise Exception(f'Embedding failed: {result.error}')

    activity.heartbeat('embeddings_complete')

    vs_rel_path = os.path.relpath(vs_save_path, inp.media_root)
    video.vectorstore_path = vs_rel_path
    video.save(update_fields=['vectorstore_path'])
    job.update_progress(85, 'vectorstore_created')

    return EmbedOutput(
        vectorstore_abs_path=vs_save_path,
        vectorstore_rel_path=vs_rel_path,
        chunk_count=result.chunk_count,
    )


@activity.defn
async def cleanup_media_files(inp: CleanupInput) -> None:
    """Delete .mp4 and .wav after FAISS index is persisted. Non-fatal on error."""
    for fpath in [inp.video_file, inp.audio_path]:
        try:
            if fpath and os.path.exists(fpath):
                os.remove(fpath)
                logger.info(f'Cleaned up: {fpath}')
        except Exception as e:
            logger.warning(f'Cleanup failed (non-fatal): {e}')


@activity.defn
async def rebuild_course_vectorstore(inp: RebuildCourseInput) -> str:
    """
    Merge all per-video FAISS indexes into the course-level index.
    This is memory-intensive — it runs as a separate workflow/activity
    so this worker fully releases RAM from the video pipeline first.
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from apps.core.models import Course
    from apps.core.services.aggregator import CourseAggregator
    from django.conf import settings

    course = Course.objects.get(id=inp.course_id)
    aggregator = CourseAggregator(openai_api_key=settings.OPENAI_API_KEY)

    activity.heartbeat('rebuilding_course_vectorstore')

    result = aggregator.force_rebuild(course)

    logger.info(
        f'Course rebuild for "{course.title}": {result.status} '
        f'({result.videos_merged} merged, {result.videos_skipped} skipped)'
    )
    return result.status
```

After writing the file, confirm it exists at apps/core/temporal/activities.py
and has no syntax errors by running: python -c "import ast; ast.parse(open('apps/core/temporal/activities.py').read()); print('OK')"
```

---

## Phase 4 — Implement workflows (`apps/core/temporal/workflows.py`)

**Tell Claude Code:**

```
Replace the contents of apps/core/temporal/workflows.py with the full
implementation below.

CRITICAL RULES for workflow code:
- No I/O of any kind (no DB, no file, no network, no subprocess)
- No datetime.now(), random(), os.getenv() calls
- No imports of Django models or services
- Activity imports MUST use: with workflow.unsafe.imports_passed_through():
- All inputs/outputs must be dataclasses (defined in activities.py)
- The workflow is ONLY orchestration — it calls activities and handles the results

```python
"""
Temporal workflow definitions for the AI Video Engine.

VideoProcessingWorkflow orchestrates the full pipeline:
    download → transcribe → embed → cleanup → [child] course rebuild

CourseRebuildWorkflow runs separately to avoid OOM from merging all FAISS indexes
while the video pipeline memory is still in use.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from apps.core.temporal.activities import (
        DownloadInput, DownloadOutput,
        TranscribeInput, TranscribeOutput,
        EmbedInput, EmbedOutput,
        CleanupInput, RebuildCourseInput,
        download_video,
        extract_and_transcribe,
        create_embeddings,
        cleanup_media_files,
        rebuild_course_vectorstore,
    )


@dataclass
class VideoProcessingInput:
    job_id: int
    video_id: int
    course_id: int
    vimeo_video_id: str
    video_url: str
    video_title: str
    media_root: str


# Retry policy for network/API-heavy steps.
# 3 attempts, exponential backoff starting at 30s.
# ValueError is non-retryable (bad input, not transient).
_network_retry = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    non_retryable_error_types=['ValueError'],
)

# Cleanup is best-effort — 2 attempts, no long wait
_cleanup_retry = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=5),
)


@workflow.defn
class VideoProcessingWorkflow:
    """
    Full video processing pipeline.

    Each step is an Activity with its own timeout, heartbeat timeout, and
    retry policy. If this worker crashes mid-pipeline, Temporal replays
    the event history and resumes from the last completed activity.

    The course rebuild runs as a child workflow so it gets its own durable
    execution context after this workflow completes and frees its memory.
    """

    @workflow.run
    async def run(self, inp: VideoProcessingInput) -> dict:

        # ── Step 1: Download video from Vimeo ────────────────────────────
        dl: DownloadOutput = await workflow.execute_activity(
            download_video,
            DownloadInput(
                job_id=inp.job_id,
                vimeo_video_id=inp.vimeo_video_id,
                video_url=inp.video_url,
                video_id=inp.video_id,
                media_root=inp.media_root,
            ),
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=_network_retry,
        )

        # ── Step 2: Extract audio + transcribe ────────────────────────────
        tx: TranscribeOutput = await workflow.execute_activity(
            extract_and_transcribe,
            TranscribeInput(
                job_id=inp.job_id,
                video_file=dl.video_file,
                media_root=inp.media_root,
            ),
            start_to_close_timeout=timedelta(minutes=90),
            heartbeat_timeout=timedelta(minutes=10),
            retry_policy=_network_retry,
        )

        # ── Step 3: Create FAISS vectorstore from transcript ─────────────
        embed: EmbedOutput = await workflow.execute_activity(
            create_embeddings,
            EmbedInput(
                job_id=inp.job_id,
                video_id=inp.video_id,
                course_id=inp.course_id,
                video_title=inp.video_title,
                transcript=tx.transcript,
                media_root=inp.media_root,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=_network_retry,
        )

        # ── Step 4: Mark job complete and update video status ─────────────
        # This activity updates the DB to mark vectorstore_created=True
        await workflow.execute_activity(
            mark_job_complete,
            MarkCompleteInput(
                job_id=inp.job_id,
                video_id=inp.video_id,
                course_id=inp.course_id,
                chunk_count=embed.chunk_count,
                segment_count=tx.segment_count,
                vectorstore_path=embed.vectorstore_abs_path,
                video_file=dl.video_file,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_cleanup_retry,
        )

        # ── Step 5: Clean up .mp4 and .wav files ──────────────────────────
        await workflow.execute_activity(
            cleanup_media_files,
            CleanupInput(
                video_file=dl.video_file,
                audio_path=tx.audio_path,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_cleanup_retry,
        )

        # ── Step 6: Rebuild course vectorstore (child workflow) ───────────
        # Run as a child workflow so this workflow can finish and release
        # memory before the FAISS merge begins.
        await workflow.execute_child_workflow(
            CourseRebuildWorkflow.run,
            RebuildCourseInput(course_id=inp.course_id),
            id=f'course-rebuild-{inp.course_id}',
            task_queue='video-processing',
            execution_timeout=timedelta(minutes=40),
        )

        return {
            'video_id': inp.video_id,
            'chunk_count': embed.chunk_count,
            'transcript_segments': tx.segment_count,
            'status': 'completed',
        }


@workflow.defn
class CourseRebuildWorkflow:
    """
    Rebuild course-level FAISS vectorstore by merging all per-video indexes.
    Runs as a standalone workflow so it always starts with a clean memory slate.
    """

    @workflow.run
    async def run(self, inp: RebuildCourseInput) -> str:
        return await workflow.execute_activity(
            rebuild_course_vectorstore,
            inp,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(seconds=30),
            ),
        )
```

IMPORTANT: The workflow references mark_job_complete and MarkCompleteInput
which are not yet defined. After writing this file, also add the following
to apps/core/temporal/activities.py:

```python
@dataclass
class MarkCompleteInput:
    job_id: int
    video_id: int
    course_id: int
    chunk_count: int
    segment_count: int
    vectorstore_path: str
    video_file: str


@activity.defn
async def mark_job_complete(inp: MarkCompleteInput) -> None:
    """Mark ProcessingJob as completed and update Video.vectorstore_created."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from apps.core.models import ProcessingJob

    job = ProcessingJob.objects.select_related('video__course').get(id=inp.job_id)
    job.processing_details = {
        'vectorstore': {
            'chunks': inp.chunk_count,
            'path': inp.vectorstore_path,
        },
        'transcript': {'segments': inp.segment_count},
    }
    job.mark_completed()   # sets video.vectorstore_created=True, course.update_statistics()
```

Also add MarkCompleteInput and mark_job_complete to the imports block in workflows.py.

After editing both files, verify syntax:
    python -c "import ast; ast.parse(open('apps/core/temporal/activities.py').read()); print('activities OK')"
    python -c "import ast; ast.parse(open('apps/core/temporal/workflows.py').read()); print('workflows OK')"
```

---

## Phase 5 — Implement Temporal client helper (`apps/core/temporal/client.py`)

**Tell Claude Code:**

```
Replace the contents of apps/core/temporal/client.py with the implementation below.

This module provides get_client() (async) and start_video_workflow() (sync wrapper
safe to call from Django views). It reads all connection details from Django settings
which in turn reads from .env.

Temporal Cloud requires TLS + API key authentication.
The API key is passed as metadata, not as a certificate.

```python
"""
Temporal Cloud client factory and sync workflow dispatch helpers.

Usage from Django views (synchronous context):

    from apps.core.temporal.client import start_video_workflow
    workflow_id = start_video_workflow(job_id=job.id, video=video)
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level cached client (reused across requests in the same worker process)
_client = None


async def get_client():
    """
    Return a connected Temporal Cloud client, creating it if needed.

    Uses API key authentication with TLS — required for Temporal Cloud.
    Connection details come from Django settings (read from .env).
    """
    global _client
    if _client is not None:
        return _client

    from django.conf import settings
    from temporalio.client import Client, TLSConfig
    from temporalio.service import ApiKeyCallCredentials

    endpoint = settings.TEMPORAL_ENDPOINT     # e.g. "quickstart-xxx.o6j79.tmprl.cloud:7233"
    namespace = settings.TEMPORAL_NAMESPACE   # e.g. "quickstart-xxx"
    api_key = settings.TEMPORAL_API_KEY
    use_tls = settings.TEMPORAL_TLS

    connect_kwargs = {
        'target_host': endpoint,
        'namespace': namespace,
    }

    if api_key:
        connect_kwargs['api_key'] = api_key

    if use_tls:
        # Temporal Cloud uses TLS on all connections.
        # TLSConfig() with no arguments uses the system CA bundle.
        connect_kwargs['tls'] = True

    logger.info(f'Connecting to Temporal Cloud: {endpoint} / namespace: {namespace}')
    _client = await Client.connect(**connect_kwargs)
    logger.info('Temporal Cloud client connected')
    return _client


def _run_async(coro):
    """Run an async coroutine from sync Django view code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an existing event loop (e.g. async Django/ASGI).
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def start_video_workflow(job_id: int, video) -> str:
    """
    Dispatch a VideoProcessingWorkflow for a video. Sync-safe for Django views.

    Args:
        job_id: ID of the ProcessingJob record.
        video:  Video model instance (needs .id, .course_id, .vimeo_video_id,
                .video_url, .title).

    Returns:
        The Temporal workflow ID (string).
    """
    from django.conf import settings
    from apps.core.temporal.workflows import VideoProcessingWorkflow, VideoProcessingInput

    async def _start():
        client = await get_client()
        workflow_input = VideoProcessingInput(
            job_id=job_id,
            video_id=video.id,
            course_id=video.course_id,
            vimeo_video_id=video.vimeo_video_id,
            video_url=video.video_url,
            video_title=video.title,
            media_root=str(settings.MEDIA_ROOT),
        )
        # Workflow ID is deterministic: re-submitting the same video+job
        # will reuse the existing workflow rather than creating a duplicate.
        workflow_id = f'video-{video.id}-job-{job_id}'
        handle = await client.start_workflow(
            VideoProcessingWorkflow.run,
            workflow_input,
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
        logger.info(f'Started Temporal workflow: {workflow_id}')
        return handle.id

    return _run_async(_start())


def start_course_rebuild(course_id: int) -> str:
    """
    Dispatch a CourseRebuildWorkflow. Sync-safe for Django views.
    Used by VideoDeleteAPI when a video is deleted.
    """
    from django.conf import settings
    from apps.core.temporal.workflows import CourseRebuildWorkflow
    from apps.core.temporal.activities import RebuildCourseInput

    async def _start():
        client = await get_client()
        workflow_id = f'course-rebuild-{course_id}-manual'
        handle = await client.start_workflow(
            CourseRebuildWorkflow.run,
            RebuildCourseInput(course_id=course_id),
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
        return handle.id

    return _run_async(_start())
```

Verify syntax:
    python -c "import ast; ast.parse(open('apps/core/temporal/client.py').read()); print('client OK')"
```

---

## Phase 6 — Implement the worker (`apps/core/temporal/worker.py`)

**Tell Claude Code:**

```
Replace the contents of apps/core/temporal/worker.py with the full
implementation below.

The worker connects to Temporal Cloud with TLS + API key, then polls
the task queue indefinitely. Run it with:
    python -m apps.core.temporal.worker

```python
"""
Temporal worker for the AI Video Engine.

Polls the 'video-processing' task queue on Temporal Cloud and executes
Workflow and Activity code locally on this machine.

Run with:
    cd new/
    python -m apps.core.temporal.worker

Environment variables required (read from .env via Django settings):
    TEMPORAL_ENDPOINT   — Temporal Cloud gRPC endpoint (host:port)
    TEMPORAL_NAMESPACE  — Temporal Cloud namespace
    TEMPORAL_API_KEY    — Temporal Cloud API key
    TEMPORAL_TASK_QUEUE — Task queue name (default: video-processing)
    DJANGO_SETTINGS_MODULE — set automatically below
"""

import asyncio
import logging
import os
import sys

# Ensure project root is on path when running as __main__
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.conf import settings
from temporalio.client import Client
from temporalio.worker import Worker

from apps.core.temporal.workflows import VideoProcessingWorkflow, CourseRebuildWorkflow
from apps.core.temporal.activities import (
    download_video,
    extract_and_transcribe,
    create_embeddings,
    cleanup_media_files,
    rebuild_course_vectorstore,
    mark_job_complete,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
)
logger = logging.getLogger(__name__)


async def main():
    endpoint = settings.TEMPORAL_ENDPOINT
    namespace = settings.TEMPORAL_NAMESPACE
    api_key = settings.TEMPORAL_API_KEY
    task_queue = settings.TEMPORAL_TASK_QUEUE
    use_tls = settings.TEMPORAL_TLS

    logger.info(f'Connecting to Temporal Cloud: {endpoint}')
    logger.info(f'Namespace: {namespace} | Task queue: {task_queue}')

    connect_kwargs = {
        'target_host': endpoint,
        'namespace': namespace,
    }
    if api_key:
        connect_kwargs['api_key'] = api_key
    if use_tls:
        connect_kwargs['tls'] = True

    client = await Client.connect(**connect_kwargs)
    logger.info('Connected to Temporal Cloud successfully')

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[
            VideoProcessingWorkflow,
            CourseRebuildWorkflow,
        ],
        activities=[
            download_video,
            extract_and_transcribe,
            create_embeddings,
            cleanup_media_files,
            rebuild_course_vectorstore,
            mark_job_complete,
        ],
        # Each activity is IO-bound (network + disk). 4 concurrent activities
        # matches the original CELERY_WORKER_CONCURRENCY=4 setting.
        max_concurrent_activities=4,
        # Limit concurrent workflow tasks (orchestration only, very lightweight)
        max_concurrent_workflow_tasks=10,
    )

    logger.info(f'Worker started. Polling task queue: "{task_queue}"')
    logger.info('Press Ctrl+C to stop.')
    await worker.run()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Worker stopped.')
```

Verify syntax:
    python -c "import ast; ast.parse(open('apps/core/temporal/worker.py').read()); print('worker OK')"
```

---

## Phase 7 — Update `__init__.py` for the temporal package

**Tell Claude Code:**

```
Replace apps/core/temporal/__init__.py with:

```python
"""Temporal Cloud workflow and activity definitions for the AI Video Engine."""
```

This is just a docstring — keep it minimal.
```

---

## Phase 8 — Update Django views to use Temporal

**Tell Claude Code:**

```
Open apps/core/api/views/video_views.py. Read the full file first.

Make the following three targeted changes. Do NOT rewrite the entire file —
use str_replace to make surgical edits only.

Change 1: In VideoCreateAPI.post(), find this block:

    # Dispatch async task safely using signature/send_task (avoids Celery 3.12 ChannelPromise bug)
    from celery import current_app
    current_app.send_task('apps.core.tasks.processing.process_video_task', args=[job.id])

    logger.info(f'Video {vimeo_id} added to course "{course.title}", job {job.id} dispatched')

Replace it with:

    from apps.core.temporal.client import start_video_workflow
    workflow_id = start_video_workflow(job_id=job.id, video=video)

    logger.info(f'Video {vimeo_id} added to course "{course.title}", Temporal workflow {workflow_id} started')

---

Change 2: In BulkVideoCreateAPI.post(), find this block inside the for loop:

            from celery import current_app
            current_app.send_task(
                'apps.core.tasks.processing.process_video_task',
                args=[job.id],
            )

Replace it with:

            from apps.core.temporal.client import start_video_workflow
            start_video_workflow(job_id=job.id, video=video)

---

Change 3: In VideoDeleteAPI.post(), find this block:

    # Rebuild course vectorstore in the background
    from celery import current_app
    current_app.send_task(
        'apps.core.tasks.processing.rebuild_course_vectorstore_task',
        args=[course_id],
    )

Replace it with:

    from apps.core.temporal.client import start_course_rebuild
    start_course_rebuild(course_id=int(course_id))

---

After making all three changes, verify the file has no syntax errors:
    python -c "import ast; ast.parse(open('apps/core/api/views/video_views.py').read()); print('video_views OK')"

Also grep to confirm no celery imports remain in video_views.py:
    grep -n "celery" apps/core/api/views/video_views.py
(expect: no output)
```

---

## Phase 9 — Preserve `config/celery.py` and `apps/core/tasks/processing.py` (no deletions)

**Tell Claude Code:**

```
IMPORTANT: Do NOT delete or modify config/celery.py or apps/core/tasks/processing.py.
Both files must remain exactly as they are. The Celery task code is kept as a
fallback and for reference — it is simply no longer called by the Django views.

The only change needed is to disable the worker_ready signal so that if someone
accidentally starts a Celery worker, it does not re-dispatch jobs that are now
being handled by Temporal.

Open config/celery.py. Find the @worker_ready.connect decorated function:

    @worker_ready.connect
    def redispatch_stuck_jobs(sender, **kwargs):

Wrap the entire body of that function in an early-return guard so it does nothing,
but keep all the original code in place as commented-out documentation.

The result should look like this — use str_replace, do NOT rewrite the whole file:

    @worker_ready.connect
    def redispatch_stuck_jobs(sender, **kwargs):
        """
        Re-queue any SCHEDULED jobs that were stuck when the worker was down.

        NOTE: This function is intentionally disabled.
        Video processing has been migrated to Temporal Cloud. The Celery task
        code in apps/core/tasks/processing.py is kept for reference but is no
        longer invoked. Temporal maintains durable workflow state — if a worker
        restarts, open VideoProcessingWorkflow executions resume automatically
        from their last completed activity without any manual re-queuing.

        To re-enable Celery processing, remove the early return below and
        revert the dispatch calls in apps/core/api/views/video_views.py.
        """
        # Disabled: processing is now handled by Temporal Cloud.
        return

        # --- Original Celery re-dispatch logic (kept for reference) ---
        import django
        django.setup()

        from apps.core.models import ProcessingJob
        stuck_jobs = list(ProcessingJob.objects.filter(status='SCHEDULED'))
        count = len(stuck_jobs)
        if count:
            for i, job in enumerate(stuck_jobs):
                app.send_task(
                    'apps.core.tasks.processing.process_video_task',
                    args=[job.id],
                    countdown=i * 60,
                )
            spread_mins = count
            print(f'[celery] Staggered re-dispatch of {count} stuck SCHEDULED job(s) '
                  f'over ~{spread_mins} minute(s)')
        else:
            print('[celery] No stuck jobs found')

After editing, verify the file has no syntax errors:
    python -c "import ast; ast.parse(open('config/celery.py').read()); print('celery.py OK')"

Also confirm apps/core/tasks/processing.py is completely untouched:
    git diff apps/core/tasks/processing.py
(expect: no output — zero changes to this file)

If git is not available, just confirm the file exists and has not been modified:
    python -c "import ast; ast.parse(open('apps/core/tasks/processing.py').read()); print('processing.py OK')"
```

---

## Phase 10 — Smoke test the connection

**Tell Claude Code:**

```
Create a temporary test script at the project root called test_temporal_connection.py:

```python
"""Quick smoke test — connect to Temporal Cloud and list namespaces."""
import asyncio
import os
import sys

sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.conf import settings

async def test():
    from temporalio.client import Client

    print(f"Endpoint : {settings.TEMPORAL_ENDPOINT}")
    print(f"Namespace: {settings.TEMPORAL_NAMESPACE}")
    print(f"TLS      : {settings.TEMPORAL_TLS}")
    print(f"API key  : {'set' if settings.TEMPORAL_API_KEY else 'NOT SET'}")
    print()

    connect_kwargs = {
        'target_host': settings.TEMPORAL_ENDPOINT,
        'namespace': settings.TEMPORAL_NAMESPACE,
    }
    if settings.TEMPORAL_API_KEY:
        connect_kwargs['api_key'] = settings.TEMPORAL_API_KEY
    if settings.TEMPORAL_TLS:
        connect_kwargs['tls'] = True

    print("Connecting...")
    client = await Client.connect(**connect_kwargs)
    print("Connected OK")

    # Try listing a workflow (will return empty list, just proves auth works)
    workflows = [w async for w in client.list_workflows(query='', page_size=1)]
    print(f"Workflow query OK (found {len(workflows)} recent workflows)")
    print()
    print("SUCCESS — Temporal Cloud connection is working.")

asyncio.run(test())
```

Run it:
    python test_temporal_connection.py

Expected output:
    Endpoint : quickstart-kaustavr-acb569e7.o6j79.tmprl.cloud:7233
    Namespace: quickstart-kaustavr-acb569e7
    TLS      : True
    API key  : set
    Connecting...
    Connected OK
    Workflow query OK (found 0 recent workflows)
    SUCCESS — Temporal Cloud connection is working.

If it fails with an authentication error, check that TEMPORAL_API_KEY is
set correctly in .env and that TEMPORAL_NAMESPACE matches the subdomain
of your endpoint.

After the test passes, delete the test script:
    rm test_temporal_connection.py
```

---

## Phase 11 — Run the worker and trigger a test workflow

**Tell Claude Code:**

```
Start the Temporal worker in a terminal:

    cd new/
    python -m apps.core.temporal.worker

You should see:
    Connected to Temporal Cloud successfully
    Worker started. Polling task queue: "video-processing"

Leave this running. Open a second terminal and start Django:

    cd new/
    python manage.py runserver

In a third terminal, trigger a test workflow via the API.
First create a course:

    curl -s -X POST http://localhost:8000/api/courses/ \
      -H "Content-Type: application/json" \
      -d '{"title": "Temporal Test Course", "description": "Testing Temporal migration"}' | python -m json.tool

Note the course ID from the response (e.g. "id": 1).

Then add a video (use a real Vimeo URL from your account):

    curl -s -X POST http://localhost:8000/api/videos/ \
      -H "Content-Type: application/json" \
      -d '{"course_id": 1, "video_url": "https://vimeo.com/YOUR_VIDEO_ID"}' | python -m json.tool

Expected response includes:
    "message": "Video added and processing started"

Check the Temporal Cloud UI:
    https://cloud.temporal.io/

Navigate to your namespace and you should see a new VideoProcessingWorkflow
execution in "Running" state.

Poll video status:
    curl -s -X POST http://localhost:8000/api/videos/status/ \
      -H "Content-Type: application/json" \
      -d '{"id": <video_id>}' | python -m json.tool

The status should progress through: downloading → transcribing → embedding → ready
```

---

## Phase 12 — Add a Django management command to start the worker

**Tell Claude Code:**

```
Create a new management command file at:
    apps/core/management/commands/run_temporal_worker.py

```python
"""
Management command: run_temporal_worker

Starts the Temporal worker process.

Usage:
    python manage.py run_temporal_worker
    python manage.py run_temporal_worker --concurrency 8
    python manage.py run_temporal_worker --task-queue custom-queue
"""

import asyncio
import logging

from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Start the Temporal Cloud worker for video processing.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--concurrency',
            type=int,
            default=4,
            help='Max concurrent activities (default: 4)',
        )
        parser.add_argument(
            '--task-queue',
            type=str,
            default=None,
            help='Task queue name (default: from settings)',
        )

    def handle(self, *args, **options):
        concurrency = options['concurrency']
        task_queue = options['task_queue'] or settings.TEMPORAL_TASK_QUEUE

        self.stdout.write(self.style.SUCCESS(
            f'\nStarting Temporal worker\n'
            f'  Endpoint  : {settings.TEMPORAL_ENDPOINT}\n'
            f'  Namespace : {settings.TEMPORAL_NAMESPACE}\n'
            f'  Task queue: {task_queue}\n'
            f'  Concurrency: {concurrency}\n'
        ))

        asyncio.run(self._run(concurrency, task_queue))

    async def _run(self, concurrency: int, task_queue: str):
        from temporalio.client import Client
        from temporalio.worker import Worker

        from apps.core.temporal.workflows import (
            VideoProcessingWorkflow, CourseRebuildWorkflow,
        )
        from apps.core.temporal.activities import (
            download_video,
            extract_and_transcribe,
            create_embeddings,
            cleanup_media_files,
            rebuild_course_vectorstore,
            mark_job_complete,
        )

        connect_kwargs = {
            'target_host': settings.TEMPORAL_ENDPOINT,
            'namespace': settings.TEMPORAL_NAMESPACE,
        }
        if settings.TEMPORAL_API_KEY:
            connect_kwargs['api_key'] = settings.TEMPORAL_API_KEY
        if settings.TEMPORAL_TLS:
            connect_kwargs['tls'] = True

        client = await Client.connect(**connect_kwargs)
        self.stdout.write(self.style.SUCCESS('Connected to Temporal Cloud.'))

        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[VideoProcessingWorkflow, CourseRebuildWorkflow],
            activities=[
                download_video,
                extract_and_transcribe,
                create_embeddings,
                cleanup_media_files,
                rebuild_course_vectorstore,
                mark_job_complete,
            ],
            max_concurrent_activities=concurrency,
            max_concurrent_workflow_tasks=10,
        )

        self.stdout.write('Worker running. Press Ctrl+C to stop.\n')
        await worker.run()
```

After creating the file, confirm it works:
    python manage.py run_temporal_worker --help

Now the worker can be started with:
    python manage.py run_temporal_worker
    python manage.py run_temporal_worker --concurrency 8
```

---

## Phase 13 — Final cleanup and verification

**Tell Claude Code:**

```
Run the following verification steps in order. Fix any errors before proceeding.

Step 1 — Syntax check all new files:
    python -c "
    import ast
    files = [
        'apps/core/temporal/__init__.py',
        'apps/core/temporal/activities.py',
        'apps/core/temporal/workflows.py',
        'apps/core/temporal/client.py',
        'apps/core/temporal/worker.py',
        'apps/core/management/commands/run_temporal_worker.py',
    ]
    for f in files:
        ast.parse(open(f).read())
        print(f'OK: {f}')
    print('All files syntax OK')
    "

Step 2 — Confirm view files no longer dispatch via Celery:
    grep -n "current_app.send_task" apps/core/api/views/video_views.py

Expected: no output (Celery dispatch calls replaced with Temporal in views)

Also confirm the underlying Celery task code is still fully intact:
    grep -n "def process_video_task\|def rebuild_course_vectorstore_task" apps/core/tasks/processing.py

Expected output (both functions must be present):
    def process_video_task(self, job_id: int):
    def rebuild_course_vectorstore_task(self, course_id: int):

Step 3 — Confirm Temporal imports resolve (without actually connecting):
    python -c "
    import os
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    import django; django.setup()
    from apps.core.temporal.activities import download_video, extract_and_transcribe
    from apps.core.temporal.workflows import VideoProcessingWorkflow
    from apps.core.temporal.client import get_client
    print('All Temporal imports OK')
    "

Step 4 — Confirm Django management command is registered:
    python manage.py help | grep temporal

Expected output includes: run_temporal_worker

Step 5 — Print summary of new files created:
    find apps/core/temporal/ -type f -name "*.py" | sort
    find apps/core/management/commands/ -name "run_temporal_worker.py"
```

---

## Final file structure

After all phases are complete, the new structure should be:

```
new/
├── .env                                    # TEMPORAL_* vars added
├── config/
│   ├── settings.py                         # TEMPORAL_* settings block added
│   └── celery.py                           # KEPT INTACT — worker_ready body disabled with early return
├── apps/
│   └── core/
│       ├── tasks/
│       │   └── processing.py              # KEPT INTACT — untouched, kept for reference
│       ├── temporal/                       # NEW
│       │   ├── __init__.py
│       │   ├── activities.py               # 6 @activity.defn functions
│       │   ├── workflows.py                # VideoProcessingWorkflow + CourseRebuildWorkflow
│       │   ├── client.py                   # get_client(), start_video_workflow(), start_course_rebuild()
│       │   └── worker.py                   # asyncio.run(main()) entry point
│       ├── api/
│       │   └── views/
│       │       └── video_views.py          # Celery send_task calls swapped for Temporal client calls
│       └── management/
│           └── commands/
│               └── run_temporal_worker.py  # NEW: python manage.py run_temporal_worker
```

---

## Running in production

```bash
# Start the Temporal worker (replaces: celery -A config worker)
python manage.py run_temporal_worker --concurrency 4

# Or directly:
python -m apps.core.temporal.worker

# Django server (unchanged)
python manage.py runserver

# Monitor workflows:
# https://cloud.temporal.io/ → your namespace → Workflows
```

## Troubleshooting

| Error | Likely cause | Fix |
|---|---|---|
| `ssl.SSLError` or `UNAVAILABLE` | TLS misconfigured | Ensure `TEMPORAL_TLS=True` in `.env` |
| `UNAUTHENTICATED` | Wrong or missing API key | Check `TEMPORAL_API_KEY` in `.env` |
| `Namespace not found` | Wrong namespace string | Must match subdomain of your endpoint exactly |
| `Activity not registered` | Worker started without new activity | Restart worker after adding activities |
| `Non-determinism error` | I/O in workflow code | Move offending code into an activity |
| `Heartbeat timeout` | Long activity not heartbeating | Add `activity.heartbeat()` calls every few minutes |
| `django.core.exceptions.AppRegistryNotReady` | `django.setup()` missing in activity | Each activity must call `django.setup()` |
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
    from temporalio.client import Client

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

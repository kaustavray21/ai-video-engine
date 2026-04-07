"""
Temporal worker for the AI Video Engine.

Polls the 'video-processing' task queue on Temporal Cloud and executes
Workflow and Activity code locally on this machine.

Run with:
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
import concurrent.futures

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

    # ThreadPoolExecutor is required because activities are sync (def, not async def).
    # Sync activities allow Django ORM calls without SynchronousOnlyOperation errors.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
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
            activity_executor=executor,
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

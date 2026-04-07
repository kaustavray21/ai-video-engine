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
        import concurrent.futures

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

        # ThreadPoolExecutor is required because activities are sync (def, not async def).
        # Sync activities allow Django ORM calls without SynchronousOnlyOperation errors.
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
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
                activity_executor=executor,
                max_concurrent_activities=concurrency,
                max_concurrent_workflow_tasks=10,
            )

            self.stdout.write('Worker running. Press Ctrl+C to stop.\n')
            await worker.run()

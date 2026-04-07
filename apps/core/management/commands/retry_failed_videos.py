"""
Management command: retry_failed_videos

Re-dispatches FAILED or stuck SCHEDULED/IN_PROGRESS video processing jobs
as new Temporal workflows. This is useful when the previous worker had bugs
(e.g. SynchronousOnlyOperation) and jobs exhausted their retries.

Usage:
    python manage.py retry_failed_videos              — retry all FAILED jobs
    python manage.py retry_failed_videos --all         — also retry stuck SCHEDULED/IN_PROGRESS
    python manage.py retry_failed_videos --dry-run     — preview without dispatching
    python manage.py retry_failed_videos --job-ids 39 40 41  — retry specific job IDs
"""

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Re-dispatch failed/stuck video processing jobs as new Temporal workflows.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            default=False,
            help='Also retry stuck SCHEDULED and IN_PROGRESS jobs (not just FAILED)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Preview jobs that would be retried without actually dispatching',
        )
        parser.add_argument(
            '--job-ids',
            nargs='+',
            type=int,
            default=None,
            help='Retry specific job IDs (space-separated)',
        )

    def handle(self, *args, **options):
        from apps.core.models import ProcessingJob

        dry_run = options['dry_run']
        include_all = options['all']
        specific_ids = options['job_ids']

        # ── Build queryset ──
        if specific_ids:
            jobs = ProcessingJob.objects.filter(
                id__in=specific_ids,
            ).select_related('video__course')
            label = f"specific IDs: {specific_ids}"
        elif include_all:
            jobs = ProcessingJob.objects.filter(
                status__in=['FAILED', 'SCHEDULED', 'IN_PROGRESS'],
            ).select_related('video__course')
            label = "FAILED + SCHEDULED + IN_PROGRESS"
        else:
            jobs = ProcessingJob.objects.filter(
                status='FAILED',
            ).select_related('video__course')
            label = "FAILED"

        jobs_list = list(jobs)
        count = len(jobs_list)

        if count == 0:
            self.stdout.write(self.style.WARNING(f'\nNo jobs found matching filter: {label}\n'))
            return

        self.stdout.write(self.style.SUCCESS(
            f'\nFound {count} job(s) to retry ({label}):\n'
        ))

        # ── Preview ──
        for job in jobs_list:
            video = job.video
            self.stdout.write(
                f'  Job {job.id:>4d} | {job.status:<12s} | '
                f'Video {video.id} "{video.title}" | '
                f'Course "{video.course.title}" | '
                f'Attempts: {job.retry_count}/{job.max_retries} | '
                f'Error: {job.error_message[:80] if job.error_message else "—"}'
            )

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\n[DRY RUN] Would retry {count} job(s). Run without --dry-run to dispatch.\n'
            ))
            return

        # ── Dispatch ──
        self.stdout.write(f'\nDispatching {count} Temporal workflow(s)...\n')

        from apps.core.temporal.client import start_video_workflow

        success_count = 0
        for job in jobs_list:
            video = job.video

            try:
                # Reset job state for a fresh run
                job.status = 'SCHEDULED'
                job.progress = 0
                job.current_step = ''
                job.error_message = ''
                job.error_traceback = ''
                job.started_at = None
                job.completed_at = None
                job.retry_count += 1
                job.save(update_fields=[
                    'status', 'progress', 'current_step',
                    'error_message', 'error_traceback',
                    'started_at', 'completed_at', 'retry_count',
                ])

                # Reset video status
                video.status = 'pending'
                video.save(update_fields=['status'])

                # Dispatch Temporal workflow
                workflow_id = start_video_workflow(job_id=job.id, video=video)

                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ Job {job.id} → workflow {workflow_id}'
                ))
                success_count += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ Job {job.id} — dispatch failed: {e}'
                ))
                logger.exception(f'Failed to dispatch retry for job {job.id}')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {success_count}/{count} workflows dispatched successfully.\n'
        ))

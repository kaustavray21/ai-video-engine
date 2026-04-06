"""
Management command: purge_video_queue

Cleanly cancels ALL pending and actively running video processing tasks.

What it does (in order):
  1. Revokes every active/reserved Celery task with SIGTERM
  2. Purges the entire Celery queue in Redis (removes waiting tasks)
  3. Marks every SCHEDULED / PROCESSING ProcessingJob in the DB as FAILED

Usage:
    python manage.py purge_video_queue
    python manage.py purge_video_queue --dry-run     # preview only, no changes
    python manage.py purge_video_queue --db-only     # only fix DB, skip Celery
"""

import json

from django.core.management.base import BaseCommand

from config.celery import app as celery_app


class Command(BaseCommand):
    help = 'Cancel all pending and running video processing tasks and reset their DB state.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making any changes.',
        )
        parser.add_argument(
            '--db-only',
            action='store_true',
            help='Only reset DB job statuses — skip Celery revoke/purge.',
        )

    def handle(self, *args, **options):
        dry = options['dry_run']
        db_only = options['db_only']

        self.stdout.write(self.style.WARNING(
            '\n══════════════════════════════════════════'
        ))
        self.stdout.write(self.style.WARNING(
            '  VIDEO QUEUE PURGE' + (' [DRY RUN]' if dry else '')
        ))
        self.stdout.write(self.style.WARNING(
            '══════════════════════════════════════════\n'
        ))

        # ── Step 1: Revoke all active / reserved tasks ──────────────────────
        if not db_only:
            self.stdout.write('▶ Step 1 — Inspecting active Celery tasks...')
            try:
                active_raw = celery_app.control.inspect(timeout=4).active() or {}
                reserved_raw = celery_app.control.inspect(timeout=4).reserved() or {}

                task_ids = []
                for worker_tasks in active_raw.values():
                    task_ids.extend(t['id'] for t in worker_tasks)
                for worker_tasks in reserved_raw.values():
                    task_ids.extend(t['id'] for t in worker_tasks)

                if task_ids:
                    self.stdout.write(
                        f'  Found {len(task_ids)} active/reserved task(s) to revoke:'
                    )
                    for tid in task_ids:
                        self.stdout.write(f'    • {tid}')

                    if not dry:
                        celery_app.control.revoke(task_ids, terminate=True, signal='SIGTERM')
                        self.stdout.write(self.style.SUCCESS(
                            f'  ✓ Revoked {len(task_ids)} task(s) with SIGTERM'
                        ))
                    else:
                        self.stdout.write('  [dry-run] Would revoke the above tasks.')
                else:
                    self.stdout.write('  No active or reserved tasks found.')

            except Exception as e:
                self.stdout.write(self.style.NOTICE(
                    f'  ⚠ Could not inspect workers (is the worker running?): {e}'
                ))

            # ── Step 2: Purge the Redis queue ───────────────────────────────
            self.stdout.write('\n▶ Step 2 — Purging Celery queue in Redis...')
            try:
                if not dry:
                    purged = celery_app.control.purge()
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✓ Purged queue — {purged} message(s) removed'
                    ))
                else:
                    self.stdout.write('  [dry-run] Would purge the Redis queue.')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ✗ Queue purge failed: {e}'))

        # ── Step 3: Reset stuck DB job statuses ─────────────────────────────
        self.stdout.write('\n▶ Step 3 — Resetting job statuses in database...')
        try:
            from apps.core.models import ProcessingJob

            stuck = ProcessingJob.objects.filter(status__in=['SCHEDULED', 'PROCESSING'])
            count = stuck.count()

            if count:
                self.stdout.write(f'  Found {count} SCHEDULED/PROCESSING job(s):')
                for job in stuck.select_related('video')[:20]:   # preview first 20
                    self.stdout.write(
                        f'    • Job #{job.id} — "{job.video.title}" [{job.status}]'
                    )
                if count > 20:
                    self.stdout.write(f'    … and {count - 20} more')

                if not dry:
                    stuck.update(
                        status='FAILED',
                        error_message='Manually cancelled via purge_video_queue command.',
                    )
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✓ Marked {count} job(s) as FAILED'
                    ))
                else:
                    self.stdout.write(f'  [dry-run] Would mark {count} job(s) as FAILED.')
            else:
                self.stdout.write('  No stuck jobs found in the database.')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  ✗ DB reset failed: {e}'))

        # ── Done ────────────────────────────────────────────────────────────
        self.stdout.write('')
        if dry:
            self.stdout.write(self.style.WARNING(
                'Dry run complete — no changes were made.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                '✓ Queue purge complete. Safe to restart the Celery worker.'
            ))
        self.stdout.write('')

"""
Celery app configuration for AI Video Engine.
"""

import os
from celery import Celery
from celery.signals import worker_ready

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('ai_video_engine')
app.config_from_object('django.conf:settings', namespace='CELERY')

# autodiscover_tasks looks for a 'tasks.py' inside each package.
# Our task lives in 'processing.py', so we include the full module path.
app.autodiscover_tasks(['apps.core.tasks'], related_name='processing')


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


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

    Jobs are staggered with a 60-second countdown between each dispatch so
    the worker pool can absorb them at its natural rate rather than
    receiving a burst of N simultaneous tasks on startup.
    """
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
                countdown=i * 60,   # 60-second gap between each re-dispatch
            )
        spread_mins = count  # one per minute
        print(f'[celery] Staggered re-dispatch of {count} stuck SCHEDULED job(s) '
              f'over ~{spread_mins} minute(s)')
    else:
        print('[celery] No stuck jobs found')


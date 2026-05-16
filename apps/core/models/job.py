"""
ProcessingJob model — tracks video processing lifecycle.

Extracted from: punarcourses/models.py (LiveVideoProcessingJob, lines 2562-2728)
"""

from django.db import models
from django.utils import timezone
from apps.core.models.video import Video


class ProcessingJob(models.Model):
    """
    Tracks a single processing attempt for a video.
    Each video can have multiple jobs (retries).
    """

    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('ABORTED', 'Aborted'),
        ('REUSED', 'Reused — Vectorstore Already Existed'),
    ]

    video = models.ForeignKey(
        Video, on_delete=models.CASCADE,
        related_name='processing_jobs',
        help_text='Video being processed'
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='SCHEDULED', db_index=True
    )
    progress = models.IntegerField(
        default=0,
        help_text='Processing progress 0-100'
    )
    current_step = models.CharField(
        max_length=50, blank=True, default='',
        help_text='Current pipeline step'
    )

    # Timing
    scheduled_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Errors
    error_message = models.TextField(blank=True, default='')
    error_traceback = models.TextField(blank=True, default='')

    # Worker
    worker_id = models.CharField(max_length=100, blank=True, default='')
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)

    # Step details
    processing_details = models.JSONField(default=dict, blank=True)
    processing_path = models.CharField(
        max_length=20,
        choices=[
            ('vimeo_transcript', 'Fast Path — Vimeo Captions'),
            ('full_pipeline', 'Full Pipeline — Download + Whisper'),
            ('reused', 'Reused — Vectorstore Already Existed'),
        ],
        blank=True, default='',
        help_text='Which processing route was taken'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['video', '-created_at']),
            models.Index(fields=['status', 'scheduled_at']),
        ]
        verbose_name = 'Processing Job'
        verbose_name_plural = 'Processing Jobs'

    def __str__(self):
        return f"Job {self.id} — {self.video.title} ({self.status})"

    @property
    def duration_seconds(self):
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        elif self.started_at:
            return (timezone.now() - self.started_at).total_seconds()
        return 0

    @property
    def can_retry(self):
        return self.status == 'FAILED' and self.retry_count < self.max_retries

    # ---- state-transition helpers ----

    def mark_started(self, worker_id: str = ''):
        self.status = 'IN_PROGRESS'
        self.started_at = timezone.now()
        self.worker_id = worker_id or str(__import__('os').getpid())
        self.save(update_fields=['status', 'started_at', 'worker_id'])

    def mark_completed(self):
        self.status = 'COMPLETED'
        self.progress = 100
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'progress', 'completed_at'])
        # Propagate to video
        self.video.vectorstore_created = True
        self.video.status = 'ready'
        self.video.save(update_fields=['vectorstore_created', 'status'])
        # Recalculate course stats
        self.video.course.update_statistics()

    def mark_failed(self, error_message: str, error_traceback: str = ''):
        self.status = 'FAILED'
        self.error_message = error_message
        self.error_traceback = error_traceback
        self.completed_at = timezone.now()
        self.save(update_fields=[
            'status', 'error_message', 'error_traceback', 'completed_at'
        ])
        self.video.status = 'failed'
        self.video.save(update_fields=['status'])

    def mark_reused(self, source_info: str):
        """Mark job as reused — vectorstore already existed on disk."""
        self.status = 'REUSED'
        self.progress = 100
        self.completed_at = timezone.now()
        self.processing_path = 'reused'
        self.processing_details = {
            'reuse_reason': 'vectorstore_exists_on_disk',
            'source': source_info,
        }
        self.save(update_fields=[
            'status', 'progress', 'completed_at',
            'processing_path', 'processing_details',
        ])
        # Mark parent video as ready
        self.video.vectorstore_created = True
        self.video.status = 'ready'
        self.video.save(update_fields=['vectorstore_created', 'status'])
        self.video.course.update_statistics()

    def update_progress(self, progress: int, step: str = ''):
        self.progress = min(100, max(0, progress))
        if step:
            self.current_step = step
        self.save(update_fields=['progress', 'current_step'])

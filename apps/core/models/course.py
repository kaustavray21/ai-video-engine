"""
Course model — container for live video recordings.

Extracted from: punarcourses/models.py (LiveCourse, lines 2316-2416)
"""

from django.db import models
from django.db.models import F


class Course(models.Model):
    """
    Represents a course containing multiple video sessions.
    Tracks course-level vectorstore for cross-video QA.
    """

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')

    # Vectorstore (course-level, merged from all video vectorstores)
    vectorstore_path = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Path to course-level FAISS vectorstore (relative to MEDIA_ROOT)'
    )
    vectorstore_created = models.BooleanField(
        default=False, db_index=True,
        help_text='Has the course-level vectorstore been built?'
    )
    vectorstore_updated_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the course vectorstore was last rebuilt'
    )

    # Content versioning — tracks when the course needs a vectorstore rebuild
    content_version = models.PositiveIntegerField(
        default=0,
        help_text='Incremented every time a video is added or removed'
    )
    vectorstore_version = models.PositiveIntegerField(
        default=0,
        help_text='The content_version the vectorstore was last built for'
    )

    # Denormalized stats
    total_videos = models.IntegerField(default=0)
    processed_videos = models.IntegerField(default=0)
    total_duration_seconds = models.IntegerField(default=0)

    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', '-created_at']),
        ]
        verbose_name = 'Course'
        verbose_name_plural = 'Courses'

    def __str__(self):
        return self.title

    def bump_content_version(self):
        """Atomically increment content_version — call on video add/delete."""
        Course.objects.filter(pk=self.pk).update(content_version=F('content_version') + 1)
        self.refresh_from_db(fields=['content_version'])

    @property
    def vectorstore_is_stale(self):
        """True if the vectorstore needs rebuilding."""
        return self.content_version != self.vectorstore_version

    def update_statistics(self):
        """Recalculate denormalized statistics from related videos."""
        videos = self.videos.filter(is_active=True)
        self.total_videos = videos.count()
        self.processed_videos = videos.filter(
            vectorstore_created=True
        ).count()
        self.total_duration_seconds = sum(
            v.duration_seconds for v in videos if v.duration_seconds
        )
        self.save(update_fields=[
            'total_videos', 'processed_videos', 'total_duration_seconds'
        ])

    @property
    def processing_progress(self):
        """Processing progress as a percentage."""
        if self.total_videos == 0:
            return 0
        return round((self.processed_videos / self.total_videos) * 100, 1)


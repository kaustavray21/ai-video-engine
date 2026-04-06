"""
Video model — individual video recording within a course.

Extracted from: punarcourses/models.py (LiveVideo, lines 2418-2560)
"""

import re
from urllib.parse import urlparse, urlunparse
from django.db import models
from apps.core.models.course import Course


class Video(models.Model):
    """
    Represents a single video in a course.
    Tracks Vimeo source, local file paths, and vectorstore status.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('downloading', 'Downloading'),
        ('transcribing', 'Transcribing'),
        ('embedding', 'Creating Embeddings'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
    ]

    # Course relationship
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='videos',
        help_text='Parent course'
    )

    # Vimeo source
    video_url = models.URLField(max_length=500, help_text='Full Vimeo URL')
    vimeo_video_id = models.CharField(
        max_length=50, db_index=True,
        help_text='Extracted Vimeo video ID'
    )

    # Metadata
    title = models.CharField(max_length=255, default='')
    description = models.TextField(blank=True, default='')
    duration_seconds = models.IntegerField(default=0)

    # File paths (relative to MEDIA_ROOT)
    local_path = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Path to downloaded video file'
    )
    audio_path = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Path to extracted audio file'
    )
    transcript_path = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Path to transcript text file'
    )

    # Vectorstore
    vectorstore_path = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Path to FAISS vectorstore directory'
    )
    vectorstore_created = models.BooleanField(
        default=False, db_index=True,
        help_text='Has vectorstore been created?'
    )

    # Processing
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='pending', db_index=True
    )
    processing_attempts = models.IntegerField(default=0)

    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['course', 'created_at']
        unique_together = ['course', 'vimeo_video_id']
        indexes = [
            models.Index(fields=['course', 'is_active']),
            models.Index(fields=['vimeo_video_id']),
            models.Index(fields=['vectorstore_created']),
        ]
        verbose_name = 'Video'
        verbose_name_plural = 'Videos'

    def __str__(self):
        return f"{self.title} (Course: {self.course.title})"

    @property
    def duration_formatted(self):
        if not self.duration_seconds:
            return '00:00'
        hours = self.duration_seconds // 3600
        minutes = (self.duration_seconds % 3600) // 60
        seconds = self.duration_seconds % 60
        if hours > 0:
            return f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        return f'{minutes:02d}:{seconds:02d}'

    @staticmethod
    def clean_vimeo_url(url: str) -> str:
        """
        Strip query parameters and fragments from a Vimeo URL.

        Example:
            "https://player.vimeo.com/video/830110440?share=copy"
            → "https://player.vimeo.com/video/830110440"
        """
        parsed = urlparse(url.strip())
        # Rebuild without query string or fragment
        cleaned = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            '', '', '',  # params, query, fragment all cleared
        ))
        return cleaned

    @staticmethod
    def extract_vimeo_id(url: str) -> str:
        """Extract Vimeo video ID from common URL formats (handles query params)."""
        # Strip query params first
        clean = Video.clean_vimeo_url(url)
        patterns = [
            r'vimeo\.com/(\d+)',
            r'player\.vimeo\.com/video/(\d+)',
            r'/videos/(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, clean)
            if match:
                return match.group(1)
        return ''


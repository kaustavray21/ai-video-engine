from django.db import models


class StudyMaterial(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, default='')
    file_path = models.CharField(max_length=500, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    files_count = models.IntegerField(default=0)
    processed_files = models.IntegerField(default=0)  # per-file VSs built so far
    vectorstore_location = models.CharField(max_length=500, blank=True, default='',
        help_text='Relative path to merged SM vectorstore under study_materials_vectorstore/complete_vectorstores/')
    error_log = models.TextField(blank=True, default='')  # last pipeline error
    created_at = models.DateTimeField(auto_now_add=True)
    attached_to_courses = models.ManyToManyField(
        'Course', blank=True,
        help_text='Courses that have a merged vectorstore for this study material',
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Study Material'
        verbose_name_plural = 'Study Materials'

    def __str__(self):
        return self.name

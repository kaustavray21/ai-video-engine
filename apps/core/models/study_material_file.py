from django.db import models


class StudyMaterialFile(models.Model):
    """
    Tracks every individual file discovered inside an uploaded study material zip.
    Created in bulk during Phase 1 (Discovery) of the pipeline.
    Updated per-file during Phase 2 (Processing).
    """

    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    study_material = models.ForeignKey(
        'StudyMaterial',
        on_delete=models.CASCADE,
        related_name='files',
    )
    original_name = models.CharField(
        max_length=500,
        help_text='Filename as extracted, e.g. "notes.pdf"',
    )
    relative_path = models.CharField(
        max_length=1000,
        help_text='Path within the zip, e.g. "lectures/week1/notes.pdf"',
    )
    file_type = models.CharField(
        max_length=20, blank=True, default='',
        help_text='File extension, e.g. ".pdf"',
    )
    file_size = models.BigIntegerField(
        default=0,
        help_text='File size in bytes',
    )
    # Set after Phase 2 conversion
    text_path = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Relative path to converted .txt file under study_materials/{name}/text/',
    )
    # Set after Phase 2 embedding
    vectorstore_path = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Relative path to per-file vectorstore under study_materials_vectorstore/individual_vectorstores/',
    )
    chunk_count = models.IntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING,
    )
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Study Material File'
        verbose_name_plural = 'Study Material Files'
        indexes = [
            models.Index(fields=['study_material', 'status']),
        ]

    def __str__(self):
        return f'{self.study_material.name} / {self.original_name}'

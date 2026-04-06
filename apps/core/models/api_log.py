"""ApiCallLog model — tracks every API call made through the dashboard."""

from django.db import models


class ApiCallLog(models.Model):
    """Persists every API request made from the dashboard UI."""

    METHOD_CHOICES = [
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('PATCH', 'PATCH'),
        ('DELETE', 'DELETE'),
    ]

    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default='POST')
    endpoint = models.CharField(max_length=512)
    request_body = models.TextField(blank=True, default='')
    response_body = models.TextField(blank=True, default='')
    status_code = models.IntegerField(default=0)
    status_text = models.CharField(max_length=100, blank=True, default='')
    latency_ms = models.IntegerField(default=0)
    saved = models.BooleanField(
        default=False,
        help_text='True when explicitly saved to history by user',
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at', 'saved']),
        ]

    def __str__(self):
        return f'{self.method} {self.endpoint} [{self.status_code}]'

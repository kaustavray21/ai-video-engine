"""Admin registration for core models."""

from django.contrib import admin
from apps.core.models import Course, Video, ProcessingJob, ApiCallLog


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'total_videos', 'processed_videos',
                    'vectorstore_created', 'is_active', 'created_at']
    list_filter = ['is_active', 'vectorstore_created']
    search_fields = ['title']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'course', 'status',
                    'vectorstore_created', 'duration_seconds', 'created_at']
    list_filter = ['status', 'vectorstore_created', 'is_active']
    search_fields = ['title', 'vimeo_video_id']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'video', 'status', 'progress',
                    'current_step', 'scheduled_at', 'completed_at']
    list_filter = ['status']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ApiCallLog)
class ApiCallLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'method', 'endpoint', 'status_code',
                    'latency_ms', 'saved', 'created_at']
    list_filter = ['method', 'saved', 'status_code']
    search_fields = ['endpoint']
    readonly_fields = ['created_at']

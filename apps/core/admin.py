"""Admin registration for core models."""

from django.contrib import admin
from apps.core.models import Course, Video, ProcessingJob, ApiCallLog, StudyMaterial, StudyMaterialFile


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


@admin.register(StudyMaterial)
class StudyMaterialAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'status', 'files_count', 'processed_files', 'created_at']
    list_filter = ['status']
    search_fields = ['name']
    readonly_fields = ['created_at']


class StudyMaterialFileInline(admin.TabularInline):
    model = StudyMaterialFile
    extra = 0
    readonly_fields = [
        'original_name', 'relative_path', 'file_type', 'file_size',
        'text_path', 'vectorstore_path', 'chunk_count',
        'status', 'error', 'created_at', 'processed_at',
    ]


@admin.register(StudyMaterialFile)
class StudyMaterialFileAdmin(admin.ModelAdmin):
    list_display = ['id', 'study_material', 'original_name', 'file_type', 'status', 'chunk_count', 'processed_at']
    list_filter = ['status', 'file_type']
    search_fields = ['original_name']
    readonly_fields = ['created_at', 'processed_at']

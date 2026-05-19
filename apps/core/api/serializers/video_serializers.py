"""Serializers for Video model."""

from rest_framework import serializers
from apps.core.models import Video


class VideoCreateSerializer(serializers.Serializer):
    course_id = serializers.IntegerField()
    video_url = serializers.URLField()


class BulkVideoCreateSerializer(serializers.Serializer):
    course_id = serializers.IntegerField()
    video_urls = serializers.ListField(
        child=serializers.URLField(),
        min_length=1,
        max_length=50,
    )


class VideoSerializer(serializers.ModelSerializer):
    duration_formatted = serializers.ReadOnlyField()
    course_title = serializers.CharField(source='course.title', read_only=True)

    class Meta:
        model = Video
        fields = [
            'id', 'course', 'course_title',
            'video_url', 'vimeo_video_id',
            'title', 'description', 'duration_seconds', 'duration_formatted',
            'local_path', 'audio_path', 'transcript_path',
            'vectorstore_path', 'vectorstore_created',
            'status', 'processing_attempts',
            'is_active', 'metadata',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


class VideoQuerySerializer(serializers.Serializer):
    video_id = serializers.IntegerField()
    question = serializers.CharField(max_length=2000)


class CourseQuerySerializer(serializers.Serializer):
    course_id = serializers.IntegerField()
    question = serializers.CharField(max_length=2000)
    include_study_materials = serializers.BooleanField(default=True, required=False)

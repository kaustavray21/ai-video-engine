"""Serializers for Course model."""

from rest_framework import serializers
from apps.core.models import Course


class CourseCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, default='')


class CourseSerializer(serializers.ModelSerializer):
    processing_progress = serializers.ReadOnlyField()

    class Meta:
        model = Course
        fields = [
            'id', 'title', 'description',
            'vectorstore_created', 'vectorstore_updated_at',
            'total_videos', 'processed_videos', 'total_duration_seconds',
            'processing_progress', 'is_active', 'metadata',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

from rest_framework import serializers
from apps.core.models.study_material import StudyMaterial
from apps.core.models.study_material_file import StudyMaterialFile


class StudyMaterialUploadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    zip_file = serializers.FileField(write_only=True)


class StudyMaterialQuerySerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000)


class StudyMaterialFileSerializer(serializers.ModelSerializer):
    """Read serializer for individual file records inside a study material."""

    class Meta:
        model = StudyMaterialFile
        fields = [
            'id', 'original_name', 'relative_path', 'file_type', 'file_size',
            'text_path', 'vectorstore_path', 'chunk_count',
            'status', 'error', 'created_at', 'processed_at',
        ]
        read_only_fields = fields


class StudyMaterialSerializer(serializers.ModelSerializer):
    attached_courses_count = serializers.SerializerMethodField()
    file_summary = serializers.SerializerMethodField()

    class Meta:
        model = StudyMaterial
        fields = [
            'id', 'name', 'description', 'file_path', 'status',
            'files_count', 'processed_files', 'vectorstore_location',
            'error_log', 'created_at',
            'attached_courses_count', 'file_summary',
        ]
        read_only_fields = fields

    @staticmethod
    def get_attached_courses_count(obj):
        return obj.attached_to_courses.count()

    @staticmethod
    def get_file_summary(obj):
        """Aggregate counts of StudyMaterialFile statuses."""
        qs = obj.files.all()
        if not qs.exists():
            return None
        return {
            'completed': qs.filter(status=StudyMaterialFile.STATUS_COMPLETED).count(),
            'pending': qs.filter(status=StudyMaterialFile.STATUS_PENDING).count(),
            'processing': qs.filter(status=StudyMaterialFile.STATUS_PROCESSING).count(),
            'failed': qs.filter(status=StudyMaterialFile.STATUS_FAILED).count(),
            'skipped': qs.filter(status=StudyMaterialFile.STATUS_SKIPPED).count(),
        }

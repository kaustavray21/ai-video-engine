import os
import logging

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.core.models import Course
from apps.core.models.study_material import StudyMaterial
from apps.core.models.study_material_file import StudyMaterialFile
from apps.core.api.serializers.study_material_serializers import (
    StudyMaterialUploadSerializer,
    StudyMaterialQuerySerializer,
    StudyMaterialSerializer,
    StudyMaterialFileSerializer,
)

logger = logging.getLogger(__name__)


class StudyMaterialUploadAPI(APIView):
    """
    POST /api/study-materials/upload/

    Save uploaded zip, dispatch Celery task for processing.
    """

    def post(self, request):
        serializer = StudyMaterialUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        name = serializer.validated_data['name']
        description = serializer.validated_data.get('description', '')
        zip_file = serializer.validated_data['zip_file']

        if StudyMaterial.objects.filter(name=name).exists():
            return Response(
                {'error': f'Study material with name "{name}" already exists'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Save zip to study_materials/{name}/
        rel_dir = os.path.join('study_materials', name)
        abs_dir = os.path.join(str(settings.MEDIA_ROOT), rel_dir)
        os.makedirs(abs_dir, exist_ok=True)

        zip_rel_path = os.path.join(rel_dir, zip_file.name)
        zip_abs_path = os.path.join(str(settings.MEDIA_ROOT), zip_rel_path)

        with open(zip_abs_path, 'wb+') as dest:
            for chunk in zip_file.chunks():
                dest.write(chunk)

        sm = StudyMaterial.objects.create(
            name=name,
            description=description,
            file_path=zip_abs_path,
            status=StudyMaterial.STATUS_PENDING,
        )

        # Dispatch Celery task
        from apps.core.tasks.study_material_tasks import process_study_material
        process_study_material.delay(sm.id)

        return Response(
            {'id': sm.id, 'name': sm.name, 'status': sm.status},
            status=status.HTTP_201_CREATED,
        )


class StudyMaterialStatusAPI(APIView):
    """
    GET /api/study-materials/<id>/status/
    """

    def get(self, request, pk):
        try:
            sm = StudyMaterial.objects.get(pk=pk)
        except StudyMaterial.DoesNotExist:
            return Response(
                {'error': f'StudyMaterial {pk} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = StudyMaterialSerializer(sm)
        data = serializer.data

        # Attach per-file processing status
        files = StudyMaterialFile.objects.filter(study_material=sm).order_by('id')
        data['files'] = [
            {
                'file_id': f.id,
                'original_name': f.original_name,
                'file_type': f.file_type,
                'status': f.status,
                'chunk_count': f.chunk_count,
                'error': f.error if f.status == 'failed' else '',
            }
            for f in files
        ]

        return Response(data)


class StudyMaterialListAPI(APIView):
    """
    GET /api/study-materials/
    """

    def get(self, request):
        qs = StudyMaterial.objects.all()
        serializer = StudyMaterialSerializer(qs, many=True)
        return Response(serializer.data)


class StudyMaterialMergeAPI(APIView):
    """
    POST /api/study-materials/<id>/merge-to-course/<course_id>/
    """

    def post(self, request, pk, course_id):
        try:
            sm = StudyMaterial.objects.get(pk=pk)
        except StudyMaterial.DoesNotExist:
            return Response(
                {'error': f'StudyMaterial {pk} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            course = Course.objects.get(pk=course_id, is_active=True)
        except Course.DoesNotExist:
            return Response(
                {'error': f'Course {course_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sm.status != StudyMaterial.STATUS_COMPLETED:
            return Response(
                {'error': f'StudyMaterial status is "{sm.status}", must be "completed"'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.core.services.study_material_merger import StudyMaterialMerger

        merger = StudyMaterialMerger()
        replaced = None

        # Check current state
        if course.study_material:
            existing_sm_id = course.study_material.get('id')
            if existing_sm_id == sm.id:
                return Response({'message': 'Already merged'}, status=status.HTTP_200_OK)

            # Different SM — replace
            replaced = course.study_material
            old_history_entry = dict(course.study_material)
            result = merger.replace(course, sm)
        else:
            result = merger.build(course, sm)

        if not result.success:
            return Response(
                {'error': result.error},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Update course model
        sm_data = {'id': sm.id, 'name': sm.name, 'description': sm.description}
        if replaced:
            history = list(course.study_materials_history or [])
            history.append(replaced)
            course.study_materials_history = history

        course.study_material = sm_data
        course.merged_vectorstore_path = result.merged_relative
        course.save(update_fields=[
            'study_material', 'merged_vectorstore_path', 'study_materials_history',
        ])

        sm.attached_to_courses.add(course)

        return Response({
            'study_material': {'id': sm.id, 'name': sm.name},
            'replaced': replaced,
            'merged_vectorstore_path': result.merged_relative,
        })


class StudyMaterialQueryAPI(APIView):
    """
    POST /api/study-materials/<id>/query/
    """

    def post(self, request, pk):
        serializer = StudyMaterialQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        question = serializer.validated_data['question']

        try:
            sm = StudyMaterial.objects.get(pk=pk)
        except StudyMaterial.DoesNotExist:
            return Response(
                {'error': f'StudyMaterial {pk} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sm.status != StudyMaterial.STATUS_COMPLETED:
            return Response(
                {'error': f'StudyMaterial status is "{sm.status}", must be "completed"'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vs_path = os.path.join(
            str(settings.MEDIA_ROOT), sm.vectorstore_location,
        )

        from apps.core.services.vectorstore import VectorStoreManager, OVERVIEW_PATTERNS

        # Build file manifest from DB for manifest injection on overview queries
        is_overview = any(p in question.lower() for p in OVERVIEW_PATTERNS)
        file_manifest = None
        if is_overview:
            sm_files = StudyMaterialFile.objects.filter(study_material=sm).order_by('id')
            file_manifest = [
                {
                    'name': f.original_name,
                    'file_type': f.file_type,
                    'status': f.status,
                }
                for f in sm_files
            ]

        manager = VectorStoreManager(openai_api_key=settings.OPENAI_API_KEY)
        result = manager.query(
            vectorstore_path=vs_path,
            question=question,
            course_title=sm.name,
            video_title='Study Material',
            filter_source_file=request.data.get('filter_source_file'),
            filter_file_type=request.data.get('filter_file_type'),
            file_manifest=file_manifest,
        )

        if not result.success:
            return Response(
                {'error': result.error},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'status': 'success',
            'answer': result.answer,
            'study_material_id': sm.id,
            'study_material_name': sm.name,
            'question': question,
            'source_chunks': result.source_chunks,
            'retrieved_sources': result.retrieved_sources,
            'retrieved_chunk_count': result.retrieved_chunk_count,
        })


class StudyMaterialFilesAPI(APIView):
    """
    GET /api/study-materials/<id>/files/

    List all StudyMaterialFile records for a study material.
    """

    def get(self, request, pk):
        try:
            sm = StudyMaterial.objects.get(pk=pk)
        except StudyMaterial.DoesNotExist:
            return Response(
                {'error': f'StudyMaterial {pk} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        files = sm.files.all().order_by('created_at')
        serializer = StudyMaterialFileSerializer(files, many=True)
        return Response({
            'study_material_id': sm.id,
            'study_material_name': sm.name,
            'total_files': files.count(),
            'files': serializer.data,
        })


class StudyMaterialRetryAPI(APIView):
    """
    POST /api/study-materials/<id>/retry/

    Re-queue a failed study material.
    Phase 2 will skip already-completed files — only pending/failed ones are retried.
    """

    def post(self, request, pk):
        try:
            sm = StudyMaterial.objects.get(pk=pk)
        except StudyMaterial.DoesNotExist:
            return Response(
                {'error': f'StudyMaterial {pk} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sm.status != StudyMaterial.STATUS_FAILED:
            return Response(
                {'error': f'StudyMaterial status is "{sm.status}", can only retry "failed"'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.core.tasks.study_material_tasks import retry_study_material
        retry_study_material.delay(sm.id)

        return Response({
            'id': sm.id,
            'name': sm.name,
            'status': 'queued_for_retry',
            'processed_files': sm.processed_files,
            'files_count': sm.files_count,
        })


class StudyMaterialFileQueryAPI(APIView):
    """
    POST /api/study-materials/files/<file_id>/query/

    Query an individual file's vectorstore by its StudyMaterialFile PK.
    """

    def post(self, request, file_id):
        serializer = StudyMaterialQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        question = serializer.validated_data['question']

        try:
            smf = StudyMaterialFile.objects.select_related('study_material').get(pk=file_id)
        except StudyMaterialFile.DoesNotExist:
            return Response(
                {'error': f'StudyMaterialFile {file_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if smf.status != StudyMaterialFile.STATUS_COMPLETED:
            return Response(
                {'error': f'File status is "{smf.status}", must be "completed"'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not smf.vectorstore_path:
            return Response(
                {'error': 'File has no vectorstore (may have been skipped)'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vs_path = os.path.join(str(settings.MEDIA_ROOT), smf.vectorstore_path)

        from apps.core.services.vectorstore import VectorStoreManager

        manager = VectorStoreManager(openai_api_key=settings.OPENAI_API_KEY)
        result = manager.query(
            vectorstore_path=vs_path,
            question=question,
            course_title=smf.study_material.name,
            video_title='Study Material',
        )

        if not result.success:
            return Response(
                {'error': result.error},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'status': 'success',
            'answer': result.answer,
            'file_id': smf.id,
            'file_name': smf.original_name,
            'file_type': smf.file_type,
            'study_material_id': smf.study_material.id,
            'study_material_name': smf.study_material.name,
            'question': question,
            'source_chunks': result.source_chunks,
            'retrieved_sources': result.retrieved_sources,
            'retrieved_chunk_count': result.retrieved_chunk_count,
        })


class StudyMaterialDeleteAPI(APIView):
    """
    DELETE /api/study-materials/<int:pk>/delete/

    Completely deletes a Study Material and all associated resources:
    1. Blocks deletion if it is currently attached to any Course.
    2. Deletes original uploaded zip if present.
    3. Deletes extracted raw & converted text directory.
    4. Deletes all per-file vectorstores.
    5. Deletes merged vectorstore.
    6. Deletes DB records (cascade deletes StudyMaterialFiles).
    """

    def delete(self, request, pk):
        from django.shortcuts import get_object_or_404
        import shutil

        sm = get_object_or_404(StudyMaterial, pk=pk)

        # 1. Check if attached to courses
        if sm.attached_to_courses.exists():
            course_names = list(sm.attached_to_courses.values_list('title', flat=True))
            return Response(
                {
                    'error': 'Cannot delete Study Material because it is currently attached to one or more courses.',
                    'attached_courses': course_names
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        deleted_resources = []
        errors = []

        # 2. Delete original zip
        if sm.file_path and os.path.exists(sm.file_path):
            try:
                os.remove(sm.file_path)
                deleted_resources.append('zip_file')
            except Exception as e:
                errors.append(f'Failed to delete zip: {e}')

        # Helper to construct directory slug securely (same logic as in zip_extractor/processor)
        slug = sm.name.strip().replace(' ', '_').lower()

        # 3. Delete extracted raw & converted text directory
        raw_dir = os.path.join(str(settings.MEDIA_ROOT), 'study_materials', slug)
        if os.path.exists(raw_dir):
            try:
                shutil.rmtree(raw_dir)
                deleted_resources.append('extracted_files')
            except Exception as e:
                errors.append(f'Failed to delete raw directory: {e}')

        # 4. Delete all per-file vectorstores
        for smf in sm.files.all():
            if smf.vectorstore_path:
                vs_abs = os.path.join(str(settings.MEDIA_ROOT), smf.vectorstore_path)
                if os.path.exists(vs_abs):
                    try:
                        shutil.rmtree(vs_abs)
                    except Exception as e:
                        errors.append(f'Failed to delete file vectorstore for {smf.original_name}: {e}')

        # 5. Delete merged vectorstore
        if sm.vectorstore_location:
            merged_vs_abs = os.path.join(str(settings.MEDIA_ROOT), sm.vectorstore_location)
            if os.path.exists(merged_vs_abs):
                try:
                    shutil.rmtree(merged_vs_abs)
                    deleted_resources.append('merged_vectorstore')
                except Exception as e:
                    errors.append(f'Failed to delete merged vectorstore: {e}')

        # 6. Delete DB record
        sm.delete()

        return Response({
            'status': 'success',
            'message': f'Study Material "{sm.name}" deleted successfully.',
            'deleted_resources': deleted_resources,
            'cleanup_errors': errors,
        })

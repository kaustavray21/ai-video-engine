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
        return Response(serializer.data)


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
        if not os.path.exists(vs_path):
            return Response(
                {'error': 'Vectorstore not found on disk'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        from apps.core.services.vectorstore import VectorStoreManager

        manager = VectorStoreManager(openai_api_key=settings.OPENAI_API_KEY)
        vs = manager.load(vs_path)
        if vs is None:
            return Response(
                {'error': 'Failed to load vectorstore'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        try:
            docs = vs.similarity_search(question, k=5)
            if not docs:
                return Response(
                    {'error': 'No relevant chunks found'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            context = '\n\n'.join(d.page_content for d in docs)

            from apps.core.services.vectorstore import QA_PROMPT
            prompt = QA_PROMPT.format(
                context=context,
                question=question,
                course_title=sm.name,
                video_title='Study Material',
            )
            response_text = manager.llm.invoke(prompt).content

            sources = []
            for doc in docs:
                meta = doc.metadata
                sources.append({
                    'original_name': meta.get('original_name', ''),
                    'type': meta.get('type', ''),
                    'chunk_index': meta.get('chunk_index', 0),
                })

            return Response({
                'status': 'success',
                'answer': response_text,
                'study_material_id': sm.id,
                'study_material_name': sm.name,
                'question': question,
                'source_chunks': len(docs),
                'sources': sources,
            })

        except Exception as e:
            logger.exception(f'Study material query failed: {e}')
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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

"""
Query API views — video-level and course-level QA.

Extracted from: api/views.py (LiveVideoQuestionAPI)
               api/live_course_views.py (LiveCourseQuestionAPI)
"""

import os
import logging

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.core.models import Course, Video
from apps.core.api.serializers.video_serializers import (
    VideoQuerySerializer, CourseQuerySerializer,
)

logger = logging.getLogger(__name__)


class VideoQueryAPI(APIView):
    """
    POST /api/query/video/
    {
        "video_id": 23,
        "question": "What is pandas?"
    }

    Answer a question using the video's FAISS vectorstore.
    """

    def post(self, request):
        serializer = VideoQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        video_id = serializer.validated_data['video_id']
        question = serializer.validated_data['question']

        try:
            video = Video.objects.select_related('course').get(
                id=video_id, is_active=True,
            )
        except Video.DoesNotExist:
            return Response(
                {'error': f'Video {video_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not video.vectorstore_created or not video.vectorstore_path:
            return Response(
                {'error': 'Video has not been processed yet'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vs_path = os.path.join(str(settings.MEDIA_ROOT), video.vectorstore_path)
        if not os.path.exists(vs_path):
            return Response(
                {'error': 'Vectorstore not found on disk'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        from apps.core.services.vectorstore import VectorStoreManager

        manager = VectorStoreManager(openai_api_key=settings.OPENAI_API_KEY)
        result = manager.query(
            vectorstore_path=vs_path,
            question=question,
            course_title=video.course.title,
            video_title=video.title,
        )

        if not result.success:
            return Response(
                {'error': result.error},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'status': 'success',
            'answer': result.answer,
            'video_id': video.id,
            'video_title': video.title,
            'course_id': video.course.id,
            'course_title': video.course.title,
            'question': question,
            'source_chunks': result.source_chunks,
        })


class CourseQueryAPI(APIView):
    """
    POST /api/query/course/
    {
        "course_id": 1,
        "question": "What topics were covered?",
        "include_study_materials": true
    }

    Answer a question using the course-level FAISS vectorstore.

    include_study_materials=true  → use course.merged_vectorstore_path (course + SM)
    include_study_materials=false → use course.vectorstore_path         (video only)
    """

    def post(self, request):
        serializer = CourseQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        course_id = serializer.validated_data['course_id']
        question = serializer.validated_data['question']
        include_sm = serializer.validated_data.get('include_study_materials', True)

        try:
            course = Course.objects.get(id=course_id, is_active=True)
        except Course.DoesNotExist:
            return Response(
                {'error': f'Course {course_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Determine which vectorstore to query
        if include_sm and course.merged_vectorstore_path:
            vs_rel_path = course.merged_vectorstore_path
            vs_label = 'merged (course + study materials)'
        elif course.vectorstore_path:
            vs_rel_path = course.vectorstore_path
            vs_label = 'course (video only)'
        else:
            return Response(
                {
                    'error': 'No vectorstore available for this course',
                    'message': 'Please wait for videos to be processed.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        vs_path = os.path.join(str(settings.MEDIA_ROOT), vs_rel_path)
        if not os.path.exists(vs_path):
            return Response(
                {'error': f'Vectorstore not found on disk: {vs_rel_path}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        from apps.core.services.vectorstore import VectorStoreManager

        manager = VectorStoreManager(openai_api_key=settings.OPENAI_API_KEY)
        result = manager.query(
            vectorstore_path=vs_path,
            question=question,
            course_title=course.title,
            video_title=f'All videos in {course.title}',
        )

        if not result.success:
            return Response(
                {'error': result.error},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'status': 'success',
            'answer': result.answer,
            'course_id': course.id,
            'course_title': course.title,
            'question': question,
            'source_chunks': result.source_chunks,
            'vectorstore_used': vs_label,
        })

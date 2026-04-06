"""
Course API views — all POST, ID in request body.

Endpoints:
    POST /api/courses/        — Create a new course
    POST /api/courses/list/   — List all courses
    POST /api/courses/detail/ — Course detail  (body: {"id": 5})
"""

import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from apps.core.models import Course
from apps.core.api.serializers.course_serializers import (
    CourseCreateSerializer, CourseSerializer,
)

logger = logging.getLogger(__name__)


class CourseCreateAPI(APIView):
    """POST /api/courses/ — Create a new course."""

    def post(self, request):
        serializer = CourseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        course = Course.objects.create(**serializer.validated_data)
        logger.info(f'Created course: {course.title} (ID: {course.id})')

        return Response(
            {
                'message': 'Course created successfully',
                'course': CourseSerializer(course).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CourseListAPI(APIView):
    """POST /api/courses/list/ — List all active courses."""

    def post(self, request):
        courses = Course.objects.filter(is_active=True)
        serializer = CourseSerializer(courses, many=True)
        return Response({
            'count': courses.count(),
            'courses': serializer.data,
        })


class CourseDetailAPI(APIView):
    """
    POST /api/courses/detail/
    Body: {"id": 5}

    Returns course detail. Supports update via "action": "update" and
    soft-delete via "action": "delete".
    """

    def post(self, request):
        course_id = request.data.get('id')
        if not course_id:
            return Response(
                {'error': 'id is required in request body'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        course = get_object_or_404(Course, id=course_id)
        action = request.data.get('action', 'detail')

        if action == 'update':
            for field in ('title', 'description', 'is_active', 'metadata'):
                if field in request.data:
                    setattr(course, field, request.data[field])
            course.save()
            return Response({
                'message': 'Course updated',
                'course': CourseSerializer(course).data,
            })

        if action == 'delete':
            course.is_active = False
            course.save()
            return Response({'message': 'Course deleted', 'course_id': course_id})

        # Default: return detail
        return Response(CourseSerializer(course).data)


class CourseDeleteAPI(APIView):
    """
    POST /api/courses/delete/
    Body: {"id": 5}

    Hard-deletes a course and all associated videos, jobs, and embeddings.
    """

    def post(self, request):
        course_id = request.data.get('id')
        if not course_id:
            return Response(
                {'error': 'id is required in request body'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        course = get_object_or_404(Course, id=course_id)
        title = course.title
        video_count = course.videos.count()
        course.delete()

        logger.info(f'Deleted course: {title} (ID: {course_id}) with {video_count} videos')

        return Response({
            'message': f'Course "{title}" and {video_count} associated video(s) deleted',
            'course_id': course_id,
        })

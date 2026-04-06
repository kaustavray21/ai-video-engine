"""
Status API views — all POST, ID in request body.

Endpoints:
    POST /api/videos/status/   — Video status (body: {"id": 3})
    POST /api/courses/status/  — Course status (body: {"id": 1})
"""

import os
import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as http_status

from apps.core.models import Course, Video, ProcessingJob

logger = logging.getLogger(__name__)


class VideoStatusAPI(APIView):
    """
    POST /api/videos/status/
    Body: {"id": 3}

    Returns processing status and vectorstore info for a video.
    """

    def post(self, request):
        video_id = request.data.get('id')
        if not video_id:
            return Response(
                {'error': 'id is required in request body'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        video = get_object_or_404(Video, id=video_id)

        latest_job = video.processing_jobs.order_by('-created_at').first()
        all_jobs = video.processing_jobs.order_by('-created_at')

        latest_job_data = None
        if latest_job:
            latest_job_data = {
                'id': latest_job.id,
                'status': latest_job.status,
                'progress': latest_job.progress,
                'current_step': latest_job.current_step,
                'started_at': latest_job.started_at.isoformat() if latest_job.started_at else None,
                'completed_at': latest_job.completed_at.isoformat() if latest_job.completed_at else None,
                'duration_seconds': latest_job.duration_seconds,
                'error_message': latest_job.error_message or None,
                'can_retry': latest_job.can_retry,
            }

        # Check vectorstore on disk
        vs_exists = False
        if video.vectorstore_path:
            vs_abs = os.path.join(str(settings.MEDIA_ROOT), video.vectorstore_path)
            vs_exists = os.path.exists(vs_abs)

        return Response({
            'video_id': video.id,
            'video_title': video.title,
            'status': video.status,
            'vectorstore': {
                'created': video.vectorstore_created,
                'path': video.vectorstore_path or None,
                'exists_on_disk': vs_exists,
            },
            'latest_job': latest_job_data,
            'total_attempts': all_jobs.count(),
        })


class CourseStatusAPI(APIView):
    """
    POST /api/courses/status/
    Body: {"id": 1}

    Returns vectorstore and processing status for a course.
    """

    def post(self, request):
        course_id = request.data.get('id')
        if not course_id:
            return Response(
                {'error': 'id is required in request body'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        course = get_object_or_404(Course, id=course_id)

        videos = course.videos.filter(is_active=True)
        total = videos.count()
        processed = videos.filter(vectorstore_created=True).count()

        # Check course-level vectorstore on disk
        course_vs_exists = False
        if course.vectorstore_path:
            abs_path = os.path.join(str(settings.MEDIA_ROOT), course.vectorstore_path)
            course_vs_exists = os.path.exists(abs_path)

        # Job counts
        all_jobs = ProcessingJob.objects.filter(
            video__course=course, video__is_active=True,
        )
        in_progress = all_jobs.filter(status='IN_PROGRESS').count()
        failed = all_jobs.filter(status='FAILED').count()
        scheduled = all_jobs.filter(status='SCHEDULED').count()

        return Response({
            'course_id': course.id,
            'course_title': course.title,
            'video_vectorstore': {
                'total_videos': total,
                'processed_videos': processed,
                'all_processed': total > 0 and processed == total,
            },
            'course_vectorstore': {
                'exists': course_vs_exists,
                'created': course.vectorstore_created,
                'updated_at': (
                    course.vectorstore_updated_at.isoformat()
                    if course.vectorstore_updated_at else None
                ),
                'path': course.vectorstore_path or None,
            },
            'jobs': {
                'in_progress': in_progress,
                'failed': failed,
                'scheduled': scheduled,
            },
            'processing_progress': course.processing_progress,
        })

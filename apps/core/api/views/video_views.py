"""
Video API views — all POST, ID in request body.

Endpoints:
    POST /api/videos/          — Add video (triggers async pipeline)
    POST /api/courses/videos/  — List videos in a course (body: {"id": 1})
"""

import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from apps.core.models import Course, Video, ProcessingJob
from apps.core.api.serializers.video_serializers import (
    VideoCreateSerializer, BulkVideoCreateSerializer, VideoSerializer,
)

logger = logging.getLogger(__name__)


class CourseVideosAPI(APIView):
    """
    POST /api/courses/videos/
    Body: {"id": 1}

    Lists all videos for a given course.
    """

    def post(self, request):
        course_id = request.data.get('id')
        if not course_id:
            return Response(
                {'error': 'id is required in request body'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        course = get_object_or_404(Course, id=course_id, is_active=True)
        videos = course.videos.filter(is_active=True)
        serializer = VideoSerializer(videos, many=True)
        return Response({
            'course_id': course.id,
            'course_title': course.title,
            'count': videos.count(),
            'videos': serializer.data,
        })


class VideoCreateAPI(APIView):
    """
    POST /api/videos/
    Body: {"course_id": 1, "video_url": "https://vimeo.com/817678028"}

    Creates a Video record, a ProcessingJob, and dispatches the Celery task.
    """

    def post(self, request):
        serializer = VideoCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        course_id = serializer.validated_data['course_id']
        raw_url = serializer.validated_data['video_url']

        # Clean URL: strip query params like ?share=copy
        video_url = Video.clean_vimeo_url(raw_url)

        course = get_object_or_404(Course, id=course_id, is_active=True)

        # Extract Vimeo ID
        vimeo_id = Video.extract_vimeo_id(video_url)
        if not vimeo_id:
            return Response(
                {'error': f'Could not extract Vimeo video ID from URL: {raw_url}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check for duplicates
        if Video.objects.filter(course=course, vimeo_video_id=vimeo_id).exists():
            return Response(
                {'error': f'Video {vimeo_id} already exists in this course'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create video record
        video = Video.objects.create(
            course=course,
            video_url=video_url,
            vimeo_video_id=vimeo_id,
            title=f'Video {vimeo_id}',
        )

        # Create processing job
        job = ProcessingJob.objects.create(video=video, status='SCHEDULED')

        # Update course stats and bump content version
        course.update_statistics()
        course.bump_content_version()

        from apps.core.temporal.client import start_video_workflow
        workflow_id = start_video_workflow(job_id=job.id, video=video)

        logger.info(f'Video {vimeo_id} added to course "{course.title}", Temporal workflow {workflow_id} started')

        return Response(
            {
                'message': 'Video added and processing started',
                'video': VideoSerializer(video).data,
                'job_id': job.id,
            },
            status=status.HTTP_201_CREATED,
        )


class BulkVideoCreateAPI(APIView):
    """
    POST /api/videos/bulk/
    Body: {"course_id": 1, "video_urls": ["https://vimeo.com/...", ...]}

    Creates multiple Video records and dispatches processing tasks for each.
    Skips duplicates and invalid URLs, reporting them in the response.
    """

    def post(self, request):
        serializer = BulkVideoCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        course_id = serializer.validated_data['course_id']
        video_urls = serializer.validated_data['video_urls']

        course = get_object_or_404(Course, id=course_id, is_active=True)

        added = []
        skipped = []

        for raw_url in video_urls:
            video_url = Video.clean_vimeo_url(raw_url)
            vimeo_id = Video.extract_vimeo_id(video_url)

            if not vimeo_id:
                skipped.append({'url': raw_url, 'reason': 'invalid URL'})
                continue

            if Video.objects.filter(course=course, vimeo_video_id=vimeo_id).exists():
                skipped.append({'url': raw_url, 'reason': 'duplicate'})
                continue

            video = Video.objects.create(
                course=course,
                video_url=video_url,
                vimeo_video_id=vimeo_id,
                title=f'Video {vimeo_id}',
            )
            job = ProcessingJob.objects.create(video=video, status='SCHEDULED')

            from apps.core.temporal.client import start_video_workflow
            start_video_workflow(job_id=job.id, video=video)

            added.append({
                'video_id': video.id,
                'vimeo_id': vimeo_id,
                'job_id': job.id,
            })

        course.update_statistics()
        if added:
            course.bump_content_version()

        logger.info(
            f'Bulk add to "{course.title}": {len(added)} added, {len(skipped)} skipped'
        )

        return Response(
            {
                'message': f'{len(added)} video(s) added, {len(skipped)} skipped',
                'added': added,
                'skipped': skipped,
            },
            status=status.HTTP_201_CREATED if added else status.HTTP_200_OK,
        )


class VideoDeleteAPI(APIView):
    """
    POST /api/videos/delete/
    Body: {"course_id": 1, "id": 5}

    Hard-deletes a video.
    """

    def post(self, request):
        course_id = request.data.get('course_id')
        video_id = request.data.get('id')
        
        if not course_id or not video_id:
            return Response(
                {'error': 'course_id and id are required in request body'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        course = get_object_or_404(Course, id=course_id)
        video = get_object_or_404(Video, id=video_id, course=course)
        
        title = video.title
        vectorstore_path = video.vectorstore_path

        # Clean up per-video vectorstore from disk
        if vectorstore_path:
            import os
            from django.conf import settings
            abs_path = os.path.join(str(settings.MEDIA_ROOT), vectorstore_path) \
                if not os.path.isabs(vectorstore_path) else vectorstore_path
            if os.path.exists(abs_path):
                import shutil
                shutil.rmtree(abs_path, ignore_errors=True)
                logger.info(f'Removed vectorstore at {abs_path}')

        video.delete()
        course.update_statistics()
        course.bump_content_version()

        # Rebuild course vectorstore in the background
        from apps.core.temporal.client import start_course_rebuild
        start_course_rebuild(course_id=int(course_id))

        logger.info(f'Deleted video: {title} (ID: {video_id}) from course {course.title}')

        return Response({
            'message': f'Video "{title}" deleted, course vectorstore rebuild queued',
            'video_id': video_id,
            'course_id': course_id,
        })

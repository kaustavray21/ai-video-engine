"""
API URL configuration for AI Video Engine.

All endpoints are POST with ID in request body — no URL parameters.

Endpoints:
    POST   /api/courses/             — Create course
    POST   /api/courses/list/        — List courses
    POST   /api/courses/detail/      — Course detail (body: {"id": 5})
    POST   /api/courses/status/      — Course status (body: {"id": 5})
    POST   /api/courses/videos/      — List videos in course (body: {"id": 5})

    POST   /api/videos/              — Add video (triggers async pipeline)
    POST   /api/videos/status/       — Video status (body: {"id": 3})

    POST   /api/query/video/         — QA against single video
    POST   /api/query/course/        — QA against entire course

    POST   /api/dashboard/log/       — Auto-log an API call
    POST   /api/dashboard/logs/      — List logs
    POST   /api/dashboard/logs/save/ — Save log to history
    POST   /api/dashboard/stats/     — Dashboard stats + chart data
"""

from django.urls import path

from apps.core.api.views.course_views import CourseCreateAPI, CourseListAPI, CourseDetailAPI, CourseDeleteAPI
from apps.core.api.views.video_views import VideoCreateAPI, BulkVideoCreateAPI, CourseVideosAPI, VideoDeleteAPI
from apps.core.api.views.query_views import VideoQueryAPI, CourseQueryAPI
from apps.core.api.views.status_views import VideoStatusAPI, CourseStatusAPI
from apps.core.api.views.dashboard_views import (
    DashboardLogAPI, DashboardLogsAPI, DashboardLogSaveAPI, DashboardStatsAPI,
)

urlpatterns = [
    # ── Course Management ──
    path('courses/', CourseCreateAPI.as_view(), name='course_create'),
    path('courses/list/', CourseListAPI.as_view(), name='course_list'),
    path('courses/detail/', CourseDetailAPI.as_view(), name='course_detail'),
    path('courses/status/', CourseStatusAPI.as_view(), name='course_status'),
    path('courses/videos/', CourseVideosAPI.as_view(), name='course_videos'),
    path('courses/delete/', CourseDeleteAPI.as_view(), name='course_delete'),

    # ── Video Management ──
    path('videos/', VideoCreateAPI.as_view(), name='video_create'),
    path('videos/bulk/', BulkVideoCreateAPI.as_view(), name='video_bulk_create'),
    path('videos/status/', VideoStatusAPI.as_view(), name='video_status'),
    path('videos/delete/', VideoDeleteAPI.as_view(), name='video_delete'),

    # ── Question Answering ──
    path('query/video/', VideoQueryAPI.as_view(), name='query_video'),
    path('query/course/', CourseQueryAPI.as_view(), name='query_course'),

    # ── Dashboard ──
    path('dashboard/log/', DashboardLogAPI.as_view(), name='dashboard_log'),
    path('dashboard/logs/', DashboardLogsAPI.as_view(), name='dashboard_logs'),
    path('dashboard/logs/save/', DashboardLogSaveAPI.as_view(), name='dashboard_log_save'),
    path('dashboard/stats/', DashboardStatsAPI.as_view(), name='dashboard_stats'),
]

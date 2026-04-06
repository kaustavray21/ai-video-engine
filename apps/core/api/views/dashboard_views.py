"""
Dashboard API views — logging, history, and stats.

Endpoints:
    POST /api/dashboard/log/           — Auto-log an API call
    POST /api/dashboard/logs/          — List logs (body: {"date": "2026-03-30", "saved_only": true, "limit": 10})
    POST /api/dashboard/logs/save/     — Mark a log as saved (body: {"id": 5})
    POST /api/dashboard/stats/         — Aggregate stats + chart data
"""

import logging
from datetime import timedelta

from django.utils import timezone
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.core.models import ApiCallLog, Video
from apps.core.api.serializers.dashboard_serializers import (
    ApiCallLogCreateSerializer, ApiCallLogSerializer,
)

logger = logging.getLogger(__name__)


class DashboardLogAPI(APIView):
    """
    POST /api/dashboard/log/
    Auto-log an API call (called by frontend after every request).
    """

    def post(self, request):
        serializer = ApiCallLogCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        log_entry = ApiCallLog.objects.create(**serializer.validated_data)

        # Prune logs older than 7 days that were never explicitly saved.
        # Prevents the table growing unboundedly as the dashboard polls every 30s
        # during video processing sessions.
        cutoff = timezone.now() - timedelta(days=7)
        ApiCallLog.objects.filter(created_at__lt=cutoff, saved=False).delete()

        return Response(
            {'id': log_entry.id, 'message': 'Logged'},
            status=status.HTTP_201_CREATED,
        )


class DashboardLogsAPI(APIView):
    """
    POST /api/dashboard/logs/
    Body: {"date": "2026-03-30", "saved_only": true, "limit": 20}
    """

    def post(self, request):
        qs = ApiCallLog.objects.all()

        # Filter by date
        date_str = request.data.get('date')
        if date_str:
            qs = qs.filter(created_at__date=date_str)

        # Filter saved only
        if request.data.get('saved_only'):
            qs = qs.filter(saved=True)

        # Limit — single query: fetch the slice, derive count from len()
        limit = int(request.data.get('limit', 50))
        logs = list(qs[:limit])

        serializer = ApiCallLogSerializer(logs, many=True)
        return Response({
            'count': len(logs),
            'logs': serializer.data,
        })



class DashboardLogSaveAPI(APIView):
    """
    POST /api/dashboard/logs/save/
    Body: {"id": 5}
    Marks a log entry as explicitly saved (appears in History).
    """

    def post(self, request):
        log_id = request.data.get('id')
        if not log_id:
            return Response(
                {'error': 'id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        log_entry = get_object_or_404(ApiCallLog, id=log_id)
        log_entry.saved = True
        log_entry.save(update_fields=['saved'])
        return Response({'message': 'Saved', 'id': log_entry.id})


class DashboardStatsAPI(APIView):
    """
    POST /api/dashboard/stats/
    Returns aggregate stats + daily chart data for last 14 days.
    """

    def post(self, request):
        total_api_calls = ApiCallLog.objects.count()
        total_videos = Video.objects.filter(is_active=True).count()
        processed_videos = Video.objects.filter(
            is_active=True, vectorstore_created=True,
        ).count()

        # Daily chart data (last 14 days)
        cutoff = timezone.now() - timedelta(days=14)
        daily = (
            ApiCallLog.objects
            .filter(created_at__gte=cutoff)
            .annotate(date=TruncDate('created_at'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )

        chart_data = [
            {'date': item['date'].isoformat(), 'count': item['count']}
            for item in daily
        ]

        return Response({
            'total_api_calls': total_api_calls,
            'total_videos': total_videos,
            'processed_videos': processed_videos,
            'chart_data': chart_data,
        })

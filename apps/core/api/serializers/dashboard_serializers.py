"""Serializers for dashboard API call logging."""

from rest_framework import serializers
from apps.core.models import ApiCallLog


class ApiCallLogCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiCallLog
        fields = ['method', 'endpoint', 'request_body', 'response_body',
                  'status_code', 'status_text', 'latency_ms']


class ApiCallLogSerializer(serializers.ModelSerializer):
    request_body = serializers.SerializerMethodField()
    response_body = serializers.SerializerMethodField()

    class Meta:
        model = ApiCallLog
        fields = ['id', 'method', 'endpoint', 'request_body', 'response_body',
                  'status_code', 'status_text', 'latency_ms', 'saved', 'created_at']

    def get_request_body(self, obj):
        if not obj.request_body:
            return ""
        return obj.request_body if len(obj.request_body) <= 2000 else obj.request_body[:2000] + "\n\n... [truncated]"

    def get_response_body(self, obj):
        if not obj.response_body:
            return ""
        return obj.response_body if len(obj.response_body) <= 2000 else obj.response_body[:2000] + "\n\n... [truncated]"

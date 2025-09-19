"""Serializers for async task monitoring and management."""

from rest_framework import serializers

from ..models import TaskExecution, WebhookLog


class TaskExecutionSerializer(serializers.ModelSerializer):
    """Serializer for TaskExecution model."""

    is_active = serializers.ReadOnlyField()
    is_completed = serializers.ReadOnlyField()
    duration_minutes = serializers.SerializerMethodField()

    class Meta:
        model = TaskExecution
        fields = [
            "public_id",
            "task_id",
            "task_name",
            "status",
            "queue_name",
            "worker_name",
            "retry_count",
            "duration_seconds",
            "duration_minutes",
            "started_at",
            "completed_at",
            "created_at",
            "progress",
            "is_active",
            "is_completed",
            "result",
        ]
        read_only_fields = fields

    def get_duration_minutes(self, obj):
        """Get duration in minutes for easier reading."""
        if obj.duration_seconds:
            return round(obj.duration_seconds / 60, 2)
        return None


class TaskExecutionDetailSerializer(TaskExecutionSerializer):
    """Detailed serializer for TaskExecution model."""

    class Meta(TaskExecutionSerializer.Meta):
        fields = TaskExecutionSerializer.Meta.fields + ["args", "kwargs", "metadata"]


class TaskStatusSerializer(serializers.Serializer):
    """Serializer for task status information."""

    task_id = serializers.CharField()
    task_name = serializers.CharField()
    status = serializers.CharField()
    progress = serializers.DictField(required=False)
    result = serializers.DictField(required=False)
    error = serializers.CharField(required=False)
    started_at = serializers.DateTimeField(required=False)
    completed_at = serializers.DateTimeField(required=False)
    duration_seconds = serializers.FloatField(required=False)
    retry_count = serializers.IntegerField(default=0)


class SystemHealthSerializer(serializers.Serializer):
    """Serializer for system health metrics."""

    status = serializers.CharField()
    total_active_tasks = serializers.IntegerField()
    total_executions = serializers.IntegerField()
    overall_success_rate = serializers.FloatField()
    recent_success_rate = serializers.FloatField()
    recent_executions = serializers.IntegerField()
    average_execution_time = serializers.FloatField()
    timestamp = serializers.DateTimeField()
    critical_issues = serializers.ListField(child=serializers.CharField(), required=False)


class QueueMetricsSerializer(serializers.Serializer):
    """Serializer for queue performance metrics."""

    name = serializers.CharField()
    active_tasks = serializers.IntegerField()
    total_tasks_24h = serializers.IntegerField()
    success_rate_24h = serializers.FloatField()
    avg_duration_24h = serializers.FloatField()


class TaskMetricsSerializer(serializers.Serializer):
    """Serializer for task performance metrics."""

    task_name = serializers.CharField()
    total_executions = serializers.IntegerField()
    successful_executions = serializers.IntegerField()
    failed_executions = serializers.IntegerField()
    success_rate = serializers.FloatField()
    average_duration = serializers.FloatField()
    min_duration = serializers.FloatField()
    max_duration = serializers.FloatField()
    active_tasks = serializers.IntegerField()
    last_execution = serializers.FloatField()


class SlowTaskSerializer(serializers.Serializer):
    """Serializer for slow-running tasks."""

    task_id = serializers.CharField()
    task_name = serializers.CharField()
    queue_name = serializers.CharField()
    duration = serializers.FloatField()


class FailureAnalysisSerializer(serializers.Serializer):
    """Serializer for failure analysis data."""

    total_failures = serializers.IntegerField()
    failure_by_task = serializers.DictField()
    failure_by_queue = serializers.DictField()
    failure_rate = serializers.FloatField()
    period_hours = serializers.IntegerField()


class WebhookLogSerializer(serializers.ModelSerializer):
    """Serializer for WebhookLog model."""

    can_retry = serializers.SerializerMethodField()
    next_retry_in_seconds = serializers.SerializerMethodField()

    class Meta:
        model = WebhookLog
        fields = [
            "public_id",
            "webhook_type",
            "url",
            "status",
            "http_status_code",
            "retry_count",
            "next_retry_at",
            "delivered_at",
            "abandoned_at",
            "error_message",
            "created_at",
            "can_retry",
            "next_retry_in_seconds",
        ]
        read_only_fields = fields

    def get_can_retry(self, obj):
        """Check if webhook can be retried."""
        return obj.status in [WebhookLog.Status.FAILED, WebhookLog.Status.RETRYING] and obj.retry_count < 3

    def get_next_retry_in_seconds(self, obj):
        """Get seconds until next retry."""
        if obj.next_retry_at:
            from django.utils import timezone

            now = timezone.now()
            if obj.next_retry_at > now:
                return int((obj.next_retry_at - now).total_seconds())
        return None


class ReportGenerationRequestSerializer(serializers.Serializer):
    """Serializer for report generation requests."""

    report_type = serializers.ChoiceField(
        choices=["daily", "weekly", "monthly"], help_text="Type of report to generate"
    )
    date_str = serializers.CharField(required=False, help_text="Date string for daily reports (YYYY-MM-DD)")
    week_start_str = serializers.CharField(required=False, help_text="Week start date for weekly reports (YYYY-MM-DD)")
    year = serializers.IntegerField(required=False, help_text="Year for monthly reports")
    month = serializers.IntegerField(
        required=False, min_value=1, max_value=12, help_text="Month for monthly reports (1-12)"
    )
    email_recipients = serializers.ListField(
        child=serializers.EmailField(), required=False, help_text="Email addresses to send the report to"
    )

    def validate(self, data):
        """Validate report generation request."""
        report_type = data.get("report_type")

        if report_type == "monthly":
            year = data.get("year")
            month = data.get("month")
            if year and not month:
                raise serializers.ValidationError("Month is required when year is specified for monthly reports")
            if month and not year:
                raise serializers.ValidationError("Year is required when month is specified for monthly reports")

        return data


class DataExportRequestSerializer(serializers.Serializer):
    """Serializer for data export requests."""

    format = serializers.ChoiceField(choices=["csv", "excel", "json"], default="csv", help_text="Export format")
    start_date = serializers.DateTimeField(required=False, help_text="Start date for data filter")
    end_date = serializers.DateTimeField(required=False, help_text="End date for data filter")
    queue_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, help_text="Queue IDs to filter by"
    )
    agent_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, help_text="Agent IDs to filter by"
    )
    status = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Call statuses to filter by"
    )

    def validate(self, data):
        """Validate export request."""
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        if start_date and end_date and start_date >= end_date:
            raise serializers.ValidationError("End date must be after start date")

        return data


class TaskRetryRequestSerializer(serializers.Serializer):
    """Serializer for task retry requests."""

    task_ids = serializers.ListField(child=serializers.CharField(), help_text="List of task IDs to retry")
    force = serializers.BooleanField(default=False, help_text="Force retry even if task is not in failed state")


class BulkTaskActionSerializer(serializers.Serializer):
    """Serializer for bulk task actions."""

    action = serializers.ChoiceField(choices=["retry", "cancel", "delete"], help_text="Action to perform on tasks")
    task_ids = serializers.ListField(child=serializers.CharField(), help_text="List of task IDs to act on")
    filters = serializers.DictField(required=False, help_text="Filters to select tasks (alternative to task_ids)")

    def validate(self, data):
        """Validate bulk action request."""
        task_ids = data.get("task_ids")
        filters = data.get("filters")

        if not task_ids and not filters:
            raise serializers.ValidationError("Either task_ids or filters must be provided")

        if task_ids and filters:
            raise serializers.ValidationError("Cannot specify both task_ids and filters")

        return data


class TaskTrendSerializer(serializers.Serializer):
    """Serializer for task performance trends."""

    task_name = serializers.CharField()
    period_days = serializers.IntegerField()
    daily_stats = serializers.ListField(child=serializers.DictField())


class DailyTaskStatsSerializer(serializers.Serializer):
    """Serializer for daily task statistics."""

    date = serializers.CharField()
    total_executions = serializers.IntegerField()
    successful_executions = serializers.IntegerField()
    success_rate = serializers.FloatField()
    avg_duration = serializers.FloatField()
    max_duration = serializers.FloatField()

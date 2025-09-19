"""API views for async task monitoring and management."""

import logging

from celery import current_app
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from ..models import TaskExecution, WebhookLog
from ..monitoring import get_system_status, task_monitor
from ..serializers.task_serializers import (
    BulkTaskActionSerializer,
    DataExportRequestSerializer,
    FailureAnalysisSerializer,
    QueueMetricsSerializer,
    ReportGenerationRequestSerializer,
    SlowTaskSerializer,
    SystemHealthSerializer,
    TaskExecutionDetailSerializer,
    TaskExecutionSerializer,
    TaskMetricsSerializer,
    TaskStatusSerializer,
    TaskTrendSerializer,
    WebhookLogSerializer,
)

logger = logging.getLogger(__name__)


class TaskExecutionViewSet(ReadOnlyModelViewSet):
    """ViewSet for viewing task execution records."""

    queryset = TaskExecution.objects.all().order_by("-created_at")
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "public_id"
    filterset_fields = ["task_name", "status", "queue_name", "worker_name"]
    search_fields = ["task_name", "task_id", "worker_name"]
    ordering_fields = ["created_at", "started_at", "completed_at", "duration_seconds"]

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == "retrieve":
            return TaskExecutionDetailSerializer
        return TaskExecutionSerializer

    def get_queryset(self):
        """Filter queryset based on query parameters."""
        queryset = super().get_queryset()

        # Filter by date range
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)

        # Filter by active/completed status
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            if is_active.lower() == "true":
                queryset = queryset.filter(status__in=[TaskExecution.Status.PENDING, TaskExecution.Status.STARTED])
            else:
                queryset = queryset.exclude(status__in=[TaskExecution.Status.PENDING, TaskExecution.Status.STARTED])

        return queryset

    @action(detail=True, methods=["post"])
    def retry(self, request, public_id=None):
        """Retry a failed task."""
        task_execution = self.get_object()

        if task_execution.status != TaskExecution.Status.FAILURE:
            return Response({"error": "Task can only be retried if it has failed"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Get the original task and retry it
            task_name = task_execution.task_name
            task_args = task_execution.args
            task_kwargs = task_execution.kwargs

            # Get the task function
            task_func = current_app.tasks.get(task_name)
            if not task_func:
                return Response({"error": f"Task {task_name} not found"}, status=status.HTTP_404_NOT_FOUND)

            # Schedule retry
            new_task = task_func.delay(*task_args, **task_kwargs)

            return Response(
                {
                    "message": "Task retry scheduled",
                    "new_task_id": new_task.id,
                    "original_task_id": task_execution.task_id,
                }
            )

        except Exception as e:
            logger.error(f"Failed to retry task {task_execution.task_id}: {e}")
            return Response({"error": f"Failed to retry task: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["get"])
    def active(self, request):
        """Get all currently active tasks."""
        active_tasks = self.get_queryset().filter(
            status__in=[TaskExecution.Status.PENDING, TaskExecution.Status.STARTED]
        )

        serializer = self.get_serializer(active_tasks, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def failed(self, request):
        """Get all failed tasks."""
        failed_tasks = self.get_queryset().filter(status=TaskExecution.Status.FAILURE)

        serializer = self.get_serializer(failed_tasks, many=True)
        return Response(serializer.data)


class TaskStatusView(APIView):
    """View for checking individual task status."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, task_id):
        """Get status of a specific task."""
        try:
            # Try to get from database first
            try:
                task_execution = TaskExecution.objects.get(task_id=task_id)
                serializer = TaskStatusSerializer(
                    {
                        "task_id": task_execution.task_id,
                        "task_name": task_execution.task_name,
                        "status": task_execution.status,
                        "progress": task_execution.progress,
                        "result": task_execution.result,
                        "started_at": task_execution.started_at,
                        "completed_at": task_execution.completed_at,
                        "duration_seconds": task_execution.duration_seconds,
                        "retry_count": task_execution.retry_count,
                    }
                )
                return Response(serializer.data)

            except TaskExecution.DoesNotExist:
                # If not in database, check Celery directly
                from celery.result import AsyncResult

                result = AsyncResult(task_id)

                task_data = {
                    "task_id": task_id,
                    "task_name": getattr(result, "name", "unknown"),
                    "status": result.status.lower() if result.status else "unknown",
                }

                if result.info:
                    if isinstance(result.info, dict):
                        task_data.update(result.info)
                    else:
                        task_data["error"] = str(result.info)

                serializer = TaskStatusSerializer(task_data)
                return Response(serializer.data)

        except Exception as e:
            logger.error(f"Failed to get task status for {task_id}: {e}")
            return Response(
                {"error": f"Failed to get task status: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SystemHealthView(APIView):
    """View for system health and monitoring information."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Get comprehensive system health metrics."""
        try:
            # Get cached system status
            system_status = get_system_status()

            # Check for critical issues
            health_data = system_status.get("health", {})
            critical_issues = []

            # Add critical issue detection logic
            if health_data.get("recent_success_rate", 100) < 90:
                critical_issues.append("High task failure rate detected")

            if len(system_status.get("slow_tasks", [])) > 5:
                critical_issues.append("Multiple slow-running tasks detected")

            health_response = {
                "status": "critical" if critical_issues else "healthy",
                "critical_issues": critical_issues,
                **health_data,
            }

            serializer = SystemHealthSerializer(health_response)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Failed to get system health: {e}")
            return Response(
                {"error": f"Failed to get system health: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"])
    def queues(self, request):
        """Get queue performance metrics."""
        try:
            system_status = get_system_status()
            queue_metrics = system_status.get("queues", {})

            serializer = QueueMetricsSerializer(
                [{"name": name, **metrics} for name, metrics in queue_metrics.items()], many=True
            )
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Failed to get queue metrics: {e}")
            return Response(
                {"error": f"Failed to get queue metrics: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"])
    def slow_tasks(self, request):
        """Get currently slow-running tasks."""
        try:
            threshold = int(request.query_params.get("threshold", 30))
            slow_tasks = task_monitor.get_slow_tasks(threshold)

            serializer = SlowTaskSerializer(slow_tasks, many=True)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Failed to get slow tasks: {e}")
            return Response({"error": f"Failed to get slow tasks: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["get"])
    def failures(self, request):
        """Get failure analysis data."""
        try:
            hours = int(request.query_params.get("hours", 24))
            failure_analysis = task_monitor.get_failure_analysis(hours)

            serializer = FailureAnalysisSerializer(failure_analysis)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Failed to get failure analysis: {e}")
            return Response(
                {"error": f"Failed to get failure analysis: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TaskMetricsView(APIView):
    """View for task performance metrics."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, task_name=None):
        """Get task performance metrics."""
        try:
            if task_name:
                # Get metrics for specific task
                metrics = task_monitor.get_task_statistics(task_name)
                if not metrics:
                    raise Http404(f"No metrics found for task {task_name}")

                serializer = TaskMetricsSerializer(metrics)
                return Response(serializer.data)
            else:
                # Get metrics for all tasks
                all_metrics = task_monitor.get_task_statistics()
                serializer = TaskMetricsSerializer([metrics for metrics in all_metrics.values()], many=True)
                return Response(serializer.data)

        except Exception as e:
            logger.error(f"Failed to get task metrics: {e}")
            return Response(
                {"error": f"Failed to get task metrics: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"], url_path="trends/(?P<task_name>[^/.]+)")
    def trends(self, request, task_name):
        """Get performance trends for a specific task."""
        try:
            days = int(request.query_params.get("days", 7))
            trends = task_monitor.get_task_performance_trends(task_name, days)

            serializer = TaskTrendSerializer(trends)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Failed to get task trends: {e}")
            return Response(
                {"error": f"Failed to get task trends: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WebhookLogViewSet(ReadOnlyModelViewSet):
    """ViewSet for viewing webhook logs."""

    queryset = WebhookLog.objects.all().order_by("-created_at")
    serializer_class = WebhookLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "public_id"
    filterset_fields = ["webhook_type", "status"]
    search_fields = ["webhook_type", "url", "error_message"]

    @action(detail=True, methods=["post"])
    def retry(self, request, public_id=None):
        """Retry a failed webhook."""
        webhook_log = self.get_object()

        if webhook_log.status == WebhookLog.Status.DELIVERED:
            return Response({"error": "Webhook has already been delivered"}, status=status.HTTP_400_BAD_REQUEST)

        if webhook_log.retry_count >= 3:
            return Response({"error": "Maximum retries exceeded"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from ..tasks import retry_failed_webhook

            task = retry_failed_webhook.delay(webhook_log.id)

            return Response(
                {
                    "message": "Webhook retry scheduled",
                    "task_id": task.id,
                    "retry_count": webhook_log.retry_count + 1,
                }
            )

        except Exception as e:
            logger.error(f"Failed to retry webhook {webhook_log.id}: {e}")
            return Response({"error": f"Failed to retry webhook: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["get"])
    def failed(self, request):
        """Get all failed webhooks."""
        failed_webhooks = self.get_queryset().filter(status__in=[WebhookLog.Status.FAILED, WebhookLog.Status.RETRYING])

        serializer = self.get_serializer(failed_webhooks, many=True)
        return Response(serializer.data)


class ReportGenerationView(APIView):
    """View for generating analytics reports asynchronously."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Generate a report asynchronously."""
        serializer = ReportGenerationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            from ..services.analytics_service import analytics_service

            task_id = analytics_service.generate_report_async(
                report_type=serializer.validated_data["report_type"],
                **{k: v for k, v in serializer.validated_data.items() if k != "report_type"},
            )

            return Response(
                {
                    "message": "Report generation scheduled",
                    "task_id": task_id,
                    "report_type": serializer.validated_data["report_type"],
                    "status_url": f"/api/tasks/{task_id}/status/",
                },
                status=status.HTTP_202_ACCEPTED,
            )

        except Exception as e:
            logger.error(f"Failed to schedule report generation: {e}")
            return Response(
                {"error": f"Failed to schedule report generation: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def get(self, request):
        """Get available report from cache."""
        cache_key = request.query_params.get("cache_key")
        if not cache_key:
            return Response({"error": "cache_key parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        report_data = cache.get(cache_key)
        if not report_data:
            return Response({"error": "Report not found or expired"}, status=status.HTTP_404_NOT_FOUND)

        return Response(report_data)


class DataExportView(APIView):
    """View for exporting call data asynchronously."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Start data export."""
        serializer = DataExportRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            from ..tasks import export_call_data

            # Convert datetime objects to ISO strings for JSON serialization
            filters = serializer.validated_data.copy()
            if filters.get("start_date"):
                filters["start_date"] = filters["start_date"].isoformat()
            if filters.get("end_date"):
                filters["end_date"] = filters["end_date"].isoformat()

            export_format = filters.pop("format", "csv")

            task = export_call_data.delay(filters=filters, format=export_format, user_id=request.user.id)

            return Response(
                {
                    "message": "Data export scheduled",
                    "task_id": task.id,
                    "format": export_format,
                    "status_url": f"/api/tasks/{task.id}/status/",
                },
                status=status.HTTP_202_ACCEPTED,
            )

        except Exception as e:
            logger.error(f"Failed to schedule data export: {e}")
            return Response(
                {"error": f"Failed to schedule data export: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def get(self, request):
        """Download exported data."""
        cache_key = request.query_params.get("cache_key")
        if not cache_key:
            return Response({"error": "cache_key parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        export_data = cache.get(cache_key)
        if not export_data:
            return Response({"error": "Export not found or expired"}, status=status.HTTP_404_NOT_FOUND)

        # Create HTTP response with appropriate content type
        file_data = export_data["data"]
        filename = export_data["filename"]
        file_format = export_data["format"]

        content_types = {
            "csv": "text/csv",
            "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "json": "application/json",
        }

        response = HttpResponse(file_data, content_type=content_types.get(file_format, "application/octet-stream"))
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        return response


class BulkTaskActionView(APIView):
    """View for performing bulk actions on tasks."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Perform bulk action on tasks."""
        serializer = BulkTaskActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        action = serializer.validated_data["action"]
        task_ids = serializer.validated_data.get("task_ids")
        filters = serializer.validated_data.get("filters")

        try:
            # Get tasks to act on
            if task_ids:
                tasks = TaskExecution.objects.filter(task_id__in=task_ids)
            else:
                tasks = TaskExecution.objects.filter(**filters)

            if not tasks.exists():
                return Response({"error": "No tasks found matching criteria"}, status=status.HTTP_404_NOT_FOUND)

            # Perform action
            if action == "retry":
                result = self._bulk_retry_tasks(tasks)
            elif action == "cancel":
                result = self._bulk_cancel_tasks(tasks)
            elif action == "delete":
                result = self._bulk_delete_tasks(tasks)
            else:
                return Response({"error": f"Unknown action: {action}"}, status=status.HTTP_400_BAD_REQUEST)

            return Response(result)

        except Exception as e:
            logger.error(f"Failed to perform bulk action {action}: {e}")
            return Response(
                {"error": f"Failed to perform bulk action: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _bulk_retry_tasks(self, tasks):
        """Retry multiple failed tasks."""
        retried_count = 0
        failed_count = 0

        for task_execution in tasks:
            if task_execution.status == TaskExecution.Status.FAILURE:
                try:
                    # Get the task function and retry
                    task_func = current_app.tasks.get(task_execution.task_name)
                    if task_func:
                        task_func.delay(*task_execution.args, **task_execution.kwargs)
                        retried_count += 1
                    else:
                        failed_count += 1
                except Exception:
                    failed_count += 1

        return {
            "action": "retry",
            "total_tasks": tasks.count(),
            "retried_count": retried_count,
            "failed_count": failed_count,
        }

    def _bulk_cancel_tasks(self, tasks):
        """Cancel multiple active tasks."""
        cancelled_count = 0

        for task_execution in tasks:
            if task_execution.is_active:
                try:
                    from celery import current_app

                    current_app.control.revoke(task_execution.task_id, terminate=True)
                    task_execution.status = TaskExecution.Status.REVOKED
                    task_execution.completed_at = timezone.now()
                    task_execution.save()
                    cancelled_count += 1
                except Exception:
                    pass

        return {
            "action": "cancel",
            "total_tasks": tasks.count(),
            "cancelled_count": cancelled_count,
        }

    def _bulk_delete_tasks(self, tasks):
        """Delete multiple task execution records."""
        deleted_count, _ = tasks.delete()

        return {
            "action": "delete",
            "deleted_count": deleted_count,
        }

"""URL patterns for async task monitoring and management APIs."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from ..views.task_views import (
    BulkTaskActionView,
    DataExportView,
    ReportGenerationView,
    SystemHealthView,
    TaskExecutionViewSet,
    TaskMetricsView,
    TaskStatusView,
    WebhookLogViewSet,
)

# Create router for viewsets
router = DefaultRouter()
router.register(r"executions", TaskExecutionViewSet, basename="task-executions")
router.register(r"webhooks", WebhookLogViewSet, basename="webhook-logs")

app_name = "tasks"

urlpatterns = [
    # ViewSet routes
    path("", include(router.urls)),
    # Individual task status
    path("status/<str:task_id>/", TaskStatusView.as_view(), name="task-status"),
    # System health and monitoring
    path("health/", SystemHealthView.as_view(), name="system-health"),
    path("health/queues/", SystemHealthView.as_view({"get": "queues"}), name="queue-metrics"),
    path("health/slow/", SystemHealthView.as_view({"get": "slow_tasks"}), name="slow-tasks"),
    path("health/failures/", SystemHealthView.as_view({"get": "failures"}), name="failure-analysis"),
    # Task performance metrics
    path("metrics/", TaskMetricsView.as_view(), name="task-metrics"),
    path("metrics/<str:task_name>/", TaskMetricsView.as_view(), name="task-metrics-detail"),
    path("metrics/<str:task_name>/trends/", TaskMetricsView.as_view({"get": "trends"}), name="task-trends"),
    # Report generation
    path("reports/generate/", ReportGenerationView.as_view(), name="generate-report"),
    path("reports/download/", ReportGenerationView.as_view(), name="download-report"),
    # Data export
    path("export/", DataExportView.as_view(), name="export-data"),
    path("export/download/", DataExportView.as_view(), name="download-export"),
    # Bulk task actions
    path("bulk-actions/", BulkTaskActionView.as_view(), name="bulk-task-actions"),
]

"""Prometheus metrics exporter for Django views."""

import logging

from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..metrics.collectors import call_center_metrics, twilio_metrics
from ..metrics.registry import metrics_registry

logger = logging.getLogger(__name__)


@method_decorator(never_cache, name="dispatch")
class PrometheusMetricsView(View):
    """Prometheus metrics endpoint."""

    def get(self, request):
        """Export Prometheus metrics."""
        try:
            # Update real-time metrics before export
            self._update_real_time_metrics()

            # Generate metrics output
            metrics_output = generate_latest(metrics_registry.registry)

            return HttpResponse(metrics_output, content_type=CONTENT_TYPE_LATEST)

        except Exception as e:
            logger.error(f"Failed to export Prometheus metrics: {e}")
            return HttpResponse(f"# Error generating metrics: {e}\n", content_type=CONTENT_TYPE_LATEST, status=500)

    def _update_real_time_metrics(self) -> None:
        """Update real-time metrics before export."""
        try:
            # Update call center KPIs
            call_center_metrics.collect_real_time_metrics()

            # Update Twilio resource metrics
            twilio_metrics.update_resource_metrics()

        except Exception as e:
            logger.warning(f"Failed to update real-time metrics: {e}")


@api_view(["GET"])
@permission_classes([AllowAny])
@never_cache
def metrics_summary(request):
    """Get a summary of current metrics for dashboards."""
    try:
        # Collect current metrics
        kpi_metrics = call_center_metrics.collect_real_time_metrics()

        summary = {
            "call_center_kpis": {
                "service_level_percentage": kpi_metrics.service_level,
                "abandonment_rate_percentage": kpi_metrics.abandonment_rate,
                "average_wait_time_seconds": kpi_metrics.average_wait_time,
                "average_talk_time_seconds": kpi_metrics.average_talk_time,
                "calls_handled_today": kpi_metrics.calls_handled,
                "calls_abandoned_today": kpi_metrics.calls_abandoned,
                "agent_utilization_percentage": kpi_metrics.agent_utilization,
                "current_queue_depth": kpi_metrics.queue_depth,
            },
            "system_health": {
                "active_agents": 0,  # Would be populated from health checks
                "active_queues": 0,
                "active_calls": 0,
            },
            "performance_indicators": {
                "average_response_time_ms": 0,  # Would be calculated from request metrics
                "error_rate_percentage": 0,
                "throughput_requests_per_minute": 0,
            },
        }

        # Add agent status breakdown
        try:
            from ...models import Agent

            agent_stats = Agent.objects.filter(is_active=True).values("status").distinct()
            summary["agent_status_breakdown"] = {
                status["status"]: Agent.objects.filter(is_active=True, status=status["status"]).count()
                for status in agent_stats
            }
        except Exception as e:
            logger.warning(f"Failed to get agent status breakdown: {e}")
            summary["agent_status_breakdown"] = {}

        return Response(summary)

    except Exception as e:
        logger.error(f"Failed to generate metrics summary: {e}")
        return Response({"error": str(e)}, status=500)

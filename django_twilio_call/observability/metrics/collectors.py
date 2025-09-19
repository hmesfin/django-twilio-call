"""Business metrics collectors for call center operations."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from django.core.cache import cache
from django.db.models import Avg
from django.utils import timezone

from .registry import metrics_registry

logger = logging.getLogger(__name__)


@dataclass
class CallCenterMetrics:
    """Data class for call center KPI metrics."""

    service_level: float
    abandonment_rate: float
    average_wait_time: float
    average_talk_time: float
    calls_handled: int
    calls_abandoned: int
    agent_utilization: float
    queue_depth: int
    first_call_resolution: float


class CallCenterKPICollector:
    """Collector for call center Key Performance Indicators."""

    def __init__(self):
        # Service Level Agreement metrics
        self.service_level = metrics_registry.register_gauge(
            "callcenter_service_level_percentage",
            "Percentage of calls answered within SLA threshold",
            ["queue", "threshold_seconds"],
        )

        self.abandonment_rate = metrics_registry.register_gauge(
            "callcenter_abandonment_rate_percentage", "Percentage of calls abandoned before being answered", ["queue"]
        )

        # Wait time metrics
        self.average_wait_time = metrics_registry.register_gauge(
            "callcenter_average_wait_time_seconds", "Average time calls spend in queue", ["queue"]
        )

        self.queue_depth = metrics_registry.register_gauge(
            "callcenter_current_queue_depth", "Current number of calls waiting in queue", ["queue"]
        )

        # Talk time and handling metrics
        self.average_talk_time = metrics_registry.register_gauge(
            "callcenter_average_talk_time_seconds", "Average duration of completed calls", ["queue", "agent"]
        )

        self.calls_handled = metrics_registry.register_counter(
            "callcenter_calls_handled_total", "Total number of calls handled", ["queue", "agent", "direction"]
        )

        # Agent performance metrics
        self.agent_utilization = metrics_registry.register_gauge(
            "callcenter_agent_utilization_percentage", "Percentage of time agents spend on calls", ["agent", "queue"]
        )

        self.agent_status = metrics_registry.register_gauge(
            "callcenter_agent_status", "Agent status (1=available, 0=unavailable)", ["agent", "status"]
        )

        # Call resolution metrics
        self.first_call_resolution = metrics_registry.register_gauge(
            "callcenter_first_call_resolution_percentage", "Percentage of calls resolved on first contact", ["queue"]
        )

        # Recording metrics
        self.recording_processing_time = metrics_registry.register_histogram(
            "callcenter_recording_processing_seconds",
            "Time taken to process call recordings",
            ["status"],
            buckets=[1, 5, 10, 30, 60, 300, 600],
        )

    def collect_real_time_metrics(self) -> CallCenterMetrics:
        """Collect real-time call center metrics."""
        from ...models import Queue

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Get active queues
        active_queues = Queue.objects.filter(is_active=True)

        overall_metrics = {
            "service_level": 0.0,
            "abandonment_rate": 0.0,
            "average_wait_time": 0.0,
            "average_talk_time": 0.0,
            "calls_handled": 0,
            "calls_abandoned": 0,
            "agent_utilization": 0.0,
            "queue_depth": 0,
            "first_call_resolution": 0.0,
        }

        for queue in active_queues:
            queue_metrics = self._collect_queue_metrics(queue, today_start, now)
            self._update_queue_gauges(queue, queue_metrics)

            # Aggregate for overall metrics
            overall_metrics["calls_handled"] += queue_metrics["calls_handled"]
            overall_metrics["calls_abandoned"] += queue_metrics["calls_abandoned"]
            overall_metrics["queue_depth"] += queue_metrics["queue_depth"]

        # Calculate overall percentages
        total_calls = overall_metrics["calls_handled"] + overall_metrics["calls_abandoned"]
        if total_calls > 0:
            overall_metrics["abandonment_rate"] = (overall_metrics["calls_abandoned"] / total_calls) * 100

        # Collect agent metrics
        self._collect_agent_metrics(today_start, now)

        return CallCenterMetrics(**overall_metrics)

    def _collect_queue_metrics(self, queue, start_time: datetime, end_time: datetime) -> Dict[str, float]:
        """Collect metrics for a specific queue."""
        from ...models import Call

        cache_key = f"queue_metrics_{queue.public_id}_{start_time.hour}"
        cached_metrics = cache.get(cache_key)
        if cached_metrics:
            return cached_metrics

        # Calls in this queue today
        queue_calls = Call.objects.filter(queue=queue, created_at__gte=start_time, created_at__lt=end_time)

        # Service level calculation (calls answered within 20 seconds)
        sla_threshold = 20  # seconds
        answered_calls = queue_calls.filter(status=Call.Status.COMPLETED)
        sla_compliant_calls = answered_calls.filter(queue_time__lte=sla_threshold)

        service_level = 0.0
        if answered_calls.count() > 0:
            service_level = (sla_compliant_calls.count() / answered_calls.count()) * 100

        # Abandonment rate
        abandoned_calls = queue_calls.filter(status__in=[Call.Status.CANCELED, Call.Status.NO_ANSWER])
        total_calls = queue_calls.count()
        abandonment_rate = 0.0
        if total_calls > 0:
            abandonment_rate = (abandoned_calls.count() / total_calls) * 100

        # Average wait time
        avg_wait_time = queue_calls.aggregate(avg_wait=Avg("queue_time"))["avg_wait"] or 0.0

        # Average talk time for completed calls
        avg_talk_time = answered_calls.aggregate(avg_talk=Avg("duration"))["avg_talk"] or 0.0

        # Current queue depth (active calls in queue)
        current_queue_depth = Call.objects.filter(queue=queue, status=Call.Status.QUEUED).count()

        metrics = {
            "service_level": service_level,
            "abandonment_rate": abandonment_rate,
            "average_wait_time": avg_wait_time,
            "average_talk_time": avg_talk_time,
            "calls_handled": answered_calls.count(),
            "calls_abandoned": abandoned_calls.count(),
            "queue_depth": current_queue_depth,
            "first_call_resolution": 85.0,  # Placeholder - would need call outcome tracking
        }

        # Cache for 5 minutes
        cache.set(cache_key, metrics, 300)
        return metrics

    def _update_queue_gauges(self, queue, metrics: Dict[str, float]) -> None:
        """Update Prometheus gauges for queue metrics."""
        queue_name = queue.name

        self.service_level.labels(queue=queue_name, threshold_seconds="20").set(metrics["service_level"])
        self.abandonment_rate.labels(queue=queue_name).set(metrics["abandonment_rate"])
        self.average_wait_time.labels(queue=queue_name).set(metrics["average_wait_time"])
        self.queue_depth.labels(queue=queue_name).set(metrics["queue_depth"])
        self.first_call_resolution.labels(queue=queue_name).set(metrics["first_call_resolution"])

    def _collect_agent_metrics(self, start_time: datetime, end_time: datetime) -> None:
        """Collect agent performance metrics."""
        from ...models import Agent, AgentActivity

        active_agents = Agent.objects.filter(is_active=True)

        for agent in active_agents:
            # Agent utilization calculation
            total_time = (end_time - start_time).total_seconds()

            # Time spent on calls today
            call_activities = AgentActivity.objects.filter(
                agent=agent,
                activity_type=AgentActivity.ActivityType.CALL_START,
                created_at__gte=start_time,
                created_at__lt=end_time,
            )

            talk_time = sum(
                [activity.duration_seconds or 0 for activity in call_activities if activity.duration_seconds]
            )

            utilization = 0.0
            if total_time > 0:
                utilization = (talk_time / total_time) * 100

            # Update agent metrics
            agent_id = str(agent.public_id)
            self.agent_utilization.labels(agent=agent_id, queue="all").set(utilization)

            # Agent status
            status_value = 1.0 if agent.is_available else 0.0
            self.agent_status.labels(agent=agent_id, status=agent.status).set(status_value)


class TwilioMetricsCollector:
    """Collector for Twilio API and webhook metrics."""

    def __init__(self):
        # Twilio API metrics
        self.twilio_api_calls = metrics_registry.register_counter(
            "twilio_api_calls_total", "Total Twilio API calls made", ["endpoint", "method", "status_code"]
        )

        self.twilio_api_duration = metrics_registry.register_histogram(
            "twilio_api_call_duration_seconds",
            "Duration of Twilio API calls",
            ["endpoint", "method"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
        )

        self.twilio_api_errors = metrics_registry.register_counter(
            "twilio_api_errors_total", "Total Twilio API errors", ["endpoint", "error_code", "error_type"]
        )

        # Webhook metrics
        self.webhook_delivery_attempts = metrics_registry.register_counter(
            "twilio_webhook_delivery_attempts_total", "Total webhook delivery attempts", ["webhook_type", "status"]
        )

        self.webhook_processing_duration = metrics_registry.register_histogram(
            "twilio_webhook_processing_seconds",
            "Time to process incoming webhooks",
            ["webhook_type"],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
        )

        # Twilio resource metrics
        self.active_calls = metrics_registry.register_gauge("twilio_active_calls", "Number of active calls in Twilio")

        self.monthly_usage = metrics_registry.register_gauge(
            "twilio_monthly_usage_dollars", "Monthly Twilio usage in dollars", ["resource_type"]
        )

    def record_api_call(
        self, endpoint: str, method: str, duration: float, status_code: int, error_code: Optional[str] = None
    ) -> None:
        """Record Twilio API call metrics."""
        # Record call count and duration
        self.twilio_api_calls.labels(endpoint=endpoint, method=method, status_code=str(status_code)).inc()

        self.twilio_api_duration.labels(endpoint=endpoint, method=method).observe(duration)

        # Record errors
        if status_code >= 400 and error_code:
            error_type = "client_error" if status_code < 500 else "server_error"
            self.twilio_api_errors.labels(endpoint=endpoint, error_code=error_code, error_type=error_type).inc()

    def record_webhook_processing(self, webhook_type: str, duration: float, status: str) -> None:
        """Record webhook processing metrics."""
        self.webhook_delivery_attempts.labels(webhook_type=webhook_type, status=status).inc()

        self.webhook_processing_duration.labels(webhook_type=webhook_type).observe(duration)

    def update_resource_metrics(self) -> None:
        """Update Twilio resource usage metrics."""
        try:
            from ...services.twilio_service import twilio_service

            # Get active calls count
            active_calls_count = twilio_service.get_active_calls_count()
            self.active_calls.set(active_calls_count)

            # Get monthly usage (if available)
            usage_data = twilio_service.get_monthly_usage()
            for resource_type, cost in usage_data.items():
                self.monthly_usage.labels(resource_type=resource_type).set(cost)

        except Exception as e:
            logger.error(f"Failed to update Twilio resource metrics: {e}")


# Global collector instances
call_center_metrics = CallCenterKPICollector()
twilio_metrics = TwilioMetricsCollector()

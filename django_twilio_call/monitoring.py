"""
Production monitoring and metrics for Django-Twilio-Call.
Provides Prometheus metrics and monitoring endpoints.
"""

import time
from typing import Dict, Any

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        multiprocess,
        REGISTRY,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Prometheus metrics (if available)
if PROMETHEUS_AVAILABLE:
    # Application metrics
    call_total = Counter(
        'django_twilio_call_total',
        'Total number of calls',
        ['status', 'direction', 'queue']
    )

    call_duration = Histogram(
        'django_twilio_call_duration_seconds',
        'Call duration in seconds',
        ['status', 'queue']
    )

    active_calls = Gauge(
        'django_twilio_call_active_total',
        'Number of active calls',
        ['queue']
    )

    agent_status = Gauge(
        'django_twilio_call_agent_status',
        'Agent status (1=available, 0=unavailable)',
        ['agent_id', 'status']
    )

    queue_size = Gauge(
        'django_twilio_call_queue_size',
        'Number of calls waiting in queue',
        ['queue_name']
    )

    # System metrics
    database_connections = Gauge(
        'django_twilio_call_db_connections',
        'Number of database connections'
    )

    cache_hit_rate = Gauge(
        'django_twilio_call_cache_hit_rate',
        'Cache hit rate percentage'
    )

    celery_task_total = Counter(
        'django_twilio_call_celery_tasks_total',
        'Total number of Celery tasks',
        ['task_name', 'status']
    )

    celery_task_duration = Histogram(
        'django_twilio_call_celery_task_duration_seconds',
        'Celery task duration in seconds',
        ['task_name']
    )

    # Business metrics
    webhook_requests = Counter(
        'django_twilio_call_webhook_requests_total',
        'Total webhook requests',
        ['webhook_type', 'status']
    )

    recording_size_bytes = Histogram(
        'django_twilio_call_recording_size_bytes',
        'Recording file size in bytes'
    )

    ivr_interactions = Counter(
        'django_twilio_call_ivr_interactions_total',
        'Total IVR interactions',
        ['flow_name', 'action']
    )


class MetricsCollector:
    """Collects and updates application metrics."""

    def __init__(self):
        self.enabled = PROMETHEUS_AVAILABLE and getattr(settings, 'METRICS_ENABLED', True)

    def record_call_started(self, call_data: Dict[str, Any]):
        """Record when a call starts."""
        if not self.enabled:
            return

        call_total.labels(
            status='started',
            direction=call_data.get('direction', 'unknown'),
            queue=call_data.get('queue', 'default')
        ).inc()

    def record_call_ended(self, call_data: Dict[str, Any]):
        """Record when a call ends."""
        if not self.enabled:
            return

        duration = call_data.get('duration', 0)
        queue = call_data.get('queue', 'default')
        status = call_data.get('status', 'completed')

        call_total.labels(
            status='ended',
            direction=call_data.get('direction', 'unknown'),
            queue=queue
        ).inc()

        call_duration.labels(
            status=status,
            queue=queue
        ).observe(duration)

    def update_active_calls(self, queue_name: str, count: int):
        """Update active calls gauge."""
        if not self.enabled:
            return

        active_calls.labels(queue=queue_name).set(count)

    def update_agent_status(self, agent_id: str, status: str, value: int):
        """Update agent status."""
        if not self.enabled:
            return

        agent_status.labels(agent_id=agent_id, status=status).set(value)

    def update_queue_size(self, queue_name: str, size: int):
        """Update queue size."""
        if not self.enabled:
            return

        queue_size.labels(queue_name=queue_name).set(size)

    def record_webhook_request(self, webhook_type: str, status_code: int):
        """Record webhook request."""
        if not self.enabled:
            return

        status = 'success' if 200 <= status_code < 300 else 'error'
        webhook_requests.labels(
            webhook_type=webhook_type,
            status=status
        ).inc()

    def record_celery_task(self, task_name: str, duration: float, status: str):
        """Record Celery task execution."""
        if not self.enabled:
            return

        celery_task_total.labels(
            task_name=task_name,
            status=status
        ).inc()

        celery_task_duration.labels(
            task_name=task_name
        ).observe(duration)

    def record_recording_size(self, size_bytes: int):
        """Record recording file size."""
        if not self.enabled:
            return

        recording_size_bytes.observe(size_bytes)

    def record_ivr_interaction(self, flow_name: str, action: str):
        """Record IVR interaction."""
        if not self.enabled:
            return

        ivr_interactions.labels(
            flow_name=flow_name,
            action=action
        ).inc()

    def update_system_metrics(self):
        """Update system-level metrics."""
        if not self.enabled:
            return

        try:
            # Database connections
            db_connections = len(connection.queries)
            database_connections.set(db_connections)

            # Cache metrics (simplified)
            cache_info = getattr(cache, '_cache', {})
            if hasattr(cache_info, 'get_stats'):
                stats = cache_info.get_stats()
                hit_rate = stats.get('hit_rate', 0) * 100
                cache_hit_rate.set(hit_rate)

        except Exception:
            # Don't fail on metrics collection errors
            pass


# Global metrics collector
metrics_collector = MetricsCollector()


@never_cache
@csrf_exempt
@require_http_methods(["GET"])
def metrics_endpoint(request):
    """
    Prometheus metrics endpoint.
    Returns metrics in Prometheus format.
    """
    if not PROMETHEUS_AVAILABLE:
        return HttpResponse(
            "Prometheus client not available",
            content_type="text/plain",
            status=503
        )

    try:
        # Update system metrics before export
        metrics_collector.update_system_metrics()

        # Generate metrics
        registry = REGISTRY
        if hasattr(settings, 'PROMETHEUS_MULTIPROC_DIR'):
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)

        metrics_data = generate_latest(registry)

        return HttpResponse(
            metrics_data,
            content_type=CONTENT_TYPE_LATEST
        )

    except Exception as e:
        return HttpResponse(
            f"Error generating metrics: {str(e)}",
            content_type="text/plain",
            status=500
        )


@never_cache
@csrf_exempt
@require_http_methods(["GET"])
def app_info(request):
    """
    Application information endpoint.
    Returns basic application information for monitoring.
    """
    try:
        from django_twilio_call import __version__
        version = __version__
    except ImportError:
        version = "unknown"

    info = {
        'name': 'django-twilio-call',
        'version': version,
        'environment': getattr(settings, 'ENVIRONMENT', 'unknown'),
        'debug': settings.DEBUG,
        'timestamp': timezone.now().isoformat(),
        'uptime_seconds': int(time.time() - getattr(settings, 'START_TIME', time.time())),
        'features': {
            'prometheus_metrics': PROMETHEUS_AVAILABLE,
            'twilio_integration': bool(getattr(settings, 'TWILIO_ACCOUNT_SID', None)),
            'celery_enabled': 'django_celery_beat' in settings.INSTALLED_APPS,
            'redis_cache': 'redis' in settings.CACHES.get('default', {}).get('BACKEND', '').lower(),
        },
        'configuration': {
            'allowed_hosts': settings.ALLOWED_HOSTS,
            'time_zone': settings.TIME_ZONE,
            'recording_enabled': getattr(settings, 'DJANGO_TWILIO_CALL', {}).get('RECORDING_ENABLED', False),
            'analytics_enabled': getattr(settings, 'DJANGO_TWILIO_CALL', {}).get('ANALYTICS_ENABLED', False),
        }
    }

    return JsonResponse(info)


# Middleware for automatic metrics collection
class MetricsMiddleware:
    """Middleware to automatically collect request metrics."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()

        response = self.get_response(request)

        # Record request metrics
        if PROMETHEUS_AVAILABLE and hasattr(request, 'resolver_match'):
            duration = time.time() - start_time
            endpoint = getattr(request.resolver_match, 'view_name', 'unknown')

            # This could be expanded to include more detailed request metrics
            # For now, webhook metrics are handled separately

        return response
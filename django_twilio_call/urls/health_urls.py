"""
Health check URLs for Django-Twilio-Call package.
Production monitoring and health check endpoints.
"""

from django.urls import path

from ..health import (
    health_check,
    health_check_detailed,
    readiness_check,
    liveness_check,
)
from ..monitoring import (
    metrics_endpoint,
    app_info,
)

app_name = 'health'

urlpatterns = [
    # Basic health check
    path('health/', health_check, name='health_check'),

    # Detailed health check with component status
    path('health/detailed/', health_check_detailed, name='health_check_detailed'),

    # Kubernetes probes
    path('health/ready/', readiness_check, name='readiness_check'),
    path('health/live/', liveness_check, name='liveness_check'),

    # Alternative paths for different deployment scenarios
    path('healthz/', health_check, name='healthz'),
    path('ready/', readiness_check, name='ready'),
    path('live/', liveness_check, name='live'),

    # Monitoring and metrics
    path('metrics/', metrics_endpoint, name='metrics'),
    path('info/', app_info, name='app_info'),
]
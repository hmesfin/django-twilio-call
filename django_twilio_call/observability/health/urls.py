"""Health check URL configuration."""

from django.urls import path

from .views import (
    HealthCheckView,
    detailed_health_check,
    liveness_check,
    metrics_health_check,
    readiness_check,
)

app_name = "health"

urlpatterns = [
    # Basic health check for load balancers
    path("", HealthCheckView.as_view(), name="basic"),
    # Detailed health check with all components
    path("detailed/", detailed_health_check, name="detailed"),
    # Kubernetes probes
    path("ready/", readiness_check, name="readiness"),
    path("live/", liveness_check, name="liveness"),
    # Metrics health check
    path("metrics/", metrics_health_check, name="metrics"),
]

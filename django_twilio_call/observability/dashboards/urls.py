"""Dashboard URL configuration."""

from django.urls import path

from .prometheus_exporter import PrometheusMetricsView, metrics_summary

app_name = "dashboards"

urlpatterns = [
    # Prometheus metrics endpoint
    path("metrics/", PrometheusMetricsView.as_view(), name="prometheus_metrics"),
    # Metrics summary for custom dashboards
    path("metrics/summary/", metrics_summary, name="metrics_summary"),
]

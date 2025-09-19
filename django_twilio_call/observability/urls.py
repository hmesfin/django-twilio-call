"""Observability URL configuration."""

from django.urls import path, include

app_name = 'observability'

urlpatterns = [
    # Health checks
    path('health/', include('django_twilio_call.observability.health.urls')),

    # Metrics and dashboards
    path('', include('django_twilio_call.observability.dashboards.urls')),
]
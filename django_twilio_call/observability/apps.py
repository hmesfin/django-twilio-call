"""Observability app configuration."""

from django.apps import AppConfig


class ObservabilityConfig(AppConfig):
    """Observability app configuration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_twilio_call.observability"
    label = "observability"

    def ready(self):
        """Initialize observability when Django starts."""
        from .config import setup_observability

        setup_observability()

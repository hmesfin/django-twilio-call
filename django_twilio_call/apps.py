"""Django app configuration for django-twilio-call."""

from django.apps import AppConfig


class DjangoTwilioCallConfig(AppConfig):
    """Configuration class for the Django Twilio Call application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_twilio_call"
    verbose_name = "Django Twilio Call"

    def ready(self) -> None:
        """Perform initialization when the app is ready."""
        # Import signal handlers when app is ready
        try:
            from . import signals  # noqa: F401
        except ImportError:
            pass

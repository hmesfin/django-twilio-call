"""Settings for django-twilio-call package.

This module is deprecated in favor of the new conf.py module.
It's kept for backwards compatibility but will be removed in a future version.
"""

import warnings
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# Issue deprecation warning
warnings.warn(
    "django_twilio_call.settings is deprecated. Use django_twilio_call.conf instead.",
    DeprecationWarning,
    stacklevel=2
)

# Twilio configuration
TWILIO_ACCOUNT_SID = getattr(settings, "TWILIO_ACCOUNT_SID", None)
TWILIO_AUTH_TOKEN = getattr(settings, "TWILIO_AUTH_TOKEN", None)
TWILIO_PHONE_NUMBER = getattr(settings, "TWILIO_PHONE_NUMBER", None)
TWILIO_WEBHOOK_URL = getattr(settings, "TWILIO_WEBHOOK_URL", None)
TWILIO_API_KEY = getattr(settings, "TWILIO_API_KEY", None)
TWILIO_API_SECRET = getattr(settings, "TWILIO_API_SECRET", None)

# Webhook configuration
TWILIO_WEBHOOK_VALIDATE = getattr(settings, "TWILIO_WEBHOOK_VALIDATE", True)
TWILIO_WEBHOOK_AUTH_TOKEN = getattr(settings, "TWILIO_WEBHOOK_AUTH_TOKEN", TWILIO_AUTH_TOKEN)

# Retry configuration
TWILIO_MAX_RETRIES = getattr(settings, "TWILIO_MAX_RETRIES", 3)
TWILIO_RETRY_BACKOFF_BASE = getattr(settings, "TWILIO_RETRY_BACKOFF_BASE", 2)
TWILIO_RETRY_BACKOFF_MAX = getattr(settings, "TWILIO_RETRY_BACKOFF_MAX", 60)
TWILIO_REQUEST_TIMEOUT = getattr(settings, "TWILIO_REQUEST_TIMEOUT", 30)

# Connection pool configuration
TWILIO_CONNECTION_POOL_SIZE = getattr(settings, "TWILIO_CONNECTION_POOL_SIZE", 10)
TWILIO_CONNECTION_POOL_MAXSIZE = getattr(settings, "TWILIO_CONNECTION_POOL_MAXSIZE", 50)

# Feature flags
ENABLE_CALL_RECORDING = getattr(settings, "ENABLE_CALL_RECORDING", True)
ENABLE_TRANSCRIPTION = getattr(settings, "ENABLE_TRANSCRIPTION", False)
ENABLE_VOICEMAIL = getattr(settings, "ENABLE_VOICEMAIL", True)
ENABLE_CONFERENCE = getattr(settings, "ENABLE_CONFERENCE", True)

# Queue configuration
MAX_QUEUE_SIZE = getattr(settings, "MAX_QUEUE_SIZE", 100)
DEFAULT_QUEUE_TIMEOUT = getattr(settings, "DEFAULT_QUEUE_TIMEOUT", 300)
DEFAULT_HOLD_MUSIC_URL = getattr(
    settings, "DEFAULT_HOLD_MUSIC_URL", "http://com.twilio.music.classical.s3.amazonaws.com/ith_brahms-116-4.mp3"
)

# Agent configuration
DEFAULT_AGENT_MAX_CONCURRENT_CALLS = getattr(settings, "DEFAULT_AGENT_MAX_CONCURRENT_CALLS", 1)
AGENT_STATUS_UPDATE_WEBHOOK = getattr(settings, "AGENT_STATUS_UPDATE_WEBHOOK", None)

# Call configuration
DEFAULT_CALL_TIME_LIMIT = getattr(settings, "DEFAULT_CALL_TIME_LIMIT", 14400)  # 4 hours
DEFAULT_RING_TIMEOUT = getattr(settings, "DEFAULT_RING_TIMEOUT", 30)
DEFAULT_CALLER_ID = getattr(settings, "DEFAULT_CALLER_ID", TWILIO_PHONE_NUMBER)

# Recording configuration
RECORDING_STATUS_CALLBACK_URL = getattr(settings, "RECORDING_STATUS_CALLBACK_URL", None)
RECORDING_STORAGE_BACKEND = getattr(settings, "RECORDING_STORAGE_BACKEND", "local")  # local, s3, azure
RECORDING_ENCRYPTION_KEY = getattr(settings, "RECORDING_ENCRYPTION_KEY", None)
RECORDING_RETENTION_DAYS = getattr(settings, "RECORDING_RETENTION_DAYS", 90)

# Logging configuration
DJANGO_TWILIO_LOG_LEVEL = getattr(settings, "DJANGO_TWILIO_LOG_LEVEL", "INFO")
DJANGO_TWILIO_LOG_API_REQUESTS = getattr(settings, "DJANGO_TWILIO_LOG_API_REQUESTS", True)
DJANGO_TWILIO_LOG_WEBHOOKS = getattr(settings, "DJANGO_TWILIO_LOG_WEBHOOKS", True)

# Cache configuration
DJANGO_TWILIO_CACHE_BACKEND = getattr(settings, "DJANGO_TWILIO_CACHE_BACKEND", "default")
DJANGO_TWILIO_CACHE_TIMEOUT = getattr(settings, "DJANGO_TWILIO_CACHE_TIMEOUT", 300)


def validate_settings():
    """Validate required settings."""
    errors = []

    if not TWILIO_ACCOUNT_SID:
        errors.append("TWILIO_ACCOUNT_SID is required")

    if not TWILIO_AUTH_TOKEN and not (TWILIO_API_KEY and TWILIO_API_SECRET):
        errors.append("Either TWILIO_AUTH_TOKEN or both TWILIO_API_KEY and TWILIO_API_SECRET are required")

    if not TWILIO_PHONE_NUMBER and not DEFAULT_CALLER_ID:
        errors.append("Either TWILIO_PHONE_NUMBER or DEFAULT_CALLER_ID is required")

    if errors:
        raise ImproperlyConfigured(f"Django-Twilio-Call configuration errors: {', '.join(errors)}")


# Validate settings on import (can be disabled for testing)
if getattr(settings, "DJANGO_TWILIO_VALIDATE_SETTINGS", True):
    try:
        validate_settings()
    except ImproperlyConfigured:
        # Only raise if we're not in testing mode
        if not getattr(settings, "TESTING", False):
            raise

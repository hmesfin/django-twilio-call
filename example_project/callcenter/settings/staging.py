"""
Staging settings for Django-Twilio-Call project.
Settings for staging environment - production-like but with debugging enabled.
"""

from .production import *
from decouple import config

# Enable debugging in staging for troubleshooting
DEBUG = config("DEBUG", default=True, cast=bool)

# Allow staging-specific hosts
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="staging.example.com,localhost").split(",")

# Staging-specific apps for debugging
INSTALLED_APPS += [
    "debug_toolbar",
    "django_extensions",
    "silk",  # Performance profiling
]

# Add debug toolbar for staging
MIDDLEWARE += [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "silk.middleware.SilkyMiddleware",
]

# Debug toolbar configuration for staging
INTERNAL_IPS = ["127.0.0.1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG,
}

# Silk configuration for performance monitoring
SILKY_PYTHON_PROFILER = True
SILKY_PYTHON_PROFILER_BINARY = True
SILKY_AUTHENTICATION = True
SILKY_AUTHORISATION = True

# Relaxed security for staging
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=False, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=False, cast=bool)

# Staging email backend
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

# Enhanced logging for staging
LOGGING["handlers"]["console"]["level"] = "DEBUG"
LOGGING["loggers"]["django_twilio_call"]["level"] = "DEBUG"
LOGGING["loggers"]["silk"] = {
    "handlers": ["console", "file"],
    "level": "INFO",
    "propagate": False,
}

# Twilio webhook validation (configurable for staging)
TWILIO_WEBHOOK_VALIDATE = config("TWILIO_WEBHOOK_VALIDATE", default=True, cast=bool)

# Staging-specific Django-Twilio-Call settings
DJANGO_TWILIO_CALL.update({
    "RECORDING_ENABLED": config("RECORDING_ENABLED", default=True, cast=bool),
    "ANALYTICS_ENABLED": True,
    "REAL_TIME_METRICS": True,
})

# DRF browsable API in staging
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# Relaxed rate limiting for staging
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update({
    "burst": "120/min",
    "sustained": "2000/hour",
})

# Staging environment identifier
ENVIRONMENT = "staging"

# Sentry configuration for staging (separate project)
if config("SENTRY_DSN", default=None):
    sentry_sdk.init(
        dsn=config("SENTRY_DSN"),
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
        ],
        traces_sample_rate=1.0,  # 100% tracing in staging
        send_default_pii=True,   # More detailed debugging info
        environment="staging",
        release=config("GIT_SHA", default="unknown"),
    )

# Performance monitoring in staging
DATABASES["default"]["CONN_MAX_AGE"] = 60  # Shorter for staging

# Staging-specific static files configuration
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Test data configuration
FIXTURE_DIRS = [BASE_DIR / "fixtures"]

# Allow CORS for staging frontend testing
CORS_ALLOW_ALL_ORIGINS = config("CORS_ALLOW_ALL_ORIGINS", default=True, cast=bool)
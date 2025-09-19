"""
Development settings for Django-Twilio-Call project.
Settings optimized for local development.
"""

from .base import *
from decouple import config

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Allow all hosts for development
ALLOWED_HOSTS = ["*"]

# Database
# Use SQLite for local development if PostgreSQL not available
if config("USE_SQLITE", default=False, cast=bool):
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }

# Development-specific apps
INSTALLED_APPS += [
    "debug_toolbar",
    "django_extensions",
]

# Development middleware
MIDDLEWARE += [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
]

# Debug toolbar configuration
INTERNAL_IPS = ["127.0.0.1", "localhost"]
DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG,
}

# Email backend for development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Disable security features for development
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0

# Cache fallback for development
if not config("REDIS_URL", default=None):
    CACHES["default"] = {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }

# Twilio webhook validation (disabled for development)
TWILIO_WEBHOOK_VALIDATE = False

# Logging configuration for development
LOGGING["handlers"]["console"]["level"] = "DEBUG"
LOGGING["loggers"]["django_twilio_call"]["level"] = "DEBUG"

# Celery configuration for development
CELERY_TASK_ALWAYS_EAGER = config("CELERY_ALWAYS_EAGER", default=False, cast=bool)
CELERY_TASK_EAGER_PROPAGATES = True

# Development environment overrides
DJANGO_TWILIO_CALL.update({
    "RECORDING_ENABLED": config("RECORDING_ENABLED", default=False, cast=bool),
    "ANALYTICS_ENABLED": True,
    "REAL_TIME_METRICS": True,
})

# DRF browsable API in development
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# CORS - allow all origins in development
CORS_ALLOW_ALL_ORIGINS = True

# Additional development settings
SHELL_PLUS_PRINT_SQL = True
RUNSERVER_PLUS_POLLER_ENABLED = True

# Development performance settings
DATABASES["default"]["OPTIONS"].update({
    "autocommit": True,
})

# Disable migrations for faster tests in development
if config("DISABLE_MIGRATIONS", default=False, cast=bool):
    class DisableMigrations:
        def __contains__(self, item):
            return True

        def __getitem__(self, item):
            return None

    MIGRATION_MODULES = DisableMigrations()

# Development file upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
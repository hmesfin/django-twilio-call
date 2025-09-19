"""
Testing settings for Django-Twilio-Call project.
Settings optimized for running tests.
"""

from .base import *
import tempfile

# Testing mode
DEBUG = False
TESTING = True

# Use in-memory SQLite for faster tests
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "OPTIONS": {
            "timeout": 20,
        },
    }
}

# Use dummy cache for tests
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }
}

# Use dummy email backend
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"

# Disable migrations for faster tests
class DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None

MIGRATION_MODULES = DisableMigrations()

# Password hasher for faster tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Celery configuration for tests
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# Disable security features for tests
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0

# Logging configuration for tests
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "CRITICAL",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "CRITICAL",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "CRITICAL",
            "propagate": False,
        },
        "django_twilio_call": {
            "handlers": ["console"],
            "level": "CRITICAL",
            "propagate": False,
        },
    },
}

# Twilio test configuration
TWILIO_WEBHOOK_VALIDATE = False
TWILIO_ACCOUNT_SID = "test_account_sid"
TWILIO_AUTH_TOKEN = "test_auth_token"
TWILIO_PHONE_NUMBER = "+15551234567"
TWILIO_WEBHOOK_BASE_URL = "http://testserver"

# Django-Twilio-Call test configuration
DJANGO_TWILIO_CALL.update({
    "RECORDING_ENABLED": False,
    "ANALYTICS_ENABLED": False,
    "REAL_TIME_METRICS": False,
})

# Media files for tests
MEDIA_ROOT = tempfile.mkdtemp()

# Static files for tests
STATIC_ROOT = tempfile.mkdtemp()

# Test file upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 1048576  # 1MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 1048576  # 1MB

# Disable throttling for tests
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {}

# Test secret key
SECRET_KEY = "test-secret-key-not-for-production"

# Test allowed hosts
ALLOWED_HOSTS = ["*"]

# Disable CORS for tests
CORS_ALLOW_ALL_ORIGINS = True

# Health check configuration for tests
HEALTH_CHECK = {
    'DISK_USAGE_MAX': 100,
    'MEMORY_MIN': 0,
}

# Test storage configuration
RECORDING_STORAGE_BACKEND = "django.core.files.storage.FileSystemStorage"
RECORDING_LOCAL_PATH = MEDIA_ROOT / "recordings"

# Fast test settings
USE_TZ = False  # Faster without timezone support in tests
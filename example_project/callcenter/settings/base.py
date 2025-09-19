"""
Base Django settings for Django-Twilio-Call project.
Common settings shared across all environments.
"""

import os
from pathlib import Path
from decouple import config
import environ

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Environment variables
env = environ.Env()

# Security
SECRET_KEY = config("SECRET_KEY")
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",")

# Encryption key for sensitive data
ENCRYPTION_KEY = config("ENCRYPTION_KEY", default=None)

# Application definition
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "django_celery_beat",
    "django_celery_results",
    "storages",
    "health_check",
    "health_check.db",
    "health_check.cache",
    "health_check.storage",
    "health_check.contrib.celery",
    "health_check.contrib.redis",
]

LOCAL_APPS = [
    "django_twilio_call",
    "apps.dashboard",
    "apps.analytics",
    "apps.webhooks",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django_twilio_call.security.SecurityHeadersMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_twilio_call.security.AuditLoggingMiddleware",
    "django_ratelimit.middleware.RatelimitMiddleware",
]

ROOT_URLCONF = "callcenter.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "callcenter.wsgi.application"

# Database base configuration
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="callcenter"),
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# JWT Configuration
from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": None,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "USER_AUTHENTICATION_RULE": "rest_framework_simplejwt.authentication.default_user_authentication_rule",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(minutes=15),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=1),
}

# JWT Security settings
JWT_BIND_TO_IP = config("JWT_BIND_TO_IP", default=False, cast=bool)
JWT_REQUIRED_SCOPE = config("JWT_REQUIRED_SCOPE", default=None)

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Media files
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ============================================
# Django-Twilio-Call Configuration
# ============================================

# Required Twilio Settings
TWILIO_ACCOUNT_SID = config("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = config("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = config("TWILIO_PHONE_NUMBER")
TWILIO_WEBHOOK_BASE_URL = config("TWILIO_WEBHOOK_BASE_URL")

# Optional Twilio Settings
TWILIO_WEBHOOK_VALIDATE = config("TWILIO_WEBHOOK_VALIDATE", default=True, cast=bool)
TWILIO_REGION = config("TWILIO_REGION", default=None)
TWILIO_EDGE = config("TWILIO_EDGE", default=None)

# Django-Twilio-Call Features
DJANGO_TWILIO_CALL = {
    # Queue Configuration
    "DEFAULT_QUEUE": config("DEFAULT_QUEUE", default="support"),
    "DEFAULT_QUEUE_TIMEOUT": 300,
    "DEFAULT_QUEUE_SIZE": 50,
    # Agent Configuration
    "DEFAULT_AGENT_TIMEOUT": 30,
    "MAX_CONCURRENT_CALLS": 1,
    # Call Configuration
    "RECORDING_ENABLED": config("RECORDING_ENABLED", default=True, cast=bool),
    "RECORDING_STORAGE": config("RECORDING_STORAGE", default="s3"),
    "VOICEMAIL_ENABLED": True,
    "CALLBACK_ENABLED": True,
    # IVR Configuration
    "IVR_ENABLED": True,
    "IVR_DEFAULT_VOICE": "Polly.Matthew",
    "IVR_DEFAULT_LANGUAGE": "en-US",
    # Analytics
    "ANALYTICS_ENABLED": True,
    "REAL_TIME_METRICS": True,
    # Business Hours (Eastern Time)
    "BUSINESS_HOURS": {
        "monday": {"start": "09:00", "end": "17:00"},
        "tuesday": {"start": "09:00", "end": "17:00"},
        "wednesday": {"start": "09:00", "end": "17:00"},
        "thursday": {"start": "09:00", "end": "17:00"},
        "friday": {"start": "09:00", "end": "17:00"},
        "saturday": None,
        "sunday": None,
    },
}

# ============================================
# REST Framework Configuration
# ============================================

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "django_twilio_call.security.EnhancedJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "django_twilio_call.security.IsOwnerOrAdmin",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "django_twilio_call.security.BurstRateThrottle",
        "django_twilio_call.security.SustainedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "burst": "60/min",
        "sustained": "1000/hour",
        "call_api": "100/hour",
        "webhook": "1000/min",
        "strict": "10/hour",
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "EXCEPTION_HANDLER": "django_twilio_call.error_handling.custom_exception_handler",
}

# Spectacular Settings for API Documentation
SPECTACULAR_SETTINGS = {
    "TITLE": "Django-Twilio-Call API",
    "DESCRIPTION": "Call center API using django-twilio-call package",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ============================================
# Cache Configuration
# ============================================

REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "CONNECTION_POOL_KWARGS": {
                "max_connections": 50,
                "retry_on_timeout": True,
            },
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
        },
        "KEY_PREFIX": "callcenter",
        "TIMEOUT": 300,
    }
}

# ============================================
# Celery Configuration
# ============================================

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_WORKER_LOG_FORMAT = "[%(asctime)s: %(levelname)s/%(processName)s] %(message)s"
CELERY_WORKER_TASK_LOG_FORMAT = "[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s"

# Celery Beat Schedule
CELERY_BEAT_SCHEDULE = {
    "cleanup-old-recordings": {
        "task": "django_twilio_call.tasks.cleanup_old_recordings",
        "schedule": 86400.0,  # Daily
    },
    "generate-daily-report": {
        "task": "apps.analytics.tasks.generate_daily_report",
        "schedule": 86400.0,  # Daily at midnight
    },
}

# ============================================
# Storage Configuration
# ============================================

if config("RECORDING_STORAGE", default="s3") == "s3":
    # AWS S3 Configuration
    AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", default=None)
    AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default=None)
    AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME", default="callcenter-recordings")
    AWS_S3_REGION_NAME = config("AWS_S3_REGION_NAME", default="us-east-1")
    AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}
    AWS_DEFAULT_ACL = "private"
    AWS_S3_ENCRYPTION = "AES256"
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    RECORDING_STORAGE_BACKEND = "storages.backends.s3boto3.S3Boto3Storage"
else:
    # Local file storage
    RECORDING_STORAGE_BACKEND = "django.core.files.storage.FileSystemStorage"
    RECORDING_LOCAL_PATH = MEDIA_ROOT / "recordings"

# ============================================
# CORS Configuration
# ============================================

CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="http://localhost:3000,http://localhost:8080").split(",")
CORS_ALLOW_CREDENTIALS = True
CORS_PREFLIGHT_MAX_AGE = 86400

# ============================================
# Session Security Configuration
# ============================================

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'
SESSION_COOKIE_AGE = 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

# CSRF Protection
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="http://localhost:8000,http://localhost:3000").split(",")
CSRF_USE_SESSIONS = True

# Security Headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# ============================================
# Health Check Configuration
# ============================================

HEALTH_CHECK = {
    'DISK_USAGE_MAX': 90,  # percent
    'MEMORY_MIN': 100,    # MB
}

# ============================================
# Logging Configuration Base
# ============================================

# Create logs directory if it doesn't exist
(BASE_DIR / "logs").mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
        "json": {
            "()": "django_structlog.formatters.JSONFormatter",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "django.log",
            "maxBytes": 1024 * 1024 * 15,  # 15MB
            "backupCount": 10,
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "django_twilio_call": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
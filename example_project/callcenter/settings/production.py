"""
Production settings for Django-Twilio-Call project.
Settings optimized for production deployment.
"""

from .base import *
from decouple import config
import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

# Production apps
INSTALLED_APPS += [
    "django_prometheus",
]

# Production middleware
MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
] + MIDDLEWARE + [
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

# Database configuration with connection pooling
DATABASES["default"].update({
    "CONN_MAX_AGE": 300,  # 5 minutes
    "OPTIONS": {
        "connect_timeout": 10,
        "options": "-c default_transaction_isolation=serializable"
    },
})

# Use connection pooling for better performance
DATABASES["default"]["ENGINE"] = "django_db_connection_pool.backends.postgresql"
DATABASES["default"]["POOL_OPTIONS"] = {
    "POOL_SIZE": 20,
    "MAX_OVERFLOW": 0,
    "RECYCLE": 300,
    "PRE_PING": True,
}

# Enhanced cache configuration for production
CACHES["default"]["OPTIONS"]["CONNECTION_POOL_KWARGS"].update({
    "max_connections": 100,
    "retry_on_timeout": True,
    "retry_on_error": [ConnectionError, TimeoutError],
})

# Session configuration for production
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_AGE = 3600  # 1 hour
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# CSRF configuration for production
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS").split(",")

# Security settings for production
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

# Additional security headers
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Email configuration for production
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@example.com")
SERVER_EMAIL = config("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)

# Logging configuration for production
LOGGING["handlers"].update({
    "file": {
        "level": "INFO",
        "class": "logging.handlers.RotatingFileHandler",
        "filename": "/var/log/django/django.log",
        "maxBytes": 1024 * 1024 * 50,  # 50MB
        "backupCount": 10,
        "formatter": "json",
    },
    "error_file": {
        "level": "ERROR",
        "class": "logging.handlers.RotatingFileHandler",
        "filename": "/var/log/django/error.log",
        "maxBytes": 1024 * 1024 * 50,  # 50MB
        "backupCount": 10,
        "formatter": "json",
    },
    "security_file": {
        "level": "INFO",
        "class": "logging.handlers.RotatingFileHandler",
        "filename": "/var/log/django/security.log",
        "maxBytes": 1024 * 1024 * 50,  # 50MB
        "backupCount": 10,
        "formatter": "json",
    },
})

LOGGING["loggers"].update({
    "django.security": {
        "handlers": ["security_file", "console"],
        "level": "INFO",
        "propagate": False,
    },
    "django.request": {
        "handlers": ["error_file", "console"],
        "level": "ERROR",
        "propagate": False,
    },
    "celery": {
        "handlers": ["file", "console"],
        "level": "INFO",
        "propagate": False,
    },
})

# Celery configuration for production
CELERY_WORKER_CONCURRENCY = config("CELERY_WORKER_CONCURRENCY", default=4, cast=int)
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000
CELERY_WORKER_DISABLE_RATE_LIMITS = False
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_REJECT_ON_WORKER_LOST = True

# Celery monitoring
CELERY_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True

# Django-Twilio-Call production configuration
DJANGO_TWILIO_CALL.update({
    "RECORDING_ENABLED": True,
    "ANALYTICS_ENABLED": True,
    "REAL_TIME_METRICS": True,
})

# File upload limits for production
FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB
FILE_UPLOAD_PERMISSIONS = 0o644

# Static files optimization
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = False

# ============================================
# Monitoring & Observability
# ============================================

# Sentry configuration
if config("SENTRY_DSN", default=None):
    sentry_sdk.init(
        dsn=config("SENTRY_DSN"),
        integrations=[
            DjangoIntegration(
                transaction_style="url",
                middleware_spans=True,
                signals_spans=True,
                cache_spans=True,
            ),
            CeleryIntegration(
                monitor_beat_tasks=True,
                propagate_traces=True,
            ),
            RedisIntegration(),
        ],
        traces_sample_rate=config("SENTRY_TRACES_SAMPLE_RATE", default=0.1, cast=float),
        profiles_sample_rate=config("SENTRY_PROFILES_SAMPLE_RATE", default=0.1, cast=float),
        send_default_pii=False,
        environment=config("ENVIRONMENT", default="production"),
        release=config("GIT_SHA", default="unknown"),
        before_send=lambda event, hint: event if not DEBUG else None,
    )

# Health check configuration
HEALTH_CHECK = {
    "DISK_USAGE_MAX": 90,
    "MEMORY_MIN": 100,
}

# ============================================
# Performance Optimizations
# ============================================

# Database query optimization
DATABASES["default"]["OPTIONS"].update({
    "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
    "charset": "utf8mb4",
})

# Template optimization
TEMPLATES[0]["OPTIONS"]["loaders"] = [
    (
        "django.template.loaders.cached.Loader",
        [
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ],
    ),
]

# ============================================
# Security Enhancements
# ============================================

# Additional security middleware for production
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "django_twilio_call.security.SecurityHeadersMiddleware",
)

# Rate limiting configuration
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = "default"

# CORS configuration for production
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="").split(",")

# Content Security Policy
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")
CSP_IMG_SRC = ("'self'", "data:", "https:")
CSP_FONT_SRC = ("'self'",)
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_SRC = ("'none'",)

# Data retention settings
DATA_RETENTION_DAYS = config("DATA_RETENTION_DAYS", default=365, cast=int)

# Backup configuration
BACKUP_ENABLED = config("BACKUP_ENABLED", default=True, cast=bool)
BACKUP_STORAGE = config("BACKUP_STORAGE", default="s3")

# ============================================
# Third-party Services
# ============================================

# AWS Configuration for production
if config("USE_AWS", default=True, cast=bool):
    AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = config("AWS_S3_REGION_NAME", default="us-east-1")

    # CloudFront configuration
    AWS_S3_CUSTOM_DOMAIN = config("AWS_CLOUDFRONT_DOMAIN", default=None)
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }

    # S3 security settings
    AWS_DEFAULT_ACL = None
    AWS_S3_ENCRYPTION = True
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_VERIFY = True

# Production environment checks
if not ENCRYPTION_KEY:
    raise ImproperlyConfigured("ENCRYPTION_KEY is required in production")

if not config("SECRET_KEY", default=None):
    raise ImproperlyConfigured("SECRET_KEY is required in production")

if not config("TWILIO_ACCOUNT_SID", default=None):
    raise ImproperlyConfigured("TWILIO_ACCOUNT_SID is required in production")

if not config("TWILIO_AUTH_TOKEN", default=None):
    raise ImproperlyConfigured("TWILIO_AUTH_TOKEN is required in production")
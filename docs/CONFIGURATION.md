# Configuration Reference

This document contains every configuration option available in django-twilio-call. If you're setting this up for the first time, start with the required settings, then add optional ones as needed.

## Table of Contents

1. [Required Settings](#required-settings)
2. [Optional Settings](#optional-settings)
3. [Model Configuration](#model-configuration)
4. [Service Configuration](#service-configuration)
5. [Webhook Configuration](#webhook-configuration)
6. [Storage Configuration](#storage-configuration)
7. [Caching Configuration](#caching-configuration)
8. [Advanced Settings](#advanced-settings)

## Required Settings

These settings MUST be configured for the library to function.

### TWILIO_ACCOUNT_SID

- **Type**: `str`
- **Required**: Yes
- **Description**: Your Twilio Account SID
- **Where to find**: [Twilio Console](https://console.twilio.com) → Dashboard
- **Example**: `'ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'`
- **Security**: Never commit this to version control

```python
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
```

### TWILIO_AUTH_TOKEN

- **Type**: `str`
- **Required**: Yes
- **Description**: Your Twilio Auth Token
- **Where to find**: [Twilio Console](https://console.twilio.com) → Dashboard
- **Example**: `'your_auth_token_here'`
- **Security**: MUST be kept secret, use environment variables

```python
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
```

### TWILIO_PHONE_NUMBER

- **Type**: `str`
- **Required**: Yes
- **Description**: Default Twilio phone number for outbound calls
- **Format**: E.164 format (`+1234567890`)
- **Example**: `'+14155551234'`
- **Note**: Must be a number you own in Twilio

```python
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '+14155551234')
```

### TWILIO_WEBHOOK_BASE_URL

- **Type**: `str`
- **Required**: Yes
- **Description**: Base URL where your application is hosted
- **Format**: Full URL without trailing slash
- **Example**: `'https://api.example.com'`
- **Note**: Must be publicly accessible for webhooks

```python
TWILIO_WEBHOOK_BASE_URL = os.environ.get('BASE_URL', 'https://api.example.com')
```

## Optional Settings

### TWILIO_WEBHOOK_VALIDATE

- **Type**: `bool`
- **Default**: `True`
- **Description**: Enable Twilio webhook signature validation
- **When to disable**: Local development, testing
- **Security**: Always enable in production

```python
TWILIO_WEBHOOK_VALIDATE = not DEBUG  # Disable in development
```

### TWILIO_REGION

- **Type**: `str`
- **Default**: `None` (uses default region)
- **Description**: Twilio region for API calls
- **Options**: `'sydney'`, `'dublin'`, `'singapore'`, `'tokyo'`, `'sao-paulo'`
- **When to use**: For latency optimization

```python
TWILIO_REGION = 'dublin'  # For EU customers
```

### TWILIO_EDGE

- **Type**: `str`
- **Default**: `None`
- **Description**: Twilio edge location
- **Options**: `'sydney'`, `'dublin'`, `'singapore'`, `'tokyo'`, `'sao-paulo'`

```python
TWILIO_EDGE = 'dublin'
```

### TWILIO_SUBACCOUNT_SID

- **Type**: `str`
- **Default**: `None`
- **Description**: Use a subaccount for isolation
- **When to use**: Multi-tenant applications

```python
TWILIO_SUBACCOUNT_SID = os.environ.get('TWILIO_SUBACCOUNT_SID')
```

## Model Configuration

### Queue Settings

```python
DJANGO_TWILIO_CALL_QUEUE = {
    'DEFAULT_NAME': 'support',
    'DEFAULT_PRIORITY': 5,
    'DEFAULT_MAX_SIZE': 100,
    'DEFAULT_MAX_WAIT_TIME': 300,  # seconds
    'DEFAULT_SERVICE_LEVEL_THRESHOLD': 20,  # seconds
    'DEFAULT_ROUTING_STRATEGY': 'round_robin',  # Options: fifo, lifo, round_robin, least_busy, skills_based
    'ENABLE_OVERFLOW': True,
    'OVERFLOW_THRESHOLD': 80,  # percentage
}
```

### Agent Settings

```python
DJANGO_TWILIO_CALL_AGENT = {
    'DEFAULT_STATUS': 'offline',  # Options: available, busy, offline, on_break
    'MAX_CONCURRENT_CALLS': 1,
    'AUTO_LOGOUT_HOURS': 12,  # Auto-logout after X hours
    'BREAK_TYPES': [
        ('lunch', 'Lunch Break'),
        ('short', 'Short Break'),
        ('training', 'Training'),
    ],
    'SKILL_CATEGORIES': [
        'language',
        'technical',
        'product',
        'priority',
    ],
}
```

### Call Settings

```python
DJANGO_TWILIO_CALL_CALL = {
    'DEFAULT_TIMEOUT': 30,  # Ring timeout in seconds
    'MAX_DURATION': 7200,  # Maximum call duration in seconds (2 hours)
    'WHISPER_ENABLED': True,  # Play message to agent before connecting
    'VOICEMAIL_ENABLED': True,
    'VOICEMAIL_MAX_LENGTH': 300,  # seconds
    'CALLBACK_ENABLED': True,
    'CALLBACK_WINDOW': 48,  # hours
}
```

## Service Configuration

### IVR Service

```python
DJANGO_TWILIO_CALL_IVR = {
    'DEFAULT_LANGUAGE': 'en-US',
    'DEFAULT_VOICE': 'Polly.Matthew',  # Twilio voice
    'SUPPORTED_LANGUAGES': [
        ('en-US', 'English'),
        ('es-ES', 'Spanish'),
        ('fr-FR', 'French'),
    ],
    'DIGIT_TIMEOUT': 5,  # seconds to wait for digit input
    'MAX_RETRIES': 3,  # Max retries for invalid input
    'BUSINESS_HOURS': {
        'monday': {'start': '09:00', 'end': '17:00'},
        'tuesday': {'start': '09:00', 'end': '17:00'},
        'wednesday': {'start': '09:00', 'end': '17:00'},
        'thursday': {'start': '09:00', 'end': '17:00'},
        'friday': {'start': '09:00', 'end': '17:00'},
        'saturday': None,  # Closed
        'sunday': None,  # Closed
    },
    'TIMEZONE': 'America/New_York',
}
```

### Recording Service

```python
DJANGO_TWILIO_CALL_RECORDING = {
    'ENABLED': True,
    'AUTOMATIC': False,  # Auto-record all calls
    'STORAGE_BACKEND': 's3',  # Options: 's3', 'local', 'azure'
    'RETENTION_DAYS': 90,  # Auto-delete after X days
    'FORMAT': 'mp3',  # Options: mp3, wav
    'CHANNELS': 'dual',  # Options: mono, dual
    'TRANSCRIPTION_ENABLED': False,
    'TRANSCRIPTION_SERVICE': 'aws',  # Options: aws, assemblyai, twilio
    'COMPLIANCE': {
        'PCI_DSS': True,  # Enable pause/resume for sensitive data
        'GDPR': True,  # Enable right-to-erasure
        'ENCRYPTION': True,  # Encrypt recordings at rest
    },
}
```

### Conference Service

```python
DJANGO_TWILIO_CALL_CONFERENCE = {
    'MAX_PARTICIPANTS': 250,
    'RECORD_BY_DEFAULT': False,
    'WAIT_URL': '/static/hold_music.mp3',
    'WAIT_METHOD': 'GET',
    'START_ON_ENTER': True,
    'END_ON_EXIT': False,
    'BEEP_ON_ENTER': True,
    'MUTED_ON_ENTRY': False,
    'COACH_MODE_ENABLED': True,
}
```

### Analytics Service

```python
DJANGO_TWILIO_CALL_ANALYTICS = {
    'CACHE_TIMEOUT': 300,  # seconds
    'REAL_TIME_CACHE': 10,  # seconds for real-time metrics
    'DEFAULT_DATE_RANGE': 30,  # days
    'ENABLE_PREDICTIVE': False,  # Enable ML predictions
    'TRACK_CUSTOM_METRICS': True,
}
```

## Webhook Configuration

```python
DJANGO_TWILIO_CALL_WEBHOOKS = {
    'VOICE_PATH': '/webhooks/voice/',
    'STATUS_PATH': '/webhooks/status/',
    'RECORDING_PATH': '/webhooks/recording/',
    'VALIDATE_SIGNATURE': True,
    'ALLOWED_HOSTS': [  # Additional webhook source validation
        'api.twilio.com',
        'eventgrid.twilio.com',
    ],
    'RETRY_FAILED': True,
    'MAX_RETRIES': 3,
    'TIMEOUT': 15,  # seconds
}
```

## Storage Configuration

### Local Storage

```python
DJANGO_TWILIO_CALL_STORAGE = {
    'BACKEND': 'local',
    'LOCAL_PATH': '/var/recordings',
    'LOCAL_URL': '/media/recordings/',
    'PERMISSIONS': 0o644,
    'DIRECTORY_PERMISSIONS': 0o755,
}
```

### S3 Storage

```python
DJANGO_TWILIO_CALL_STORAGE = {
    'BACKEND': 's3',
    'AWS_ACCESS_KEY_ID': os.environ.get('AWS_ACCESS_KEY_ID'),
    'AWS_SECRET_ACCESS_KEY': os.environ.get('AWS_SECRET_ACCESS_KEY'),
    'AWS_STORAGE_BUCKET_NAME': 'my-recordings-bucket',
    'AWS_S3_REGION_NAME': 'us-east-1',
    'AWS_S3_ENCRYPTION': 'AES256',
    'AWS_S3_SIGNATURE_VERSION': 's3v4',
    'AWS_S3_FILE_OVERWRITE': False,
    'AWS_DEFAULT_ACL': 'private',
    'AWS_PRESIGNED_EXPIRY': 3600,  # seconds
}
```

### Azure Storage

```python
DJANGO_TWILIO_CALL_STORAGE = {
    'BACKEND': 'azure',
    'AZURE_ACCOUNT_NAME': 'mystorageaccount',
    'AZURE_ACCOUNT_KEY': os.environ.get('AZURE_ACCOUNT_KEY'),
    'AZURE_CONTAINER': 'recordings',
    'AZURE_SSL': True,
    'AZURE_UPLOAD_MAX_CONN': 2,
    'AZURE_CONNECTION_TIMEOUT': 20,
}
```

## Caching Configuration

### Redis Cache (Recommended)

```python
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'retry_on_timeout': True,
            },
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
            'IGNORE_EXCEPTIONS': True,  # Continue if cache is down
        },
        'KEY_PREFIX': 'twilio_call',
    }
}

# Cache key patterns
DJANGO_TWILIO_CALL_CACHE_KEYS = {
    'QUEUE_METRICS': 'queue:metrics:{queue_id}',
    'AGENT_STATUS': 'agent:status:{agent_id}',
    'CALL_ANALYTICS': 'analytics:calls:{date_range}',
    'REAL_TIME': 'metrics:realtime',
}
```

### Memcached Alternative

```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
        'LOCATION': '127.0.0.1:11211',
        'OPTIONS': {
            'no_delay': True,
            'ignore_exc': True,
            'max_pool_size': 4,
            'use_pooling': True,
        }
    }
}
```

## Advanced Settings

### Rate Limiting

```python
DJANGO_TWILIO_CALL_RATE_LIMIT = {
    'ENABLED': True,
    'DEFAULT_RATE': '100/hour',
    'BURST_RATE': '10/minute',
    'WEBHOOK_RATE': '1000/minute',  # Higher for webhooks
    'PER_IP': True,
    'PER_USER': True,
}
```

### Monitoring and Alerting

```python
DJANGO_TWILIO_CALL_MONITORING = {
    'SENTRY_DSN': os.environ.get('SENTRY_DSN'),
    'SENTRY_ENVIRONMENT': os.environ.get('ENVIRONMENT', 'development'),
    'ENABLE_METRICS': True,
    'METRICS_BACKEND': 'statsd',  # Options: statsd, prometheus, datadog
    'STATSD_HOST': 'localhost',
    'STATSD_PORT': 8125,
    'STATSD_PREFIX': 'twilio_call',
}
```

### Security Settings

```python
DJANGO_TWILIO_CALL_SECURITY = {
    'ENCRYPT_SENSITIVE_DATA': True,
    'ENCRYPTION_KEY': os.environ.get('ENCRYPTION_KEY'),
    'MASK_PHONE_NUMBERS': True,  # In logs
    'AUDIT_LOG_ENABLED': True,
    'AUDIT_LOG_RETENTION': 365,  # days
    'IP_WHITELIST': [],  # Restrict webhook access
    'REQUIRE_HTTPS': True,
}
```

### Performance Tuning

```python
DJANGO_TWILIO_CALL_PERFORMANCE = {
    'CONNECTION_POOLING': {
        'ENABLED': True,
        'MAX_SIZE': 10,
        'MIN_SIZE': 2,
        'TIMEOUT': 30,
    },
    'DATABASE_OPTIMIZATION': {
        'USE_SELECT_RELATED': True,
        'USE_PREFETCH_RELATED': True,
        'BATCH_SIZE': 100,
    },
    'ASYNC_TASKS': {
        'USE_CELERY': True,
        'TASK_TIME_LIMIT': 300,  # seconds
        'TASK_SOFT_TIME_LIMIT': 240,
    },
}
```

### Feature Flags

```python
DJANGO_TWILIO_CALL_FEATURES = {
    'BETA_FEATURES': False,
    'WEBSOCKET_SUPPORT': True,
    'GRAPHQL_API': False,
    'MULTI_TENANT': False,
    'ADVANCED_ANALYTICS': True,
    'AI_ROUTING': False,
    'SENTIMENT_ANALYSIS': False,
}
```

## Environment-Specific Configuration

### Development

```python
if DEBUG:
    DJANGO_TWILIO_CALL = {
        **DJANGO_TWILIO_CALL,
        'TWILIO_WEBHOOK_VALIDATE': False,
        'USE_NGROK': True,
        'MOCK_TWILIO': True,  # Use mocks instead of real API
        'VERBOSE_LOGGING': True,
    }
```

### Staging

```python
if ENVIRONMENT == 'staging':
    DJANGO_TWILIO_CALL = {
        **DJANGO_TWILIO_CALL,
        'TWILIO_WEBHOOK_VALIDATE': True,
        'USE_SANDBOX': True,
        'ALERT_ON_ERROR': False,
    }
```

### Production

```python
if ENVIRONMENT == 'production':
    DJANGO_TWILIO_CALL = {
        **DJANGO_TWILIO_CALL,
        'TWILIO_WEBHOOK_VALIDATE': True,
        'HIGH_AVAILABILITY': True,
        'AUTO_SCALING': True,
        'ALERT_ON_ERROR': True,
        'BACKUP_ENABLED': True,
    }
```

## Complete Example Configuration

```python
# settings.py

import os
from pathlib import Path

# Core Django settings
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get('SECRET_KEY')
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')

# Required Twilio settings
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')
TWILIO_WEBHOOK_BASE_URL = os.environ.get('BASE_URL')

# Django-Twilio-Call configuration
DJANGO_TWILIO_CALL = {
    # Core settings
    'WEBHOOK_VALIDATE': not DEBUG,
    'DEFAULT_QUEUE': 'support',
    'DEFAULT_TIMEOUT': 30,

    # Features
    'RECORDING_ENABLED': True,
    'RECORDING_STORAGE': os.environ.get('RECORDING_STORAGE', 's3'),
    'IVR_ENABLED': True,
    'ANALYTICS_ENABLED': True,

    # Performance
    'USE_CACHE': True,
    'CACHE_TIMEOUT': 300,
    'CONNECTION_POOL_SIZE': 10,

    # Security
    'ENCRYPT_RECORDINGS': True,
    'AUDIT_LOGGING': True,
    'RATE_LIMITING': True,
}

# Cache configuration
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Storage configuration
if DJANGO_TWILIO_CALL['RECORDING_STORAGE'] == 's3':
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.environ.get('AWS_REGION', 'us-east-1')

# Celery configuration
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']

# Monitoring
if not DEBUG:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=os.environ.get('SENTRY_DSN'),
        integrations=[DjangoIntegration()],
        environment=os.environ.get('ENVIRONMENT', 'production'),
    )
```

## Validation

To validate your configuration:

```python
python manage.py django_twilio_call_check_config
```

This command will check:

- Required settings are present
- Twilio credentials are valid
- Phone numbers are in correct format
- Webhook URLs are accessible
- Storage backend is configured
- Cache is working

## Migration from Other Systems

If migrating from another call center system:

```python
DJANGO_TWILIO_CALL_MIGRATION = {
    'IMPORT_EXISTING_CALLS': False,
    'MAP_AGENT_IDS': True,
    'PRESERVE_CALL_HISTORY': True,
    'MIGRATION_BATCH_SIZE': 100,
}
```

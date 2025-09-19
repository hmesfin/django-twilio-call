# Observability Integration Guide

This guide shows how to integrate the comprehensive observability system into your Django Twilio Call Center application.

## Quick Start

### 1. Update Django Settings

Add the observability configuration to your Django settings:

```python
# settings.py

# Add observability middleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # Add observability middleware
    'django_twilio_call.observability.middleware.performance.DatabaseQueryCountMiddleware',
    'django_twilio_call.observability.middleware.performance.PerformanceMonitoringMiddleware',
    'django_twilio_call.observability.middleware.business.BusinessMetricsMiddleware',
]

# Add observability app
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'django_twilio_call',
    'django_twilio_call.observability',  # Add this
]

# Observability configuration
OBSERVABILITY_CONFIG = {
    'enabled': True,
    'metrics': {
        'enabled': True,
        'export_interval': 30,
    },
    'tracing': {
        'enabled': True,
        'jaeger': {
            'enabled': True,
            'host': 'localhost',
            'port': 14268,
        }
    },
    'alerting': {
        'enabled': True,
        'email': {
            'enabled': True,
            'recipients': ['admin@yourcompany.com', 'ops@yourcompany.com'],
        },
        'slack': {
            'enabled': True,
            'webhook_url': 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK',
        },
        'pagerduty': {
            'enabled': True,
            'routing_key': 'your-pagerduty-routing-key',
        }
    }
}

# Update logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'django_twilio_call.observability.logging.formatters.StructuredJsonFormatter',
        },
        'call_center': {
            '()': 'django_twilio_call.observability.logging.formatters.CallCenterLogFormatter',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/django-twilio-call/app.log',
            'maxBytes': 50 * 1024 * 1024,
            'backupCount': 10,
            'formatter': 'json',
        },
        'call_center_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/django-twilio-call/call_center.log',
            'maxBytes': 100 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'json',
        },
    },
    'loggers': {
        'django_twilio_call': {
            'handlers': ['console', 'call_center_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django_twilio_call.observability': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
```

### 2. Update URL Configuration

Add observability URLs to your main URL configuration:

```python
# urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('django_twilio_call.urls')),
    path('observability/', include('django_twilio_call.observability.urls')),  # Add this
]
```

### 3. Install Required Dependencies

Add these to your requirements.txt:

```txt
prometheus-client>=0.14.0
python-json-logger>=2.0.0
opentelemetry-api>=1.15.0
opentelemetry-sdk>=1.15.0
opentelemetry-exporter-jaeger-thrift>=1.15.0
requests>=2.28.0
```

## Adding Observability to Existing Code

### Services Layer

Add observability to your service methods:

```python
# services/call_service.py
from django_twilio_call.observability.integration import (
    instrument_service_method,
    track_call_operation,
    track_twilio_api_call
)
from django_twilio_call.observability.config import get_call_center_logger

logger = get_call_center_logger(__name__)

class CallService:

    @instrument_service_method
    @track_call_operation('create_call')
    def create_call(self, from_number, to_number, queue_id=None):
        """Create a new outbound call."""
        with PerformanceTracker('create_call', queue_id=queue_id):
            # Your existing code
            pass

    @track_twilio_api_call('calls', 'POST')
    def initiate_twilio_call(self, call_data):
        """Initiate call through Twilio API."""
        # Your existing Twilio API call code
        pass
```

### Views Layer

Add observability to your views:

```python
# views.py
from django_twilio_call.observability.integration import (
    instrument_view,
    ObservabilityMixin
)

# Function-based views
@instrument_view
def call_status_webhook(request):
    """Handle Twilio call status webhook."""
    # Your existing code
    pass

# Class-based views
class CallViewSet(ObservabilityMixin, viewsets.ModelViewSet):
    """Call management viewset with observability."""
    # Your existing code
    pass
```

### Models Layer

Add observability to your models:

```python
# models.py
from django_twilio_call.observability.integration import monitor_model_save

@monitor_model_save
class Call(TimeStampedModel):
    """Call model with observability."""
    # Your existing model code
    pass
```

### Celery Tasks

Your Celery tasks automatically get monitoring through signals. For additional tracking:

```python
# tasks.py
from django_twilio_call.observability.config import get_call_center_logger
from django_twilio_call.observability.integration import PerformanceTracker

logger = get_call_center_logger(__name__)

@shared_task(bind=True)
def process_call_recording(self, call_id):
    """Process call recording with observability."""
    with PerformanceTracker('process_recording', call_id=call_id):
        try:
            # Your existing task code
            logger.log_task_execution(
                task_id=self.request.id,
                task_name='process_call_recording',
                status='success'
            )
        except Exception as e:
            logger.log_task_execution(
                task_id=self.request.id,
                task_name='process_call_recording',
                status='failure'
            )
            raise
```

## Available Endpoints

After integration, you'll have these monitoring endpoints:

- **Health Checks:**
  - `/observability/health/` - Basic health check
  - `/observability/health/detailed/` - Detailed component health
  - `/observability/health/ready/` - Kubernetes readiness probe
  - `/observability/health/live/` - Kubernetes liveness probe

- **Metrics:**
  - `/observability/metrics/` - Prometheus metrics endpoint
  - `/observability/metrics/summary/` - JSON metrics summary

## CLI Monitoring Tools

Use the provided CLI commands for monitoring:

```bash
# Real-time system monitoring
python manage.py monitor_system --continuous --interval 30

# Alert management
python manage.py monitor_alerts --list
python manage.py monitor_alerts --resolve alert_id_here
python manage.py monitor_alerts --statistics

# Task monitoring
python manage.py monitor_tasks --failed --since 1h
```

## Grafana Dashboard Setup

1. Import the dashboard configurations from:
   - `django_twilio_call/observability/dashboards/grafana_dashboards.json`

2. Configure Prometheus to scrape metrics from:
   - `http://your-app:8000/observability/metrics/`

3. Set up alerts in Grafana or use the built-in alerting system.

## Docker Configuration

Add monitoring to your docker-compose.yml:

```yaml
version: '3.8'
services:
  app:
    # Your app configuration
    environment:
      - OBSERVABILITY_ENABLED=true
    ports:
      - "8000:8000"
    volumes:
      - ./logs:/var/log/django-twilio-call

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

## Alerting Configuration

Configure alerts by setting environment variables or updating settings:

```python
# Alert thresholds can be customized
ALERT_CONFIG = {
    'thresholds': {
        'service_level_minimum': 80,
        'abandonment_rate_maximum': 10,
        'queue_depth_warning': 10,
        'queue_depth_critical': 20,
        'error_rate_maximum': 5,
    }
}
```

## Performance Impact

The observability system is designed to have minimal performance impact:

- Middleware adds ~1-2ms per request
- Metrics collection is non-blocking
- Structured logging uses efficient JSON serialization
- Health checks are cached appropriately

For high-traffic environments, you can:
- Adjust metrics collection intervals
- Use sampling for distributed tracing
- Configure log levels appropriately

## Troubleshooting

### Common Issues

1. **Metrics not appearing**: Check that middleware is properly installed and Prometheus endpoint is accessible.

2. **Alerts not firing**: Verify alert configuration and notification channel settings.

3. **High memory usage**: Adjust metrics retention and logging levels.

4. **Performance degradation**: Review middleware order and disable non-essential monitoring.

### Debug Mode

Enable debug logging for observability:

```python
LOGGING['loggers']['django_twilio_call.observability']['level'] = 'DEBUG'
```

This provides detailed information about metrics collection, alert evaluation, and system health checks.
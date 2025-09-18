# Django-Twilio-Call Integration Guide

## Table of Contents
1. [Quick Start](#quick-start)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Basic Setup](#basic-setup)
5. [Common Use Cases](#common-use-cases)
6. [Production Deployment](#production-deployment)
7. [Troubleshooting](#troubleshooting)

## Quick Start

If you're reading this with no context about what this library does - it's a Django package that provides a complete call center solution using Twilio's telephony APIs. Think of it as the backend for a customer service call center.

### What This Library Does
- **Handles incoming calls** from customers
- **Routes calls** to available agents based on skills and availability
- **Manages queues** with different routing strategies
- **Records calls** with compliance features (PCI, GDPR)
- **Provides analytics** on call center performance
- **Supports IVR** (Interactive Voice Response) menus

### What You Need
1. Django 4.2+ or 5.1 project
2. Twilio account (free trial works for testing)
3. PostgreSQL database (recommended for production)
4. Redis for caching (optional but recommended)

## Installation

### Step 1: Install the Package

```bash
pip install django-twilio-call
```

### Step 2: Add to Django Settings

```python
# settings.py

INSTALLED_APPS = [
    # ... your other apps
    'rest_framework',  # Required dependency
    'django_twilio_call',
    'drf_spectacular',  # For API documentation (optional)
]

# Add middleware (optional but recommended for API)
MIDDLEWARE = [
    # ... other middleware
    'django_twilio_call.middleware.WebhookValidationMiddleware',  # Validates Twilio webhooks
]
```

### Step 3: Database Migration

```bash
python manage.py migrate django_twilio_call
```

## Configuration

### Required Settings

```python
# settings.py

# Twilio Credentials (get from https://console.twilio.com)
TWILIO_ACCOUNT_SID = 'ACxxxxxxxxxxxxx'  # Your Account SID
TWILIO_AUTH_TOKEN = 'your_auth_token'    # Keep this secret!
TWILIO_PHONE_NUMBER = '+1234567890'      # Your Twilio phone number

# Webhook Configuration
TWILIO_WEBHOOK_BASE_URL = 'https://your-domain.com'  # Your public domain
TWILIO_WEBHOOK_VALIDATE = True  # Enable signature validation (recommended)

# Optional but Recommended
DJANGO_TWILIO_CALL = {
    'DEFAULT_QUEUE': 'support',  # Default queue for incoming calls
    'DEFAULT_TIMEOUT': 30,        # Default ring timeout in seconds
    'MAX_QUEUE_SIZE': 100,        # Maximum calls in a queue
    'RECORDING_ENABLED': True,    # Enable call recording
    'RECORDING_STORAGE': 's3',    # 's3' or 'local'
}
```

### Storage Configuration (for recordings)

```python
# For S3 storage
AWS_ACCESS_KEY_ID = 'your-access-key'
AWS_SECRET_ACCESS_KEY = 'your-secret-key'
AWS_STORAGE_BUCKET_NAME = 'your-bucket'
AWS_S3_REGION_NAME = 'us-east-1'

# For local storage
RECORDING_LOCAL_PATH = '/path/to/recordings'
```

### Caching Configuration

```python
# Using Redis (recommended)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'KEY_PREFIX': 'twilio_call',
        'TIMEOUT': 300,  # 5 minutes default
    }
}
```

## Basic Setup

### 1. URL Configuration

```python
# urls.py
from django.urls import path, include

urlpatterns = [
    # ... your other URLs
    path('api/', include('django_twilio_call.urls')),
]
```

This provides:
- `/api/v1/` - REST API endpoints
- `/api/v1/webhooks/` - Twilio webhook endpoints
- `/api/v1/docs/` - Swagger documentation (if drf-spectacular is installed)

### 2. Create Initial Data

```python
# In Django shell or management command
from django_twilio_call.models import Queue, Agent, PhoneNumber
from django.contrib.auth.models import User

# Create a queue
support_queue = Queue.objects.create(
    name='support',
    description='General support queue',
    priority=5,
    max_size=50,
    routing_strategy='round_robin'
)

# Create an agent
user = User.objects.create_user('agent1', 'agent1@example.com', 'password')
agent = Agent.objects.create(
    user=user,
    first_name='John',
    last_name='Doe',
    extension='1001',
    email='john.doe@example.com'
)
agent.queues.add(support_queue)

# Register your Twilio phone number
phone = PhoneNumber.objects.create(
    number='+1234567890',
    friendly_name='Main Support Line',
    twilio_sid='PNxxxxx'  # From Twilio console
)
```

### 3. Configure Twilio Webhooks

In your Twilio Console:

1. Go to Phone Numbers > Manage > Active Numbers
2. Click on your phone number
3. Set the webhook URLs:

```
Voice & Fax:
- WHEN A CALL COMES IN: https://your-domain.com/api/v1/webhooks/voice/
- METHOD: POST
- STATUS CALLBACK URL: https://your-domain.com/api/v1/webhooks/status/
```

## Common Use Cases

### Handling Incoming Calls

When a call comes in, the library:
1. Creates a Call record
2. Checks business hours (if configured)
3. Plays IVR menu (if configured)
4. Routes to appropriate queue
5. Finds available agent
6. Connects the call

```python
# Customize incoming call handling
from django_twilio_call.services import call_service

def handle_incoming_call(request):
    call_data = {
        'CallSid': request.POST['CallSid'],
        'From': request.POST['From'],
        'To': request.POST['To'],
    }

    # Library handles this automatically via webhook
    call = call_service.handle_incoming_call(call_data)

    # You can customize routing
    if '+1555' in call.from_number:
        call.queue_id = Queue.objects.get(name='vip').id
        call.save()
```

### Making Outbound Calls

```python
from django_twilio_call.services import call_service

# Simple outbound call
call = call_service.initiate_call(
    to_number='+1234567890',
    from_number='+0987654321'
)

# Assign to specific agent
call = call_service.initiate_call(
    to_number='+1234567890',
    from_number='+0987654321',
    agent_id=agent.id
)
```

### Managing Agent Status

```python
from django_twilio_call.services import agent_service

# Agent login/logout
agent_service.login(agent_id=1)
agent_service.logout(agent_id=1)

# Status changes
agent_service.set_available(agent_id=1)
agent_service.start_break(agent_id=1, reason='lunch')
agent_service.end_break(agent_id=1)
```

### Queue Management

```python
from django_twilio_call.services import queue_service

# Add call to queue
queue_service.add_call_to_queue(call, queue_id=1)

# Get queue statistics
stats = queue_service.get_queue_statistics(queue_id=1)
print(f"Calls waiting: {stats['calls_in_queue']}")
print(f"Avg wait time: {stats['avg_wait_time']}s")

# Route next call
queue_service.route_next_call(queue_id=1)
```

### IVR Configuration

```python
from django_twilio_call.services import ivr_service

# Create custom IVR flow
flow = ivr_service.create_flow('custom_menu')

# Add menu node
ivr_service.add_custom_node(
    flow_name='custom_menu',
    node_id='main_menu',
    node_type='menu',
    message='Press 1 for sales, 2 for support',
    options={'1': 'sales_queue', '2': 'support_queue'},
    is_start=True
)
```

### Recording Management

```python
from django_twilio_call.services import recording_service

# Start recording
recording_service.start_recording(call_id=1)

# Pause for sensitive info (PCI compliance)
recording_service.pause_recording(call_id=1)
recording_service.resume_recording(call_id=1)

# Stop recording
recording_service.stop_recording(call_id=1)

# Get recording URL
url = recording_service.get_recording_url(recording_id=1)
```

## Production Deployment

### 1. Environment Variables

```bash
# .env file
DJANGO_SECRET_KEY=your-secret-key
TWILIO_ACCOUNT_SID=ACxxxxx
TWILIO_AUTH_TOKEN=xxxxx
DATABASE_URL=postgresql://user:pass@localhost/dbname
REDIS_URL=redis://localhost:6379/1
```

### 2. Gunicorn Configuration

```python
# gunicorn_config.py
bind = "0.0.0.0:8000"
workers = 4
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
timeout = 30
```

### 3. Nginx Configuration

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/v1/webhooks/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Twilio-Signature $http_x_twilio_signature;
        proxy_buffering off;  # Important for webhooks
    }
}
```

### 4. Celery for Async Tasks

```python
# celery.py
from celery import Celery

app = Celery('django_twilio_call')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Run with: celery -A your_project worker -l info
```

### 5. Monitoring

```python
# Monitor key metrics
from django_twilio_call.services import analytics_service

# Get real-time metrics
metrics = analytics_service.get_real_time_metrics()

# Set up alerts
if metrics['current_activity']['queued_calls'] > 10:
    send_alert("High queue volume")

if metrics['agents']['available'] == 0:
    send_alert("No agents available")
```

## WebSocket Support (Optional)

For real-time updates in your frontend:

```python
# consumers.py
from channels.generic.websocket import AsyncWebsocketConsumer
import json

class CallCenterConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("call_center", self.channel_name)
        await self.accept()

    async def call_update(self, event):
        await self.send(text_data=json.dumps(event['data']))
```

## Security Considerations

1. **Always validate webhooks** - Set `TWILIO_WEBHOOK_VALIDATE = True`
2. **Use HTTPS** - Twilio requires HTTPS for webhooks
3. **Restrict API access** - Use Django's permission system
4. **Encrypt sensitive data** - Use Django's encryption for storing tokens
5. **Audit logging** - All actions are logged via CallLog model
6. **Rate limiting** - Implement rate limiting on API endpoints

## Performance Tips

1. **Use Redis caching** - Significantly improves performance
2. **Database indexes** - Run `python manage.py django_twilio_call_optimize_db`
3. **Async processing** - Use Celery for heavy tasks
4. **Connection pooling** - Configure for Twilio client
5. **Pagination** - Use for large result sets

## API Authentication

```python
# Using Token Authentication
from rest_framework.authtoken.models import Token

token = Token.objects.create(user=user)

# API request
headers = {'Authorization': f'Token {token.key}'}
response = requests.get('https://your-api.com/api/v1/calls/', headers=headers)
```

## Testing Your Integration

```python
# test_integration.py
from django.test import TestCase
from django_twilio_call.tests.test_twilio_mocks import create_mock_twilio_client
from unittest.mock import patch

class IntegrationTest(TestCase):
    @patch('django_twilio_call.services.twilio_service.client')
    def test_incoming_call(self, mock_client):
        mock_client.return_value = create_mock_twilio_client()

        # Simulate incoming call
        response = self.client.post('/api/v1/webhooks/voice/', {
            'CallSid': 'CA123',
            'From': '+1234567890',
            'To': '+0987654321'
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('Enqueue', response.content.decode())
```

## Debugging Tips

1. **Check Twilio Console Debugger** - Shows all API requests and errors
2. **Enable Django Debug Toolbar** - Add to INSTALLED_APPS
3. **Check webhook signatures** - Use `ngrok` for local testing
4. **Monitor logs** - Check both Django and Twilio logs
5. **Test with Twilio CLI** - `twilio phone-numbers:update +1234567890 --voice-url=...`

## Getting Help

- **API Documentation**: `/api/v1/docs/` (when drf-spectacular is installed)
- **Django Admin**: Register models in admin for easy management
- **Logs**: Check `django_twilio_call` logger output
- **Twilio Status**: https://status.twilio.com/

Remember: This library handles the complex telephony logic, but you still need to understand basic Twilio concepts like TwiML, webhooks, and phone number configuration.
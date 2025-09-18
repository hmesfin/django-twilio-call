# Troubleshooting Guide

This guide covers common issues you might encounter with django-twilio-call and how to solve them. Each issue includes symptoms, causes, and step-by-step solutions.

## Table of Contents
1. [Installation Issues](#installation-issues)
2. [Webhook Issues](#webhook-issues)
3. [Call Issues](#call-issues)
4. [Database Issues](#database-issues)
5. [Performance Issues](#performance-issues)
6. [Twilio API Issues](#twilio-api-issues)
7. [Common Error Messages](#common-error-messages)
8. [Debug Techniques](#debug-techniques)

---

## Installation Issues

### Problem: ImportError: cannot import name 'django_twilio_call'

**Symptoms:**
```python
ImportError: cannot import name 'django_twilio_call' from 'django_twilio_call'
```

**Causes:**
- Package not installed correctly
- Virtual environment issues
- Python path problems

**Solution:**
```bash
# 1. Verify installation
pip show django-twilio-call

# 2. Reinstall if needed
pip uninstall django-twilio-call
pip install django-twilio-call

# 3. Check Python path
python -c "import sys; print(sys.path)"

# 4. Verify in Django shell
python manage.py shell
>>> import django_twilio_call
>>> print(django_twilio_call.__version__)
```

### Problem: Migration failures

**Symptoms:**
```
django.db.utils.ProgrammingError: relation "django_twilio_call_queue" does not exist
```

**Solution:**
```bash
# 1. Check migration status
python manage.py showmigrations django_twilio_call

# 2. Create migrations if missing
python manage.py makemigrations django_twilio_call

# 3. Apply migrations
python manage.py migrate django_twilio_call

# 4. If still failing, fake initial migration
python manage.py migrate django_twilio_call --fake-initial

# 5. For complete reset (CAUTION: loses data)
python manage.py migrate django_twilio_call zero
python manage.py migrate django_twilio_call
```

---

## Webhook Issues

### Problem: Webhooks not receiving calls

**Symptoms:**
- Incoming calls not appearing in system
- No logs for webhook requests
- Twilio console shows webhook errors

**Diagnosis:**
```python
# Check webhook URL configuration
from django.conf import settings
print(settings.TWILIO_WEBHOOK_BASE_URL)

# Test webhook endpoint
curl -X POST https://your-domain.com/api/v1/webhooks/voice/ \
  -d "CallSid=TEST123" \
  -d "From=+1234567890" \
  -d "To=+0987654321"
```

**Common Causes & Solutions:**

1. **URL not publicly accessible**
   ```bash
   # For local development, use ngrok
   ngrok http 8000
   # Update TWILIO_WEBHOOK_BASE_URL with ngrok URL
   ```

2. **HTTPS required but not configured**
   ```python
   # Twilio requires HTTPS in production
   TWILIO_WEBHOOK_BASE_URL = 'https://your-domain.com'  # Not http://
   ```

3. **Webhook signature validation failing**
   ```python
   # Temporarily disable for testing (not for production!)
   TWILIO_WEBHOOK_VALIDATE = False

   # Check auth token is correct
   print(settings.TWILIO_AUTH_TOKEN)
   ```

4. **URL path incorrect**
   ```python
   # Verify URL patterns
   # Should be: https://your-domain.com/api/v1/webhooks/voice/
   # Not: https://your-domain.com/webhooks/voice/
   ```

### Problem: Webhook signature validation errors

**Symptoms:**
```
403 Forbidden: Invalid webhook signature
```

**Solution:**
```python
# 1. Verify auth token matches Twilio console
TWILIO_AUTH_TOKEN = 'your_actual_token'  # From Twilio console

# 2. Check if proxy is stripping headers
# In nginx.conf:
proxy_set_header X-Twilio-Signature $http_x_twilio_signature;

# 3. Ensure body isn't being modified
# Disable body parsing middleware before webhook routes

# 4. For debugging, temporarily bypass validation
@csrf_exempt
def voice_webhook(request):
    # Log the signature for debugging
    signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
    print(f"Received signature: {signature}")
    # Process webhook...
```

---

## Call Issues

### Problem: Calls not connecting to agents

**Symptoms:**
- Calls stuck in queue
- Agents show available but don't receive calls
- "No agents available" error despite agents being online

**Diagnosis:**
```python
# Check agent status
from django_twilio_call.models import Agent
agents = Agent.objects.filter(is_active=True)
for agent in agents:
    print(f"{agent.extension}: {agent.status} - Queues: {agent.queues.all()}")

# Check queue configuration
from django_twilio_call.models import Queue
queue = Queue.objects.get(name='support')
print(f"Queue active: {queue.is_active}")
print(f"Agents in queue: {queue.agents.count()}")
```

**Solutions:**

1. **Agent not in queue**
   ```python
   agent = Agent.objects.get(extension='1001')
   queue = Queue.objects.get(name='support')
   agent.queues.add(queue)
   ```

2. **Agent status incorrect**
   ```python
   from django_twilio_call.services import agent_service
   agent_service.set_available(agent_id=agent.id)
   ```

3. **Queue routing strategy issue**
   ```python
   queue.routing_strategy = 'round_robin'  # Try different strategy
   queue.save()
   ```

### Problem: Calls dropping immediately

**Symptoms:**
- Call connects then immediately disconnects
- Duration shows 0 seconds
- Status changes to 'failed'

**Common Causes:**

1. **TwiML response error**
   ```python
   # Check webhook response
   response = voice_webhook(mock_request)
   print(response.content)  # Should be valid TwiML XML
   ```

2. **Invalid phone number format**
   ```python
   # Numbers must be E.164 format
   good = "+14155551234"
   bad = "415-555-1234"  # Won't work
   ```

3. **Twilio account issues**
   ```python
   # Check account balance and status
   from django_twilio_call.services import twilio_service
   account = twilio_service.client.api.accounts(
       settings.TWILIO_ACCOUNT_SID
   ).fetch()
   print(f"Status: {account.status}")  # Should be 'active'
   ```

---

## Database Issues

### Problem: Database connection pool exhausted

**Symptoms:**
```
OperationalError: FATAL: remaining connection slots are reserved
```

**Solution:**
```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'OPTIONS': {
            'connect_timeout': 10,
            'options': '-c statement_timeout=30000'  # 30 seconds
        },
        'CONN_MAX_AGE': 60,  # Reuse connections for 60 seconds
    }
}

# For high traffic, use connection pooling
DATABASES['default']['OPTIONS']['connection_pool'] = {
    'min_size': 4,
    'max_size': 20,
}
```

### Problem: Slow queries

**Symptoms:**
- API endpoints timing out
- Database CPU high
- Slow page loads

**Diagnosis:**
```python
# Enable query logging
LOGGING = {
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}

# Find slow queries
from django.db import connection
print(connection.queries)  # After running slow operation
```

**Solutions:**

1. **Add missing indexes**
   ```python
   # In migration file
   migrations.AddIndex(
       model_name='call',
       index=models.Index(fields=['queue', 'status', '-created_at']),
   )
   ```

2. **Optimize ORM queries**
   ```python
   # Bad: N+1 query
   calls = Call.objects.all()
   for call in calls:
       print(call.agent.name)  # Hits DB each time

   # Good: Prefetch related
   calls = Call.objects.select_related('agent').all()
   for call in calls:
       print(call.agent.name)  # No additional queries
   ```

---

## Performance Issues

### Problem: High memory usage

**Symptoms:**
- Server running out of memory
- Gunicorn workers being killed
- OOM (Out of Memory) errors

**Diagnosis:**
```python
# Check memory usage
import psutil
process = psutil.Process()
print(f"Memory: {process.memory_info().rss / 1024 / 1024:.2f} MB")

# Find memory leaks
import tracemalloc
tracemalloc.start()
# ... run operations ...
snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
for stat in top_stats[:10]:
    print(stat)
```

**Solutions:**

1. **Paginate large querysets**
   ```python
   # Bad: Loads all records
   calls = Call.objects.all()

   # Good: Use pagination
   from django.core.paginator import Paginator
   paginator = Paginator(Call.objects.all(), 100)
   for page_num in paginator.page_range:
       page = paginator.page(page_num)
       for call in page:
           # Process call
   ```

2. **Use iterator for large datasets**
   ```python
   # For large result sets
   for call in Call.objects.all().iterator(chunk_size=1000):
       # Process without loading all into memory
   ```

### Problem: Slow API responses

**Solutions:**

1. **Enable caching**
   ```python
   from django.core.cache import cache

   def get_queue_metrics(queue_id):
       cache_key = f'queue_metrics_{queue_id}'
       metrics = cache.get(cache_key)
       if metrics is None:
           metrics = calculate_metrics(queue_id)
           cache.set(cache_key, metrics, 60)  # Cache for 60 seconds
       return metrics
   ```

2. **Use select_related and prefetch_related**
   ```python
   # Optimize viewset queries
   class CallViewSet(viewsets.ModelViewSet):
       queryset = Call.objects.select_related(
           'agent', 'queue'
       ).prefetch_related(
           'logs'
       )
   ```

---

## Twilio API Issues

### Problem: Twilio API rate limits

**Symptoms:**
```
429 Too Many Requests
```

**Solution:**
```python
# Implement exponential backoff
import time
from functools import wraps

def retry_with_backoff(max_retries=3):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except TwilioRestException as e:
                    if e.status == 429 and i < max_retries - 1:
                        wait = (2 ** i) + random.random()
                        time.sleep(wait)
                    else:
                        raise
            return None
        return wrapper
    return decorator

@retry_with_backoff()
def make_call(to_number, from_number):
    return twilio_service.make_call(to_number, from_number)
```

### Problem: Invalid Twilio credentials

**Symptoms:**
```
20003: Authentication Error - Invalid credentials
```

**Solution:**
```bash
# 1. Verify credentials in Twilio console
# https://console.twilio.com

# 2. Test with Twilio CLI
twilio api:core:calls:list --limit=1

# 3. Test in Python
from twilio.rest import Client
client = Client('ACxxx', 'auth_token')
try:
    client.api.accounts(client.account_sid).fetch()
    print("Credentials valid!")
except Exception as e:
    print(f"Invalid: {e}")
```

---

## Common Error Messages

### "Queue 'support' not found"

```python
# Create the queue
from django_twilio_call.models import Queue
Queue.objects.create(
    name='support',
    description='Support queue',
    max_size=50
)
```

### "No available agents"

```python
# Check agent availability
from django_twilio_call.models import Agent
Agent.objects.filter(
    status='available',
    is_active=True,
    queues__name='support'
).count()
```

### "Call not found"

```python
# Check if call exists with correct SID
from django_twilio_call.models import Call
Call.objects.filter(twilio_sid='CAxxxx').exists()
```

---

## Debug Techniques

### Enable detailed logging

```python
# settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': '/tmp/django_twilio_call.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django_twilio_call': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'twilio': {
            'handlers': ['file'],
            'level': 'DEBUG',
        },
    },
}
```

### Use Django Debug Toolbar

```python
# settings.py
if DEBUG:
    INSTALLED_APPS += ['debug_toolbar']
    MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
    INTERNAL_IPS = ['127.0.0.1']

# urls.py
if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
```

### Test webhooks locally

```bash
# Use ngrok for local testing
ngrok http 8000

# Update Twilio webhook URL to ngrok URL
# https://xxxx.ngrok.io/api/v1/webhooks/voice/

# Monitor requests
ngrok http 8000 --inspect
# Visit http://127.0.0.1:4040 to see all requests
```

### Check Twilio debugger

1. Go to [Twilio Console](https://console.twilio.com)
2. Navigate to Monitor → Logs → Debugger
3. Look for errors and warnings
4. Click on events for details

### Use management commands for testing

```python
# management/commands/test_twilio.py
from django.core.management.base import BaseCommand
from django_twilio_call.services import twilio_service

class Command(BaseCommand):
    def handle(self, *args, **options):
        # Test Twilio connection
        try:
            account = twilio_service.client.api.accounts(
                settings.TWILIO_ACCOUNT_SID
            ).fetch()
            self.stdout.write(f"✓ Connected to Twilio: {account.friendly_name}")
        except Exception as e:
            self.stdout.write(f"✗ Twilio error: {e}")

        # Test database
        from django_twilio_call.models import Queue
        self.stdout.write(f"✓ Queues in database: {Queue.objects.count()}")

# Run with: python manage.py test_twilio
```

### Common debugging queries

```python
# Recent failed calls
Call.objects.filter(
    status='failed',
    created_at__gte=timezone.now() - timedelta(hours=1)
).values('twilio_sid', 'from_number', 'created_at')

# Agent activity log
AgentActivity.objects.filter(
    agent_id=1,
    timestamp__gte=timezone.now() - timedelta(hours=24)
).order_by('-timestamp')

# Queue wait times
from django.db.models import Avg
Call.objects.filter(
    queue_id=1,
    status='completed'
).aggregate(avg_wait=Avg('queue_time'))
```

## Getting Additional Help

1. **Check logs**: `/tmp/django_twilio_call.log`
2. **Twilio Support**: https://support.twilio.com
3. **Django Debug Mode**: Set `DEBUG=True` temporarily
4. **API Documentation**: `/api/v1/docs/`
5. **Run tests**: `pytest django_twilio_call/tests/`

Remember: Most issues are configuration-related. Double-check your settings!
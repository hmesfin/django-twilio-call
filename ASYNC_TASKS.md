# Django Twilio Call - Async Task Processing System

This document provides comprehensive documentation for the async task processing system implemented in the django-twilio-call package using Celery.

## Overview

The async task system is designed to handle high-volume call center operations including:

- **Recording Processing**: Download, store, and transcribe call recordings
- **Analytics Generation**: Generate daily, weekly, and monthly reports
- **Data Maintenance**: Clean up old data and archive recordings
- **Email Notifications**: Send reports and alerts
- **Webhook Retries**: Handle failed webhook deliveries
- **System Monitoring**: Track performance and health metrics

## Architecture

### Task Queues

The system uses multiple specialized queues for optimal performance:

| Queue | Priority | Purpose | Concurrency |
|-------|----------|---------|-------------|
| `webhooks` | High (10) | Real-time webhook processing | 4 |
| `realtime` | High (9) | Real-time call updates | 4 |
| `notifications` | High (8) | User notifications | 4 |
| `recordings` | Medium (6) | Recording processing | 2 |
| `analytics` | Medium (5) | Analytics calculations | 2 |
| `reports` | Low (3) | Report generation | 1 |
| `exports` | Low (2) | Data exports | 1 |
| `maintenance` | Low (1) | Cleanup and maintenance | 2 |
| `email` | Low (3) | Email sending | 2 |
| `retries` | Medium (4) | Retry failed tasks | 2 |

### Worker Types

Different worker types are optimized for specific workloads:

- **realtime-worker**: Handles high-priority, time-sensitive tasks
- **processing-worker**: Handles recording and analytics processing
- **reports-worker**: Handles CPU-intensive report generation
- **maintenance-worker**: Handles background maintenance tasks

## Key Tasks

### Recording Processing

```python
# Process call recording asynchronously
from django_twilio_call.tasks import process_call_recording
result = process_call_recording.delay(call_id=123)

# Transcribe recording
from django_twilio_call.tasks import transcribe_recording
result = transcribe_recording.delay(recording_id=456, language='en-US')
```

### Analytics and Reporting

```python
# Generate reports asynchronously
from django_twilio_call.services.analytics_service import analytics_service

# Daily report
task_id = analytics_service.generate_report_async('daily', date_str='2023-10-15')

# Weekly report
task_id = analytics_service.generate_report_async('weekly', week_start_str='2023-10-09')

# Monthly report
task_id = analytics_service.generate_report_async('monthly', year=2023, month=10)

# Agent metrics
task_id = analytics_service.calculate_agent_metrics_async(
    agent_id=789,
    date_range={'start': '2023-10-15T00:00:00Z', 'end': '2023-10-15T23:59:59Z'}
)
```

### Data Export

```python
# Export call data
from django_twilio_call.tasks import export_call_data

filters = {
    'start_date': '2023-10-01T00:00:00Z',
    'end_date': '2023-10-31T23:59:59Z',
    'queue_ids': [1, 2, 3],
    'status': ['completed', 'failed']
}

result = export_call_data.delay(filters=filters, format='csv', user_id=1)
```

### Webhook Processing

```python
# Process webhook callback
from django_twilio_call.tasks import process_webhook_callback

webhook_data = {
    'CallSid': 'CA123...',
    'CallStatus': 'completed',
    'Duration': '120'
}

result = process_webhook_callback.delay(
    webhook_data=webhook_data,
    webhook_type='call-status'
)

# Retry failed webhook
from django_twilio_call.tasks import retry_failed_webhook
result = retry_failed_webhook.delay(webhook_log_id=123)
```

## API Endpoints

### Task Status and Monitoring

```bash
# Get task status
GET /api/tasks/status/{task_id}/

# Get system health
GET /api/tasks/health/

# Get queue metrics
GET /api/tasks/health/queues/

# Get slow tasks
GET /api/tasks/health/slow/?threshold=30

# Get failure analysis
GET /api/tasks/health/failures/?hours=24
```

### Task Execution Records

```bash
# List task executions
GET /api/tasks/executions/

# Filter by status
GET /api/tasks/executions/?status=failure

# Filter by task name
GET /api/tasks/executions/?task_name=process_call_recording

# Get active tasks
GET /api/tasks/executions/active/

# Get failed tasks
GET /api/tasks/executions/failed/

# Retry a failed task
POST /api/tasks/executions/{public_id}/retry/
```

### Report Generation

```bash
# Generate daily report
POST /api/tasks/reports/generate/
{
  "report_type": "daily",
  "date_str": "2023-10-15",
  "email_recipients": ["admin@example.com"]
}

# Download report
GET /api/tasks/reports/download/?cache_key={cache_key}
```

### Data Export

```bash
# Start data export
POST /api/tasks/export/
{
  "format": "csv",
  "start_date": "2023-10-01T00:00:00Z",
  "end_date": "2023-10-31T23:59:59Z",
  "queue_ids": [1, 2, 3]
}

# Download export
GET /api/tasks/export/download/?cache_key={cache_key}
```

### Bulk Actions

```bash
# Retry multiple failed tasks
POST /api/tasks/bulk-actions/
{
  "action": "retry",
  "task_ids": ["task-1", "task-2", "task-3"]
}

# Cancel active tasks by filter
POST /api/tasks/bulk-actions/
{
  "action": "cancel",
  "filters": {"task_name": "long_running_task", "status": "started"}
}
```

## Docker Deployment

### Using Docker Compose

```bash
# Start all services including Celery workers
docker-compose -f docker/docker-compose.celery.yml up -d

# Scale workers
docker-compose -f docker/docker-compose.celery.yml up -d --scale celery-worker-realtime=2

# View logs
docker-compose -f docker/docker-compose.celery.yml logs -f celery-worker-realtime

# Stop services
docker-compose -f docker/docker-compose.celery.yml down
```

### Manual Worker Deployment

```bash
# Build image
docker build -f docker/Dockerfile -t django-twilio-call .

# Run different worker types
docker run -e WORKER_TYPE=realtime django-twilio-call /app/docker/start-celery-worker.sh
docker run -e WORKER_TYPE=processing django-twilio-call /app/docker/start-celery-worker.sh
docker run -e WORKER_TYPE=reports django-twilio-call /app/docker/start-celery-worker.sh
docker run -e WORKER_TYPE=maintenance django-twilio-call /app/docker/start-celery-worker.sh

# Run Celery Beat scheduler
docker run django-twilio-call celery -A django_twilio_call.celery beat --loglevel=info
```

## Monitoring and Management

### Command Line Monitoring

```bash
# Monitor system health
python manage.py monitor_tasks --health

# Watch mode (continuous monitoring)
python manage.py monitor_tasks --watch

# Show slow tasks
python manage.py monitor_tasks --slow --threshold=60

# Show failure analysis
python manage.py monitor_tasks --failures --hours=48

# Monitor specific task
python manage.py monitor_tasks --task process_call_recording

# Show queue metrics
python manage.py monitor_tasks --queues
```

### Flower Monitoring

Access Flower web interface at `http://localhost:5555` (credentials: admin/admin123)

### Redis Monitoring

Access Redis Commander at `http://localhost:8081`

## Configuration

### Environment Variables

```bash
# Celery Configuration
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Database
DATABASE_URL=postgres://user:password@localhost:5432/dbname

# Email Configuration
DEFAULT_FROM_EMAIL=noreply@example.com
DAILY_REPORT_RECIPIENTS=admin@example.com,manager@example.com
CRITICAL_ALERT_RECIPIENTS=admin@example.com

# Recording Configuration
ENABLE_TRANSCRIPTION=True
RECORDING_STORAGE_BACKEND=s3  # or 'local' or 'twilio'
RECORDING_RETENTION_DAYS=365
RECORDING_ENCRYPTION_KEY=your-encryption-key

# AWS Configuration (if using S3)
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_S3_REGION_NAME=us-east-1
AWS_STORAGE_BUCKET_NAME=your-bucket
```

### Django Settings

```python
# settings.py

INSTALLED_APPS = [
    # ... other apps
    'django_twilio_call',
]

# Celery Configuration
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')

# Task Configuration
ENABLE_TRANSCRIPTION = os.environ.get('ENABLE_TRANSCRIPTION', 'False').lower() == 'true'
RECORDING_STORAGE_BACKEND = os.environ.get('RECORDING_STORAGE_BACKEND', 'local')
RECORDING_RETENTION_DAYS = int(os.environ.get('RECORDING_RETENTION_DAYS', 365))

# Email Configuration
DAILY_REPORT_RECIPIENTS = os.environ.get('DAILY_REPORT_RECIPIENTS', '').split(',')
CRITICAL_ALERT_RECIPIENTS = os.environ.get('CRITICAL_ALERT_RECIPIENTS', '').split(',')
```

## Periodic Tasks

The system includes several periodic tasks that run automatically:

### Hourly Tasks
- `calculate_hourly_metrics`: Update real-time dashboard metrics

### Daily Tasks
- `generate_daily_report`: Generate daily analytics report (2 AM)
- `cleanup_old_call_logs`: Remove old call logs (1 AM)
- `archive_old_recordings`: Archive old recordings (12:30 AM)
- `cleanup_expired_sessions`: Clean up expired sessions (midnight)

### Weekly Tasks
- `generate_weekly_report`: Generate weekly analytics report (Monday 3 AM)

### Monthly Tasks
- `generate_monthly_report`: Generate monthly analytics report (1st of month 4 AM)

### Monitoring Tasks
- `system_health_check`: Monitor system health (every 5 minutes)
- `check_failed_webhooks`: Check and retry failed webhooks (every 10 minutes)
- `update_all_agent_metrics`: Update agent performance metrics (every 15 minutes)
- `optimize_queue_routing`: Analyze and optimize queue performance (every 30 minutes)

### Processing Tasks
- `process_pending_recordings`: Process unprocessed recordings (every 3 minutes)
- `transcribe_pending_recordings`: Transcribe recordings (every 10 minutes)

## Error Handling and Fault Tolerance

### Retry Strategies

Different error types have specialized retry strategies:

- **Connection Errors**: Exponential backoff with jitter
- **Timeout Errors**: Progressive timeout increases
- **Validation Errors**: Single retry with input sanitization
- **Resource Exhaustion**: Progressive delays with resource reduction
- **Twilio API Errors**: Rate limit aware retries
- **Database Errors**: Connection pool aware retries

### Circuit Breaker

External service calls use circuit breaker pattern to prevent cascading failures:

```python
from django_twilio_call.error_handling import with_circuit_breaker

@with_circuit_breaker(failure_threshold=5, recovery_timeout=300)
def call_external_service():
    # Your external service call
    pass
```

### Dead Letter Queue

Failed tasks that exceed maximum retries are sent to a dead letter queue for manual processing.

## Performance Optimization

### Task Design Best Practices

1. **Keep tasks small and focused**: Break large operations into smaller tasks
2. **Use progress tracking**: Update task state for long-running operations
3. **Implement proper timeouts**: Set appropriate soft and hard time limits
4. **Handle failures gracefully**: Implement proper error handling and recovery
5. **Use appropriate queues**: Route tasks to appropriate priority queues

### Resource Management

- **Memory limits**: Tasks are limited to 200MB memory per child process
- **Task limits**: Workers restart after processing 1000 tasks (100 for reports)
- **Time limits**: Hard limit of 30 minutes, soft limit of 25 minutes
- **Connection pooling**: Database connections are properly managed

### Scaling Guidelines

- **Horizontal scaling**: Add more worker instances for increased throughput
- **Queue-specific scaling**: Scale workers based on queue backlogs
- **Resource-based scaling**: Monitor CPU and memory usage
- **Geographic scaling**: Deploy workers in multiple regions for global operations

## Troubleshooting

### Common Issues

1. **High memory usage**: Check for memory leaks in custom tasks
2. **Task timeouts**: Increase time limits or break tasks into smaller chunks
3. **Queue backlogs**: Add more workers or optimize task performance
4. **Database connection issues**: Check connection pool settings
5. **Redis connection issues**: Verify Redis configuration and connectivity

### Debugging Tasks

```python
# Get detailed task information
from django_twilio_call.models import TaskExecution
task = TaskExecution.objects.get(task_id='your-task-id')
print(task.result)  # Error details or results

# Check task status in Celery
from celery.result import AsyncResult
result = AsyncResult('your-task-id')
print(result.status)
print(result.info)

# Monitor task execution
python manage.py monitor_tasks --task your_task_name --watch
```

### Performance Analysis

```python
# Get task performance trends
from django_twilio_call.monitoring import task_monitor
trends = task_monitor.get_task_performance_trends('process_call_recording', days=7)

# Get failure analysis
failures = task_monitor.get_failure_analysis(hours=24)

# Get slow tasks
slow_tasks = task_monitor.get_slow_tasks(threshold=30)
```

## Security Considerations

1. **Input validation**: All task inputs are validated and sanitized
2. **Authentication**: API endpoints require proper authentication
3. **Rate limiting**: Implement rate limiting for API endpoints
4. **Encryption**: Sensitive data is encrypted at rest and in transit
5. **Access control**: Limit access to monitoring and management endpoints
6. **Audit logging**: All task executions are logged for audit purposes

## Contributing

When adding new async tasks:

1. Define tasks in `django_twilio_call/tasks.py`
2. Add appropriate routing in `django_twilio_call/celery.py`
3. Implement error handling using `FaultTolerantTaskMixin`
4. Add monitoring and metrics collection
5. Update API endpoints if needed
6. Add tests for task functionality
7. Update documentation

## Support

For issues and questions:

1. Check the task execution logs
2. Use the monitoring command: `python manage.py monitor_tasks`
3. Check Flower monitoring interface
4. Review system health metrics via API
5. Analyze failure patterns and trends
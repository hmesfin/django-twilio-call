"""Celery configuration for django-twilio-call package."""

import os
import time

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure, task_postrun, task_prerun
from django.conf import settings
from kombu import Exchange, Queue

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django.conf.global_settings")

# Create Celery instance
app = Celery("django_twilio_call")

# Load configuration from Django settings
app.config_from_object("django.conf:settings", namespace="CELERY")

# Advanced Celery configuration for production call center workloads
app.conf.update(
    # Broker settings - optimized for high-volume call processing
    broker_url=getattr(settings, "CELERY_BROKER_URL", "redis://localhost:6379/0"),
    result_backend=getattr(settings, "CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    # Serialization - JSON for security and compatibility
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task routing for different priorities and types
    task_routes={
        # High priority real-time tasks
        "django_twilio_call.tasks.process_webhook_callback": {"queue": "webhooks"},
        "django_twilio_call.tasks.update_call_status": {"queue": "realtime"},
        "django_twilio_call.tasks.send_real_time_notification": {"queue": "notifications"},
        # Medium priority processing tasks
        "django_twilio_call.tasks.process_call_recording": {"queue": "recordings"},
        "django_twilio_call.tasks.transcribe_recording": {"queue": "recordings"},
        "django_twilio_call.tasks.calculate_agent_metrics": {"queue": "analytics"},
        # Low priority background tasks
        "django_twilio_call.tasks.generate_daily_report": {"queue": "reports"},
        "django_twilio_call.tasks.generate_weekly_report": {"queue": "reports"},
        "django_twilio_call.tasks.generate_monthly_report": {"queue": "reports"},
        "django_twilio_call.tasks.cleanup_old_data": {"queue": "maintenance"},
        "django_twilio_call.tasks.send_report_email": {"queue": "email"},
        "django_twilio_call.tasks.export_call_data": {"queue": "exports"},
        "django_twilio_call.tasks.retry_failed_webhook": {"queue": "retries"},
    },
    # Define task queues with different priorities and settings
    task_queues=(
        # Real-time webhooks - highest priority
        Queue(
            "webhooks",
            Exchange("webhooks"),
            routing_key="webhooks",
            queue_arguments={"x-max-priority": 10, "x-message-ttl": 30000},
        ),
        # Real-time updates - high priority
        Queue(
            "realtime",
            Exchange("realtime"),
            routing_key="realtime",
            queue_arguments={"x-max-priority": 9, "x-message-ttl": 60000},
        ),
        # Notifications - high priority
        Queue(
            "notifications",
            Exchange("notifications"),
            routing_key="notifications",
            queue_arguments={"x-max-priority": 8, "x-message-ttl": 120000},
        ),
        # Recording processing - medium priority
        Queue("recordings", Exchange("recordings"), routing_key="recordings", queue_arguments={"x-max-priority": 6}),
        # Analytics - medium priority
        Queue("analytics", Exchange("analytics"), routing_key="analytics", queue_arguments={"x-max-priority": 5}),
        # Reports - low priority, longer TTL
        Queue("reports", Exchange("reports"), routing_key="reports", queue_arguments={"x-max-priority": 3}),
        # Email - low priority
        Queue("email", Exchange("email"), routing_key="email", queue_arguments={"x-max-priority": 3}),
        # Exports - low priority, can take time
        Queue("exports", Exchange("exports"), routing_key="exports", queue_arguments={"x-max-priority": 2}),
        # Maintenance - lowest priority
        Queue("maintenance", Exchange("maintenance"), routing_key="maintenance", queue_arguments={"x-max-priority": 1}),
        # Retries - medium priority
        Queue("retries", Exchange("retries"), routing_key="retries", queue_arguments={"x-max-priority": 4}),
        # Default queue
        Queue("celery", Exchange("celery"), routing_key="celery"),
    ),
    # Task execution settings optimized for call center operations
    task_acks_late=True,  # Acknowledge after completion for reliability
    task_reject_on_worker_lost=True,  # Requeue if worker dies
    task_default_retry_delay=60,  # 1 minute default retry delay
    task_max_retries=3,  # Maximum retries for failed tasks
    task_soft_time_limit=300,  # 5 minutes soft limit
    task_time_limit=600,  # 10 minutes hard limit
    # Worker settings for optimal performance
    worker_prefetch_multiplier=1,  # Fair distribution of tasks
    worker_max_tasks_per_child=1000,  # Restart workers periodically
    worker_disable_rate_limits=False,
    worker_send_task_events=True,
    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour
    result_compression="gzip",  # Compress results to save memory
    result_persistent=True,  # Persist results to disk
    # Monitoring and events
    task_send_sent_event=True,
    # Beat schedule for periodic tasks
    beat_schedule={
        # Analytics and reporting
        "generate-hourly-metrics": {
            "task": "django_twilio_call.tasks.calculate_hourly_metrics",
            "schedule": crontab(minute=5),  # Every hour at 5 minutes past
        },
        "generate-daily-report": {
            "task": "django_twilio_call.tasks.generate_daily_report",
            "schedule": crontab(hour=2, minute=0),  # 2 AM daily
        },
        "generate-weekly-report": {
            "task": "django_twilio_call.tasks.generate_weekly_report",
            "schedule": crontab(hour=3, minute=0, day_of_week=1),  # Monday 3 AM
        },
        "generate-monthly-report": {
            "task": "django_twilio_call.tasks.generate_monthly_report",
            "schedule": crontab(hour=4, minute=0, day_of_month=1),  # 1st of month 4 AM
        },
        # Data maintenance
        "cleanup-old-call-logs": {
            "task": "django_twilio_call.tasks.cleanup_old_call_logs",
            "schedule": crontab(hour=1, minute=0),  # 1 AM daily
        },
        "archive-old-recordings": {
            "task": "django_twilio_call.tasks.archive_old_recordings",
            "schedule": crontab(hour=0, minute=30),  # 12:30 AM daily
        },
        "cleanup-expired-sessions": {
            "task": "django_twilio_call.tasks.cleanup_expired_sessions",
            "schedule": crontab(hour=0, minute=0),  # Midnight daily
        },
        # System health checks
        "health-check": {
            "task": "django_twilio_call.tasks.system_health_check",
            "schedule": 300.0,  # Every 5 minutes
        },
        "check-failed-webhooks": {
            "task": "django_twilio_call.tasks.check_failed_webhooks",
            "schedule": 600.0,  # Every 10 minutes
        },
        # Agent and queue monitoring
        "update-agent-metrics": {
            "task": "django_twilio_call.tasks.update_all_agent_metrics",
            "schedule": crontab(minute="*/15"),  # Every 15 minutes
        },
        "optimize-queue-routing": {
            "task": "django_twilio_call.tasks.optimize_queue_routing",
            "schedule": crontab(minute="*/30"),  # Every 30 minutes
        },
        # Recording processing
        "process-pending-recordings": {
            "task": "django_twilio_call.tasks.process_pending_recordings",
            "schedule": 180.0,  # Every 3 minutes
        },
        "transcribe-pending-recordings": {
            "task": "django_twilio_call.tasks.transcribe_pending_recordings",
            "schedule": 600.0,  # Every 10 minutes
        },
    },
)


class BaseTaskClass(app.Task):
    """Enhanced base task class with logging, error handling, and metrics."""

    def __call__(self, *args, **kwargs):
        """Override call to add request context and timing."""
        start_time = time.time()

        try:
            result = super().__call__(*args, **kwargs)

            # Record success metrics
            self._record_task_metrics("success", time.time() - start_time)
            return result

        except Exception as exc:
            # Record failure metrics
            self._record_task_metrics("failure", time.time() - start_time)

            # Enhanced error logging
            self._log_task_error(exc, args, kwargs)
            raise

    def retry(
        self, args=None, kwargs=None, exc=None, throw=True, eta=None, countdown=None, max_retries=None, **options
    ):
        """Enhanced retry with exponential backoff."""
        if countdown is None and eta is None:
            # Exponential backoff: 2^retry_count * base_delay
            base_delay = getattr(self, "retry_backoff", 60)
            countdown = base_delay * (2**self.request.retries)

            # Add jitter to prevent thundering herd
            import random

            jitter = random.uniform(0.5, 1.5)
            countdown = int(countdown * jitter)

            # Cap at maximum delay
            max_delay = getattr(self, "max_retry_delay", 3600)  # 1 hour max
            countdown = min(countdown, max_delay)

        return super().retry(
            args=args,
            kwargs=kwargs,
            exc=exc,
            throw=throw,
            eta=eta,
            countdown=countdown,
            max_retries=max_retries,
            **options,
        )

    def _record_task_metrics(self, status: str, duration: float):
        """Record task execution metrics."""
        try:
            from .models import TaskExecution

            TaskExecution.objects.create(
                task_name=self.name,
                task_id=self.request.id,
                status=status,
                duration_seconds=duration,
                queue_name=self.request.delivery_info.get("routing_key", "unknown"),
                retry_count=self.request.retries,
                worker_name=self.request.hostname,
            )
        except Exception:
            # Don't fail the task if metrics recording fails
            pass

    def _log_task_error(self, exc: Exception, args: tuple, kwargs: dict):
        """Enhanced error logging with context."""
        import logging

        logger = logging.getLogger(f"celery.task.{self.name}")

        logger.error(
            "Task failed: %s",
            str(exc),
            extra={
                "task_name": self.name,
                "task_id": self.request.id,
                "args": args,
                "kwargs": kwargs,
                "retries": self.request.retries,
                "eta": self.request.eta,
                "expires": self.request.expires,
                "queue": self.request.delivery_info.get("routing_key"),
                "worker": self.request.hostname,
            },
            exc_info=True,
        )


# Set the base task class
app.Task = BaseTaskClass

# Auto-discover tasks
app.autodiscover_tasks()


# Task execution monitoring signals
@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
    """Handle task start - record in monitoring system."""
    try:
        from .monitoring import task_monitor

        queue_name = task.request.delivery_info.get("routing_key", "unknown")
        task_monitor.record_task_start(task_id, task.name, queue_name)
    except Exception:
        # Don't fail if monitoring fails
        pass


@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kwds):
    """Handle task completion."""
    try:
        from .monitoring import task_monitor

        success = state == "SUCCESS"
        task_monitor.record_task_completion(task_id, success, retval)
    except Exception:
        # Don't fail if monitoring fails
        pass


@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, traceback=None, einfo=None, **kwds):
    """Handle task failure - enhanced error tracking."""
    try:
        from .monitoring import task_monitor

        task_monitor.record_task_completion(task_id, success=False, result=str(exception))

        # Check if we need to send alerts for critical failures
        if sender and hasattr(sender, "name"):
            critical_tasks = [
                "django_twilio_call.tasks.process_webhook_callback",
                "django_twilio_call.tasks.update_call_status",
            ]

            if sender.name in critical_tasks:
                # Send alert for critical task failures
                from .tasks import send_critical_alert

                send_critical_alert.delay(task_name=sender.name, task_id=task_id, error=str(exception))
    except Exception:
        # Don't fail if monitoring/alerting fails
        pass


def get_celery_app():
    """Get the Celery application instance."""
    return app

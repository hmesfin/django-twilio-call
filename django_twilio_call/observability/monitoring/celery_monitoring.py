"""Celery monitoring and task performance tracking."""

import logging
import time
from typing import Any, Dict

from celery import signals
from django.utils import timezone

from ..metrics.registry import metrics_registry

logger = logging.getLogger(__name__)


class CeleryMonitoring:
    """Comprehensive Celery task monitoring system."""

    def __init__(self):
        # Task execution metrics
        self.task_total = metrics_registry.register_counter(
            "celery_tasks_total", "Total number of Celery tasks", ["task_name", "status", "queue"]
        )

        self.task_duration = metrics_registry.register_histogram(
            "celery_task_duration_seconds",
            "Task execution duration in seconds",
            ["task_name", "queue"],
            buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0],
        )

        self.task_retry_count = metrics_registry.register_histogram(
            "celery_task_retries", "Number of task retries", ["task_name"], buckets=[0, 1, 2, 3, 5, 10, 20]
        )

        # Queue metrics
        self.queue_length = metrics_registry.register_gauge(
            "celery_queue_length", "Number of tasks in queue", ["queue_name"]
        )

        self.active_tasks = metrics_registry.register_gauge(
            "celery_active_tasks", "Number of currently active tasks", ["worker_name"]
        )

        # Worker metrics
        self.worker_online = metrics_registry.register_gauge(
            "celery_workers_online", "Number of online workers", ["worker_name"]
        )

        self.worker_load = metrics_registry.register_gauge("celery_worker_load", "Worker load average", ["worker_name"])

        # Task-specific metrics for call center operations
        self.recording_processing_time = metrics_registry.register_histogram(
            "celery_recording_processing_seconds",
            "Time to process call recordings",
            ["status"],
            buckets=[1, 5, 10, 30, 60, 300, 600, 1800],
        )

        self.webhook_delivery_time = metrics_registry.register_histogram(
            "celery_webhook_delivery_seconds",
            "Time to deliver webhooks",
            ["webhook_type", "status"],
            buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
        )

        # Task state tracking
        self._task_start_times: Dict[str, float] = {}

        # Connect signal handlers
        self._connect_signals()

    def _connect_signals(self) -> None:
        """Connect Celery signal handlers for monitoring."""

        @signals.task_sent.connect
        def task_sent_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
            """Handle task sent signal."""
            queue_name = kwds.get("queue", "default")
            self.task_total.labels(task_name=task, status="sent", queue=queue_name).inc()

        @signals.task_prerun.connect
        def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
            """Handle task prerun signal."""
            self._task_start_times[task_id] = time.time()

            # Log task start
            logger.info(
                "Task started",
                extra={
                    "task_id": task_id,
                    "task_name": task.name if hasattr(task, "name") else str(task),
                    "args": args,
                    "kwargs": kwargs,
                },
            )

        @signals.task_postrun.connect
        def task_postrun_handler(
            sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kwds
        ):
            """Handle task postrun signal."""
            # Calculate duration
            start_time = self._task_start_times.pop(task_id, None)
            duration = time.time() - start_time if start_time else 0

            task_name = task.name if hasattr(task, "name") else str(task)
            queue_name = getattr(task.request, "delivery_info", {}).get("routing_key", "default")

            # Record metrics
            self.task_total.labels(
                task_name=task_name, status=state.lower() if state else "unknown", queue=queue_name
            ).inc()

            self.task_duration.labels(task_name=task_name, queue=queue_name).observe(duration)

            # Record task-specific metrics
            self._record_task_specific_metrics(task_name, duration, state, retval)

            # Log task completion
            log_level = logging.INFO if state == "SUCCESS" else logging.ERROR
            logger.log(
                log_level,
                "Task completed",
                extra={
                    "task_id": task_id,
                    "task_name": task_name,
                    "state": state,
                    "duration_seconds": duration,
                    "result": str(retval) if retval else None,
                },
            )

        @signals.task_retry.connect
        def task_retry_handler(sender=None, task_id=None, reason=None, traceback=None, einfo=None, **kwds):
            """Handle task retry signal."""
            task_name = sender.name if hasattr(sender, "name") else str(sender)

            # Get retry count
            retry_count = getattr(sender.request, "retries", 0)

            self.task_retry_count.labels(task_name=task_name).observe(retry_count)

            logger.warning(
                "Task retry",
                extra={
                    "task_id": task_id,
                    "task_name": task_name,
                    "retry_count": retry_count,
                    "reason": str(reason),
                },
            )

        @signals.task_failure.connect
        def task_failure_handler(sender=None, task_id=None, exception=None, traceback=None, einfo=None, **kwds):
            """Handle task failure signal."""
            task_name = sender.name if hasattr(sender, "name") else str(sender)

            logger.error(
                "Task failed",
                extra={
                    "task_id": task_id,
                    "task_name": task_name,
                    "exception": str(exception),
                    "traceback": str(traceback),
                },
                exc_info=einfo,
            )

    def _record_task_specific_metrics(self, task_name: str, duration: float, state: str, result: Any) -> None:
        """Record metrics for specific task types."""
        # Recording processing tasks
        if "recording" in task_name.lower():
            status = "success" if state == "SUCCESS" else "failed"
            self.recording_processing_time.labels(status=status).observe(duration)

        # Webhook delivery tasks
        if "webhook" in task_name.lower():
            webhook_type = self._extract_webhook_type(task_name)
            status = "success" if state == "SUCCESS" else "failed"
            self.webhook_delivery_time.labels(webhook_type=webhook_type, status=status).observe(duration)

    def _extract_webhook_type(self, task_name: str) -> str:
        """Extract webhook type from task name."""
        if "call_status" in task_name:
            return "call_status"
        elif "recording" in task_name:
            return "recording"
        elif "transcription" in task_name:
            return "transcription"
        else:
            return "unknown"

    def update_queue_metrics(self, queue_stats: Dict[str, Any]) -> None:
        """Update queue length metrics."""
        for queue_name, stats in queue_stats.items():
            if isinstance(stats, dict) and "length" in stats:
                self.queue_length.labels(queue_name=queue_name).set(stats["length"])

    def update_worker_metrics(self, worker_stats: Dict[str, Any]) -> None:
        """Update worker metrics."""
        for worker_name, stats in worker_stats.items():
            if isinstance(stats, dict):
                # Worker online status
                is_online = stats.get("status") == "online"
                self.worker_online.labels(worker_name=worker_name).set(1 if is_online else 0)

                # Active tasks count
                active_count = stats.get("active", 0)
                self.active_tasks.labels(worker_name=worker_name).set(active_count)

                # Load average
                load_avg = stats.get("loadavg", [0, 0, 0])
                if load_avg:
                    self.worker_load.labels(worker_name=worker_name).set(load_avg[0])


class TaskExecutionTracker:
    """Track detailed task execution for database storage."""

    def __init__(self):
        """Initialize task execution tracker."""
        self._connect_signals()

    def _connect_signals(self) -> None:
        """Connect signals for task execution tracking."""

        @signals.task_prerun.connect
        def track_task_start(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
            """Track task start in database."""
            try:
                from ...models import TaskExecution

                queue_name = getattr(task.request, "delivery_info", {}).get("routing_key", "default")
                worker_name = getattr(task.request, "hostname", "unknown")

                TaskExecution.objects.update_or_create(
                    task_id=task_id,
                    defaults={
                        "task_name": task.name if hasattr(task, "name") else str(task),
                        "status": TaskExecution.Status.STARTED,
                        "queue_name": queue_name,
                        "worker_name": worker_name,
                        "started_at": timezone.now(),
                        "args": list(args) if args else [],
                        "kwargs": dict(kwargs) if kwargs else {},
                    },
                )
            except Exception as e:
                logger.error(f"Failed to track task start: {e}")

        @signals.task_postrun.connect
        def track_task_completion(sender=None, task_id=None, task=None, retval=None, state=None, **kwds):
            """Track task completion in database."""
            try:
                from ...models import TaskExecution

                task_execution = TaskExecution.objects.filter(task_id=task_id).first()
                if task_execution:
                    completed_at = timezone.now()
                    duration = None
                    if task_execution.started_at:
                        duration = (completed_at - task_execution.started_at).total_seconds()

                    # Map Celery states to model states
                    status_mapping = {
                        "SUCCESS": TaskExecution.Status.SUCCESS,
                        "FAILURE": TaskExecution.Status.FAILURE,
                        "RETRY": TaskExecution.Status.RETRY,
                        "REVOKED": TaskExecution.Status.REVOKED,
                    }

                    task_execution.status = status_mapping.get(state, TaskExecution.Status.SUCCESS)
                    task_execution.completed_at = completed_at
                    task_execution.duration_seconds = duration
                    task_execution.result = retval
                    task_execution.save()

            except Exception as e:
                logger.error(f"Failed to track task completion: {e}")

        @signals.task_retry.connect
        def track_task_retry(sender=None, task_id=None, reason=None, einfo=None, **kwds):
            """Track task retry in database."""
            try:
                from ...models import TaskExecution

                task_execution = TaskExecution.objects.filter(task_id=task_id).first()
                if task_execution:
                    task_execution.retry_count += 1
                    task_execution.status = TaskExecution.Status.RETRY
                    task_execution.result = {
                        "retry_reason": str(reason),
                        "error_info": str(einfo) if einfo else None,
                    }
                    task_execution.save()

            except Exception as e:
                logger.error(f"Failed to track task retry: {e}")


# Global monitoring instances
celery_monitoring = CeleryMonitoring()
task_execution_tracker = TaskExecutionTracker()

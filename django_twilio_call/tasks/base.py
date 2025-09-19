"""
Base task classes and utilities for django-twilio-call.

Provides common functionality and patterns used across all task modules.
"""

import hashlib
import logging
from typing import Any, Dict, Optional

from celery import current_task, shared_task
from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)


class BaseTask:
    """
    Base class for all call center tasks.

    Provides common functionality like progress tracking, error handling,
    and result caching.
    """

    def __init__(self, task_name: str):
        self.task_name = task_name

    def update_progress(
        self,
        current: int,
        total: int,
        status: str,
        task_instance=None
    ) -> None:
        """
        Update task progress.

        Args:
            current: Current step number
            total: Total number of steps
            status: Current status message
            task_instance: Celery task instance (optional)
        """
        if task_instance is None:
            task_instance = current_task

        if task_instance:
            task_instance.update_state(
                state='PROGRESS',
                meta={
                    'current': current,
                    'total': total,
                    'status': status,
                    'task_name': self.task_name
                }
            )

    def handle_error(
        self,
        error: Exception,
        context: Dict[str, Any] = None,
        task_instance=None
    ) -> Dict[str, Any]:
        """
        Handle task errors with consistent logging and result format.

        Args:
            error: The exception that occurred
            context: Additional context for logging
            task_instance: Celery task instance (optional)

        Returns:
            Dict: Error result dictionary
        """
        context = context or {}
        error_message = str(error)

        logger.error(
            f"Error in task {self.task_name}: {error_message}",
            extra={
                'task_name': self.task_name,
                'error_type': type(error).__name__,
                'context': context,
            },
            exc_info=True
        )

        if task_instance is None:
            task_instance = current_task

        if task_instance:
            task_instance.update_state(
                state='FAILURE',
                meta={
                    'error': error_message,
                    'error_type': type(error).__name__,
                    'task_name': self.task_name,
                    'context': context
                }
            )

        return {
            'success': False,
            'error': error_message,
            'error_type': type(error).__name__,
            'task_name': self.task_name
        }

    def cache_result(
        self,
        key: str,
        result: Any,
        timeout: int = 3600
    ) -> None:
        """
        Cache task result.

        Args:
            key: Cache key
            result: Result to cache
            timeout: Cache timeout in seconds
        """
        cache_key = f"task_result:{self.task_name}:{key}"
        cache.set(cache_key, result, timeout)

    def get_cached_result(self, key: str) -> Any:
        """
        Get cached task result.

        Args:
            key: Cache key

        Returns:
            Cached result or None
        """
        cache_key = f"task_result:{self.task_name}:{key}"
        return cache.get(cache_key)

    def generate_idempotency_key(self, *args, **kwargs) -> str:
        """
        Generate an idempotency key for task execution.

        Args:
            *args: Task arguments
            **kwargs: Task keyword arguments

        Returns:
            str: Idempotency key
        """
        content = f"{self.task_name}:{args}:{sorted(kwargs.items())}"
        return hashlib.md5(content.encode()).hexdigest()


class ProgressTrackingMixin:
    """
    Mixin to add progress tracking to tasks.
    """

    def track_progress(
        self,
        step: int,
        total_steps: int,
        message: str,
        data: Dict[str, Any] = None
    ) -> None:
        """
        Track and update task progress.

        Args:
            step: Current step number
            total_steps: Total number of steps
            message: Progress message
            data: Additional progress data
        """
        progress_data = {
            'current': step,
            'total': total_steps,
            'status': message,
            'percentage': int((step / total_steps) * 100) if total_steps > 0 else 0
        }

        if data:
            progress_data['data'] = data

        if hasattr(self, 'update_state'):
            self.update_state(state='PROGRESS', meta=progress_data)


class TransactionMixin:
    """
    Mixin to add database transaction support to tasks.
    """

    def run_in_transaction(self, func, *args, **kwargs):
        """
        Execute function within a database transaction.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result
        """
        with transaction.atomic():
            return func(*args, **kwargs)


class RetryMixin:
    """
    Mixin to add intelligent retry logic to tasks.
    """

    def should_retry(self, exception: Exception, retry_count: int) -> bool:
        """
        Determine if task should be retried based on exception type and count.

        Args:
            exception: The exception that occurred
            retry_count: Current retry count

        Returns:
            bool: Whether to retry the task
        """
        # Don't retry for certain exception types
        non_retryable_exceptions = (
            ValueError,
            TypeError,
            AttributeError,
        )

        if isinstance(exception, non_retryable_exceptions):
            return False

        # Don't retry after max attempts
        max_retries = getattr(self, 'max_retries', 3)
        return retry_count < max_retries

    def get_retry_delay(self, retry_count: int) -> int:
        """
        Calculate retry delay with exponential backoff.

        Args:
            retry_count: Current retry count

        Returns:
            int: Delay in seconds
        """
        base_delay = getattr(self, 'base_retry_delay', 60)
        max_delay = getattr(self, 'max_retry_delay', 3600)

        delay = min(base_delay * (2 ** retry_count), max_delay)
        return delay


def create_task_execution_record(
    task_id: str,
    task_name: str,
    args: tuple = (),
    kwargs: Dict[str, Any] = None,
    queue_name: str = 'default'
) -> Optional[Any]:
    """
    Create a task execution record for monitoring.

    Args:
        task_id: Celery task ID
        task_name: Name of the task
        args: Task arguments
        kwargs: Task keyword arguments
        queue_name: Queue name

    Returns:
        TaskExecution model instance or None
    """
    try:
        from ..models import TaskExecution

        return TaskExecution.objects.create(
            task_id=task_id,
            task_name=task_name,
            args=list(args) if args else [],
            kwargs=kwargs or {},
            queue_name=queue_name,
            status=TaskExecution.Status.PENDING
        )
    except Exception as e:
        logger.error(f"Failed to create task execution record: {e}")
        return None


def update_task_execution_record(
    task_id: str,
    status: str,
    result: Any = None,
    error_message: str = None
) -> None:
    """
    Update task execution record with completion status.

    Args:
        task_id: Celery task ID
        status: Task status
        result: Task result
        error_message: Error message if failed
    """
    try:
        from django.utils import timezone
        from ..models import TaskExecution

        execution = TaskExecution.objects.filter(task_id=task_id).first()
        if not execution:
            return

        execution.status = status
        execution.completed_at = timezone.now()

        if execution.started_at:
            duration = (execution.completed_at - execution.started_at).total_seconds()
            execution.duration_seconds = duration

        if result is not None:
            execution.result = result

        if error_message:
            execution.result = {'error': error_message}

        execution.save()

    except Exception as e:
        logger.error(f"Failed to update task execution record: {e}")


class BaseCallCenterTask(BaseTask, ProgressTrackingMixin, TransactionMixin, RetryMixin):
    """
    Comprehensive base class for all call center tasks.

    Combines all common functionality needed by call center tasks.
    """

    def __init__(self, task_name: str):
        super().__init__(task_name)
        self.max_retries = 3
        self.base_retry_delay = 60
        self.max_retry_delay = 3600

    def execute(self, *args, **kwargs):
        """
        Execute the task with full error handling and monitoring.

        This method should be overridden by subclasses.
        """
        raise NotImplementedError("Subclasses must implement execute method")

    def run_with_monitoring(self, task_instance, *args, **kwargs):
        """
        Run task with full monitoring and error handling.

        Args:
            task_instance: Celery task instance
            *args: Task arguments
            **kwargs: Task keyword arguments

        Returns:
            Task result
        """
        task_id = task_instance.request.id if task_instance else None

        # Create execution record
        execution = create_task_execution_record(
            task_id=task_id,
            task_name=self.task_name,
            args=args,
            kwargs=kwargs
        )

        try:
            # Mark as started
            if execution:
                from django.utils import timezone
                execution.status = execution.Status.STARTED
                execution.started_at = timezone.now()
                execution.save()

            # Execute the task
            result = self.execute(*args, **kwargs)

            # Update as successful
            update_task_execution_record(
                task_id=task_id,
                status='SUCCESS',
                result=result
            )

            return result

        except Exception as e:
            # Handle error
            error_result = self.handle_error(e, task_instance=task_instance)

            # Update as failed
            update_task_execution_record(
                task_id=task_id,
                status='FAILURE',
                error_message=str(e)
            )

            # Decide whether to retry
            retry_count = getattr(task_instance, 'request', {}).get('retries', 0)
            if self.should_retry(e, retry_count):
                delay = self.get_retry_delay(retry_count)
                raise task_instance.retry(countdown=delay, exc=e)

            return error_result
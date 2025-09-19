"""Advanced error handling and fault tolerance for async tasks."""

import random
import time
import traceback
from typing import Dict, Optional, Type

from celery.exceptions import Ignore, Retry
from django.core.cache import cache
from django.utils import timezone


class TaskErrorHandler:
    """Advanced error handling and recovery strategies for call center tasks."""

    def __init__(self):
        """Initialize error handler with strategy mappings."""
        self.error_strategies = {
            "connection_error": self.handle_connection_error,
            "timeout_error": self.handle_timeout_error,
            "validation_error": self.handle_validation_error,
            "business_logic_error": self.handle_business_logic_error,
            "resource_exhaustion": self.handle_resource_exhaustion,
            "twilio_api_error": self.handle_twilio_api_error,
            "database_error": self.handle_database_error,
            "external_service_error": self.handle_external_service_error,
        }

    def handle_task_error(self, task, exc: Exception, args: tuple, kwargs: dict) -> None:
        """Central error handling logic for all task failures.

        Args:
            task: Celery task instance
            exc: Exception that occurred
            args: Task arguments
            kwargs: Task keyword arguments

        Raises:
            Retry: If task should be retried
            Ignore: If task should be ignored
            Exception: If task should fail

        """
        error_type = self.classify_error(exc)
        error_context = {
            "task_name": task.name,
            "task_id": task.request.id,
            "error_type": error_type,
            "error_message": str(exc),
            "stack_trace": traceback.format_exc(),
            "args": args,
            "kwargs": kwargs,
            "retries": task.request.retries,
            "max_retries": task.max_retries,
            "timestamp": timezone.now().isoformat(),
        }

        # Log error with context
        self.log_error(error_context)

        # Record error metrics
        self.record_error_metrics(error_context)

        # Apply error handling strategy
        strategy = self.error_strategies.get(error_type, self.handle_generic_error)
        strategy(task, exc, error_context)

    def classify_error(self, exc: Exception) -> str:
        """Classify error type for appropriate handling strategy.

        Args:
            exc: Exception to classify

        Returns:
            Error classification string

        """
        error_name = type(exc).__name__
        error_message = str(exc).lower()

        # Connection and network errors
        if any(keyword in error_name.lower() for keyword in ["connection", "network", "timeout"]):
            return "connection_error"

        # Timeout errors
        if "timeout" in error_name.lower() or "timeout" in error_message:
            return "timeout_error"

        # Validation errors
        if any(keyword in error_name.lower() for keyword in ["validation", "invalid", "malformed"]):
            return "validation_error"

        # Resource exhaustion
        if any(keyword in error_name.lower() for keyword in ["memory", "disk", "space"]):
            return "resource_exhaustion"

        # Twilio API errors
        if "twilio" in error_message or any(
            keyword in error_message for keyword in ["api error", "unauthorized", "forbidden", "rate limit"]
        ):
            return "twilio_api_error"

        # Database errors
        if any(keyword in error_name.lower() for keyword in ["database", "db", "sql", "integrity"]):
            return "database_error"

        # External service errors
        if any(keyword in error_message for keyword in ["http", "service unavailable", "503", "502", "504"]):
            return "external_service_error"

        # Business logic errors (custom exceptions)
        if hasattr(exc, "__module__") and "django_twilio_call" in exc.__module__:
            return "business_logic_error"

        return "generic_error"

    def handle_connection_error(self, task, exc: Exception, context: Dict) -> None:
        """Handle connection-related errors with exponential backoff.

        Args:
            task: Celery task instance
            exc: Connection exception
            context: Error context dictionary

        """
        if context["retries"] < task.max_retries:
            # Calculate exponential backoff with jitter
            base_delay = getattr(task, "connection_retry_delay", 60)  # 1 minute default
            max_delay = getattr(task, "max_connection_delay", 3600)  # 1 hour max

            delay = min(base_delay * (2 ** context["retries"]), max_delay)
            jitter = random.uniform(0.5, 1.5)  # Add jitter to prevent thundering herd
            final_delay = int(delay * jitter)

            # Check circuit breaker
            if self._is_circuit_open(task.name, "connection"):
                final_delay *= 2  # Double delay if circuit is open

            self._log_retry_attempt(context, final_delay, "connection error")

            raise task.retry(countdown=final_delay, exc=exc)
        else:
            # Send to dead letter queue and alert
            self._handle_max_retries_exceeded(task, exc, context)
            raise Ignore()

    def handle_timeout_error(self, task, exc: Exception, context: Dict) -> None:
        """Handle timeout errors by adjusting task parameters.

        Args:
            task: Celery task instance
            exc: Timeout exception
            context: Error context dictionary

        """
        if context["retries"] < task.max_retries:
            # Increase timeout for retry
            current_timeout = context["kwargs"].get("timeout", 300)
            new_timeout = min(current_timeout * 1.5, 1800)  # Max 30 minutes
            context["kwargs"]["timeout"] = new_timeout

            # Progressive delay
            delay = 120 * (context["retries"] + 1)  # 2, 4, 6 minutes

            self._log_retry_attempt(context, delay, f"timeout error (new timeout: {new_timeout}s)")

            raise task.retry(countdown=delay, kwargs=context["kwargs"], exc=exc)
        else:
            self._escalate_timeout_error(context)
            raise Ignore()

    def handle_validation_error(self, task, exc: Exception, context: Dict) -> None:
        """Handle validation errors (usually don't retry).

        Args:
            task: Celery task instance
            exc: Validation exception
            context: Error context dictionary

        """
        # Log validation error for analysis
        self._log_validation_error(context)

        # Try input sanitization once
        if context["retries"] == 0 and hasattr(task, "sanitize_input"):
            try:
                sanitized_kwargs = task.sanitize_input(context["kwargs"])
                if sanitized_kwargs != context["kwargs"]:
                    self._log_retry_attempt(context, 30, "validation error with sanitized input")
                    raise task.retry(kwargs=sanitized_kwargs, exc=exc, max_retries=1)
            except Exception:
                pass  # Sanitization failed, proceed to ignore

        # Don't retry validation errors by default
        raise Ignore()

    def handle_business_logic_error(self, task, exc: Exception, context: Dict) -> None:
        """Handle business logic errors with custom recovery.

        Args:
            task: Celery task instance
            exc: Business logic exception
            context: Error context dictionary

        """
        # Check for custom recovery strategy
        if hasattr(task, "recovery_strategy"):
            try:
                recovery_result = task.recovery_strategy(exc, context)
                if recovery_result and recovery_result.should_retry:
                    delay = recovery_result.retry_delay or 60
                    modified_kwargs = recovery_result.modified_kwargs or context["kwargs"]

                    self._log_retry_attempt(context, delay, "business logic error with recovery")

                    raise task.retry(countdown=delay, kwargs=modified_kwargs, exc=exc)
            except Exception as recovery_exc:
                self._log_error({**context, "recovery_error": str(recovery_exc), "recovery_failed": True})

        # Log for business team review
        self._log_business_logic_error(context)
        raise Ignore()

    def handle_resource_exhaustion(self, task, exc: Exception, context: Dict) -> None:
        """Handle resource exhaustion with adaptive strategies.

        Args:
            task: Celery task instance
            exc: Resource exhaustion exception
            context: Error context dictionary

        """
        if context["retries"] < task.max_retries:
            # Progressive delay to allow resource recovery
            delay = 300 * (context["retries"] + 1)  # 5, 10, 15 minutes

            # Try to reduce resource usage
            self._adjust_resource_usage(context["kwargs"])

            self._log_retry_attempt(context, delay, "resource exhaustion")

            raise task.retry(countdown=delay, kwargs=context["kwargs"], exc=exc)
        else:
            self._alert_resource_exhaustion(context)
            raise Ignore()

    def handle_twilio_api_error(self, task, exc: Exception, context: Dict) -> None:
        """Handle Twilio API errors with rate limiting awareness.

        Args:
            task: Celery task instance
            exc: Twilio API exception
            context: Error context dictionary

        """
        error_message = str(exc).lower()

        # Handle rate limiting
        if "rate limit" in error_message or "429" in error_message:
            if context["retries"] < task.max_retries:
                # Extract retry-after if available, otherwise use exponential backoff
                delay = self._extract_retry_after(exc) or (60 * (2 ** context["retries"]))
                delay = min(delay, 3600)  # Max 1 hour

                self._log_retry_attempt(context, delay, "Twilio rate limit")

                raise task.retry(countdown=delay, exc=exc)

        # Handle authentication errors (don't retry)
        elif any(keyword in error_message for keyword in ["unauthorized", "forbidden", "invalid credentials"]):
            self._alert_twilio_auth_error(context)
            raise Ignore()

        # Handle service errors (retry with backoff)
        elif any(keyword in error_message for keyword in ["service unavailable", "internal error", "5"]):
            if context["retries"] < task.max_retries:
                delay = 120 * (context["retries"] + 1)  # 2, 4, 6 minutes

                self._log_retry_attempt(context, delay, "Twilio service error")

                raise task.retry(countdown=delay, exc=exc)

        # Default Twilio error handling
        else:
            if context["retries"] < task.max_retries:
                delay = 60 + (30 * context["retries"])  # 60, 90, 120 seconds

                self._log_retry_attempt(context, delay, "Twilio API error")

                raise task.retry(countdown=delay, exc=exc)

        # Max retries exceeded
        self._alert_twilio_persistent_error(context)
        raise Ignore()

    def handle_database_error(self, task, exc: Exception, context: Dict) -> None:
        """Handle database errors with connection pool awareness.

        Args:
            task: Celery task instance
            exc: Database exception
            context: Error context dictionary

        """
        error_message = str(exc).lower()

        # Handle connection pool exhaustion
        if any(keyword in error_message for keyword in ["connection", "pool", "too many"]):
            if context["retries"] < task.max_retries:
                # Use longer delays for connection issues
                delay = 30 * (2 ** context["retries"])  # 30, 60, 120 seconds

                self._log_retry_attempt(context, delay, "database connection error")

                # Close any existing connections
                from django.db import connections

                connections.close_all()

                raise task.retry(countdown=delay, exc=exc)

        # Handle deadlocks and lock timeouts
        elif any(keyword in error_message for keyword in ["deadlock", "lock", "timeout"]):
            if context["retries"] < task.max_retries:
                # Short delay with jitter for deadlocks
                delay = random.randint(1, 10) + (context["retries"] * 5)

                self._log_retry_attempt(context, delay, "database lock error")

                raise task.retry(countdown=delay, exc=exc)

        # Handle integrity constraint violations (usually don't retry)
        elif any(keyword in error_message for keyword in ["integrity", "constraint", "duplicate"]):
            self._log_database_integrity_error(context)
            raise Ignore()

        # Generic database error
        else:
            if context["retries"] < task.max_retries:
                delay = 60 + (30 * context["retries"])

                self._log_retry_attempt(context, delay, "database error")

                raise task.retry(countdown=delay, exc=exc)

        # Max retries exceeded
        self._alert_database_persistent_error(context)
        raise Ignore()

    def handle_external_service_error(self, task, exc: Exception, context: Dict) -> None:
        """Handle external service errors with circuit breaker pattern.

        Args:
            task: Celery task instance
            exc: External service exception
            context: Error context dictionary

        """
        service_name = self._extract_service_name(exc, context)

        # Check circuit breaker
        if self._is_circuit_open(task.name, service_name):
            delay = getattr(task, "circuit_open_delay", 300)  # 5 minutes default
            self._log_retry_attempt(context, delay, f"circuit breaker open for {service_name}")
            raise task.retry(countdown=delay, exc=exc)

        if context["retries"] < task.max_retries:
            # Record failure for circuit breaker
            self._record_service_failure(task.name, service_name)

            # Exponential backoff
            delay = 60 * (2 ** context["retries"])
            delay = min(delay, 1800)  # Max 30 minutes

            self._log_retry_attempt(context, delay, f"external service error ({service_name})")

            raise task.retry(countdown=delay, exc=exc)
        else:
            self._alert_external_service_persistent_error(context, service_name)
            raise Ignore()

    def handle_generic_error(self, task, exc: Exception, context: Dict) -> None:
        """Handle generic/unknown errors with conservative retry strategy.

        Args:
            task: Celery task instance
            exc: Generic exception
            context: Error context dictionary

        """
        if context["retries"] < task.max_retries:
            # Conservative exponential backoff
            delay = 120 * (2 ** context["retries"])  # 2, 4, 8 minutes
            delay = min(delay, 1800)  # Max 30 minutes

            self._log_retry_attempt(context, delay, "generic error")

            raise task.retry(countdown=delay, exc=exc)
        else:
            self._handle_max_retries_exceeded(task, exc, context)
            raise Ignore()

    # ======================
    # HELPER METHODS
    # ======================

    def log_error(self, context: Dict) -> None:
        """Log error with comprehensive context."""
        import logging

        task_name = context.get("task_name", "unknown")
        logger = logging.getLogger(f"celery.error.{task_name}")

        logger.error(
            "Task failed: %(error_message)s",
            context,
            extra={
                "task_id": context.get("task_id"),
                "error_type": context.get("error_type"),
                "retries": context.get("retries"),
                "stack_trace": context.get("stack_trace"),
            },
            exc_info=False,  # We already have the stack trace
        )

    def record_error_metrics(self, context: Dict) -> None:
        """Record error metrics for monitoring."""
        try:
            from .models import TaskExecution

            # Update or create task execution record
            TaskExecution.objects.update_or_create(
                task_id=context["task_id"],
                defaults={
                    "task_name": context["task_name"],
                    "status": TaskExecution.Status.FAILURE,
                    "retry_count": context["retries"],
                    "result": {
                        "error_type": context["error_type"],
                        "error_message": context["error_message"][:1000],  # Truncate long messages
                        "failed_at": context["timestamp"],
                    },
                },
            )

            # Update error rate cache for circuit breaker
            cache_key = f"error_rate_{context['task_name']}"
            error_count = cache.get(cache_key, 0) + 1
            cache.set(cache_key, error_count, 3600)  # 1 hour window

        except Exception:
            # Don't fail the error handler if metrics recording fails
            pass

    def _log_retry_attempt(self, context: Dict, delay: int, reason: str) -> None:
        """Log retry attempt with context."""
        import logging

        task_name = context.get("task_name", "unknown")
        logger = logging.getLogger(f"celery.retry.{task_name}")

        logger.info(
            "Retrying task %(task_id)s (attempt %(retry_count)d) in %(delay)ds: %(reason)s",
            {
                "task_id": context["task_id"],
                "retry_count": context["retries"] + 1,
                "delay": delay,
                "reason": reason,
            },
        )

    def _is_circuit_open(self, task_name: str, service_name: str) -> bool:
        """Check if circuit breaker is open for a service."""
        cache_key = f"circuit_breaker_{task_name}_{service_name}"
        return cache.get(cache_key, False)

    def _record_service_failure(self, task_name: str, service_name: str) -> None:
        """Record service failure for circuit breaker logic."""
        failure_key = f"service_failures_{task_name}_{service_name}"
        failure_count = cache.get(failure_key, 0) + 1

        # Open circuit if failure threshold exceeded
        failure_threshold = 5  # Open after 5 failures
        if failure_count >= failure_threshold:
            circuit_key = f"circuit_breaker_{task_name}_{service_name}"
            cache.set(circuit_key, True, 300)  # Open for 5 minutes

        cache.set(failure_key, failure_count, 300)

    def _extract_service_name(self, exc: Exception, context: Dict) -> str:
        """Extract service name from exception or context."""
        error_message = str(exc).lower()

        # Try to identify service from error message
        if "twilio" in error_message:
            return "twilio"
        elif "aws" in error_message or "s3" in error_message:
            return "aws"
        elif "redis" in error_message:
            return "redis"
        elif "database" in error_message or "postgres" in error_message:
            return "database"

        # Default to task name
        return context.get("task_name", "unknown")

    def _extract_retry_after(self, exc: Exception) -> Optional[int]:
        """Extract retry-after header from HTTP exceptions."""
        # This would depend on the specific exception type
        # For now, return None to use default backoff
        return None

    def _adjust_resource_usage(self, kwargs: Dict) -> None:
        """Adjust task parameters to reduce resource usage."""
        # Reduce batch sizes
        if "batch_size" in kwargs:
            kwargs["batch_size"] = max(kwargs["batch_size"] // 2, 10)

        if "chunk_size" in kwargs:
            kwargs["chunk_size"] = max(kwargs["chunk_size"] // 2, 100)

        # Reduce concurrent operations
        if "max_workers" in kwargs:
            kwargs["max_workers"] = max(kwargs["max_workers"] // 2, 1)

    def _handle_max_retries_exceeded(self, task, exc: Exception, context: Dict) -> None:
        """Handle case where maximum retries have been exceeded."""
        self._send_to_dead_letter_queue(context)
        self._send_max_retries_alert(context)

    def _send_to_dead_letter_queue(self, context: Dict) -> None:
        """Send failed task to dead letter queue for manual processing."""
        try:
            from .models import TaskExecution

            # Mark as failed in database
            TaskExecution.objects.update_or_create(
                task_id=context["task_id"],
                defaults={
                    "status": TaskExecution.Status.FAILURE,
                    "result": {
                        "error_type": context["error_type"],
                        "error_message": context["error_message"],
                        "max_retries_exceeded": True,
                        "dead_letter_at": context["timestamp"],
                    },
                    "completed_at": timezone.now(),
                },
            )

            # Cache for dead letter queue processing
            cache_key = f"dead_letter_{context['task_id']}"
            cache.set(cache_key, context, 86400)  # Keep for 24 hours

        except Exception:
            pass  # Don't fail if dead letter processing fails

    def _send_max_retries_alert(self, context: Dict) -> None:
        """Send alert for tasks that exceeded maximum retries."""
        try:
            from .tasks import send_critical_alert

            send_critical_alert.delay(
                task_name=context["task_name"],
                task_id=context["task_id"],
                error=f"Max retries exceeded: {context['error_message']}",
            )
        except Exception:
            pass  # Don't fail if alert sending fails

    # Alert methods for different error types
    def _escalate_timeout_error(self, context: Dict) -> None:
        """Escalate persistent timeout errors."""
        # Implementation for timeout escalation
        pass

    def _log_validation_error(self, context: Dict) -> None:
        """Log validation errors for analysis."""
        # Implementation for validation error logging
        pass

    def _log_business_logic_error(self, context: Dict) -> None:
        """Log business logic errors for review."""
        # Implementation for business logic error logging
        pass

    def _alert_resource_exhaustion(self, context: Dict) -> None:
        """Alert on persistent resource exhaustion."""
        # Implementation for resource exhaustion alerts
        pass

    def _alert_twilio_auth_error(self, context: Dict) -> None:
        """Alert on Twilio authentication errors."""
        # Implementation for Twilio auth error alerts
        pass

    def _alert_twilio_persistent_error(self, context: Dict) -> None:
        """Alert on persistent Twilio errors."""
        # Implementation for persistent Twilio error alerts
        pass

    def _log_database_integrity_error(self, context: Dict) -> None:
        """Log database integrity errors."""
        # Implementation for database integrity error logging
        pass

    def _alert_database_persistent_error(self, context: Dict) -> None:
        """Alert on persistent database errors."""
        # Implementation for persistent database error alerts
        pass

    def _alert_external_service_persistent_error(self, context: Dict, service_name: str) -> None:
        """Alert on persistent external service errors."""
        # Implementation for external service error alerts
        pass


# Global error handler instance
error_handler = TaskErrorHandler()


class FaultTolerantTaskMixin:
    """Mixin for tasks that need enhanced error handling."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Enhanced failure handling using the error handler."""
        try:
            error_handler.handle_task_error(self, exc, args, kwargs)
        except (Retry, Ignore):
            # Let Celery handle retries and ignores
            raise
        except Exception:
            # If error handler fails, use default failure handling
            super().on_failure(exc, task_id, args, kwargs, einfo)

    def sanitize_input(self, kwargs: Dict) -> Dict:
        """Override to implement input sanitization for validation errors."""
        # Default implementation - subclasses can override
        return kwargs

    def recovery_strategy(self, exc: Exception, context: Dict):
        """Override to implement custom recovery logic for business errors."""
        # Default implementation - subclasses can override
        from dataclasses import dataclass

        @dataclass
        class RecoveryResult:
            should_retry: bool = False
            retry_delay: int = 60
            modified_kwargs: Optional[Dict] = None

        return RecoveryResult()


class CircuitBreaker:
    """Circuit breaker pattern for external service calls."""

    def __init__(
        self, failure_threshold: int = 5, recovery_timeout: int = 300, expected_exception: Type[Exception] = Exception
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Time to wait before attempting reset (seconds)
            expected_exception: Exception type to catch

        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

    def __call__(self, func):
        """Decorator to apply circuit breaker pattern."""

        def wrapper(*args, **kwargs):
            service_name = func.__name__

            # Check if circuit is open
            if self._is_circuit_open(service_name):
                if self._should_attempt_reset(service_name):
                    self._set_circuit_half_open(service_name)
                else:
                    raise Exception(f"Circuit breaker is OPEN for {service_name}")

            try:
                result = func(*args, **kwargs)
                self._on_success(service_name)
                return result
            except self.expected_exception as e:
                self._on_failure(service_name)
                raise e

        return wrapper

    def _is_circuit_open(self, service_name: str) -> bool:
        """Check if circuit is open."""
        return cache.get(f"circuit_open_{service_name}", False)

    def _should_attempt_reset(self, service_name: str) -> bool:
        """Check if enough time has passed to attempt reset."""
        last_failure_time = cache.get(f"circuit_last_failure_{service_name}")
        if not last_failure_time:
            return True

        return time.time() - last_failure_time >= self.recovery_timeout

    def _set_circuit_half_open(self, service_name: str) -> None:
        """Set circuit to half-open state."""
        cache.set(f"circuit_half_open_{service_name}", True, self.recovery_timeout)

    def _on_success(self, service_name: str) -> None:
        """Handle successful call - reset circuit."""
        cache.delete(f"circuit_failures_{service_name}")
        cache.delete(f"circuit_open_{service_name}")
        cache.delete(f"circuit_half_open_{service_name}")
        cache.delete(f"circuit_last_failure_{service_name}")

    def _on_failure(self, service_name: str) -> None:
        """Handle failed call - potentially open circuit."""
        failure_count = cache.get(f"circuit_failures_{service_name}", 0) + 1
        cache.set(f"circuit_failures_{service_name}", failure_count, self.recovery_timeout)
        cache.set(f"circuit_last_failure_{service_name}", time.time(), self.recovery_timeout)

        if failure_count >= self.failure_threshold:
            cache.set(f"circuit_open_{service_name}", True, self.recovery_timeout)


def with_circuit_breaker(failure_threshold: int = 5, recovery_timeout: int = 300):
    """Decorator to add circuit breaker to a function.

    Args:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Time to wait before attempting reset (seconds)

    """

    def decorator(func):
        circuit_breaker = CircuitBreaker(failure_threshold, recovery_timeout)
        return circuit_breaker(func)

    return decorator


def with_retry_backoff(max_retries: int = 3, base_delay: int = 60, max_delay: int = 3600):
    """Decorator to add retry logic with exponential backoff.

    Args:
        max_retries: Maximum number of retries
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds

    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc

                    if attempt >= max_retries:
                        break

                    # Calculate delay with exponential backoff and jitter
                    delay = min(base_delay * (2**attempt), max_delay)
                    jitter = random.uniform(0.5, 1.5)
                    actual_delay = delay * jitter

                    time.sleep(actual_delay)

            # If we get here, all retries failed
            raise last_exception

        return wrapper

    return decorator

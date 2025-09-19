"""Structured logging formatters for call center operations."""

import logging
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

from django.conf import settings
from pythonjsonlogger import jsonlogger


class StructuredJsonFormatter(jsonlogger.JsonFormatter):
    """Enhanced JSON formatter with call center context."""

    def __init__(self, *args, **kwargs):
        # Define which fields to include in every log record
        self.base_fields = [
            "asctime",
            "name",
            "levelname",
            "message",
            "pathname",
            "lineno",
            "funcName",
            "process",
            "thread",
        ]
        super().__init__(*args, **kwargs)

    def add_fields(self, log_record: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]) -> None:
        """Add custom fields to log record."""
        super().add_fields(log_record, record, message_dict)

        # Add timestamp in ISO format
        log_record["timestamp"] = datetime.utcnow().isoformat() + "Z"

        # Add service information
        log_record["service"] = "django-twilio-call"
        log_record["version"] = getattr(settings, "APP_VERSION", "1.0.0")
        log_record["environment"] = getattr(settings, "ENVIRONMENT", "development")

        # Add request context if available
        if hasattr(record, "request_id"):
            log_record["request_id"] = record.request_id

        if hasattr(record, "trace_id"):
            log_record["trace_id"] = record.trace_id

        if hasattr(record, "span_id"):
            log_record["span_id"] = record.span_id

        # Add user context if available
        if hasattr(record, "user_id"):
            log_record["user_id"] = record.user_id

        if hasattr(record, "agent_id"):
            log_record["agent_id"] = record.agent_id

        # Add call center context
        if hasattr(record, "call_id"):
            log_record["call_id"] = record.call_id

        if hasattr(record, "queue_id"):
            log_record["queue_id"] = record.queue_id

        if hasattr(record, "task_id"):
            log_record["task_id"] = record.task_id

        # Add business context
        if hasattr(record, "business_context"):
            log_record["business_context"] = record.business_context

        # Add error context for exceptions
        if record.exc_info:
            log_record["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Add performance metrics if available
        if hasattr(record, "duration_ms"):
            log_record["duration_ms"] = record.duration_ms

        if hasattr(record, "db_queries"):
            log_record["db_queries"] = record.db_queries

        # Add custom fields from extra parameter
        if hasattr(record, "_custom_fields"):
            log_record.update(record._custom_fields)

        # Ensure message is always present
        if "message" not in log_record:
            log_record["message"] = record.getMessage()


class CallCenterLogFormatter(logging.Formatter):
    """Human-readable formatter for call center operations."""

    def __init__(self):
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:
        """Format log record for human readability."""
        # Base format
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname.ljust(8)
        name = record.name

        # Build context string
        context_parts = []

        if hasattr(record, "request_id"):
            context_parts.append(f"req:{record.request_id[:8]}")

        if hasattr(record, "call_id"):
            context_parts.append(f"call:{record.call_id}")

        if hasattr(record, "agent_id"):
            context_parts.append(f"agent:{record.agent_id}")

        if hasattr(record, "task_id"):
            context_parts.append(f"task:{record.task_id[:8]}")

        context_str = f"[{' '.join(context_parts)}]" if context_parts else ""

        # Format message
        message = record.getMessage()

        # Add performance info if available
        perf_info = ""
        if hasattr(record, "duration_ms"):
            perf_info = f" ({record.duration_ms:.2f}ms"
            if hasattr(record, "db_queries"):
                perf_info += f", {record.db_queries} queries"
            perf_info += ")"

        # Build final message
        formatted = f"{timestamp} {level} {name}: {context_str} {message}{perf_info}"

        # Add exception if present
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)

        return formatted


class CallCenterLogger:
    """Enhanced logger for call center operations."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

    def info(self, message: str, **context) -> None:
        """Log info message with context."""
        self._log(logging.INFO, message, **context)

    def warning(self, message: str, **context) -> None:
        """Log warning message with context."""
        self._log(logging.WARNING, message, **context)

    def error(self, message: str, **context) -> None:
        """Log error message with context."""
        self._log(logging.ERROR, message, **context)

    def debug(self, message: str, **context) -> None:
        """Log debug message with context."""
        self._log(logging.DEBUG, message, **context)

    def critical(self, message: str, **context) -> None:
        """Log critical message with context."""
        self._log(logging.CRITICAL, message, **context)

    def log_call_event(self, call_id: str, event: str, **context) -> None:
        """Log call-specific event."""
        self._log(logging.INFO, f"Call event: {event}", call_id=call_id, **context)

    def log_agent_activity(self, agent_id: str, activity: str, **context) -> None:
        """Log agent activity."""
        self._log(logging.INFO, f"Agent activity: {activity}", agent_id=agent_id, **context)

    def log_queue_operation(self, queue_id: str, operation: str, **context) -> None:
        """Log queue operation."""
        self._log(logging.INFO, f"Queue operation: {operation}", queue_id=queue_id, **context)

    def log_twilio_api_call(self, endpoint: str, method: str, duration_ms: float, status_code: int, **context) -> None:
        """Log Twilio API call."""
        self._log(
            logging.INFO,
            f"Twilio API call: {method} {endpoint}",
            duration_ms=duration_ms,
            status_code=status_code,
            **context,
        )

    def log_task_execution(
        self, task_id: str, task_name: str, status: str, duration_ms: Optional[float] = None, **context
    ) -> None:
        """Log task execution."""
        message = f"Task {status}: {task_name}"
        level = logging.INFO if status == "success" else logging.ERROR

        log_context = {"task_id": task_id, **context}
        if duration_ms is not None:
            log_context["duration_ms"] = duration_ms

        self._log(level, message, **log_context)

    def log_webhook_processing(self, webhook_type: str, status: str, duration_ms: float, **context) -> None:
        """Log webhook processing."""
        level = logging.INFO if status == "success" else logging.WARNING
        self._log(
            level,
            f"Webhook processed: {webhook_type}",
            webhook_type=webhook_type,
            status=status,
            duration_ms=duration_ms,
            **context,
        )

    def log_performance_issue(self, component: str, metric: str, value: float, threshold: float, **context) -> None:
        """Log performance issue."""
        self._log(
            logging.WARNING,
            f"Performance issue: {component} {metric} ({value}) exceeds threshold ({threshold})",
            component=component,
            metric=metric,
            value=value,
            threshold=threshold,
            **context,
        )

    def _log(self, level: int, message: str, **context) -> None:
        """Internal log method with context."""
        # Create log record with extra context
        extra = {"_custom_fields": context}

        # Add business context categorization
        business_context = self._categorize_business_context(context)
        if business_context:
            extra["business_context"] = business_context

        self.logger.log(level, message, extra=extra)

    def _categorize_business_context(self, context: Dict[str, Any]) -> Optional[str]:
        """Categorize log context for business analysis."""
        if "call_id" in context:
            return "call_operations"
        elif "agent_id" in context:
            return "agent_activity"
        elif "queue_id" in context:
            return "queue_management"
        elif "task_id" in context:
            return "background_processing"
        elif "webhook_type" in context:
            return "webhook_processing"
        else:
            return "general"


# Structured logging configuration for Django settings
STRUCTURED_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": StructuredJsonFormatter, "format": "%(levelname)s %(name)s %(message)s"},
        "call_center": {
            "()": CallCenterLogFormatter,
        },
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
        "console_readable": {
            "class": "logging.StreamHandler",
            "formatter": "call_center",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/var/log/django-twilio-call/app.log",
            "maxBytes": 50 * 1024 * 1024,  # 50MB
            "backupCount": 10,
            "formatter": "json",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/var/log/django-twilio-call/error.log",
            "maxBytes": 50 * 1024 * 1024,  # 50MB
            "backupCount": 10,
            "formatter": "json",
            "level": "ERROR",
        },
        "call_center_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/var/log/django-twilio-call/call_center.log",
            "maxBytes": 100 * 1024 * 1024,  # 100MB
            "backupCount": 5,
            "formatter": "json",
        },
        "performance_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/var/log/django-twilio-call/performance.log",
            "maxBytes": 50 * 1024 * 1024,  # 50MB
            "backupCount": 5,
            "formatter": "json",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "error_file"],
            "level": "ERROR",
            "propagate": False,
        },
        "django_twilio_call": {
            "handlers": ["console", "call_center_file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "django_twilio_call.observability": {
            "handlers": ["console", "performance_file"],
            "level": "INFO",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "celery.task": {
            "handlers": ["console", "call_center_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

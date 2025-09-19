"""Observability configuration and integration helpers."""

import logging
from typing import Any, Dict, Optional

from django.conf import settings

from .logging.formatters import CallCenterLogger

logger = logging.getLogger(__name__)


class ObservabilityConfig:
    """Configuration manager for observability features."""

    def __init__(self):
        self.config = getattr(settings, "OBSERVABILITY_CONFIG", {})

    def is_monitoring_enabled(self) -> bool:
        """Check if monitoring is enabled."""
        return self.config.get("enabled", True)

    def is_metrics_collection_enabled(self) -> bool:
        """Check if metrics collection is enabled."""
        return self.config.get("metrics", {}).get("enabled", True)

    def is_tracing_enabled(self) -> bool:
        """Check if distributed tracing is enabled."""
        return self.config.get("tracing", {}).get("enabled", False)

    def is_alerting_enabled(self) -> bool:
        """Check if alerting is enabled."""
        return self.config.get("alerting", {}).get("enabled", True)

    def get_metrics_export_interval(self) -> int:
        """Get metrics export interval in seconds."""
        return self.config.get("metrics", {}).get("export_interval", 30)

    def get_alert_config(self) -> Dict[str, Any]:
        """Get alert configuration."""
        return self.config.get("alerting", {})

    def get_tracing_config(self) -> Dict[str, Any]:
        """Get tracing configuration."""
        return self.config.get("tracing", {})


def setup_observability() -> None:
    """Setup observability components during app initialization."""
    config = ObservabilityConfig()

    if not config.is_monitoring_enabled():
        logger.info("Observability monitoring is disabled")
        return

    logger.info("Initializing observability components...")

    # Initialize metrics collection
    if config.is_metrics_collection_enabled():
        _setup_metrics_collection()

    # Initialize distributed tracing
    if config.is_tracing_enabled():
        _setup_distributed_tracing(config.get_tracing_config())

    # Initialize alerting
    if config.is_alerting_enabled():
        _setup_alerting(config.get_alert_config())

    logger.info("Observability initialization complete")


def _setup_metrics_collection() -> None:
    """Setup metrics collection."""
    try:
        logger.info("Metrics collection initialized")
    except Exception as e:
        logger.error(f"Failed to initialize metrics collection: {e}")


def _setup_distributed_tracing(tracing_config: Dict[str, Any]) -> None:
    """Setup distributed tracing."""
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        # Configure tracer provider
        trace.set_tracer_provider(TracerProvider())

        # Configure Jaeger exporter if enabled
        jaeger_config = tracing_config.get("jaeger", {})
        if jaeger_config.get("enabled", False):
            jaeger_exporter = JaegerExporter(
                agent_host_name=jaeger_config.get("host", "localhost"),
                agent_port=jaeger_config.get("port", 14268),
            )
            span_processor = BatchSpanProcessor(jaeger_exporter)
            trace.get_tracer_provider().add_span_processor(span_processor)

        logger.info("Distributed tracing initialized")
    except ImportError:
        logger.warning("OpenTelemetry not available, skipping tracing setup")
    except Exception as e:
        logger.error(f"Failed to initialize distributed tracing: {e}")


def _setup_alerting(alert_config: Dict[str, Any]) -> None:
    """Setup alerting system."""
    try:
        # Alert configuration is handled by the alert manager itself
        logger.info("Alerting system initialized")
    except Exception as e:
        logger.error(f"Failed to initialize alerting: {e}")


def get_call_center_logger(name: str) -> CallCenterLogger:
    """Get a call center logger instance."""
    return CallCenterLogger(name)


# Decorators for adding observability to existing code
def monitor_performance(func_name: Optional[str] = None):
    """Decorator to monitor function performance."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            import time

            from .metrics.registry import metrics_registry

            start_time = time.time()
            function_name = func_name or f"{func.__module__}.{func.__name__}"

            # Create histogram metric if it doesn't exist
            duration_metric = metrics_registry.register_histogram(
                "function_duration_seconds", "Function execution duration", ["function_name"]
            )

            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                duration_metric.labels(function_name=function_name).observe(duration)
                return result
            except Exception as e:
                duration = time.time() - start_time
                duration_metric.labels(function_name=function_name).observe(duration)

                # Log error
                logger.error(
                    f"Function {function_name} failed",
                    extra={
                        "function_name": function_name,
                        "duration_ms": duration * 1000,
                        "error": str(e),
                    },
                )
                raise

        return wrapper

    return decorator


def track_business_event(event_type: str, **metadata):
    """Decorator to track business events."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            from .metrics.registry import metrics_registry

            # Create counter metric if it doesn't exist
            event_metric = metrics_registry.register_counter(
                "business_events_total", "Business events tracked", ["event_type", "status"]
            )

            try:
                result = func(*args, **kwargs)
                event_metric.labels(event_type=event_type, status="success").inc()

                # Log business event
                logger.info(
                    f"Business event: {event_type}",
                    extra={
                        "event_type": event_type,
                        "status": "success",
                        "metadata": metadata,
                    },
                )

                return result
            except Exception as e:
                event_metric.labels(event_type=event_type, status="failure").inc()

                # Log failed business event
                logger.error(
                    f"Business event failed: {event_type}",
                    extra={
                        "event_type": event_type,
                        "status": "failure",
                        "error": str(e),
                        "metadata": metadata,
                    },
                )
                raise

        return wrapper

    return decorator


# Context managers for observability
class PerformanceTracker:
    """Context manager for tracking operation performance."""

    def __init__(self, operation_name: str, **tags):
        self.operation_name = operation_name
        self.tags = tags
        self.start_time = None
        self.logger = get_call_center_logger(__name__)

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time

        if exc_type is None:
            self.logger.info(f"Operation completed: {self.operation_name}", duration_ms=duration * 1000, **self.tags)
        else:
            self.logger.error(
                f"Operation failed: {self.operation_name}", duration_ms=duration * 1000, error=str(exc_val), **self.tags
            )


# Global configuration instance
observability_config = ObservabilityConfig()


# Default Django settings for observability
OBSERVABILITY_SETTINGS = {
    "OBSERVABILITY_CONFIG": {
        "enabled": True,
        "metrics": {
            "enabled": True,
            "export_interval": 30,
        },
        "tracing": {
            "enabled": False,
            "jaeger": {
                "enabled": False,
                "host": "localhost",
                "port": 14268,
            },
        },
        "alerting": {
            "enabled": True,
            "email": {
                "enabled": False,
                "recipients": [],
            },
            "slack": {
                "enabled": False,
                "webhook_url": "",
            },
            "pagerduty": {
                "enabled": False,
                "routing_key": "",
            },
        },
    },
    "MIDDLEWARE": [
        # Add these to existing middleware
        "django_twilio_call.observability.middleware.performance.DatabaseQueryCountMiddleware",
        "django_twilio_call.observability.middleware.performance.PerformanceMonitoringMiddleware",
        "django_twilio_call.observability.middleware.business.BusinessMetricsMiddleware",
    ],
    "LOGGING": {
        # Import structured logging configuration
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "django_twilio_call.observability.logging.formatters.StructuredJsonFormatter",
            },
            "call_center": {
                "()": "django_twilio_call.observability.logging.formatters.CallCenterLogFormatter",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": "/var/log/django-twilio-call/app.log",
                "maxBytes": 50 * 1024 * 1024,
                "backupCount": 10,
                "formatter": "json",
            },
        },
        "loggers": {
            "django_twilio_call": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
        },
    },
}

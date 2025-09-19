"""Integration helpers for adding observability to existing code."""

import functools
import time
from typing import Any, Callable, Dict, Optional

from django.db import models
from django.http import HttpRequest, HttpResponse

from .config import get_call_center_logger, observability_config
from .metrics.collectors import twilio_metrics

logger = get_call_center_logger(__name__)


def instrument_view(view_func: Callable) -> Callable:
    """Decorator to instrument Django views with observability."""

    @functools.wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not observability_config.is_monitoring_enabled():
            return view_func(request, *args, **kwargs)

        start_time = time.time()
        view_name = f"{view_func.__module__}.{view_func.__name__}"

        try:
            response = view_func(request, *args, **kwargs)
            duration = time.time() - start_time

            # Log view execution
            logger.info(
                f"View executed: {view_name}",
                extra={
                    "view_name": view_name,
                    "method": request.method,
                    "path": request.path,
                    "status_code": response.status_code,
                    "duration_ms": duration * 1000,
                    "user_id": getattr(request.user, "id", None)
                    if hasattr(request, "user") and request.user.is_authenticated
                    else None,
                },
            )

            return response

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"View failed: {view_name}",
                extra={
                    "view_name": view_name,
                    "method": request.method,
                    "path": request.path,
                    "duration_ms": duration * 1000,
                    "error": str(e),
                },
            )
            raise

    return wrapper


def instrument_service_method(method_func: Callable) -> Callable:
    """Decorator to instrument service methods with observability."""

    @functools.wraps(method_func)
    def wrapper(*args, **kwargs) -> Any:
        if not observability_config.is_monitoring_enabled():
            return method_func(*args, **kwargs)

        start_time = time.time()
        method_name = f"{method_func.__module__}.{method_func.__qualname__}"

        try:
            result = method_func(*args, **kwargs)
            duration = time.time() - start_time

            # Log service method execution
            logger.info(
                f"Service method executed: {method_name}",
                extra={
                    "method_name": method_name,
                    "duration_ms": duration * 1000,
                },
            )

            return result

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Service method failed: {method_name}",
                extra={
                    "method_name": method_name,
                    "duration_ms": duration * 1000,
                    "error": str(e),
                },
            )
            raise

    return wrapper


def track_twilio_api_call(endpoint: str, method: str = "POST"):
    """Decorator to track Twilio API calls."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                # Record successful API call
                twilio_metrics.record_api_call(
                    endpoint=endpoint,
                    method=method,
                    duration=duration,
                    status_code=200,  # Assume success if no exception
                )

                logger.log_twilio_api_call(
                    endpoint=endpoint, method=method, duration_ms=duration * 1000, status_code=200
                )

                return result

            except Exception as e:
                duration = time.time() - start_time
                status_code = getattr(e, "status", 500)
                error_code = getattr(e, "code", "unknown")

                # Record failed API call
                twilio_metrics.record_api_call(
                    endpoint=endpoint, method=method, duration=duration, status_code=status_code, error_code=error_code
                )

                logger.log_twilio_api_call(
                    endpoint=endpoint, method=method, duration_ms=duration * 1000, status_code=status_code, error=str(e)
                )

                raise

        return wrapper

    return decorator


def track_call_operation(operation: str):
    """Decorator to track call center operations."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                logger.log_call_event(
                    call_id=_extract_call_id(args, kwargs), event=f"{operation}_success", duration_ms=duration * 1000
                )

                return result

            except Exception as e:
                duration = time.time() - start_time

                logger.log_call_event(
                    call_id=_extract_call_id(args, kwargs),
                    event=f"{operation}_failed",
                    duration_ms=duration * 1000,
                    error=str(e),
                )

                raise

        return wrapper

    return decorator


def track_agent_activity(activity: str):
    """Decorator to track agent activities."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                logger.log_agent_activity(
                    agent_id=_extract_agent_id(args, kwargs),
                    activity=f"{activity}_success",
                    duration_ms=duration * 1000,
                )

                return result

            except Exception as e:
                duration = time.time() - start_time

                logger.log_agent_activity(
                    agent_id=_extract_agent_id(args, kwargs),
                    activity=f"{activity}_failed",
                    duration_ms=duration * 1000,
                    error=str(e),
                )

                raise

        return wrapper

    return decorator


def monitor_model_save(model_class: models.Model):
    """Class decorator to monitor model save operations."""
    original_save = model_class.save

    @functools.wraps(original_save)
    def instrumented_save(self, *args, **kwargs):
        start_time = time.time()
        model_name = self.__class__.__name__
        is_creation = self.pk is None

        try:
            result = original_save(self, *args, **kwargs)
            duration = time.time() - start_time

            operation = "create" if is_creation else "update"
            logger.debug(
                f"Model {operation}: {model_name}",
                extra={
                    "model_name": model_name,
                    "operation": operation,
                    "duration_ms": duration * 1000,
                    "object_id": str(self.pk),
                },
            )

            return result

        except Exception as e:
            duration = time.time() - start_time
            operation = "create" if is_creation else "update"

            logger.error(
                f"Model {operation} failed: {model_name}",
                extra={
                    "model_name": model_name,
                    "operation": operation,
                    "duration_ms": duration * 1000,
                    "error": str(e),
                },
            )

            raise

    model_class.save = instrumented_save
    return model_class


def _extract_call_id(args: tuple, kwargs: dict) -> Optional[str]:
    """Extract call ID from function arguments."""
    # Look for call_id in kwargs
    if "call_id" in kwargs:
        return kwargs["call_id"]

    # Look for call object in args/kwargs
    for arg in args:
        if hasattr(arg, "public_id"):
            return str(arg.public_id)

    if "call" in kwargs and hasattr(kwargs["call"], "public_id"):
        return str(kwargs["call"].public_id)

    return None


def _extract_agent_id(args: tuple, kwargs: dict) -> Optional[str]:
    """Extract agent ID from function arguments."""
    # Look for agent_id in kwargs
    if "agent_id" in kwargs:
        return kwargs["agent_id"]

    # Look for agent object in args/kwargs
    for arg in args:
        if hasattr(arg, "public_id"):
            return str(arg.public_id)

    if "agent" in kwargs and hasattr(kwargs["agent"], "public_id"):
        return str(kwargs["agent"].public_id)

    return None


class ObservabilityMixin:
    """Mixin to add observability to Django views."""

    def dispatch(self, request, *args, **kwargs):
        """Override dispatch to add observability."""
        if not observability_config.is_monitoring_enabled():
            return super().dispatch(request, *args, **kwargs)

        start_time = time.time()
        view_name = self.__class__.__name__

        try:
            response = super().dispatch(request, *args, **kwargs)
            duration = time.time() - start_time

            logger.info(
                f"Class-based view executed: {view_name}",
                extra={
                    "view_name": view_name,
                    "method": request.method,
                    "path": request.path,
                    "status_code": response.status_code,
                    "duration_ms": duration * 1000,
                },
            )

            return response

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Class-based view failed: {view_name}",
                extra={
                    "view_name": view_name,
                    "method": request.method,
                    "path": request.path,
                    "duration_ms": duration * 1000,
                    "error": str(e),
                },
            )
            raise


# Helper functions for manual instrumentation
def record_business_metric(metric_name: str, value: float, tags: Dict[str, str] = None):
    """Record a business metric manually."""
    from .metrics.registry import metrics_registry

    # Create gauge metric if it doesn't exist
    gauge = metrics_registry.register_gauge(
        f"business_{metric_name}", f"Business metric: {metric_name}", list(tags.keys()) if tags else []
    )

    if tags:
        gauge.labels(**tags).set(value)
    else:
        gauge.set(value)

    logger.info(
        f"Business metric recorded: {metric_name}",
        extra={
            "metric_name": metric_name,
            "value": value,
            "tags": tags or {},
        },
    )


def evaluate_alerts_for_metrics(metrics: Dict[str, Any]):
    """Evaluate alerts for provided metrics."""
    if not observability_config.is_alerting_enabled():
        return

    from .alerts.manager import alert_manager

    alert_manager.evaluate_metrics(metrics)

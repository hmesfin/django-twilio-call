"""Performance monitoring middleware for Django requests."""

import logging
import time
import uuid

from django.http import HttpRequest, HttpResponse
from django.urls import resolve
from django.utils.deprecation import MiddlewareMixin
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from ..metrics.registry import metrics_registry

logger = logging.getLogger(__name__)


class PerformanceMonitoringMiddleware(MiddlewareMixin):
    """Comprehensive performance monitoring middleware for Django requests."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.tracer = trace.get_tracer(__name__)

        # Initialize metrics
        self.request_count = metrics_registry.register_counter(
            "django_requests_total", "Total number of HTTP requests", ["method", "endpoint", "status_code", "user_type"]
        )

        self.request_duration = metrics_registry.register_histogram(
            "django_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )

        self.active_requests = metrics_registry.register_gauge(
            "django_active_requests", "Number of active HTTP requests"
        )

        self.response_size = metrics_registry.register_histogram(
            "django_response_size_bytes",
            "HTTP response size in bytes",
            ["method", "endpoint"],
            buckets=[100, 1000, 10000, 100000, 1000000, 10000000],
        )

        self.db_queries = metrics_registry.register_histogram(
            "django_db_queries_per_request",
            "Number of database queries per request",
            ["method", "endpoint"],
            buckets=[1, 5, 10, 25, 50, 100],
        )

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Process request with comprehensive monitoring."""
        start_time = time.time()
        request_id = str(uuid.uuid4())

        # Add request ID to request for correlation
        request.request_id = request_id

        # Track active requests
        self.active_requests.inc()

        try:
            # Create distributed tracing span
            with self.tracer.start_as_current_span("http_request") as span:
                # Set span attributes
                self._set_span_attributes(span, request, request_id)

                # Process request
                response = self.get_response(request)

                # Calculate metrics
                duration = time.time() - start_time
                endpoint = self._get_endpoint_name(request)
                user_type = self._get_user_type(request)

                # Record metrics
                self._record_metrics(request, response, duration, endpoint, user_type)

                # Update span with response data
                self._update_span_with_response(span, response, duration)

                # Log request details
                self._log_request(request, response, duration, endpoint, request_id)

                return response

        except Exception as e:
            # Handle exceptions in monitoring
            logger.error(
                f"Error in performance monitoring: {e}",
                extra={"request_id": request_id, "path": request.path, "method": request.method},
            )
            raise
        finally:
            # Always decrement active requests
            self.active_requests.dec()

    def _set_span_attributes(self, span: trace.Span, request: HttpRequest, request_id: str) -> None:
        """Set distributed tracing span attributes."""
        span.set_attributes(
            {
                "http.method": request.method,
                "http.url": request.build_absolute_uri(),
                "http.scheme": request.scheme,
                "http.host": request.get_host(),
                "http.target": request.path,
                "http.user_agent": request.META.get("HTTP_USER_AGENT", ""),
                "request.id": request_id,
                "user.id": getattr(request.user, "id", None)
                if hasattr(request, "user") and request.user.is_authenticated
                else None,
                "user.username": getattr(request.user, "username", None)
                if hasattr(request, "user") and request.user.is_authenticated
                else None,
                "request.content_length": request.META.get("CONTENT_LENGTH", 0),
                "request.remote_addr": self._get_client_ip(request),
            }
        )

    def _update_span_with_response(self, span: trace.Span, response: HttpResponse, duration: float) -> None:
        """Update span with response information."""
        span.set_attributes(
            {
                "http.status_code": response.status_code,
                "http.response_size": len(response.content) if hasattr(response, "content") else 0,
                "response.duration": duration,
            }
        )

        # Set span status based on HTTP status code
        if response.status_code >= 400:
            span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
        else:
            span.set_status(Status(StatusCode.OK))

    def _record_metrics(
        self, request: HttpRequest, response: HttpResponse, duration: float, endpoint: str, user_type: str
    ) -> None:
        """Record performance metrics."""
        method = request.method
        status_code = str(response.status_code)

        # Record request count
        self.request_count.labels(method=method, endpoint=endpoint, status_code=status_code, user_type=user_type).inc()

        # Record request duration
        self.request_duration.labels(method=method, endpoint=endpoint).observe(duration)

        # Record response size
        response_size_bytes = len(response.content) if hasattr(response, "content") else 0
        self.response_size.labels(method=method, endpoint=endpoint).observe(response_size_bytes)

        # Record database queries if available
        if hasattr(request, "_db_query_count"):
            self.db_queries.labels(method=method, endpoint=endpoint).observe(request._db_query_count)

    def _log_request(
        self, request: HttpRequest, response: HttpResponse, duration: float, endpoint: str, request_id: str
    ) -> None:
        """Log request details with structured format."""
        log_data = {
            "request_id": request_id,
            "method": request.method,
            "path": request.path,
            "endpoint": endpoint,
            "status_code": response.status_code,
            "duration_ms": round(duration * 1000, 2),
            "response_size": len(response.content) if hasattr(response, "content") else 0,
            "user_id": getattr(request.user, "id", None)
            if hasattr(request, "user") and request.user.is_authenticated
            else None,
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "client_ip": self._get_client_ip(request),
            "referer": request.META.get("HTTP_REFERER", ""),
        }

        # Add database query count if available
        if hasattr(request, "_db_query_count"):
            log_data["db_queries"] = request._db_query_count

        # Log at appropriate level based on status code
        if response.status_code >= 500:
            logger.error("HTTP request completed", extra=log_data)
        elif response.status_code >= 400:
            logger.warning("HTTP request completed", extra=log_data)
        else:
            logger.info("HTTP request completed", extra=log_data)

    def _get_endpoint_name(self, request: HttpRequest) -> str:
        """Extract endpoint name from request."""
        try:
            resolver_match = resolve(request.path)
            if resolver_match.namespace:
                return f"{resolver_match.namespace}:{resolver_match.url_name}"
            return resolver_match.url_name or request.path
        except Exception:
            return request.path

    def _get_user_type(self, request: HttpRequest) -> str:
        """Determine user type for metrics labeling."""
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return "anonymous"

        if request.user.is_superuser:
            return "superuser"
        elif request.user.is_staff:
            return "staff"
        elif hasattr(request.user, "agent_profile"):
            return "agent"
        else:
            return "user"

    def _get_client_ip(self, request: HttpRequest) -> str:
        """Get real client IP address."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()

        x_real_ip = request.META.get("HTTP_X_REAL_IP")
        if x_real_ip:
            return x_real_ip

        return request.META.get("REMOTE_ADDR", "unknown")


class DatabaseQueryCountMiddleware(MiddlewareMixin):
    """Middleware to count database queries per request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Count database queries during request processing."""
        from django.db import connection

        # Store initial query count
        initial_queries = len(connection.queries)

        response = self.get_response(request)

        # Calculate query count for this request
        request._db_query_count = len(connection.queries) - initial_queries

        return response

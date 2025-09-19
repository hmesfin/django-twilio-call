"""Business metrics collection middleware for call center operations."""

import logging
import time
from typing import Any, Dict

from django.http import HttpRequest, HttpResponse
from django.urls import resolve
from django.utils.deprecation import MiddlewareMixin

from ..metrics.registry import metrics_registry

logger = logging.getLogger(__name__)


class BusinessMetricsMiddleware(MiddlewareMixin):
    """Middleware for collecting call center business metrics."""

    def __init__(self, get_response):
        self.get_response = get_response

        # Initialize business metrics
        self.api_usage = metrics_registry.register_counter(
            "callcenter_api_usage_total", "Total API endpoint usage", ["endpoint", "user_type", "operation"]
        )

        self.agent_actions = metrics_registry.register_counter(
            "callcenter_agent_actions_total", "Total agent actions", ["action_type", "agent_id", "queue"]
        )

        self.call_operations = metrics_registry.register_counter(
            "callcenter_call_operations_total", "Total call operations", ["operation", "direction", "status", "queue"]
        )

        self.queue_operations = metrics_registry.register_counter(
            "callcenter_queue_operations_total", "Total queue operations", ["operation", "queue_name"]
        )

        self.webhook_processing = metrics_registry.register_counter(
            "callcenter_webhook_processing_total", "Total webhook processing events", ["webhook_type", "status"]
        )

        self.user_sessions = metrics_registry.register_gauge(
            "callcenter_active_user_sessions", "Number of active user sessions by type", ["user_type"]
        )

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Process request and collect business metrics."""
        start_time = time.time()

        # Extract business context before processing
        business_context = self._extract_business_context(request)

        response = self.get_response(request)

        # Collect metrics after processing
        self._collect_business_metrics(request, response, business_context, start_time)

        return response

    def _extract_business_context(self, request: HttpRequest) -> Dict[str, Any]:
        """Extract business context from request."""
        context = {
            "endpoint_name": self._get_endpoint_name(request),
            "user_type": self._get_user_type(request),
            "agent_id": None,
            "queue_name": None,
            "operation_type": None,
        }

        # Extract agent information
        if hasattr(request, "user") and request.user.is_authenticated:
            if hasattr(request.user, "agent_profile"):
                context["agent_id"] = str(request.user.agent_profile.public_id)

        # Extract operation type from URL and method
        context["operation_type"] = self._determine_operation_type(request)

        # Extract queue information from request data
        if hasattr(request, "data") and isinstance(request.data, dict):
            queue_id = request.data.get("queue") or request.data.get("queue_id")
            if queue_id:
                context["queue_name"] = self._get_queue_name(queue_id)

        return context

    def _collect_business_metrics(
        self, request: HttpRequest, response: HttpResponse, context: Dict[str, Any], start_time: float
    ) -> None:
        """Collect business-specific metrics."""
        endpoint = context["endpoint_name"]
        user_type = context["user_type"]
        operation = context["operation_type"]

        # Record API usage
        self.api_usage.labels(endpoint=endpoint, user_type=user_type, operation=operation).inc()

        # Record agent-specific actions
        if context["agent_id"] and self._is_agent_action(endpoint):
            self.agent_actions.labels(
                action_type=operation, agent_id=context["agent_id"], queue=context["queue_name"] or "unknown"
            ).inc()

        # Record call operations
        if self._is_call_operation(endpoint):
            call_data = self._extract_call_data(request, response)
            self.call_operations.labels(
                operation=operation,
                direction=call_data.get("direction", "unknown"),
                status=call_data.get("status", "unknown"),
                queue=context["queue_name"] or "unknown",
            ).inc()

        # Record queue operations
        if self._is_queue_operation(endpoint) and context["queue_name"]:
            self.queue_operations.labels(operation=operation, queue_name=context["queue_name"]).inc()

        # Record webhook processing
        if self._is_webhook_endpoint(endpoint):
            webhook_type = self._extract_webhook_type(request)
            webhook_status = "success" if response.status_code < 400 else "failed"
            self.webhook_processing.labels(webhook_type=webhook_type, status=webhook_status).inc()

        # Update active user sessions
        self._update_user_sessions(user_type)

    def _get_endpoint_name(self, request: HttpRequest) -> str:
        """Get normalized endpoint name."""
        try:
            resolver_match = resolve(request.path)
            if resolver_match.namespace:
                return f"{resolver_match.namespace}:{resolver_match.url_name}"
            return resolver_match.url_name or "unknown"
        except Exception:
            return "unknown"

    def _get_user_type(self, request: HttpRequest) -> str:
        """Determine user type for business metrics."""
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return "anonymous"

        if request.user.is_superuser:
            return "admin"
        elif hasattr(request.user, "agent_profile"):
            return "agent"
        else:
            return "user"

    def _determine_operation_type(self, request: HttpRequest) -> str:
        """Determine operation type from request."""
        method = request.method.lower()
        path = request.path.lower()

        # Map HTTP methods to operations
        method_map = {
            "get": "read",
            "post": "create",
            "put": "update",
            "patch": "update",
            "delete": "delete",
        }

        # Check for specific operations in path
        if "transfer" in path:
            return "transfer"
        elif "hold" in path:
            return "hold"
        elif "conference" in path:
            return "conference"
        elif "recording" in path:
            return "recording"
        elif "webhook" in path:
            return "webhook"
        elif "status" in path:
            return "status_update"
        elif "position" in path:
            return "queue_position"
        elif "statistics" in path:
            return "statistics"

        return method_map.get(method, "unknown")

    def _get_queue_name(self, queue_id: str) -> str:
        """Get queue name from queue ID."""
        try:
            from ...models import Queue

            queue = Queue.objects.filter(public_id=queue_id).first()
            return queue.name if queue else "unknown"
        except Exception:
            return "unknown"

    def _is_agent_action(self, endpoint: str) -> bool:
        """Check if endpoint represents agent action."""
        agent_endpoints = [
            "agent-status-update",
            "agent-break",
            "agent-login",
            "agent-logout",
            "call-transfer",
            "call-hold",
            "call-unhold",
        ]
        return any(ae in endpoint for ae in agent_endpoints)

    def _is_call_operation(self, endpoint: str) -> bool:
        """Check if endpoint represents call operation."""
        call_endpoints = [
            "call-create",
            "call-update",
            "call-transfer",
            "call-hold",
            "call-conference",
            "call-recording",
        ]
        return any(ce in endpoint for ce in call_endpoints)

    def _is_queue_operation(self, endpoint: str) -> bool:
        """Check if endpoint represents queue operation."""
        queue_endpoints = [
            "queue-create",
            "queue-update",
            "queue-statistics",
            "queue-position",
        ]
        return any(qe in endpoint for qe in queue_endpoints)

    def _is_webhook_endpoint(self, endpoint: str) -> bool:
        """Check if endpoint is a webhook."""
        return "webhook" in endpoint.lower()

    def _extract_call_data(self, request: HttpRequest, response: HttpResponse) -> Dict[str, str]:
        """Extract call-specific data from request/response."""
        data = {}

        # Try to extract from request data
        if hasattr(request, "data") and isinstance(request.data, dict):
            data["direction"] = request.data.get("direction", "unknown")
            data["status"] = request.data.get("status", "unknown")

        # Try to extract from response data for GET requests
        if request.method == "GET" and hasattr(response, "data"):
            if isinstance(response.data, dict):
                data["direction"] = response.data.get("direction", data.get("direction", "unknown"))
                data["status"] = response.data.get("status", data.get("status", "unknown"))

        return data

    def _extract_webhook_type(self, request: HttpRequest) -> str:
        """Extract webhook type from request."""
        path = request.path.lower()

        if "call-status" in path:
            return "call_status"
        elif "recording" in path:
            return "recording"
        elif "transcription" in path:
            return "transcription"
        elif "conference" in path:
            return "conference"
        else:
            return "unknown"

    def _update_user_sessions(self, user_type: str) -> None:
        """Update active user sessions gauge."""
        # This is a simplified implementation
        # In production, you'd want to track actual sessions
        if user_type != "anonymous":
            # For now, just increment - in practice, you'd use session tracking
            pass

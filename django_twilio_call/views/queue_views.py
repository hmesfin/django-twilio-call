"""Queue management views for django-twilio-call.

Handles CRUD operations, queue statistics, and routing operations.
"""

import logging

from rest_framework import status
from rest_framework.decorators import action

from ..exceptions import QueueServiceError
from ..models import Queue
from ..permissions import CanAccessQueue
from ..serializers import (
    CallSerializer,
    QueueSerializer,
    QueueStatisticsSerializer,
)
from ..services import queue_service
from .base import BaseCallCenterViewSet

logger = logging.getLogger(__name__)


class QueueViewSet(BaseCallCenterViewSet):
    """ViewSet for Queue model with routing and statistics functionality."""

    queryset = Queue.objects.all()
    serializer_class = QueueSerializer
    permission_classes = [CanAccessQueue]

    def get_queryset(self):
        """Filter queryset based on user permissions and query parameters."""
        queryset = super().get_queryset().prefetch_related("agents__user")

        # Non-admins only see active queues they're assigned to
        if not self.request.user.is_staff:
            if hasattr(self.request.user, "agent_profile"):
                agent = self.request.user.agent_profile
                queryset = queryset.filter(agents=agent, is_active=True)
            else:
                queryset = queryset.none()

        # Filter by active status if requested
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == "true")

        return queryset.order_by("-priority", "name")

    @action(detail=True, methods=["get"])
    def statistics(self, request, public_id=None):
        """Get comprehensive queue statistics.

        Returns current queue state, performance metrics, and historical data.
        """
        queue = self.get_object()
        try:
            stats = queue_service.get_queue_statistics(queue.id)
            serializer = QueueStatisticsSerializer(stats)

            return self.success_response(data=serializer.data, message=f"Statistics retrieved for queue {queue.name}")
        except QueueServiceError as e:
            return self.handle_error(e, f"get statistics for queue {queue.name}")

    @action(detail=True, methods=["post"])
    def activate(self, request, public_id=None):
        """Activate a queue for call routing.

        Activates the queue and makes it available for receiving calls.
        """
        queue = self.get_object()
        try:
            queue_service.activate_queue(queue.id)
            return self.success_response(message=f"Queue {queue.name} activated successfully")
        except QueueServiceError as e:
            return self.handle_error(e, f"activate queue {queue.name}")

    @action(detail=True, methods=["post"])
    def deactivate(self, request, public_id=None):
        """Deactivate a queue.

        Deactivates the queue and stops accepting new calls.
        Existing calls in the queue will continue to be processed.
        """
        queue = self.get_object()
        try:
            queue_service.deactivate_queue(queue.id)
            return self.success_response(message=f"Queue {queue.name} deactivated successfully")
        except QueueServiceError as e:
            return self.handle_error(e, f"deactivate queue {queue.name}")

    @action(detail=True, methods=["get"])
    def metrics(self, request, public_id=None):
        """Get real-time queue metrics.

        Returns current call volume, wait times, agent availability,
        and other real-time operational metrics.
        """
        # Import here to avoid circular imports
        from ..services import routing_service

        queue = self.get_object()
        try:
            metrics = routing_service.get_queue_metrics(queue)
            return self.success_response(data=metrics, message=f"Real-time metrics for queue {queue.name}")
        except Exception as e:
            return self.handle_error(e, f"get metrics for queue {queue.name}")

    @action(detail=True, methods=["post"])
    def route_next(self, request, public_id=None):
        """Manually trigger routing of the next call in queue.

        Forces the queue to attempt routing the next waiting call
        to an available agent.
        """
        queue = self.get_object()
        try:
            routed_call = queue_service.route_next_call(queue.id)
            if routed_call:
                serializer = CallSerializer(routed_call)
                return self.success_response(data={"call": serializer.data}, message="Call routed successfully")
            else:
                return self.success_response(message="No calls to route or no agents available")
        except Exception as e:
            return self.handle_error(e, f"route next call in queue {queue.name}")

    @action(detail=True, methods=["get"])
    def waiting_calls(self, request, public_id=None):
        """Get all calls currently waiting in this queue.

        Returns a list of calls with their position and wait time.
        """
        queue = self.get_object()
        try:
            waiting_calls = queue_service.get_waiting_calls(queue.id)
            calls_data = []

            for idx, call in enumerate(waiting_calls, 1):
                call_data = CallSerializer(call).data
                call_data["queue_position"] = idx
                call_data["wait_time_seconds"] = call.queue_time if hasattr(call, "queue_time") else 0
                calls_data.append(call_data)

            return self.success_response(
                data={"calls": calls_data, "total_waiting": len(calls_data)},
                message=f"Retrieved {len(calls_data)} waiting calls",
            )
        except Exception as e:
            return self.handle_error(e, f"get waiting calls for queue {queue.name}")

    @action(detail=True, methods=["post"])
    def clear_queue(self, request, public_id=None):
        """Clear all waiting calls from the queue.

        This action will end all waiting calls. Use with caution.
        Requires admin permissions.
        """
        if not self.request.user.is_staff:
            return self.handle_error(
                PermissionError("Admin access required"), "clear queue", status_code=status.HTTP_403_FORBIDDEN
            )

        queue = self.get_object()
        try:
            cleared_count = queue_service.clear_queue(queue.id)
            return self.success_response(
                data={"cleared_calls": cleared_count}, message=f"Cleared {cleared_count} calls from queue {queue.name}"
            )
        except Exception as e:
            return self.handle_error(e, f"clear queue {queue.name}")

    @action(detail=True, methods=["patch"])
    def update_priority(self, request, public_id=None):
        """Update the priority of this queue.

        Higher priority queues are processed before lower priority ones.
        """
        queue = self.get_object()
        new_priority = request.data.get("priority")

        if new_priority is None:
            return self.handle_error(
                ValueError("priority is required"), "update queue priority", status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            old_priority = queue.priority
            queue.priority = int(new_priority)
            queue.save()

            return self.success_response(
                data=self.get_serializer(queue).data,
                message=f"Queue priority updated from {old_priority} to {new_priority}",
            )
        except (ValueError, TypeError) as e:
            return self.handle_error(e, "update queue priority", status_code=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return self.handle_error(e, f"update priority for queue {queue.name}")

    @action(detail=True, methods=["post"])
    def assign_agents(self, request, public_id=None):
        """Assign agents to this queue.

        Expects a list of agent public_ids in the request data.
        """
        from ..models import Agent

        queue = self.get_object()
        agent_ids = request.data.get("agent_ids", [])

        if not agent_ids:
            return self.handle_error(
                ValueError("agent_ids list is required"),
                "assign agents to queue",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            agents = Agent.objects.filter(public_id__in=agent_ids, is_active=True)

            if len(agents) != len(agent_ids):
                found_ids = [str(agent.public_id) for agent in agents]
                missing_ids = [aid for aid in agent_ids if aid not in found_ids]
                return self.handle_error(
                    ValueError(f"Agents not found: {missing_ids}"),
                    "assign agents to queue",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            queue.agents.add(*agents)

            return self.success_response(
                data=self.get_serializer(queue).data, message=f"Assigned {len(agents)} agents to queue {queue.name}"
            )
        except Exception as e:
            return self.handle_error(e, f"assign agents to queue {queue.name}")

    @action(detail=True, methods=["post"])
    def remove_agents(self, request, public_id=None):
        """Remove agents from this queue.

        Expects a list of agent public_ids in the request data.
        """
        from ..models import Agent

        queue = self.get_object()
        agent_ids = request.data.get("agent_ids", [])

        if not agent_ids:
            return self.handle_error(
                ValueError("agent_ids list is required"),
                "remove agents from queue",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            agents = Agent.objects.filter(public_id__in=agent_ids)
            queue.agents.remove(*agents)

            return self.success_response(
                data=self.get_serializer(queue).data, message=f"Removed {len(agents)} agents from queue {queue.name}"
            )
        except Exception as e:
            return self.handle_error(e, f"remove agents from queue {queue.name}")

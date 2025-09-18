"""Queue service layer for managing call queues and routing."""

import logging
from typing import Any, Dict, Optional

from django.db import models, transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from ..exceptions import QueueServiceError
from ..models import Agent, Call, CallLog, Queue

logger = logging.getLogger(__name__)


class QueueService:
    """Service for managing call queues and routing."""

    def __init__(self):
        """Initialize queue service."""
        pass

    @transaction.atomic
    def add_call_to_queue(
        self,
        call: Call,
        queue_id: int,
        priority: Optional[int] = None,
    ) -> Call:
        """Add a call to a queue.

        Args:
            call: Call object to queue
            queue_id: Queue ID to add call to
            priority: Optional priority override

        Returns:
            Updated Call object

        Raises:
            QueueServiceError: If queue is full or inactive

        """
        try:
            queue = Queue.objects.get(id=queue_id)

            if not queue.is_active:
                raise QueueServiceError(f"Queue {queue.name} is not active", queue_id=str(queue_id))

            # Check queue capacity
            current_size = Call.objects.filter(
                queue=queue,
                status=Call.Status.QUEUED,
            ).count()

            if current_size >= queue.max_size:
                raise QueueServiceError(
                    f"Queue {queue.name} is full ({current_size}/{queue.max_size})",
                    queue_id=str(queue_id),
                )

            # Update call
            call.queue = queue
            call.status = Call.Status.QUEUED
            call.save(update_fields=["queue", "status"])

            # Log queue entry
            CallLog.objects.create(
                call=call,
                event_type=CallLog.EventType.QUEUED,
                description=f"Call added to queue {queue.name}",
                data={"queue_id": queue_id, "priority": priority or queue.priority},
            )

            logger.info(f"Call {call.twilio_sid} added to queue {queue.name}")

            # Try to route immediately
            self.route_next_call(queue_id)

            return call

        except Queue.DoesNotExist:
            raise QueueServiceError("Queue not found", queue_id=str(queue_id))
        except Exception as e:
            logger.error(f"Failed to add call to queue: {e}")
            raise QueueServiceError(f"Failed to add call to queue: {e}", queue_id=str(queue_id))  # noqa: B904

    def remove_call_from_queue(self, call: Call) -> Call:
        """Remove a call from its queue.

        Args:
            call: Call object to remove from queue

        Returns:
            Updated Call object

        """
        if call.queue:
            queue_name = call.queue.name
            call.queue = None
            call.save(update_fields=["queue"])

            logger.info(f"Call {call.twilio_sid} removed from queue {queue_name}")

        return call

    @transaction.atomic
    def route_next_call(self, queue_id: int) -> Optional[Call]:
        """Route the next call in queue to an available agent.

        Args:
            queue_id: Queue ID to route from

        Returns:
            Routed Call object or None if no routing occurred

        """
        try:
            from .routing_service import routing_service

            queue = Queue.objects.get(id=queue_id)

            if not queue.is_active:
                return None

            # Get next call based on routing strategy
            next_call = self._get_next_call(queue)
            if not next_call:
                return None

            # Use advanced routing service
            agent = routing_service.route_call(next_call, queue)
            if agent:
                logger.info(f"Call {next_call.twilio_sid} routed to agent {agent.extension}")
                return next_call

            logger.debug(f"No available agent for queue {queue.name}")
            return None

        except Queue.DoesNotExist:
            logger.error(f"Queue {queue_id} not found")
            return None
        except Exception as e:
            logger.error(f"Failed to route call from queue {queue_id}: {e}")
            return None

    def _get_next_call(self, queue: Queue) -> Optional[Call]:
        """Get next call from queue based on routing strategy.

        Args:
            queue: Queue object

        Returns:
            Next Call object or None

        """
        base_query = Call.objects.filter(
            queue=queue,
            status=Call.Status.QUEUED,
        )

        if queue.routing_strategy == Queue.RoutingStrategy.FIFO:
            return base_query.order_by("created_at").first()

        elif queue.routing_strategy == Queue.RoutingStrategy.LIFO:
            return base_query.order_by("-created_at").first()

        else:
            # For other strategies, just get oldest for now
            return base_query.order_by("created_at").first()

    def _find_available_agent(self, queue: Queue, call: Call) -> Optional[Agent]:
        """Find an available agent for the queue and call.

        Args:
            queue: Queue object
            call: Call object to route

        Returns:
            Available Agent object or None

        """
        # Base query for available agents
        agents_query = (
            Agent.objects.filter(
                queues=queue,
                status=Agent.Status.AVAILABLE,
                is_active=True,
            )
            .annotate(
                current_calls_count=Count(
                    "calls",
                    filter=Q(calls__status=Call.Status.IN_PROGRESS),
                )
            )
            .filter(current_calls_count__lt=F("max_concurrent_calls"))
        )

        # Apply routing strategy
        if queue.routing_strategy == Queue.RoutingStrategy.ROUND_ROBIN:
            # Get agent who hasn't received a call for the longest time
            agents = agents_query.order_by("last_status_change")

        elif queue.routing_strategy == Queue.RoutingStrategy.LEAST_BUSY:
            # Get agent with least calls today
            agents = agents_query.order_by("calls_handled_today", "last_status_change")

        elif queue.routing_strategy == Queue.RoutingStrategy.SKILLS_BASED:
            # Filter by required skills
            if queue.required_skills:
                # Agents must have all required skills
                for skill in queue.required_skills:
                    agents_query = agents_query.filter(skills__contains=[skill])

            agents = agents_query.order_by("last_status_change")

        else:
            # Default: get any available agent
            agents = agents_query.order_by("?")  # Random selection

        return agents.first()

    @transaction.atomic
    def _assign_call_to_agent(self, call: Call, agent: Agent, queue: Queue) -> Call:
        """Assign a call to an agent.

        Args:
            call: Call object
            agent: Agent object
            queue: Queue object

        Returns:
            Updated Call object

        """
        # Update call
        call.agent = agent
        call.status = Call.Status.RINGING
        queue_time = (timezone.now() - call.created_at).seconds
        call.queue_time = queue_time
        call.save(update_fields=["agent", "status", "queue_time"])

        # Update agent status
        agent.status = Agent.Status.BUSY
        agent.last_status_change = timezone.now()
        agent.calls_handled_today = F("calls_handled_today") + 1
        agent.save(update_fields=["status", "last_status_change", "calls_handled_today"])

        # Log assignment
        CallLog.objects.create(
            call=call,
            event_type=CallLog.EventType.CONNECTED,
            description=f"Call routed to agent {agent.extension}",
            agent=agent,
            data={
                "queue_id": queue.id,
                "queue_name": queue.name,
                "queue_time": queue_time,
                "routing_strategy": queue.routing_strategy,
            },
        )

        logger.info(f"Call {call.twilio_sid} assigned to agent {agent.extension}")

        return call

    def get_queue_statistics(self, queue_id: int) -> Dict[str, Any]:
        """Get statistics for a queue.

        Args:
            queue_id: Queue ID

        Returns:
            Dict containing queue statistics

        """
        try:
            queue = Queue.objects.get(id=queue_id)

            # Get call counts
            calls_in_queue = Call.objects.filter(
                queue=queue,
                status=Call.Status.QUEUED,
            ).count()

            # Calculate average wait time
            completed_calls = Call.objects.filter(
                queue=queue,
                status=Call.Status.COMPLETED,
                queue_time__gt=0,
            ).aggregate(
                avg_queue_time=models.Avg("queue_time"),
                max_queue_time=models.Max("queue_time"),
            )

            # Get available agents
            available_agents = Agent.objects.filter(
                queues=queue,
                status=Agent.Status.AVAILABLE,
                is_active=True,
            ).count()

            total_agents = queue.agents.filter(is_active=True).count()

            return {
                "queue_id": queue.id,
                "queue_name": queue.name,
                "is_active": queue.is_active,
                "calls_in_queue": calls_in_queue,
                "max_size": queue.max_size,
                "available_agents": available_agents,
                "total_agents": total_agents,
                "avg_wait_time": completed_calls["avg_queue_time"] or 0,
                "max_wait_time": completed_calls["max_queue_time"] or 0,
                "routing_strategy": queue.routing_strategy,
            }

        except Queue.DoesNotExist:
            raise QueueServiceError("Queue not found", queue_id=str(queue_id))

    def get_queue_position(self, call: Call) -> int:
        """Get a call's position in its queue.

        Args:
            call: Call object

        Returns:
            Position in queue (1-based) or 0 if not in queue

        """
        if not call.queue or call.status != Call.Status.QUEUED:
            return 0

        position = (
            Call.objects.filter(
                queue=call.queue,
                status=Call.Status.QUEUED,
                created_at__lt=call.created_at,
            ).count()
            + 1
        )

        return position

    def estimate_wait_time(self, call: Call) -> int:
        """Estimate wait time for a call in queue.

        Args:
            call: Call object

        Returns:
            Estimated wait time in seconds

        """
        if not call.queue:
            return 0

        position = self.get_queue_position(call)
        if position == 0:
            return 0

        # Get average call duration for this queue
        avg_duration = (
            Call.objects.filter(
                queue=call.queue,
                status=Call.Status.COMPLETED,
                duration__gt=0,
            ).aggregate(avg_duration=models.Avg("duration"))["avg_duration"]
            or 180
        )  # Default 3 minutes

        # Get number of available agents
        available_agents = (
            Agent.objects.filter(
                queues=call.queue,
                status=Agent.Status.AVAILABLE,
                is_active=True,
            ).count()
            or 1
        )

        # Simple estimation: position * average duration / available agents
        estimated_wait = int((position * avg_duration) / available_agents)

        return estimated_wait

    def update_queue_priority(self, queue_id: int, priority: int) -> Queue:
        """Update queue priority.

        Args:
            queue_id: Queue ID
            priority: New priority value

        Returns:
            Updated Queue object

        """
        try:
            queue = Queue.objects.get(id=queue_id)
            queue.priority = priority
            queue.save(update_fields=["priority"])

            logger.info(f"Updated queue {queue.name} priority to {priority}")
            return queue

        except Queue.DoesNotExist:
            raise QueueServiceError("Queue not found", queue_id=str(queue_id))

    def activate_queue(self, queue_id: int) -> Queue:
        """Activate a queue."""
        return self._set_queue_status(queue_id, is_active=True)

    def deactivate_queue(self, queue_id: int) -> Queue:
        """Deactivate a queue."""
        return self._set_queue_status(queue_id, is_active=False)

    def _set_queue_status(self, queue_id: int, is_active: bool) -> Queue:
        """Set queue active status.

        Args:
            queue_id: Queue ID
            is_active: Active status

        Returns:
            Updated Queue object

        """
        try:
            queue = Queue.objects.get(id=queue_id)
            queue.is_active = is_active
            queue.save(update_fields=["is_active"])

            status = "activated" if is_active else "deactivated"
            logger.info(f"Queue {queue.name} {status}")

            return queue

        except Queue.DoesNotExist:
            raise QueueServiceError("Queue not found", queue_id=str(queue_id))


# Create service instance
queue_service = QueueService()

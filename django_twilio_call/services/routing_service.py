"""Advanced routing service for queue management."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from django.db import models, transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from ..models import Agent, Call, CallLog, Queue
from .base import BaseService

logger = logging.getLogger(__name__)


class RoutingStrategy:
    """Base class for routing strategies."""

    def select_agent(self, queue: Queue, call: Call, available_agents: models.QuerySet) -> Optional[Agent]:
        """Select an agent based on the routing strategy.

        Args:
            queue: Queue object
            call: Call object to route
            available_agents: QuerySet of available agents

        Returns:
            Selected Agent or None

        """
        raise NotImplementedError


class FIFORoutingStrategy(RoutingStrategy):
    """First In First Out routing - oldest call gets next available agent."""

    def select_agent(self, queue: Queue, call: Call, available_agents: models.QuerySet) -> Optional[Agent]:
        """Select first available agent."""
        return available_agents.first()


class RoundRobinRoutingStrategy(RoutingStrategy):
    """Round-robin routing - distribute calls evenly among agents."""

    def select_agent(self, queue: Queue, call: Call, available_agents: models.QuerySet) -> Optional[Agent]:
        """Select agent who hasn't received a call for the longest time."""
        # Order by last call assignment time
        return available_agents.order_by("last_status_change").first()


class LeastBusyRoutingStrategy(RoutingStrategy):
    """Route to the agent with fewest calls today."""

    def select_agent(self, queue: Queue, call: Call, available_agents: models.QuerySet) -> Optional[Agent]:
        """Select agent with minimum calls handled today."""
        return available_agents.order_by("calls_handled_today", "last_status_change").first()


class LongestIdleRoutingStrategy(RoutingStrategy):
    """Route to the agent who has been idle the longest."""

    def select_agent(self, queue: Queue, call: Call, available_agents: models.QuerySet) -> Optional[Agent]:
        """Select agent who has been available the longest."""
        # Filter only agents in AVAILABLE status
        idle_agents = available_agents.filter(status=Agent.Status.AVAILABLE)
        return idle_agents.order_by("last_status_change").first()


class SkillsBasedRoutingStrategy(RoutingStrategy):
    """Route based on agent skills matching requirements."""

    def select_agent(self, queue: Queue, call: Call, available_agents: models.QuerySet) -> Optional[Agent]:
        """Select agent with best skill match."""
        required_skills = queue.required_skills or []

        if not required_skills:
            # No skills required, use round-robin
            return available_agents.order_by("last_status_change").first()

        # Score agents based on skill match
        best_agent = None
        best_score = -1

        for agent in available_agents:
            agent_skills = set(agent.skills or [])
            required_set = set(required_skills)

            # Calculate match score
            matched_skills = agent_skills.intersection(required_set)
            score = len(matched_skills)

            # Prefer agents with all required skills
            if matched_skills == required_set:
                score += 100

            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent


class PriorityBasedRoutingStrategy(RoutingStrategy):
    """Route high-priority calls to senior agents."""

    def select_agent(self, queue: Queue, call: Call, available_agents: models.QuerySet) -> Optional[Agent]:
        """Select agent based on call priority."""
        # Check call metadata for priority
        priority = call.metadata.get("priority", "normal")

        if priority == "high":
            # Route to agents with senior skill
            senior_agents = available_agents.filter(Q(skills__contains=["senior"]) | Q(skills__contains=["supervisor"]))
            if senior_agents.exists():
                return senior_agents.order_by("last_status_change").first()

        # Default to round-robin for normal priority
        return available_agents.order_by("last_status_change").first()


class LoadBalancedRoutingStrategy(RoutingStrategy):
    """Balance load based on current call count and agent capacity."""

    def select_agent(self, queue: Queue, call: Call, available_agents: models.QuerySet) -> Optional[Agent]:
        """Select agent with most available capacity."""
        # Annotate with current active calls
        agents_with_capacity = available_agents.annotate(
            active_calls=Count("calls", filter=Q(calls__status=Call.Status.IN_PROGRESS)),
            available_capacity=F("max_concurrent_calls") - F("active_calls"),
        ).filter(available_capacity__gt=0)

        # Select agent with most available capacity
        return agents_with_capacity.order_by("-available_capacity", "last_status_change").first()


class AdvancedRoutingService(BaseService):
    """Advanced routing service with multiple strategies."""

    ROUTING_STRATEGIES = {
        Queue.RoutingStrategy.FIFO: FIFORoutingStrategy(),
        Queue.RoutingStrategy.ROUND_ROBIN: RoundRobinRoutingStrategy(),
        Queue.RoutingStrategy.LEAST_BUSY: LeastBusyRoutingStrategy(),
        Queue.RoutingStrategy.SKILLS_BASED: SkillsBasedRoutingStrategy(),
    }

    def __init__(self):
        """Initialize routing service."""
        super().__init__()
        self.strategies = self.ROUTING_STRATEGIES.copy()
        # Add custom strategies
        self.strategies["longest_idle"] = LongestIdleRoutingStrategy()
        self.strategies["priority_based"] = PriorityBasedRoutingStrategy()

        # Import here to avoid circular import
        from .agent_service import agent_service

        self.agent_service = agent_service
        self.strategies["load_balanced"] = LoadBalancedRoutingStrategy()

    @transaction.atomic
    def route_call(
        self,
        call: Call,
        queue: Queue,
        preferred_agent_id: Optional[int] = None,
        required_skills: Optional[List[str]] = None,
    ) -> Optional[Agent]:
        """Route a call to the best available agent.

        Args:
            call: Call to route
            queue: Queue to route from
            preferred_agent_id: Optional preferred agent
            required_skills: Optional required skills override

        Returns:
            Assigned Agent or None if no agent available

        """
        try:
            # Check if preferred agent is available
            if preferred_agent_id:
                agent = self._try_preferred_agent(preferred_agent_id, queue)
                if agent:
                    return self._assign_call_to_agent(call, agent, queue)

            # Get available agents from agent service (eliminates duplication)
            available_agents = self.agent_service.get_available_agents_queryset(
                queue=queue, skills=required_skills, business_hours_check=True
            )

            if not available_agents.exists():
                # Try overflow handling
                return self._handle_overflow(call, queue)

            # Select routing strategy
            strategy = self._get_routing_strategy(queue)

            # Select agent using strategy
            selected_agent = strategy.select_agent(queue, call, available_agents)

            if selected_agent:
                return self._assign_call_to_agent(call, selected_agent, queue)

            return None

        except Exception as e:
            logger.error(f"Error routing call {call.twilio_sid}: {e}")
            return None

    def _try_preferred_agent(self, agent_id: int, queue: Queue) -> Optional[Agent]:
        """Try to get preferred agent if available."""
        # Use agent service for consistent availability checking
        availability = self.agent_service.check_agent_availability(agent_id=agent_id, queue=queue)

        if availability.get("available", False):
            try:
                return Agent.objects.get(id=agent_id)
            except Agent.DoesNotExist:
                pass

        return None

    def _get_routing_strategy(self, queue: Queue) -> RoutingStrategy:
        """Get the appropriate routing strategy for the queue."""
        strategy_name = queue.routing_strategy

        # Check for time-based strategy override
        current_hour = timezone.now().hour
        if queue.metadata.get("peak_hours_strategy"):
            peak_hours = queue.metadata.get("peak_hours", [9, 10, 11, 14, 15, 16])
            if current_hour in peak_hours:
                strategy_name = queue.metadata["peak_hours_strategy"]

        return self.strategies.get(strategy_name, self.strategies[Queue.RoutingStrategy.FIFO])

    @transaction.atomic
    def _assign_call_to_agent(self, call: Call, agent: Agent, queue: Queue) -> Agent:
        """Assign call to agent and update statuses."""
        # Update call
        call.agent = agent
        call.status = Call.Status.RINGING
        queue_time = (timezone.now() - call.created_at).seconds
        call.queue_time = queue_time
        call.save(update_fields=["agent", "status", "queue_time"])

        # Update agent
        agent.status = Agent.Status.BUSY
        agent.last_status_change = timezone.now()
        agent.calls_handled_today = F("calls_handled_today") + 1
        agent.save(update_fields=["status", "last_status_change", "calls_handled_today"])

        # Log assignment
        CallLog.objects.create(
            call=call,
            event_type=CallLog.EventType.CONNECTED,
            description=f"Call routed to agent {agent.extension} via {queue.routing_strategy}",
            agent=agent,
            data={
                "queue_id": queue.id,
                "queue_name": queue.name,
                "routing_strategy": queue.routing_strategy,
                "queue_time": queue_time,
            },
        )

        logger.info(f"Call {call.twilio_sid} assigned to agent {agent.extension}")
        return agent

    def _handle_overflow(self, call: Call, queue: Queue) -> Optional[Agent]:
        """Handle queue overflow scenarios."""
        overflow_strategy = queue.metadata.get("overflow_strategy", "wait")

        if overflow_strategy == "transfer":
            # Transfer to overflow queue
            overflow_queue_name = queue.metadata.get("overflow_queue")
            if overflow_queue_name:
                try:
                    overflow_queue = Queue.objects.get(name=overflow_queue_name, is_active=True)
                    logger.info(f"Transferring call {call.twilio_sid} to overflow queue {overflow_queue_name}")
                    call.queue = overflow_queue
                    call.save(update_fields=["queue"])
                    # Try routing in overflow queue
                    return self.route_call(call, overflow_queue)
                except Queue.DoesNotExist:
                    logger.warning(f"Overflow queue {overflow_queue_name} not found")

        elif overflow_strategy == "voicemail":
            # Mark call for voicemail
            call.metadata["send_to_voicemail"] = True
            call.save(update_fields=["metadata"])
            logger.info(f"Call {call.twilio_sid} marked for voicemail")

        elif overflow_strategy == "callback":
            # Mark call for callback
            call.metadata["callback_requested"] = True
            call.save(update_fields=["metadata"])
            logger.info(f"Call {call.twilio_sid} marked for callback")

        # Default: keep in queue
        return None

    def get_queue_metrics(self, queue: Queue) -> Dict:
        """Get real-time queue metrics."""
        now = timezone.now()
        hour_ago = now - timedelta(hours=1)

        metrics = {
            "queue_id": queue.id,
            "queue_name": queue.name,
            "current_size": Call.objects.filter(queue=queue, status=Call.Status.QUEUED).count(),
            "agents_available": Agent.objects.filter(
                queues=queue, status=Agent.Status.AVAILABLE, is_active=True
            ).count(),
            "agents_busy": Agent.objects.filter(queues=queue, status=Agent.Status.BUSY, is_active=True).count(),
            "agents_total": queue.agents.filter(is_active=True).count(),
            "calls_completed_hour": Call.objects.filter(
                queue=queue, status=Call.Status.COMPLETED, end_time__gte=hour_ago
            ).count(),
            "avg_wait_time": Call.objects.filter(
                queue=queue, status=Call.Status.COMPLETED, queue_time__gt=0, end_time__gte=hour_ago
            ).aggregate(avg=models.Avg("queue_time"))["avg"]
            or 0,
            "avg_handle_time": Call.objects.filter(
                queue=queue, status=Call.Status.COMPLETED, duration__gt=0, end_time__gte=hour_ago
            ).aggregate(avg=models.Avg("duration"))["avg"]
            or 0,
            "service_level": self._calculate_service_level(queue, hour_ago),
            "abandonment_rate": self._calculate_abandonment_rate(queue, hour_ago),
        }

        return metrics

    def _calculate_service_level(self, queue: Queue, since: datetime) -> float:
        """Calculate service level (% calls answered within threshold)."""
        threshold = queue.metadata.get("service_level_threshold", 30)  # seconds

        total_calls = Call.objects.filter(
            queue=queue, created_at__gte=since, status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS]
        ).count()

        if total_calls == 0:
            return 100.0

        answered_within_threshold = Call.objects.filter(
            queue=queue,
            created_at__gte=since,
            queue_time__lte=threshold,
            status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS],
        ).count()

        return (answered_within_threshold / total_calls) * 100

    def _calculate_abandonment_rate(self, queue: Queue, since: datetime) -> float:
        """Calculate call abandonment rate."""
        total_calls = Call.objects.filter(queue=queue, created_at__gte=since).count()

        if total_calls == 0:
            return 0.0

        abandoned_calls = Call.objects.filter(
            queue=queue,
            created_at__gte=since,
            status__in=[Call.Status.FAILED, Call.Status.NO_ANSWER, Call.Status.CANCELED],
        ).count()

        return (abandoned_calls / total_calls) * 100


# Create service instance
routing_service = AdvancedRoutingService()

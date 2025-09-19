"""Agent management views for django-twilio-call.

Handles agent status management, performance tracking, and authentication.
"""

import logging

from rest_framework import status
from rest_framework.decorators import action

from ..models import Agent
from ..permissions import IsAgentOrAdmin
from ..serializers import (
    AgentSerializer,
    AgentStatusUpdateSerializer,
    CallSerializer,
)
from .base import AgentAccessMixin, BaseCallCenterViewSet

logger = logging.getLogger(__name__)


class AgentViewSet(BaseCallCenterViewSet, AgentAccessMixin):
    """ViewSet for Agent model with status management and performance tracking."""

    queryset = Agent.objects.all()
    serializer_class = AgentSerializer
    permission_classes = [IsAgentOrAdmin]

    def get_queryset(self):
        """Filter queryset based on user permissions and query parameters."""
        queryset = super().get_queryset().select_related("user").prefetch_related("queues")

        # Non-admins only see their own profile
        if not self.request.user.is_staff:
            if hasattr(self.request.user, "agent_profile"):
                queryset = queryset.filter(user=self.request.user)
            else:
                queryset = queryset.none()

        # Filter by status if requested
        agent_status = self.request.query_params.get("status")
        if agent_status:
            queryset = queryset.filter(status=agent_status)

        # Filter by queue if requested
        queue_id = self.request.query_params.get("queue_id")
        if queue_id:
            queryset = queryset.filter(queues__id=queue_id)

        return queryset.order_by("user__first_name", "user__last_name")

    @action(detail=True, methods=["post"])
    def update_status(self, request, public_id=None):
        """Update agent status.

        Allowed statuses: available, busy, on_break, after_call_work, offline
        """
        agent = self.get_object()
        serializer = AgentStatusUpdateSerializer(data=request.data)

        if not serializer.is_valid():
            return self.handle_error(
                ValueError(serializer.errors), "update agent status", status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            old_status = agent.status
            agent.status = serializer.validated_data["status"]
            agent.save(update_fields=["status", "last_status_change"])

            # Log status change
            logger.info(f"Agent {agent.extension} status changed from {old_status} to {agent.status}")

            return self.success_response(
                data={
                    "status": agent.status,
                    "previous_status": old_status,
                },
                message=f"Status updated to {agent.get_status_display()}",
            )
        except Exception as e:
            return self.handle_error(e, f"update status for agent {agent.extension}")

    @action(detail=True, methods=["get"])
    def calls(self, request, public_id=None):
        """Get calls associated with this agent.

        Query parameters:
        - status: Filter by call status
        - limit: Limit number of results (default 50)
        """
        agent = self.get_object()
        queryset = agent.calls.all()

        # Filter by status if requested
        call_status = request.query_params.get("status")
        if call_status:
            queryset = queryset.filter(status=call_status)

        # Limit results
        limit = int(request.query_params.get("limit", 50))
        queryset = queryset.order_by("-created_at")[:limit]

        try:
            serializer = CallSerializer(queryset, many=True)
            return self.success_response(
                data={"calls": serializer.data, "total": len(serializer.data)},
                message=f"Retrieved calls for agent {agent.extension}",
            )
        except Exception as e:
            return self.handle_error(e, f"get calls for agent {agent.extension}")

    @action(detail=True, methods=["post"])
    def login(self, request, public_id=None):
        """Log agent into the system.

        Sets agent status to available and records login activity.
        """
        agent = self.get_object()

        try:
            # Only allow agents to log themselves in (unless admin)
            if not self.request.user.is_staff and agent.user != self.request.user:
                raise PermissionError("Can only log in your own agent profile")

            # Update status to available
            old_status = agent.status
            agent.status = Agent.Status.AVAILABLE
            agent.save(update_fields=["status", "last_status_change"])

            # Log the activity
            from ..models import AgentActivity

            AgentActivity.objects.create(
                agent=agent,
                activity_type=AgentActivity.ActivityType.LOGIN,
                from_status=old_status,
                to_status=agent.status,
                description="Agent logged in via API",
            )

            logger.info(f"Agent {agent.extension} logged in")

            return self.success_response(
                data=self.get_serializer(agent).data, message=f"Agent {agent.extension} logged in successfully"
            )
        except Exception as e:
            return self.handle_error(e, f"login agent {agent.extension}")

    @action(detail=True, methods=["post"])
    def logout(self, request, public_id=None):
        """Log agent out of the system.

        Sets agent status to offline and records logout activity.
        """
        agent = self.get_object()

        try:
            # Only allow agents to log themselves out (unless admin)
            if not self.request.user.is_staff and agent.user != self.request.user:
                raise PermissionError("Can only log out your own agent profile")

            # Update status to offline
            old_status = agent.status
            agent.status = Agent.Status.OFFLINE
            agent.save(update_fields=["status", "last_status_change"])

            # Log the activity
            from ..models import AgentActivity

            AgentActivity.objects.create(
                agent=agent,
                activity_type=AgentActivity.ActivityType.LOGOUT,
                from_status=old_status,
                to_status=agent.status,
                description="Agent logged out via API",
            )

            logger.info(f"Agent {agent.extension} logged out")

            return self.success_response(
                data=self.get_serializer(agent).data, message=f"Agent {agent.extension} logged out successfully"
            )
        except Exception as e:
            return self.handle_error(e, f"logout agent {agent.extension}")

    @action(detail=True, methods=["post"])
    def start_break(self, request, public_id=None):
        """Start agent break.

        Puts agent in break status and records break start time.
        """
        agent = self.get_object()
        reason = request.data.get("reason", "Break")

        try:
            if agent.status == Agent.Status.ON_BREAK:
                raise ValueError("Agent is already on break")

            old_status = agent.status
            agent.status = Agent.Status.ON_BREAK
            agent.save(update_fields=["status", "last_status_change"])

            # Log the activity
            from ..models import AgentActivity

            AgentActivity.objects.create(
                agent=agent,
                activity_type=AgentActivity.ActivityType.BREAK_START,
                from_status=old_status,
                to_status=agent.status,
                description=f"Break started: {reason}",
            )

            return self.success_response(
                data=self.get_serializer(agent).data, message=f"Break started for agent {agent.extension}"
            )
        except Exception as e:
            return self.handle_error(e, f"start break for agent {agent.extension}")

    @action(detail=True, methods=["post"])
    def end_break(self, request, public_id=None):
        """End agent break.

        Returns agent to available status and calculates break duration.
        """
        agent = self.get_object()

        try:
            if agent.status != Agent.Status.ON_BREAK:
                raise ValueError("Agent is not currently on break")

            # Calculate break duration
            from django.utils import timezone

            from ..models import AgentActivity

            last_break = (
                AgentActivity.objects.filter(agent=agent, activity_type=AgentActivity.ActivityType.BREAK_START)
                .order_by("-created_at")
                .first()
            )

            break_duration = None
            if last_break:
                break_duration = int((timezone.now() - last_break.created_at).total_seconds())

            old_status = agent.status
            agent.status = Agent.Status.AVAILABLE
            agent.save(update_fields=["status", "last_status_change"])

            # Log the activity
            AgentActivity.objects.create(
                agent=agent,
                activity_type=AgentActivity.ActivityType.BREAK_END,
                from_status=old_status,
                to_status=agent.status,
                duration_seconds=break_duration,
                description="Break ended",
            )

            return self.success_response(
                data={"agent": self.get_serializer(agent).data, "break_duration_seconds": break_duration},
                message=f"Break ended for agent {agent.extension}",
            )
        except Exception as e:
            return self.handle_error(e, f"end break for agent {agent.extension}")

    @action(detail=True, methods=["post"])
    def update_skills(self, request, public_id=None):
        """Update agent skills.

        Skills are used for skills-based routing.
        """
        agent = self.get_object()
        skills = request.data.get("skills", [])

        if not isinstance(skills, list):
            return self.handle_error(
                ValueError("skills must be a list"), "update agent skills", status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            old_skills = agent.skills.copy()
            agent.skills = skills
            agent.save(update_fields=["skills"])

            # Log the activity
            from ..models import AgentActivity

            AgentActivity.objects.create(
                agent=agent,
                activity_type=AgentActivity.ActivityType.SKILL_UPDATE,
                description=f"Skills updated from {old_skills} to {skills}",
            )

            return self.success_response(
                data=self.get_serializer(agent).data, message=f"Skills updated for agent {agent.extension}"
            )
        except Exception as e:
            return self.handle_error(e, f"update skills for agent {agent.extension}")

    @action(detail=True, methods=["get"])
    def performance(self, request, public_id=None):
        """Get agent performance metrics.

        Returns performance data including call volume, average handle time,
        and other key metrics.
        """
        agent = self.get_object()

        try:
            # Import here to avoid circular imports
            from ..services import analytics_service

            performance_data = analytics_service.get_agent_performance(
                agent.id,
                start_date=request.query_params.get("start_date"),
                end_date=request.query_params.get("end_date"),
            )

            return self.success_response(
                data=performance_data, message=f"Performance metrics for agent {agent.extension}"
            )
        except Exception as e:
            return self.handle_error(e, f"get performance for agent {agent.extension}")

    @action(detail=True, methods=["get"])
    def dashboard(self, request, public_id=None):
        """Get agent dashboard data.

        Returns real-time dashboard information including current status,
        active calls, queue statistics, and recent activity.
        """
        agent = self.get_object()

        try:
            from ..models import Call

            # Current active calls
            active_calls = Call.objects.filter(agent=agent, status__in=[Call.Status.RINGING, Call.Status.IN_PROGRESS])

            # Today's call statistics
            from datetime import date

            today = date.today()
            today_calls = Call.objects.filter(agent=agent, created_at__date=today)

            dashboard_data = {
                "agent": self.get_serializer(agent).data,
                "active_calls": CallSerializer(active_calls, many=True).data,
                "today_stats": {
                    "total_calls": today_calls.count(),
                    "completed_calls": today_calls.filter(status=Call.Status.COMPLETED).count(),
                    "average_duration": today_calls.aggregate(avg_duration=models.Avg("duration"))["avg_duration"] or 0,
                },
                "queue_assignments": [
                    {"name": q.name, "priority": q.priority} for q in agent.queues.filter(is_active=True)
                ],
            }

            return self.success_response(data=dashboard_data, message=f"Dashboard data for agent {agent.extension}")
        except Exception as e:
            return self.handle_error(e, f"get dashboard for agent {agent.extension}")

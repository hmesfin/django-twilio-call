"""Agent management service."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.db import models, transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

from ..exceptions import AgentNotAvailableError
from ..models import Agent, AgentActivity, Call
from ..conf import get_config
from ..constants import DefaultValues, CacheTimeouts
from .base import BaseService

logger = logging.getLogger(__name__)


class AgentService(BaseService):
    """Service for managing agent operations."""

    service_type = "agent"

    def __init__(self):
        """Initialize agent service."""
        super().__init__()
        self.status_webhooks = []

    @transaction.atomic
    def login_agent(
        self,
        agent_id: int,
        extension: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> Agent:
        """Log in an agent and make them available.

        Args:
            agent_id: Agent ID
            extension: Optional extension update
            phone_number: Optional phone number update

        Returns:
            Updated Agent object

        """
        try:
            agent = Agent.objects.get(id=agent_id)

            # Update extension/phone if provided
            if extension:
                agent.extension = extension
            if phone_number:
                agent.phone_number = phone_number

            # Set agent as available
            agent.status = Agent.Status.AVAILABLE
            agent.is_active = True
            agent.last_status_change = timezone.now()

            # Reset daily counter if it's a new day
            if agent.updated_at.date() < timezone.now().date():
                agent.calls_handled_today = 0

            agent.save()

            # Log the login
            self._log_agent_activity(agent, "login", {"extension": extension})

            # Send status webhook
            self._send_status_webhook(agent, "login")

            logger.info(f"Agent {agent.extension} logged in")
            return agent

        except Agent.DoesNotExist:
            raise AgentNotAvailableError(f"Agent {agent_id} not found")

    @transaction.atomic
    def logout_agent(self, agent_id: int) -> Agent:
        """Log out an agent.

        Args:
            agent_id: Agent ID

        Returns:
            Updated Agent object

        """
        try:
            agent = Agent.objects.get(id=agent_id)

            # Check if agent has active calls
            active_calls = Call.objects.filter(
                agent=agent,
                status__in=[Call.Status.IN_PROGRESS, Call.Status.RINGING],
            ).count()

            if active_calls > 0:
                raise AgentNotAvailableError(f"Agent has {active_calls} active calls. Cannot logout.")

            # Set agent as offline
            previous_status = agent.status
            agent.status = Agent.Status.OFFLINE
            agent.is_active = False
            agent.last_status_change = timezone.now()

            # Update talk time for the day
            self._update_agent_talk_time(agent)

            agent.save()

            # Log the logout
            self._log_agent_activity(agent, "logout", {"previous_status": previous_status})

            # Send status webhook
            self._send_status_webhook(agent, "logout")

            logger.info(f"Agent {agent.extension} logged out")
            return agent

        except Agent.DoesNotExist:
            raise AgentNotAvailableError(f"Agent {agent_id} not found")

    @transaction.atomic
    def set_agent_status(
        self,
        agent_id: int,
        status: str,
        reason: Optional[str] = None,
    ) -> Agent:
        """Set agent status.

        Args:
            agent_id: Agent ID
            status: New status
            reason: Optional reason for status change

        Returns:
            Updated Agent object

        """
        try:
            agent = Agent.objects.get(id=agent_id)

            # Validate status transition
            if not self._is_valid_status_transition(agent.status, status):
                raise AgentNotAvailableError(f"Invalid status transition from {agent.status} to {status}")

            # Check if agent can go on break
            if status in [Agent.Status.ON_BREAK, Agent.Status.AFTER_CALL_WORK]:
                active_calls = Call.objects.filter(
                    agent=agent,
                    status=Call.Status.IN_PROGRESS,
                ).count()

                if active_calls > 0:
                    raise AgentNotAvailableError("Cannot go on break with active calls")

            # Update status
            previous_status = agent.status
            agent.status = status
            agent.last_status_change = timezone.now()
            agent.save()

            # Log status change
            self._log_agent_activity(
                agent,
                "status_change",
                {
                    "previous_status": previous_status,
                    "new_status": status,
                    "reason": reason,
                },
            )

            # Send status webhook
            self._send_status_webhook(agent, "status_change")

            logger.info(f"Agent {agent.extension} status changed to {status}")
            return agent

        except Agent.DoesNotExist:
            raise AgentNotAvailableError(f"Agent {agent_id} not found")

    def start_break(
        self,
        agent_id: int,
        break_type: str = "standard",
        duration_minutes: Optional[int] = None,
    ) -> Tuple[Agent, datetime]:
        """Start agent break.

        Args:
            agent_id: Agent ID
            break_type: Type of break (standard, lunch, training, etc.)
            duration_minutes: Optional break duration

        Returns:
            Tuple of (Agent, expected_return_time)

        """
        agent = self.set_agent_status(agent_id, Agent.Status.ON_BREAK, reason=break_type)

        # Calculate expected return time
        if duration_minutes:
            expected_return = timezone.now() + timedelta(minutes=duration_minutes)
        else:
            # Default break durations
            default_durations = {
                "standard": 15,
                "lunch": DefaultValues.LUNCH_DURATION_MINUTES,
                "training": DefaultValues.TRAINING_DURATION_MINUTES,
            }
            duration = default_durations.get(break_type, 15)
            expected_return = timezone.now() + timedelta(minutes=duration)

        # Store expected return in metadata
        agent.metadata["break_info"] = {
            "type": break_type,
            "started_at": timezone.now().isoformat(),
            "expected_return": expected_return.isoformat(),
        }
        agent.save(update_fields=["metadata"])

        return agent, expected_return

    def end_break(self, agent_id: int) -> Agent:
        """End agent break and return to available.

        Args:
            agent_id: Agent ID

        Returns:
            Updated Agent object

        """
        agent = self.set_agent_status(agent_id, Agent.Status.AVAILABLE)

        # Clear break info from metadata
        if "break_info" in agent.metadata:
            break_info = agent.metadata.pop("break_info")
            agent.save(update_fields=["metadata"])

            # Log break duration
            if "started_at" in break_info:
                started_at = datetime.fromisoformat(break_info["started_at"])
                duration = (timezone.now() - started_at).seconds
                self._log_agent_activity(
                    agent,
                    "break_ended",
                    {
                        "break_type": break_info.get("type"),
                        "duration_seconds": duration,
                    },
                )

        return agent

    @transaction.atomic
    def update_agent_skills(
        self,
        agent_id: int,
        skills: List[str],
        append: bool = False,
    ) -> Agent:
        """Update agent skills.

        Args:
            agent_id: Agent ID
            skills: List of skills
            append: If True, append to existing skills

        Returns:
            Updated Agent object

        """
        try:
            agent = Agent.objects.get(id=agent_id)

            if append:
                # Append to existing skills
                existing_skills = set(agent.skills or [])
                new_skills = existing_skills.union(set(skills))
                agent.skills = list(new_skills)
            else:
                # Replace skills
                agent.skills = skills

            agent.save(update_fields=["skills"])

            # Log skill update
            self._log_agent_activity(agent, "skills_updated", {"skills": agent.skills})

            logger.info(f"Agent {agent.extension} skills updated: {agent.skills}")
            return agent

        except Agent.DoesNotExist:
            raise AgentNotAvailableError(f"Agent {agent_id} not found")

    def get_agent_performance(
        self,
        agent_id: int,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> Dict:
        """Get agent performance metrics.

        Args:
            agent_id: Agent ID
            date_from: Start date for metrics
            date_to: End date for metrics

        Returns:
            Dictionary of performance metrics

        """
        try:
            agent = Agent.objects.get(id=agent_id)

            # Default to last 30 days
            if not date_from:
                date_from = timezone.now() - timedelta(days=DefaultValues.DEFAULT_ANALYSIS_PERIOD_DAYS)
            if not date_to:
                date_to = timezone.now()

            # Get call statistics
            calls = Call.objects.filter(
                agent=agent,
                created_at__gte=date_from,
                created_at__lte=date_to,
            )

            total_calls = calls.count()
            completed_calls = calls.filter(status=Call.Status.COMPLETED).count()

            # Calculate metrics
            metrics = {
                "agent_id": agent.id,
                "agent_name": agent.user.get_full_name(),
                "period_start": date_from.isoformat(),
                "period_end": date_to.isoformat(),
                "total_calls": total_calls,
                "completed_calls": completed_calls,
                "abandoned_calls": calls.filter(status__in=[Call.Status.FAILED, Call.Status.NO_ANSWER]).count(),
                "avg_call_duration": calls.filter(duration__gt=0).aggregate(avg=Avg("duration"))["avg"] or 0,
                "total_talk_time": calls.aggregate(total=Sum("duration"))["total"] or 0,
                "avg_queue_time": calls.filter(queue_time__gt=0).aggregate(avg=Avg("queue_time"))["avg"] or 0,
                "completion_rate": ((completed_calls / total_calls * 100) if total_calls > 0 else 0),
            }

            # Add daily breakdown
            daily_stats = (
                calls.values("created_at__date")
                .annotate(
                    calls=Count("id"),
                    talk_time=Sum("duration"),
                )
                .order_by("created_at__date")
            )

            metrics["daily_breakdown"] = [
                {
                    "date": stat["created_at__date"].isoformat(),
                    "calls": stat["calls"],
                    "talk_time": stat["talk_time"] or 0,
                }
                for stat in daily_stats
            ]

            # Add current day stats
            metrics["today"] = {
                "calls_handled": agent.calls_handled_today,
                "current_status": agent.status,
                "last_status_change": agent.last_status_change.isoformat(),
            }

            return metrics

        except Agent.DoesNotExist:
            raise AgentNotAvailableError(f"Agent {agent_id} not found")

    def get_agent_dashboard(self, agent_id: int) -> Dict:
        """Get comprehensive dashboard data for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            Dictionary of dashboard data

        """
        try:
            agent = (
                Agent.objects.select_related("user")
                .prefetch_related(
                    "queues",
                    Prefetch(
                        "calls",
                        queryset=Call.objects.filter(status__in=["queued", "ringing", "in-progress"]).select_related(
                            "queue"
                        ),
                        to_attr="active_calls_list",
                    ),
                )
                .get(id=agent_id)
            )

            # Get current status info
            dashboard = {
                "agent": {
                    "id": agent.id,
                    "name": agent.user.get_full_name(),
                    "extension": agent.extension,
                    "status": agent.status,
                    "is_available": agent.is_available,
                    "skills": agent.skills,
                    "queues": [{"id": q.id, "name": q.name} for q in agent.queues.all()],
                },
                "current_session": {
                    "login_time": self._get_login_time(agent),
                    "status_duration": (timezone.now() - agent.last_status_change).seconds,
                    "calls_handled_today": agent.calls_handled_today,
                    "total_talk_time_today": agent.total_talk_time,
                },
            }

            # Get active call if any
            active_call = Call.objects.filter(agent=agent, status=Call.Status.IN_PROGRESS).first()

            if active_call:
                dashboard["active_call"] = {
                    "id": active_call.id,
                    "twilio_sid": active_call.twilio_sid,
                    "from_number": active_call.from_number,
                    "duration": (timezone.now() - active_call.start_time).seconds if active_call.start_time else 0,
                    "queue": active_call.queue.name if active_call.queue else None,
                }
            else:
                dashboard["active_call"] = None

            # Get recent calls
            recent_calls = (
                Call.objects.filter(agent=agent)
                .order_by("-created_at")[:10]
                .values(
                    "id",
                    "from_number",
                    "to_number",
                    "direction",
                    "status",
                    "duration",
                    "created_at",
                )
            )

            dashboard["recent_calls"] = list(recent_calls)

            # Get today's stats
            today_start = timezone.now().replace(hour=0, minute=0, second=0)
            today_calls = Call.objects.filter(agent=agent, created_at__gte=today_start)

            dashboard["today_stats"] = {
                "total_calls": today_calls.count(),
                "completed_calls": today_calls.filter(status=Call.Status.COMPLETED).count(),
                "avg_duration": today_calls.filter(duration__gt=0).aggregate(avg=Avg("duration"))["avg"] or 0,
                "total_talk_time": today_calls.aggregate(total=Sum("duration"))["total"] or 0,
            }

            # Get queue status for agent's queues
            queue_status = []
            for queue in agent.queues.filter(is_active=True):
                queue_status.append(
                    {
                        "id": queue.id,
                        "name": queue.name,
                        "calls_waiting": Call.objects.filter(queue=queue, status=Call.Status.QUEUED).count(),
                        "agents_available": Agent.objects.filter(
                            queues=queue,
                            status=Agent.Status.AVAILABLE,
                            is_active=True,
                        ).count(),
                    }
                )

            dashboard["queue_status"] = queue_status

            return dashboard

        except Agent.DoesNotExist:
            raise AgentNotAvailableError(f"Agent {agent_id} not found")

    def get_available_agents(
        self,
        queue_id: Optional[int] = None,
        skills: Optional[List[str]] = None,
    ) -> List[Agent]:
        """Get list of available agents.

        Args:
            queue_id: Optional queue filter
            skills: Optional required skills

        Returns:
            List of available Agent objects

        """
        queryset = self.get_available_agents_queryset(queue_id=queue_id, skills=skills)
        return list(queryset.order_by("last_status_change"))

    def get_available_agents_queryset(
        self,
        queue: Optional["Queue"] = None,
        queue_id: Optional[int] = None,
        skills: Optional[List[str]] = None,
        business_hours_check: bool = False,
    ) -> models.QuerySet:
        """Get QuerySet of available agents with flexible filtering.

        Args:
            queue: Queue object (takes precedence over queue_id)
            queue_id: Optional queue filter by ID
            skills: Optional required skills
            business_hours_check: Whether to apply business hours filtering

        Returns:
            QuerySet of available Agent objects

        """
        # Base query for available agents with capacity
        agents = (
            Agent.objects.select_related("user")
            .filter(status=Agent.Status.AVAILABLE, is_active=True)
            .annotate(current_calls_count=Count("calls", filter=Q(calls__status=Call.Status.IN_PROGRESS)))
            .filter(current_calls_count__lt=F("max_concurrent_calls"))
        )

        # Apply queue filtering
        if queue:
            agents = agents.filter(queues=queue)
        elif queue_id:
            agents = agents.filter(queues__id=queue_id)

        # Apply skill filtering
        skills_to_check = skills or (queue.required_skills if queue else [])
        if skills_to_check:
            # Filter agents who have all required skills
            for skill in skills_to_check:
                agents = agents.filter(skills__contains=[skill])

        # Apply business hours filtering if configured
        if business_hours_check and queue and queue.business_hours:
            if not self._is_within_business_hours(queue.business_hours):
                # Only return on-call agents during off hours
                agents = agents.filter(Q(skills__contains=["on_call"]) | Q(metadata__on_call=True))

        return agents

    def _is_within_business_hours(self, business_hours: Dict) -> bool:
        """Check if current time is within business hours.

        Args:
            business_hours: Business hours configuration

        Returns:
            True if within business hours

        """
        now = timezone.now()
        current_time = now.time()
        current_day = now.weekday()  # 0=Monday, 6=Sunday

        # Get day name
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        current_day_name = day_names[current_day]

        # Check if current day is configured
        if current_day_name not in business_hours:
            return False

        day_config = business_hours[current_day_name]
        if not day_config.get("enabled", True):
            return False

        # Check time range
        start_time = day_config.get("start_time", "09:00")
        end_time = day_config.get("end_time", "17:00")

        try:
            from datetime import time

            start = time.fromisoformat(start_time)
            end = time.fromisoformat(end_time)
            return start <= current_time <= end
        except (ValueError, AttributeError):
            # If time parsing fails, assume within business hours
            return True

    def check_agent_availability(
        self,
        agent_id: int,
        queue: Optional["Queue"] = None,
        required_skills: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Check detailed availability status for a specific agent.

        Args:
            agent_id: Agent ID to check
            queue: Optional queue to check compatibility
            required_skills: Optional required skills

        Returns:
            Dict with availability details

        """
        try:
            agent = Agent.objects.select_related("user").get(id=agent_id)

            # Basic availability checks
            is_available = agent.status == Agent.Status.AVAILABLE and agent.is_active

            # Check capacity
            current_calls = Call.objects.filter(agent=agent, status=Call.Status.IN_PROGRESS).count()
            has_capacity = current_calls < agent.max_concurrent_calls

            # Check queue membership
            queue_compatible = True
            if queue:
                queue_compatible = agent.queues.filter(id=queue.id).exists()

            # Check skills
            skills_compatible = True
            skill_gaps = []
            if required_skills:
                agent_skills = set(agent.skills or [])
                required_skills_set = set(required_skills)
                skill_gaps = list(required_skills_set - agent_skills)
                skills_compatible = len(skill_gaps) == 0

            # Overall availability
            overall_available = is_available and has_capacity and queue_compatible and skills_compatible

            return {
                "agent_id": agent.id,
                "agent_name": agent.user.get_full_name(),
                "available": overall_available,
                "details": {
                    "status_available": is_available,
                    "current_status": agent.status,
                    "has_capacity": has_capacity,
                    "current_calls": current_calls,
                    "max_calls": agent.max_concurrent_calls,
                    "queue_compatible": queue_compatible,
                    "skills_compatible": skills_compatible,
                    "skill_gaps": skill_gaps,
                },
            }

        except Agent.DoesNotExist:
            return {
                "agent_id": agent_id,
                "available": False,
                "error": "Agent not found",
            }

    def get_agents_summary(self) -> Dict:
        """Get summary of all agents.

        Returns:
            Dictionary with agent summary statistics

        """
        total_agents = Agent.objects.filter(is_active=True).count()

        status_counts = Agent.objects.filter(is_active=True).values("status").annotate(count=Count("id"))

        status_summary = {stat["status"]: stat["count"] for stat in status_counts}

        # Get agents on calls
        agents_on_calls = (
            Agent.objects.filter(
                is_active=True,
                calls__status=Call.Status.IN_PROGRESS,
            )
            .distinct()
            .count()
        )

        return {
            "total_agents": total_agents,
            "available": status_summary.get(Agent.Status.AVAILABLE, 0),
            "busy": status_summary.get(Agent.Status.BUSY, 0),
            "on_break": status_summary.get(Agent.Status.ON_BREAK, 0),
            "after_call_work": status_summary.get(Agent.Status.AFTER_CALL_WORK, 0),
            "offline": status_summary.get(Agent.Status.OFFLINE, 0),
            "agents_on_calls": agents_on_calls,
            "utilization_rate": ((agents_on_calls / total_agents * 100) if total_agents > 0 else 0),
        }

    def _is_valid_status_transition(self, from_status: str, to_status: str) -> bool:
        """Check if status transition is valid."""
        # Define valid transitions
        valid_transitions = {
            Agent.Status.OFFLINE: [
                Agent.Status.AVAILABLE,
            ],
            Agent.Status.AVAILABLE: [
                Agent.Status.BUSY,
                Agent.Status.ON_BREAK,
                Agent.Status.AFTER_CALL_WORK,
                Agent.Status.OFFLINE,
            ],
            Agent.Status.BUSY: [
                Agent.Status.AVAILABLE,
                Agent.Status.AFTER_CALL_WORK,
                Agent.Status.OFFLINE,
            ],
            Agent.Status.ON_BREAK: [
                Agent.Status.AVAILABLE,
                Agent.Status.OFFLINE,
            ],
            Agent.Status.AFTER_CALL_WORK: [
                Agent.Status.AVAILABLE,
                Agent.Status.ON_BREAK,
                Agent.Status.OFFLINE,
            ],
        }

        return to_status in valid_transitions.get(from_status, [])

    def _update_agent_talk_time(self, agent: Agent) -> None:
        """Update agent's total talk time for the day."""
        today_start = timezone.now().replace(hour=0, minute=0, second=0)

        total_talk_time = (
            Call.objects.filter(
                agent=agent,
                status=Call.Status.COMPLETED,
                created_at__gte=today_start,
            ).aggregate(total=Sum("duration"))["total"]
            or 0
        )

        agent.total_talk_time = total_talk_time

    def _get_login_time(self, agent: Agent) -> Optional[str]:
        """Get agent's login time for current session."""
        # This would ideally be tracked in a separate session model
        # For now, we'll estimate based on status changes
        if agent.status == Agent.Status.OFFLINE:
            return None

        # Look for the most recent offline -> available transition
        # This is a simplified implementation
        return agent.last_status_change.isoformat()

    def _log_agent_activity(self, agent: Agent, activity_type: str, data: Optional[Dict] = None) -> AgentActivity:
        """Log agent activity."""
        # Map activity types
        activity_map = {
            "login": AgentActivity.ActivityType.LOGIN,
            "logout": AgentActivity.ActivityType.LOGOUT,
            "status_change": AgentActivity.ActivityType.STATUS_CHANGE,
            "break_started": AgentActivity.ActivityType.BREAK_START,
            "break_ended": AgentActivity.ActivityType.BREAK_END,
            "skills_updated": AgentActivity.ActivityType.SKILL_UPDATE,
        }

        activity = AgentActivity.objects.create(
            agent=agent,
            activity_type=activity_map.get(activity_type, AgentActivity.ActivityType.STATUS_CHANGE),
            description=f"Agent {activity_type}",
            from_status=data.get("previous_status", "") if data else "",
            to_status=data.get("new_status", agent.status) if data else agent.status,
            metadata=data or {},
        )

        logger.info(
            f"Agent activity logged: {agent.extension} - {activity_type}",
            extra={"agent_id": agent.id, "activity_id": activity.id, "data": data},
        )

        return activity

    def _send_status_webhook(self, agent: Agent, event_type: str) -> None:
        """Send agent status webhook."""
        from ..settings import AGENT_STATUS_UPDATE_WEBHOOK

        if not AGENT_STATUS_UPDATE_WEBHOOK:
            return

        # In production, this would make an HTTP request to the webhook URL
        webhook_data = {
            "event": event_type,
            "agent_id": agent.id,
            "agent_extension": agent.extension,
            "status": agent.status,
            "timestamp": timezone.now().isoformat(),
        }

        logger.info(f"Sending agent status webhook: {webhook_data}")
        # TODO: Implement actual webhook sending


# Create service instance
agent_service = AgentService()

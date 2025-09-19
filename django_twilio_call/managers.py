"""Optimized model managers and querysets for django-twilio-call."""

from django.db import models
from django.db.models import Count, F, Prefetch, Q
from django.utils import timezone


class AgentQuerySet(models.QuerySet):
    """Optimized queryset for Agent model."""

    def active(self):
        """Get active agents only."""
        return self.filter(is_active=True)

    def available(self):
        """Get available agents with optimized query."""
        return self.filter(status="available", is_active=True).select_related("user")

    def with_call_counts(self):
        """Annotate agents with current call counts."""
        return self.annotate(
            active_calls=Count(
                "calls",
                filter=Q(calls__status="in-progress"),
            )
        )

    def available_for_calls(self):
        """Get agents available to take new calls."""
        return (
            self.active()
            .filter(status="available")
            .with_call_counts()
            .filter(active_calls__lt=F("max_concurrent_calls"))
            .select_related("user")
        )

    def for_queue(self, queue):
        """Get agents assigned to a specific queue."""
        return self.filter(queues=queue)

    def with_skills(self, skills):
        """Filter agents by required skills."""
        queryset = self
        for skill in skills:
            queryset = queryset.filter(skills__contains=[skill])
        return queryset

    def dashboard_data(self):
        """Optimized query for dashboard display."""
        return self.select_related("user").prefetch_related(
            "queues",
            Prefetch(
                "calls",
                queryset=Call.objects.filter(status__in=["queued", "ringing", "in-progress"]).only(
                    "id", "status", "created_at", "from_number"
                ),
                to_attr="active_calls_list",
            ),
        )


class AgentManager(models.Manager):
    """Optimized manager for Agent model."""

    def get_queryset(self):
        return AgentQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def available(self):
        return self.get_queryset().available()

    def available_for_calls(self):
        return self.get_queryset().available_for_calls()

    def for_queue(self, queue):
        return self.get_queryset().for_queue(queue)

    def with_skills(self, skills):
        return self.get_queryset().with_skills(skills)

    def dashboard_data(self):
        return self.get_queryset().dashboard_data()


class CallQuerySet(models.QuerySet):
    """Optimized queryset for Call model."""

    def active(self):
        """Get active calls (queued, ringing, in-progress)."""
        return self.filter(status__in=["queued", "ringing", "in-progress"])

    def completed(self):
        """Get completed calls."""
        return self.filter(status="completed")

    def for_agent(self, agent):
        """Get calls for specific agent."""
        return self.filter(agent=agent)

    def for_queue(self, queue):
        """Get calls for specific queue."""
        return self.filter(queue=queue)

    def inbound(self):
        """Get inbound calls."""
        return self.filter(direction="inbound")

    def outbound(self):
        """Get outbound calls."""
        return self.filter(direction="outbound")

    def today(self):
        """Get today's calls."""
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.filter(created_at__gte=today_start)

    def with_duration_stats(self):
        """Annotate calls with computed duration stats."""
        return self.annotate(
            computed_duration=models.Case(
                models.When(end_time__isnull=False, start_time__isnull=False, then=F("end_time") - F("start_time")),
                default=F("duration"),
                output_field=models.IntegerField(),
            )
        )

    def for_analytics(self):
        """Optimized query for analytics."""
        return self.select_related("agent__user", "queue", "phone_number_used").only(
            "id",
            "created_at",
            "status",
            "direction",
            "duration",
            "queue_time",
            "agent__id",
            "agent__extension",
            "agent__user__first_name",
            "agent__user__last_name",
            "queue__id",
            "queue__name",
        )

    def for_dashboard(self):
        """Optimized query for dashboard display."""
        return self.select_related("agent__user", "queue").only(
            "id",
            "public_id",
            "twilio_sid",
            "from_number",
            "to_number",
            "direction",
            "status",
            "created_at",
            "duration",
            "agent__extension",
            "agent__user__first_name",
            "agent__user__last_name",
            "queue__name",
        )


class CallManager(models.Manager):
    """Optimized manager for Call model."""

    def get_queryset(self):
        return CallQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def completed(self):
        return self.get_queryset().completed()

    def for_agent(self, agent):
        return self.get_queryset().for_agent(agent)

    def for_queue(self, queue):
        return self.get_queryset().for_queue(queue)

    def today(self):
        return self.get_queryset().today()

    def for_analytics(self):
        return self.get_queryset().for_analytics()

    def for_dashboard(self):
        return self.get_queryset().for_dashboard()


class QueueQuerySet(models.QuerySet):
    """Optimized queryset for Queue model."""

    def active(self):
        """Get active queues."""
        return self.filter(is_active=True)

    def with_call_counts(self):
        """Annotate queues with call counts."""
        return self.annotate(
            total_calls=Count("calls"),
            active_calls=Count("calls", filter=Q(calls__status__in=["queued", "ringing", "in-progress"])),
            queued_calls=Count("calls", filter=Q(calls__status="queued")),
        )

    def with_agent_counts(self):
        """Annotate queues with agent counts."""
        return self.annotate(
            total_agents=Count("agents", filter=Q(agents__is_active=True)),
            available_agents=Count("agents", filter=Q(agents__is_active=True, agents__status="available")),
        )

    def for_dashboard(self):
        """Optimized query for dashboard display."""
        return (
            self.active()
            .with_call_counts()
            .with_agent_counts()
            .prefetch_related(
                Prefetch("agents", queryset=Agent.objects.active().select_related("user"), to_attr="active_agents_list")
            )
        )


class QueueManager(models.Manager):
    """Optimized manager for Queue model."""

    def get_queryset(self):
        return QueueQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def with_call_counts(self):
        return self.get_queryset().with_call_counts()

    def with_agent_counts(self):
        return self.get_queryset().with_agent_counts()

    def for_dashboard(self):
        return self.get_queryset().for_dashboard()


class CallLogQuerySet(models.QuerySet):
    """Optimized queryset for CallLog model."""

    def for_call(self, call):
        """Get logs for specific call."""
        return self.filter(call=call)

    def for_agent(self, agent):
        """Get logs for specific agent."""
        return self.filter(agent=agent)

    def event_type(self, event_type):
        """Filter by event type."""
        return self.filter(event_type=event_type)

    def recent(self, days=7):
        """Get recent logs."""
        cutoff = timezone.now() - timezone.timedelta(days=days)
        return self.filter(created_at__gte=cutoff)

    def for_analytics(self):
        """Optimized query for analytics."""
        return self.select_related("call", "agent__user").only(
            "id",
            "created_at",
            "event_type",
            "call__id",
            "call__twilio_sid",
            "agent__id",
            "agent__extension",
        )


class CallLogManager(models.Manager):
    """Optimized manager for CallLog model."""

    def get_queryset(self):
        return CallLogQuerySet(self.model, using=self._db)

    def for_call(self, call):
        return self.get_queryset().for_call(call)

    def for_agent(self, agent):
        return self.get_queryset().for_agent(agent)

    def event_type(self, event_type):
        return self.get_queryset().event_type(event_type)

    def recent(self, days=7):
        return self.get_queryset().recent(days)

    def for_analytics(self):
        return self.get_queryset().for_analytics()


class AgentActivityQuerySet(models.QuerySet):
    """Optimized queryset for AgentActivity model."""

    def for_agent(self, agent):
        """Get activities for specific agent."""
        return self.filter(agent=agent)

    def activity_type(self, activity_type):
        """Filter by activity type."""
        return self.filter(activity_type=activity_type)

    def status_changes(self):
        """Get only status change activities."""
        return self.filter(activity_type="status_change")

    def today(self):
        """Get today's activities."""
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.filter(created_at__gte=today_start)

    def for_analytics(self):
        """Optimized query for analytics."""
        return self.select_related("agent__user").only(
            "id",
            "created_at",
            "activity_type",
            "from_status",
            "to_status",
            "duration_seconds",
            "agent__id",
            "agent__extension",
        )


class AgentActivityManager(models.Manager):
    """Optimized manager for AgentActivity model."""

    def get_queryset(self):
        return AgentActivityQuerySet(self.model, using=self._db)

    def for_agent(self, agent):
        return self.get_queryset().for_agent(agent)

    def activity_type(self, activity_type):
        return self.get_queryset().activity_type(activity_type)

    def status_changes(self):
        return self.get_queryset().status_changes()

    def today(self):
        return self.get_queryset().today()

    def for_analytics(self):
        return self.get_queryset().for_analytics()


# Import here to avoid circular imports
from .models import Agent, Call

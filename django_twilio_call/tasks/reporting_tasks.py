"""Reporting and analytics tasks for django-twilio-call.

Handles generation of daily, weekly, and monthly reports and metrics.
"""

import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.utils import timezone

from .base import BaseCallCenterTask

logger = logging.getLogger(__name__)


class ReportGenerator(BaseCallCenterTask):
    """Base class for report generation tasks."""

    def __init__(self, report_type: str):
        super().__init__(f"generate_{report_type}_report")
        self.report_type = report_type

    def generate_call_statistics(self, start_date, end_date):
        """Generate call statistics for the given period."""
        from django.db.models import Avg, Count, Sum

        from ..models import Call

        calls = Call.objects.filter(created_at__gte=start_date, created_at__lt=end_date)

        stats = calls.aggregate(
            total_calls=Count("id"),
            completed_calls=Count("id", filter=Q(status=Call.Status.COMPLETED)),
            avg_duration=Avg("duration"),
            total_duration=Sum("duration"),
            avg_queue_time=Avg("queue_time"),
        )

        # Calculate additional metrics
        stats["completion_rate"] = (
            (stats["completed_calls"] / stats["total_calls"] * 100) if stats["total_calls"] > 0 else 0
        )

        return stats

    def generate_agent_statistics(self, start_date, end_date):
        """Generate agent performance statistics."""
        from django.db.models import Avg, Count, Sum

        from ..models import Agent, Call

        agent_stats = []
        agents = Agent.objects.filter(is_active=True)

        for agent in agents:
            calls = Call.objects.filter(agent=agent, created_at__gte=start_date, created_at__lt=end_date)

            stats = calls.aggregate(
                total_calls=Count("id"),
                completed_calls=Count("id", filter=Q(status=Call.Status.COMPLETED)),
                avg_duration=Avg("duration"),
                total_talk_time=Sum("duration"),
            )

            stats["agent_name"] = agent.user.get_full_name()
            stats["agent_extension"] = agent.extension
            agent_stats.append(stats)

        return agent_stats


@shared_task(bind=True, name="generate_daily_report")
def generate_daily_report(self, date_str: str = None):
    """Generate daily call center report.

    Args:
        date_str: Date string in YYYY-MM-DD format (defaults to yesterday)

    Returns:
        Dictionary with report data

    """
    generator = ReportGenerator("daily")

    if date_str:
        report_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        report_date = timezone.now().date() - timedelta(days=1)

    start_date = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
    end_date = start_date + timedelta(days=1)

    generator.track_progress(1, 4, "Generating call statistics")
    call_stats = generator.generate_call_statistics(start_date, end_date)

    generator.track_progress(2, 4, "Generating agent statistics")
    agent_stats = generator.generate_agent_statistics(start_date, end_date)

    generator.track_progress(3, 4, "Compiling report")
    report_data = {
        "report_type": "daily",
        "date": report_date.isoformat(),
        "call_statistics": call_stats,
        "agent_statistics": agent_stats,
        "generated_at": timezone.now().isoformat(),
    }

    generator.track_progress(4, 4, "Report generation completed")
    return report_data


@shared_task(bind=True, name="generate_weekly_report")
def generate_weekly_report(self, week_start_str: str = None):
    """Generate weekly call center report.

    Args:
        week_start_str: Week start date string in YYYY-MM-DD format

    Returns:
        Dictionary with report data

    """
    generator = ReportGenerator("weekly")

    if week_start_str:
        week_start = datetime.strptime(week_start_str, "%Y-%m-%d").date()
    else:
        # Default to last Monday
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday() + 7)

    start_date = timezone.make_aware(datetime.combine(week_start, datetime.min.time()))
    end_date = start_date + timedelta(days=7)

    generator.track_progress(1, 5, "Generating weekly call statistics")
    call_stats = generator.generate_call_statistics(start_date, end_date)

    generator.track_progress(2, 5, "Generating weekly agent statistics")
    agent_stats = generator.generate_agent_statistics(start_date, end_date)

    generator.track_progress(3, 5, "Calculating trends")
    # Generate daily breakdown for the week
    daily_breakdown = []
    for i in range(7):
        day_start = start_date + timedelta(days=i)
        day_end = day_start + timedelta(days=1)
        day_stats = generator.generate_call_statistics(day_start, day_end)
        day_stats["date"] = day_start.date().isoformat()
        daily_breakdown.append(day_stats)

    generator.track_progress(4, 5, "Compiling weekly report")
    report_data = {
        "report_type": "weekly",
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "call_statistics": call_stats,
        "agent_statistics": agent_stats,
        "daily_breakdown": daily_breakdown,
        "generated_at": timezone.now().isoformat(),
    }

    generator.track_progress(5, 5, "Weekly report generation completed")
    return report_data


@shared_task(bind=True, name="generate_monthly_report")
def generate_monthly_report(self, year: int = None, month: int = None):
    """Generate monthly call center report.

    Args:
        year: Year for the report
        month: Month for the report (1-12)

    Returns:
        Dictionary with report data

    """
    generator = ReportGenerator("monthly")

    if year is None or month is None:
        # Default to last month
        today = timezone.now().date()
        if today.month == 1:
            year = today.year - 1
            month = 12
        else:
            year = today.year
            month = today.month - 1

    start_date = timezone.make_aware(datetime(year, month, 1))
    if month == 12:
        end_date = timezone.make_aware(datetime(year + 1, 1, 1))
    else:
        end_date = timezone.make_aware(datetime(year, month + 1, 1))

    generator.track_progress(1, 6, "Generating monthly call statistics")
    call_stats = generator.generate_call_statistics(start_date, end_date)

    generator.track_progress(2, 6, "Generating monthly agent statistics")
    agent_stats = generator.generate_agent_statistics(start_date, end_date)

    generator.track_progress(3, 6, "Calculating weekly trends")
    # Generate weekly breakdown for the month
    weekly_breakdown = []
    current_date = start_date
    while current_date < end_date:
        week_end = min(current_date + timedelta(days=7), end_date)
        week_stats = generator.generate_call_statistics(current_date, week_end)
        week_stats["week_start"] = current_date.date().isoformat()
        week_stats["week_end"] = (week_end - timedelta(days=1)).date().isoformat()
        weekly_breakdown.append(week_stats)
        current_date = week_end

    generator.track_progress(4, 6, "Calculating queue performance")
    # Queue performance metrics
    from ..models import Call, Queue

    queue_stats = []
    for queue in Queue.objects.filter(is_active=True):
        queue_calls = Call.objects.filter(queue=queue, created_at__gte=start_date, created_at__lt=end_date)

        queue_metrics = queue_calls.aggregate(
            total_calls=Count("id"),
            avg_queue_time=Avg("queue_time"),
            max_queue_time=Max("queue_time"),
        )
        queue_metrics["queue_name"] = queue.name
        queue_stats.append(queue_metrics)

    generator.track_progress(5, 6, "Compiling monthly report")
    report_data = {
        "report_type": "monthly",
        "year": year,
        "month": month,
        "month_name": start_date.strftime("%B"),
        "call_statistics": call_stats,
        "agent_statistics": agent_stats,
        "weekly_breakdown": weekly_breakdown,
        "queue_statistics": queue_stats,
        "generated_at": timezone.now().isoformat(),
    }

    generator.track_progress(6, 6, "Monthly report generation completed")
    return report_data


@shared_task(bind=True, name="calculate_agent_metrics")
def calculate_agent_metrics(self, agent_id: int, start_date_str: str = None, end_date_str: str = None):
    """Calculate detailed metrics for a specific agent.

    Args:
        agent_id: Agent ID to calculate metrics for
        start_date_str: Start date string (YYYY-MM-DD)
        end_date_str: End date string (YYYY-MM-DD)

    Returns:
        Dictionary with agent metrics

    """
    from django.db.models import Avg, Count, Q, Sum

    from ..models import Agent, AgentActivity, Call

    agent = Agent.objects.get(id=agent_id)

    # Default to last 30 days if dates not provided
    if not start_date_str or not end_date_str:
        end_date = timezone.now()
        start_date = end_date - timedelta(days=30)
    else:
        start_date = timezone.make_aware(datetime.strptime(start_date_str, "%Y-%m-%d"))
        end_date = timezone.make_aware(datetime.strptime(end_date_str, "%Y-%m-%d"))

    # Call metrics
    calls = Call.objects.filter(agent=agent, created_at__gte=start_date, created_at__lt=end_date)

    call_metrics = calls.aggregate(
        total_calls=Count("id"),
        completed_calls=Count("id", filter=Q(status=Call.Status.COMPLETED)),
        avg_duration=Avg("duration"),
        total_talk_time=Sum("duration"),
        avg_queue_time=Avg("queue_time"),
    )

    # Activity metrics
    activities = AgentActivity.objects.filter(agent=agent, created_at__gte=start_date, created_at__lt=end_date)

    # Break time calculation
    break_activities = activities.filter(
        activity_type__in=[AgentActivity.ActivityType.BREAK_START, AgentActivity.ActivityType.BREAK_END]
    ).order_by("created_at")

    total_break_time = 0
    break_start = None
    for activity in break_activities:
        if activity.activity_type == AgentActivity.ActivityType.BREAK_START:
            break_start = activity.created_at
        elif activity.activity_type == AgentActivity.ActivityType.BREAK_END and break_start:
            total_break_time += (activity.created_at - break_start).total_seconds()
            break_start = None

    # Compile metrics
    metrics = {
        "agent_name": agent.user.get_full_name(),
        "agent_extension": agent.extension,
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "call_metrics": call_metrics,
        "activity_metrics": {
            "total_break_time_seconds": total_break_time,
            "login_count": activities.filter(activity_type=AgentActivity.ActivityType.LOGIN).count(),
            "status_changes": activities.filter(activity_type=AgentActivity.ActivityType.STATUS_CHANGE).count(),
        },
        "calculated_at": timezone.now().isoformat(),
    }

    return metrics


@shared_task(name="calculate_hourly_metrics")
def calculate_hourly_metrics():
    """Calculate hourly call center metrics for the current hour.
    This task should be run every hour to maintain real-time analytics.
    """
    from django.db.models import Avg, Count

    from ..models import Agent, Call

    current_hour = timezone.now().replace(minute=0, second=0, microsecond=0)
    next_hour = current_hour + timedelta(hours=1)

    # Call metrics for this hour
    hourly_calls = Call.objects.filter(created_at__gte=current_hour, created_at__lt=next_hour)

    call_metrics = hourly_calls.aggregate(
        total_calls=Count("id"),
        inbound_calls=Count("id", filter=Q(direction=Call.Direction.INBOUND)),
        outbound_calls=Count("id", filter=Q(direction=Call.Direction.OUTBOUND)),
        completed_calls=Count("id", filter=Q(status=Call.Status.COMPLETED)),
        avg_duration=Avg("duration"),
    )

    # Agent status snapshot
    agent_status_snapshot = {}
    for status_choice in Agent.Status.choices:
        status_value = status_choice[0]
        count = Agent.objects.filter(status=status_value, is_active=True).count()
        agent_status_snapshot[status_value] = count

    metrics = {
        "hour": current_hour.isoformat(),
        "call_metrics": call_metrics,
        "agent_status_snapshot": agent_status_snapshot,
        "calculated_at": timezone.now().isoformat(),
    }

    # Cache the metrics for dashboard use
    from django.core.cache import cache

    cache_key = f"hourly_metrics:{current_hour.strftime('%Y%m%d%H')}"
    cache.set(cache_key, metrics, timeout=3600)  # Cache for 1 hour

    return metrics

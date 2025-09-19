"""Unified metrics service for analytics, reporting, and KPIs."""

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.core.mail import EmailMessage
from django.db.models import Avg, Count, F, Max, Min, Q, Sum
from django.utils import timezone

from ..models import Agent, Call, Queue
from ..constants import DefaultValues, Limits
from .base import BaseService, cache_result, log_execution

logger = logging.getLogger(__name__)


class ReportType:
    """Report type constants."""

    CALL_SUMMARY = "call_summary"
    AGENT_PERFORMANCE = "agent_performance"
    QUEUE_PERFORMANCE = "queue_performance"
    ABANDONED_CALLS = "abandoned_calls"
    SERVICE_LEVEL = "service_level"
    CALL_DETAIL = "call_detail"
    AGENT_ACTIVITY = "agent_activity"
    HOURLY_DISTRIBUTION = "hourly_distribution"


class ReportFormat:
    """Report format constants."""

    CSV = "csv"
    JSON = "json"
    PDF = "pdf"
    EXCEL = "excel"


class MetricsService(BaseService):
    """Unified service for analytics, metrics, and reporting."""

    service_type = "metrics"

    def __init__(self):
        """Initialize metrics service."""
        super().__init__()

    # ===========================================
    # ANALYTICS METHODS (Real-time & Historical)
    # ===========================================

    def generate_report_async(self, report_type: str, **kwargs) -> str:
        """Generate analytics report asynchronously.

        Args:
            report_type: Type of report (daily, weekly, monthly)
            **kwargs: Report parameters

        Returns:
            Task ID for the report generation job

        """
        from ..tasks import generate_daily_report, generate_monthly_report, generate_weekly_report

        if report_type == "daily":
            task = generate_daily_report.delay(kwargs.get("date_str"))
        elif report_type == "weekly":
            task = generate_weekly_report.delay(kwargs.get("week_start_str"))
        elif report_type == "monthly":
            task = generate_monthly_report.delay(kwargs.get("year"), kwargs.get("month"))
        else:
            raise ValueError(f"Unknown report type: {report_type}")

        logger.info(f"Scheduled {report_type} report generation, task ID: {task.id}")
        return task.id

    def calculate_agent_metrics_async(self, agent_id: int, date_range: Optional[Dict] = None) -> str:
        """Calculate agent metrics asynchronously.

        Args:
            agent_id: Agent ID
            date_range: Optional date range

        Returns:
            Task ID for the calculation job

        """
        from ..tasks import calculate_agent_metrics

        task = calculate_agent_metrics.delay(agent_id, date_range)
        logger.info(f"Scheduled agent metrics calculation for agent {agent_id}, task ID: {task.id}")
        return task.id

    @cache_result(service_type="analytics", key_prefix="call_analytics")
    @log_execution()
    def get_call_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        queue_id: Optional[int] = None,
        agent_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get comprehensive call analytics.

        Args:
            start_date: Start of date range
            end_date: End of date range
            queue_id: Filter by queue
            agent_id: Filter by agent

        Returns:
            Dict containing call metrics

        """
        # Default to last 30 days
        if not end_date:
            end_date = timezone.now()
        if not start_date:
            start_date = end_date - timedelta(days=DefaultValues.DEFAULT_ANALYSIS_PERIOD_DAYS)

        # Use BaseService caching (decorator handles this now, but keeping for reference)
        # cache_key = self.get_cache_key("call_analytics", str(start_date), str(end_date), str(queue_id), str(agent_id))

        # Base query with optimized select_related and prefetch_related
        calls_query = self._get_optimized_calls_query(start_date, end_date, queue_id, agent_id)

        # Calculate core metrics with bulk aggregation
        volume_metrics = self._calculate_volume_metrics(calls_query)
        duration_metrics = self._calculate_duration_metrics(calls_query)
        queue_metrics = self._calculate_queue_metrics(calls_query)

        # Service level (calls answered within threshold)
        service_level_threshold = 20  # seconds
        service_level = self._calculate_service_level(calls_query, service_level_threshold)

        # Distribution analysis
        hourly_distribution = self._get_hourly_distribution(calls_query)
        weekly_distribution = self._get_weekly_distribution(calls_query)
        call_reasons = self._get_call_reasons(calls_query)

        # Performance indicators
        asa = queue_metrics["avg_queue_time"] or 0
        abandonment_rate = self._calculate_abandonment_rate(volume_metrics)
        fcr = self._calculate_fcr(calls_query)

        analytics = {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "volume": volume_metrics,
            "duration": duration_metrics,
            "queue": {
                **queue_metrics,
                "service_level": round(service_level, 2),
                "service_level_threshold": service_level_threshold,
            },
            "performance": {
                "abandonment_rate": round(abandonment_rate, 2),
                "avg_speed_of_answer": round(asa, 2),
                "first_call_resolution": round(fcr, 2),
            },
            "distribution": {
                "hourly": hourly_distribution,
                "weekly": weekly_distribution,
                "reasons": call_reasons,
            },
        }

        # Caching is handled by decorator
        return analytics

    def get_agent_analytics(
        self,
        agent_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get agent performance analytics.

        Args:
            agent_id: Specific agent or all agents
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dict containing agent metrics

        """
        # Default to today
        if not end_date:
            end_date = timezone.now()
        if not start_date:
            start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)

        # Build cache key
        cache_key = f"agent_analytics_{agent_id}_{start_date}_{end_date}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data

        # Optimize agent query with select_related and prefetch_related
        agents = self._get_optimized_agents_query(agent_id)
        agent_metrics = []

        for agent in agents:
            # Get agent's calls with optimized query
            agent_calls = self._get_agent_calls_query(agent, start_date, end_date)

            # Calculate agent-specific metrics
            metrics = self._calculate_agent_metrics(agent, agent_calls, start_date, end_date)
            agent_metrics.append(metrics)

        # Calculate team averages
        team_averages = self._calculate_team_averages(agent_metrics)

        analytics = {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "agents": agent_metrics,
            "team_averages": team_averages,
            "total_agents": len(agent_metrics),
        }

        # Cache results
        cache.set(cache_key, analytics, self.cache_timeout)
        return analytics

    def get_queue_analytics(
        self,
        queue_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get queue performance analytics.

        Args:
            queue_id: Specific queue or all queues
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dict containing queue metrics

        """
        # Default to today
        if not end_date:
            end_date = timezone.now()
        if not start_date:
            start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)

        # Build cache key
        cache_key = f"queue_analytics_{queue_id}_{start_date}_{end_date}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data

        # Optimize queue query with prefetch_related for agents
        queues = self._get_optimized_queues_query(queue_id)
        queue_metrics = []

        for queue in queues:
            metrics = self._calculate_queue_metrics_detailed(queue, start_date, end_date)
            queue_metrics.append(metrics)

        analytics = {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "queues": queue_metrics,
            "total_queues": len(queue_metrics),
        }

        # Cache results
        cache.set(cache_key, analytics, self.cache_timeout)
        return analytics

    def get_real_time_metrics(self) -> Dict[str, Any]:
        """Get real-time operational metrics.

        Returns:
            Dict containing current metrics

        """
        # Check cache first
        cache_key = "real_time_metrics"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data

        # Optimize with bulk queries using aggregation
        call_status_counts = self._get_call_status_counts()
        agent_status_counts = self._get_agent_status_counts()

        # Calculate longest wait and today's stats
        longest_wait = self._get_longest_wait()
        today_stats = self._get_today_stats()

        metrics = {
            "timestamp": timezone.now().isoformat(),
            "current_activity": {
                "active_calls": call_status_counts["active_calls"],
                "queued_calls": call_status_counts["queued_calls"],
                "longest_wait_seconds": longest_wait.total_seconds() if longest_wait else 0,
            },
            "agents": self._format_agent_status_counts(agent_status_counts),
            "today_summary": today_stats,
        }

        # Cache for 10 seconds
        cache.set(cache_key, metrics, 10)
        return metrics

    # ===========================================
    # REPORTING METHODS (Structured Reports)
    # ===========================================

    def generate_report(
        self,
        report_type: str,
        start_date: datetime,
        end_date: datetime,
        format: str = ReportFormat.CSV,
        filters: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Generate a structured report.

        Args:
            report_type: Type of report to generate
            start_date: Start of reporting period
            end_date: End of reporting period
            format: Output format
            filters: Additional filters

        Returns:
            Dict with report data and metadata

        """
        filters = filters or {}

        # Get report data based on type
        data = self._generate_report_data(report_type, start_date, end_date, filters)

        # Format report based on requested format
        output = self._format_report_output(data, format, report_type)

        return {
            "report_type": report_type,
            "format": format,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "generated_at": timezone.now().isoformat(),
            "filters": filters,
            "data": output,
        }

    def schedule_report(
        self,
        report_type: str,
        schedule: str,
        recipients: List[str],
        filters: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Schedule a recurring report.

        Args:
            report_type: Type of report
            schedule: Schedule (daily, weekly, monthly)
            recipients: Email recipients
            filters: Report filters

        Returns:
            Schedule confirmation

        """
        return {
            "report_type": report_type,
            "schedule": schedule,
            "recipients": recipients,
            "filters": filters or {},
            "status": "scheduled",
            "next_run": timezone.now() + timedelta(days=1),
        }

    def email_report(
        self,
        report_data: Dict[str, Any],
        recipients: List[str],
        subject: Optional[str] = None,
    ) -> bool:
        """Email a report to recipients.

        Args:
            report_data: Generated report data
            recipients: Email addresses
            subject: Email subject

        Returns:
            Success status

        """
        if not subject:
            subject = f"Call Center Report - {report_data['report_type']}"

        try:
            # Create email
            email = EmailMessage(
                subject=subject,
                body=f"Please find attached your {report_data['report_type']} report.",
                to=recipients,
            )

            # Attach report
            self._attach_report_to_email(email, report_data)

            # Send email
            email.send()

            logger.info(f"Report emailed to {recipients}")
            return True

        except Exception as e:
            logger.error(f"Failed to email report: {e}")
            return False

    # ===========================================
    # PRIVATE HELPER METHODS (Optimized Queries)
    # ===========================================

    def _get_optimized_calls_query(self, start_date, end_date, queue_id=None, agent_id=None):
        """Get optimized calls query with select_related and filters."""
        query = Call.objects.select_related("agent__user", "queue", "phone_number_used").filter(
            created_at__gte=start_date,
            created_at__lte=end_date,
        )

        if queue_id:
            query = query.filter(queue_id=queue_id)
        if agent_id:
            query = query.filter(agent_id=agent_id)

        return query

    def _get_optimized_agents_query(self, agent_id=None):
        """Get optimized agents query."""
        query = Agent.objects.select_related("user").prefetch_related("calls__queue")

        if agent_id:
            return query.filter(id=agent_id)
        else:
            return query.filter(is_active=True)

    def _get_optimized_queues_query(self, queue_id=None):
        """Get optimized queues query."""
        query = Queue.objects.prefetch_related("agents__user")

        if queue_id:
            return query.filter(id=queue_id)
        else:
            return query.filter(is_active=True)

    def _get_agent_calls_query(self, agent, start_date, end_date):
        """Get agent's calls with optimized query."""
        return Call.objects.select_related("queue").filter(
            agent=agent,
            created_at__gte=start_date,
            created_at__lte=end_date,
        )

    def _calculate_volume_metrics(self, calls_query):
        """Calculate volume metrics with bulk aggregation."""
        return calls_query.aggregate(
            total_calls=Count("id"),
            completed_calls=Count("id", filter=Q(status=Call.Status.COMPLETED)),
            abandoned_calls=Count("id", filter=Q(status=Call.Status.ABANDONED)),
            failed_calls=Count("id", filter=Q(status=Call.Status.FAILED)),
        )

    def _calculate_duration_metrics(self, calls_query):
        """Calculate duration metrics."""
        duration_stats = calls_query.filter(
            status=Call.Status.COMPLETED,
            duration__gt=0,
        ).aggregate(
            avg_duration=Avg("duration"),
            max_duration=Max("duration"),
            min_duration=Min("duration"),
            total_duration=Sum("duration"),
        )

        return {
            "avg_duration": round(duration_stats["avg_duration"] or 0, 2),
            "max_duration": duration_stats["max_duration"] or 0,
            "min_duration": duration_stats["min_duration"] or 0,
            "total_duration": duration_stats["total_duration"] or 0,
        }

    def _calculate_queue_metrics(self, calls_query):
        """Calculate queue time metrics."""
        return calls_query.filter(
            status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS],
            queue_time__gt=0,
        ).aggregate(
            avg_queue_time=Avg("queue_time"),
            max_queue_time=Max("queue_time"),
        )

    def _calculate_service_level(self, calls_query, threshold):
        """Calculate service level percentage."""
        total_calls = calls_query.filter(
            status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS, Call.Status.ABANDONED]
        ).count()

        calls_within_sl = calls_query.filter(
            status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS],
            queue_time__lte=threshold,
        ).count()

        return (calls_within_sl / total_calls * 100) if total_calls > 0 else 0

    def _calculate_abandonment_rate(self, volume_metrics):
        """Calculate abandonment rate."""
        total = volume_metrics["total_calls"]
        abandoned = volume_metrics["abandoned_calls"]
        return (abandoned / total * 100) if total > 0 else 0

    def _get_call_status_counts(self):
        """Get current call status counts with single query."""
        return Call.objects.aggregate(
            active_calls=Count("id", filter=Q(status=Call.Status.IN_PROGRESS)),
            queued_calls=Count("id", filter=Q(status=Call.Status.QUEUED)),
        )

    def _get_agent_status_counts(self):
        """Get agent status counts with single query."""
        return Agent.objects.filter(is_active=True).aggregate(
            total_agents=Count("id"),
            available_agents=Count("id", filter=Q(status=Agent.Status.AVAILABLE)),
            busy_agents=Count("id", filter=Q(status=Agent.Status.BUSY)),
            on_break_agents=Count("id", filter=Q(status=Agent.Status.ON_BREAK)),
        )

    def _format_agent_status_counts(self, counts):
        """Format agent status counts for response."""
        total = counts["total_agents"]
        available = counts["available_agents"]
        busy = counts["busy_agents"]
        on_break = counts["on_break_agents"]

        return {
            "total": total,
            "available": available,
            "busy": busy,
            "on_break": on_break,
            "offline": total - (available + busy + on_break),
        }

    def _get_longest_wait(self):
        """Get longest queue wait time."""
        return Call.objects.filter(status=Call.Status.QUEUED).aggregate(max_wait=Max(timezone.now() - F("created_at")))[
            "max_wait"
        ]

    def _get_today_stats(self):
        """Get today's statistics with optimized single query."""
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return Call.objects.filter(created_at__gte=today_start).aggregate(
            total_calls=Count("id"),
            completed_calls=Count("id", filter=Q(status=Call.Status.COMPLETED)),
            abandoned_calls=Count("id", filter=Q(status=Call.Status.ABANDONED)),
            avg_duration=Avg("duration", filter=Q(status=Call.Status.COMPLETED)),
            avg_queue_time=Avg("queue_time", filter=Q(status=Call.Status.COMPLETED)),
        )

    def _calculate_agent_metrics(self, agent, agent_calls, start_date, end_date):
        """Calculate comprehensive agent metrics."""
        # Basic call metrics
        call_metrics = agent_calls.aggregate(
            total_calls=Count("id"),
            completed_calls=Count("id", filter=Q(status=Call.Status.COMPLETED)),
            avg_handling_time=Avg("duration", filter=Q(status=Call.Status.COMPLETED)),
        )

        # Transfer metrics
        transfers = agent_calls.filter(metadata__transferred=True).count()
        transfer_rate = (
            (transfers / call_metrics["completed_calls"] * 100) if call_metrics["completed_calls"] > 0 else 0
        )

        # Status time and occupancy
        status_time = self._calculate_agent_status_time(agent, start_date, end_date)
        occupancy_rate = self._calculate_occupancy_rate(agent, start_date, end_date)

        return {
            "agent_id": agent.id,
            "agent_name": agent.user.get_full_name(),
            "extension": agent.extension,
            "calls": {
                "total": call_metrics["total_calls"],
                "completed": call_metrics["completed_calls"],
                "avg_handling_time": round(call_metrics["avg_handling_time"] or 0, 2),
                "transfers": transfers,
                "transfer_rate": round(transfer_rate, 2),
            },
            "status_time": status_time,
            "occupancy_rate": round(occupancy_rate, 2),
            "current_status": agent.status,
            "skills": agent.skills,
        }

    def _calculate_team_averages(self, agent_metrics):
        """Calculate team averages from agent metrics."""
        if not agent_metrics:
            return {"avg_calls": 0, "avg_handling_time": 0, "avg_occupancy": 0}

        count = len(agent_metrics)
        return {
            "avg_calls": sum(a["calls"]["total"] for a in agent_metrics) / count,
            "avg_handling_time": sum(a["calls"]["avg_handling_time"] for a in agent_metrics) / count,
            "avg_occupancy": sum(a["occupancy_rate"] for a in agent_metrics) / count,
        }

    def _calculate_queue_metrics_detailed(self, queue, start_date, end_date):
        """Calculate detailed queue metrics."""
        # Get queue's calls
        queue_calls = Call.objects.filter(
            queue=queue,
            created_at__gte=start_date,
            created_at__lte=end_date,
        )

        # Basic metrics
        metrics = queue_calls.aggregate(
            total_calls=Count("id"),
            completed_calls=Count("id", filter=Q(status=Call.Status.COMPLETED)),
            abandoned_calls=Count("id", filter=Q(status=Call.Status.ABANDONED)),
            avg_wait_time=Avg("queue_time", filter=Q(queue_time__gt=0)),
        )

        # Service level calculation
        sl_threshold = queue.service_level_threshold or 20
        calls_within_sl = queue_calls.filter(
            status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS],
            queue_time__lte=sl_threshold,
        ).count()

        service_level = (
            (calls_within_sl / (metrics["completed_calls"] + metrics["abandoned_calls"]) * 100)
            if (metrics["completed_calls"] + metrics["abandoned_calls"]) > 0
            else 0
        )

        # Current queue state
        current_size = Call.objects.filter(
            queue=queue,
            status=Call.Status.QUEUED,
        ).count()

        # Agent utilization
        available_agents = queue.agents.filter(
            status=Agent.Status.AVAILABLE,
            is_active=True,
        ).count()
        total_agents = queue.agents.filter(is_active=True).count()

        return {
            "queue_id": queue.id,
            "queue_name": queue.name,
            "priority": queue.priority,
            "calls": {
                "total": metrics["total_calls"],
                "completed": metrics["completed_calls"],
                "abandoned": metrics["abandoned_calls"],
                "current_size": current_size,
            },
            "performance": {
                "avg_wait_time": round(metrics["avg_wait_time"] or 0, 2),
                "service_level": round(service_level, 2),
                "service_level_threshold": sl_threshold,
                "abandonment_rate": round(
                    (metrics["abandoned_calls"] / metrics["total_calls"] * 100) if metrics["total_calls"] > 0 else 0, 2
                ),
            },
            "agents": {
                "available": available_agents,
                "total": total_agents,
                "utilization": round(
                    ((total_agents - available_agents) / total_agents * 100) if total_agents > 0 else 0, 2
                ),
            },
            "routing_strategy": queue.routing_strategy,
        }

    # ===========================================
    # DISTRIBUTION AND PATTERN ANALYSIS
    # ===========================================

    def _get_hourly_distribution(self, calls_query) -> List[Dict]:
        """Get call distribution by hour with optimized single query."""
        # Use aggregation to get all hours at once
        hourly_counts = (
            calls_query.extra(select={"hour": "EXTRACT(hour FROM created_at)"})
            .values("hour")
            .annotate(count=Count("id"))
            .order_by("hour")
        )

        # Create full 24-hour array
        hourly_data = [{"hour": hour, "count": 0} for hour in range(24)]

        # Fill in actual counts
        for item in hourly_counts:
            hour = int(item["hour"])
            hourly_data[hour]["count"] = item["count"]

        return hourly_data

    def _get_weekly_distribution(self, calls_query) -> List[Dict]:
        """Get call distribution by day of week with optimized query."""
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        # Use aggregation to get all days at once
        daily_counts = (
            calls_query.extra(select={"day": "EXTRACT(dow FROM created_at)"}).values("day").annotate(count=Count("id"))
        )

        # Create full week array (Django uses 0=Sunday, we want 0=Monday)
        weekly_data = [{"day": day, "count": 0} for day in days]

        # Fill in actual counts, adjusting for Django's day numbering
        for item in daily_counts:
            django_day = int(item["day"])  # 0=Sunday in Django
            our_day = (django_day + 6) % 7  # Convert to 0=Monday
            weekly_data[our_day]["count"] = item["count"]

        return weekly_data

    def _get_call_reasons(self, calls_query) -> List[Dict]:
        """Get top call reasons/tags with optimized approach."""
        # Use database-level JSON aggregation where possible
        reasons = {}

        # Limit the sample size for performance
        sample_calls = calls_query.filter(metadata__tags__isnull=False).values_list("metadata", flat=True)[:Limits.MAX_ANALYTICS_RESULTS]

        for metadata in sample_calls:
            tags = metadata.get("tags", []) if metadata else []
            for tag in tags:
                reasons[tag] = reasons.get(tag, 0) + 1

        # Sort by count and return top 10
        sorted_reasons = sorted(reasons.items(), key=lambda x: x[1], reverse=True)[:10]
        return [{"reason": reason, "count": count} for reason, count in sorted_reasons]

    def _calculate_fcr(self, calls_query) -> float:
        """Calculate first call resolution rate with optimized sampling."""
        completed_calls = calls_query.filter(status=Call.Status.COMPLETED)
        total_sample = min(100, completed_calls.count())

        if total_sample == 0:
            return 0

        # Sample calls for FCR calculation
        sample_calls = completed_calls.values("from_number", "created_at")[:total_sample]
        fcr_count = 0

        for call_data in sample_calls:
            # Check for follow-up calls within 7 days
            follow_up_exists = Call.objects.filter(
                from_number=call_data["from_number"],
                created_at__gt=call_data["created_at"],
                created_at__lt=call_data["created_at"] + timedelta(days=7),
            ).exists()

            if not follow_up_exists:
                fcr_count += 1

        return (fcr_count / total_sample * 100) if total_sample > 0 else 0

    def _calculate_agent_status_time(self, agent, start_date, end_date) -> Dict[str, int]:
        """Calculate time spent in each status."""
        from ..models import AgentActivity

        activities = AgentActivity.objects.filter(
            agent=agent,
            timestamp__gte=start_date,
            timestamp__lte=end_date,
        ).order_by("timestamp")

        status_time = {"available": 0, "busy": 0, "on_break": 0, "offline": 0}

        last_activity = None
        for activity in activities:
            if last_activity:
                duration = (activity.timestamp - last_activity.timestamp).total_seconds()
                status_key = last_activity.new_status.lower().replace("_", "")
                if status_key in status_time:
                    status_time[status_key] += duration
            last_activity = activity

        # Add time from last activity to end_date
        if last_activity:
            duration = (end_date - last_activity.timestamp).total_seconds()
            status_key = last_activity.new_status.lower().replace("_", "")
            if status_key in status_time:
                status_time[status_key] += duration

        return status_time

    def _calculate_occupancy_rate(self, agent, start_date, end_date) -> float:
        """Calculate agent occupancy rate."""
        status_time = self._calculate_agent_status_time(agent, start_date, end_date)

        productive_time = status_time["busy"]
        available_time = status_time["available"] + status_time["busy"]

        return (productive_time / available_time * 100) if available_time > 0 else 0

    # ===========================================
    # REPORT GENERATION AND FORMATTING
    # ===========================================

    def _generate_report_data(self, report_type, start_date, end_date, filters):
        """Generate report data based on type."""
        if report_type == ReportType.CALL_SUMMARY:
            return self._generate_call_summary(start_date, end_date, filters)
        elif report_type == ReportType.AGENT_PERFORMANCE:
            return self._generate_agent_performance(start_date, end_date, filters)
        elif report_type == ReportType.QUEUE_PERFORMANCE:
            return self._generate_queue_performance(start_date, end_date, filters)
        elif report_type == ReportType.ABANDONED_CALLS:
            return self._generate_abandoned_calls(start_date, end_date, filters)
        elif report_type == ReportType.SERVICE_LEVEL:
            return self._generate_service_level(start_date, end_date, filters)
        elif report_type == ReportType.CALL_DETAIL:
            return self._generate_call_detail(start_date, end_date, filters)
        elif report_type == ReportType.AGENT_ACTIVITY:
            return self._generate_agent_activity(start_date, end_date, filters)
        elif report_type == ReportType.HOURLY_DISTRIBUTION:
            return self._generate_hourly_distribution(start_date, end_date, filters)
        else:
            raise ValueError(f"Unknown report type: {report_type}")

    def _format_report_output(self, data, format_type, report_type):
        """Format report output based on requested format."""
        if format_type == ReportFormat.CSV:
            return self._format_as_csv(data)
        elif format_type == ReportFormat.JSON:
            return data
        elif format_type == ReportFormat.PDF:
            return self._format_as_pdf(data, report_type)
        elif format_type == ReportFormat.EXCEL:
            return self._format_as_excel(data)
        else:
            raise ValueError(f"Unknown format: {format_type}")

    def _generate_call_summary(self, start_date, end_date, filters) -> List[Dict]:
        """Generate call summary report."""
        calls_query = Call.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date,
        )

        # Apply filters
        if filters.get("queue_id"):
            calls_query = calls_query.filter(queue_id=filters["queue_id"])
        if filters.get("agent_id"):
            calls_query = calls_query.filter(agent_id=filters["agent_id"])

        # Group by date with optimized aggregation
        summary = []
        current_date = start_date.date()
        end = end_date.date()

        while current_date <= end:
            day_start = timezone.make_aware(datetime.combine(current_date, datetime.min.time()))
            day_end = timezone.make_aware(datetime.combine(current_date, datetime.max.time()))

            day_calls = calls_query.filter(
                created_at__gte=day_start,
                created_at__lte=day_end,
            )

            metrics = day_calls.aggregate(
                total_calls=Count("id"),
                completed=Count("id", filter=Q(status=Call.Status.COMPLETED)),
                abandoned=Count("id", filter=Q(status=Call.Status.ABANDONED)),
                avg_duration=Avg("duration", filter=Q(status=Call.Status.COMPLETED)),
                avg_queue_time=Avg("queue_time"),
                total_duration=Sum("duration", filter=Q(status=Call.Status.COMPLETED)),
            )

            summary.append(
                {
                    "date": current_date.isoformat(),
                    "total_calls": metrics["total_calls"],
                    "completed_calls": metrics["completed"],
                    "abandoned_calls": metrics["abandoned"],
                    "avg_duration": round(metrics["avg_duration"] or 0, 2),
                    "avg_queue_time": round(metrics["avg_queue_time"] or 0, 2),
                    "total_duration": metrics["total_duration"] or 0,
                    "abandonment_rate": round(
                        (metrics["abandoned"] / metrics["total_calls"] * 100) if metrics["total_calls"] > 0 else 0, 2
                    ),
                }
            )

            current_date += timedelta(days=1)

        return summary

    def _generate_agent_performance(self, start_date, end_date, filters) -> List[Dict]:
        """Generate agent performance report."""
        agents_query = Agent.objects.filter(is_active=True)

        if filters.get("agent_id"):
            agents_query = agents_query.filter(id=filters["agent_id"])

        performance_data = []

        for agent in agents_query:
            calls = Call.objects.filter(
                agent=agent,
                created_at__gte=start_date,
                created_at__lte=end_date,
            )

            metrics = calls.aggregate(
                total_calls=Count("id"),
                completed=Count("id", filter=Q(status=Call.Status.COMPLETED)),
                avg_duration=Avg("duration", filter=Q(status=Call.Status.COMPLETED)),
                total_duration=Sum("duration", filter=Q(status=Call.Status.COMPLETED)),
            )

            # Transfer and hold metrics
            transfers = calls.filter(metadata__transferred=True).count()
            hold_time = calls.aggregate(avg_hold=Avg("metadata__hold_time"))["avg_hold"] or 0

            performance_data.append(
                {
                    "agent_id": agent.id,
                    "agent_name": f"{agent.first_name} {agent.last_name}",
                    "extension": agent.extension,
                    "total_calls": metrics["total_calls"],
                    "completed_calls": metrics["completed"],
                    "avg_handling_time": round(metrics["avg_duration"] or 0, 2),
                    "total_talk_time": metrics["total_duration"] or 0,
                    "transfers": transfers,
                    "transfer_rate": round(
                        (transfers / metrics["completed"] * 100) if metrics["completed"] > 0 else 0, 2
                    ),
                    "avg_hold_time": round(hold_time, 2),
                }
            )

        return performance_data

    def _generate_queue_performance(self, start_date, end_date, filters) -> List[Dict]:
        """Generate queue performance report - reuses _calculate_queue_metrics_detailed."""
        queues_query = Queue.objects.filter(is_active=True)

        if filters.get("queue_id"):
            queues_query = queues_query.filter(id=filters["queue_id"])

        return [self._calculate_queue_metrics_detailed(queue, start_date, end_date) for queue in queues_query]

    def _generate_abandoned_calls(self, start_date, end_date, filters) -> List[Dict]:
        """Generate abandoned calls report."""
        calls_query = Call.objects.filter(
            status=Call.Status.ABANDONED,
            created_at__gte=start_date,
            created_at__lte=end_date,
        )

        # Apply filters
        if filters.get("queue_id"):
            calls_query = calls_query.filter(queue_id=filters["queue_id"])
        if filters.get("min_wait_time"):
            calls_query = calls_query.filter(queue_time__gte=filters["min_wait_time"])

        abandoned_data = []
        for call in calls_query.select_related("queue"):
            abandoned_data.append(
                {
                    "call_id": str(call.public_id),
                    "from_number": call.from_number,
                    "to_number": call.to_number,
                    "queue": call.queue.name if call.queue else "N/A",
                    "wait_time": call.queue_time or 0,
                    "created_at": call.created_at.isoformat(),
                    "abandoned_at": call.updated_at.isoformat(),
                }
            )

        return abandoned_data

    def _generate_service_level(self, start_date, end_date, filters) -> List[Dict]:
        """Generate service level report."""
        service_level_data = []
        current_time = start_date

        while current_time < end_date:
            hour_end = current_time + timedelta(hours=1)

            calls_query = Call.objects.filter(
                created_at__gte=current_time,
                created_at__lt=hour_end,
            )

            if filters.get("queue_id"):
                calls_query = calls_query.filter(queue_id=filters["queue_id"])

            # Calculate metrics
            total_offered = calls_query.count()
            answered = calls_query.filter(status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS]).count()
            abandoned = calls_query.filter(status=Call.Status.ABANDONED).count()

            # Service level calculation
            threshold = filters.get("service_level_threshold", 20)
            within_sl = calls_query.filter(
                status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS],
                queue_time__lte=threshold,
            ).count()

            service_level = (within_sl / answered * 100) if answered > 0 else 0

            service_level_data.append(
                {
                    "timestamp": current_time.isoformat(),
                    "hour": current_time.hour,
                    "offered": total_offered,
                    "answered": answered,
                    "abandoned": abandoned,
                    "within_service_level": within_sl,
                    "service_level": round(service_level, 2),
                    "threshold_seconds": threshold,
                }
            )

            current_time = hour_end

        return service_level_data

    def _generate_call_detail(self, start_date, end_date, filters) -> List[Dict]:
        """Generate detailed call records."""
        calls_query = Call.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date,
        ).select_related("agent", "queue")

        # Apply filters
        if filters.get("queue_id"):
            calls_query = calls_query.filter(queue_id=filters["queue_id"])
        if filters.get("agent_id"):
            calls_query = calls_query.filter(agent_id=filters["agent_id"])
        if filters.get("status"):
            calls_query = calls_query.filter(status=filters["status"])

        call_details = []
        for call in calls_query[:Limits.MAX_ANALYTICS_RESULTS]:  # Limit for performance
            call_details.append(
                {
                    "call_id": str(call.public_id),
                    "twilio_sid": call.twilio_sid,
                    "from_number": call.from_number,
                    "to_number": call.to_number,
                    "direction": call.direction,
                    "status": call.status,
                    "queue": call.queue.name if call.queue else "N/A",
                    "agent": f"{call.agent.first_name} {call.agent.last_name}" if call.agent else "N/A",
                    "duration": call.duration or 0,
                    "queue_time": call.queue_time or 0,
                    "created_at": call.created_at.isoformat(),
                    "answered_at": call.answered_at.isoformat() if call.answered_at else None,
                    "ended_at": call.ended_at.isoformat() if call.ended_at else None,
                    "recording_url": call.recording_url,
                    "voicemail_url": call.voicemail_url,
                }
            )

        return call_details

    def _generate_agent_activity(self, start_date, end_date, filters) -> List[Dict]:
        """Generate agent activity report."""
        from ..models import AgentActivity

        activities_query = AgentActivity.objects.filter(
            timestamp__gte=start_date,
            timestamp__lte=end_date,
        ).select_related("agent")

        if filters.get("agent_id"):
            activities_query = activities_query.filter(agent_id=filters["agent_id"])

        activity_data = []
        for activity in activities_query[:Limits.MAX_ANALYTICS_RESULTS]:  # Limit for performance
            activity_data.append(
                {
                    "agent_id": activity.agent.id,
                    "agent_name": f"{activity.agent.first_name} {activity.agent.last_name}",
                    "activity_type": activity.activity_type,
                    "old_status": activity.old_status,
                    "new_status": activity.new_status,
                    "reason": activity.reason,
                    "timestamp": activity.timestamp.isoformat(),
                }
            )

        return activity_data

    def _generate_hourly_distribution(self, start_date, end_date, filters) -> List[Dict]:
        """Generate hourly call distribution report."""
        calls_query = Call.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date,
        )

        if filters.get("queue_id"):
            calls_query = calls_query.filter(queue_id=filters["queue_id"])

        hourly_data = []
        for hour in range(24):
            hour_calls = calls_query.filter(created_at__hour=hour)

            metrics = hour_calls.aggregate(
                total=Count("id"),
                completed=Count("id", filter=Q(status=Call.Status.COMPLETED)),
                abandoned=Count("id", filter=Q(status=Call.Status.ABANDONED)),
                avg_duration=Avg("duration", filter=Q(status=Call.Status.COMPLETED)),
                avg_queue_time=Avg("queue_time"),
            )

            hourly_data.append(
                {
                    "hour": hour,
                    "hour_label": f"{hour:02d}:00",
                    "total_calls": metrics["total"],
                    "completed": metrics["completed"],
                    "abandoned": metrics["abandoned"],
                    "avg_duration": round(metrics["avg_duration"] or 0, 2),
                    "avg_queue_time": round(metrics["avg_queue_time"] or 0, 2),
                }
            )

        return hourly_data

    def _format_as_csv(self, data: List[Dict]) -> str:
        """Format data as CSV."""
        if not data:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)

        return output.getvalue()

    def _format_as_pdf(self, data: List[Dict], report_type: str) -> bytes:
        """Format data as PDF."""
        logger.info(f"PDF generation requested for {report_type}")
        return b"PDF generation not implemented"

    def _format_as_excel(self, data: List[Dict]) -> bytes:
        """Format data as Excel."""
        return self._format_as_csv(data).encode()

    def _attach_report_to_email(self, email, report_data):
        """Attach report to email based on format."""
        if report_data["format"] == ReportFormat.CSV:
            email.attach(
                f"report_{report_data['report_type']}.csv",
                report_data["data"],
                "text/csv",
            )
        elif report_data["format"] == ReportFormat.PDF:
            email.attach(
                f"report_{report_data['report_type']}.pdf",
                report_data["data"],
                "application/pdf",
            )


# Create unified service instance
metrics_service = MetricsService()

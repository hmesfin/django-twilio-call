"""Analytics service for call metrics and KPIs."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.core.cache import cache
from django.db.models import Avg, Count, F, Max, Min, Q, Sum
from django.utils import timezone

from ..models import Agent, Call, Queue
from ..conf import get_config
from ..constants import CacheTimeouts, DefaultValues, Limits
from .base import BaseService

logger = logging.getLogger(__name__)


class AnalyticsService(BaseService):
    """Service for generating analytics and metrics."""

    service_type = "analytics"

    def __init__(self):
        """Initialize analytics service."""
        super().__init__()

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

        # Build cache key
        cache_key = f"call_analytics_{start_date}_{end_date}_{queue_id}_{agent_id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data

        # Base query with optimized select_related and prefetch_related
        calls_query = Call.objects.select_related("agent__user", "queue", "phone_number_used").filter(
            created_at__gte=start_date,
            created_at__lte=end_date,
        )

        if queue_id:
            calls_query = calls_query.filter(queue_id=queue_id)
        if agent_id:
            calls_query = calls_query.filter(agent_id=agent_id)

        # Calculate metrics
        total_calls = calls_query.count()
        completed_calls = calls_query.filter(status=Call.Status.COMPLETED).count()
        abandoned_calls = calls_query.filter(status=Call.Status.ABANDONED).count()
        failed_calls = calls_query.filter(status=Call.Status.FAILED).count()

        # Duration metrics
        duration_stats = calls_query.filter(
            status=Call.Status.COMPLETED,
            duration__gt=0,
        ).aggregate(
            avg_duration=Avg("duration"),
            max_duration=Max("duration"),
            min_duration=Min("duration"),
            total_duration=Sum("duration"),
        )

        # Queue time metrics
        queue_stats = calls_query.filter(
            status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS],
            queue_time__gt=0,
        ).aggregate(
            avg_queue_time=Avg("queue_time"),
            max_queue_time=Max("queue_time"),
        )

        # Service level (calls answered within threshold)
        service_level_threshold = 20  # seconds
        calls_within_sl = calls_query.filter(
            status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS],
            queue_time__lte=service_level_threshold,
        ).count()

        service_level = (
            (calls_within_sl / (completed_calls + abandoned_calls) * 100)
            if (completed_calls + abandoned_calls) > 0
            else 0
        )

        # Call distribution by hour
        hourly_distribution = self._get_hourly_distribution(calls_query)

        # Call distribution by day of week
        weekly_distribution = self._get_weekly_distribution(calls_query)

        # Top call reasons/tags
        call_reasons = self._get_call_reasons(calls_query)

        # Average speed of answer (ASA)
        asa = queue_stats["avg_queue_time"] or 0

        # Abandonment rate
        abandonment_rate = (abandoned_calls / total_calls * 100) if total_calls > 0 else 0

        # First call resolution (FCR) - simplified
        fcr = self._calculate_fcr(calls_query)

        analytics = {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "volume": {
                "total_calls": total_calls,
                "completed_calls": completed_calls,
                "abandoned_calls": abandoned_calls,
                "failed_calls": failed_calls,
            },
            "duration": {
                "avg_duration": round(duration_stats["avg_duration"] or 0, 2),
                "max_duration": duration_stats["max_duration"] or 0,
                "min_duration": duration_stats["min_duration"] or 0,
                "total_duration": duration_stats["total_duration"] or 0,
            },
            "queue": {
                "avg_queue_time": round(queue_stats["avg_queue_time"] or 0, 2),
                "max_queue_time": queue_stats["max_queue_time"] or 0,
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

        # Cache results
        cache.set(cache_key, analytics, self.cache_timeout)

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
        if agent_id:
            agents = Agent.objects.select_related("user").prefetch_related("calls__queue").filter(id=agent_id)
        else:
            agents = Agent.objects.select_related("user").prefetch_related("calls__queue").filter(is_active=True)

        agent_metrics = []

        for agent in agents:
            # Get agent's calls with optimized query - use prefetched data when possible
            agent_calls = Call.objects.select_related("queue").filter(
                agent=agent,
                created_at__gte=start_date,
                created_at__lte=end_date,
            )

            # Calculate metrics
            total_calls = agent_calls.count()
            completed_calls = agent_calls.filter(status=Call.Status.COMPLETED).count()

            # Average handling time
            aht = (
                agent_calls.filter(
                    status=Call.Status.COMPLETED,
                    duration__gt=0,
                ).aggregate(avg=Avg("duration"))["avg"]
                or 0
            )

            # Status breakdown
            status_time = self._calculate_agent_status_time(agent, start_date, end_date)

            # Occupancy rate
            occupancy_rate = self._calculate_occupancy_rate(agent, start_date, end_date)

            # Transfer rate
            transfers = agent_calls.filter(metadata__transferred=True).count()
            transfer_rate = (transfers / completed_calls * 100) if completed_calls > 0 else 0

            agent_metrics.append(
                {
                    "agent_id": agent.id,
                    "agent_name": agent.user.get_full_name(),  # Use select_related user
                    "extension": agent.extension,
                    "calls": {
                        "total": total_calls,
                        "completed": completed_calls,
                        "avg_handling_time": round(aht, 2),
                        "transfers": transfers,
                        "transfer_rate": round(transfer_rate, 2),
                    },
                    "status_time": status_time,
                    "occupancy_rate": round(occupancy_rate, 2),
                    "current_status": agent.status,
                    "skills": agent.skills,
                }
            )

        # Calculate team averages
        if len(agent_metrics) > 0:
            team_averages = {
                "avg_calls": sum(a["calls"]["total"] for a in agent_metrics) / len(agent_metrics),
                "avg_handling_time": sum(a["calls"]["avg_handling_time"] for a in agent_metrics) / len(agent_metrics),
                "avg_occupancy": sum(a["occupancy_rate"] for a in agent_metrics) / len(agent_metrics),
            }
        else:
            team_averages = {
                "avg_calls": 0,
                "avg_handling_time": 0,
                "avg_occupancy": 0,
            }

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
        if queue_id:
            queues = Queue.objects.prefetch_related("agents__user").filter(id=queue_id)
        else:
            queues = Queue.objects.prefetch_related("agents__user").filter(is_active=True)

        queue_metrics = []

        for queue in queues:
            # Get queue's calls
            queue_calls = Call.objects.filter(
                queue=queue,
                created_at__gte=start_date,
                created_at__lte=end_date,
            )

            # Calculate metrics
            total_calls = queue_calls.count()
            completed_calls = queue_calls.filter(status=Call.Status.COMPLETED).count()
            abandoned_calls = queue_calls.filter(status=Call.Status.ABANDONED).count()

            # Average wait time
            awt = queue_calls.filter(queue_time__gt=0).aggregate(avg=Avg("queue_time"))["avg"] or 0

            # Service level
            sl_threshold = queue.service_level_threshold or 20
            calls_within_sl = queue_calls.filter(
                status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS],
                queue_time__lte=sl_threshold,
            ).count()

            service_level = (
                (calls_within_sl / (completed_calls + abandoned_calls) * 100)
                if (completed_calls + abandoned_calls) > 0
                else 0
            )

            # Current queue size
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

            queue_metrics.append(
                {
                    "queue_id": queue.id,
                    "queue_name": queue.name,
                    "priority": queue.priority,
                    "calls": {
                        "total": total_calls,
                        "completed": completed_calls,
                        "abandoned": abandoned_calls,
                        "current_size": current_size,
                    },
                    "performance": {
                        "avg_wait_time": round(awt, 2),
                        "service_level": round(service_level, 2),
                        "service_level_threshold": sl_threshold,
                        "abandonment_rate": round((abandoned_calls / total_calls * 100) if total_calls > 0 else 0, 2),
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
            )

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

        # Current calls with single query
        call_status_counts = Call.objects.aggregate(
            active_calls=Count("id", filter=Q(status=Call.Status.IN_PROGRESS)),
            queued_calls=Count("id", filter=Q(status=Call.Status.QUEUED)),
        )
        active_calls = call_status_counts["active_calls"]
        queued_calls = call_status_counts["queued_calls"]

        # Agent status with single query
        agent_status_counts = Agent.objects.filter(is_active=True).aggregate(
            total_agents=Count("id"),
            available_agents=Count("id", filter=Q(status=Agent.Status.AVAILABLE)),
            busy_agents=Count("id", filter=Q(status=Agent.Status.BUSY)),
            on_break_agents=Count("id", filter=Q(status=Agent.Status.ON_BREAK)),
        )
        total_agents = agent_status_counts["total_agents"]
        available_agents = agent_status_counts["available_agents"]
        busy_agents = agent_status_counts["busy_agents"]
        on_break_agents = agent_status_counts["on_break_agents"]

        # Queue metrics
        longest_wait = Call.objects.filter(status=Call.Status.QUEUED).aggregate(
            max_wait=Max(timezone.now() - F("created_at"))
        )["max_wait"]

        # Today's statistics with optimized single query
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_stats = Call.objects.filter(created_at__gte=today_start).aggregate(
            total_calls=Count("id"),
            completed_calls=Count("id", filter=Q(status=Call.Status.COMPLETED)),
            abandoned_calls=Count("id", filter=Q(status=Call.Status.ABANDONED)),
            avg_duration=Avg("duration", filter=Q(status=Call.Status.COMPLETED)),
            avg_queue_time=Avg("queue_time", filter=Q(status=Call.Status.COMPLETED)),
        )

        metrics = {
            "timestamp": timezone.now().isoformat(),
            "current_activity": {
                "active_calls": active_calls,
                "queued_calls": queued_calls,
                "longest_wait_seconds": longest_wait.total_seconds() if longest_wait else 0,
            },
            "agents": {
                "total": total_agents,
                "available": available_agents,
                "busy": busy_agents,
                "on_break": on_break_agents,
                "offline": total_agents - (available_agents + busy_agents + on_break_agents),
            },
            "today_summary": {
                "total_calls": today_stats["total_calls"],
                "completed": today_stats["completed_calls"],
                "abandoned": today_stats["abandoned_calls"],
                "avg_duration": round(today_stats["avg_duration"] or 0, 2),
                "avg_queue_time": round(today_stats["avg_queue_time"] or 0, 2),
            },
        }

        # Cache for 10 seconds
        cache.set(cache_key, metrics, 10)

        return metrics

    def _get_hourly_distribution(self, calls_query) -> List[Dict]:
        """Get call distribution by hour.

        Args:
            calls_query: Filtered call queryset

        Returns:
            List of hourly counts

        """
        hourly_data = []
        for hour in range(24):
            count = calls_query.filter(created_at__hour=hour).count()
            hourly_data.append(
                {
                    "hour": hour,
                    "count": count,
                }
            )
        return hourly_data

    def _get_weekly_distribution(self, calls_query) -> List[Dict]:
        """Get call distribution by day of week.

        Args:
            calls_query: Filtered call queryset

        Returns:
            List of daily counts

        """
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        weekly_data = []
        for day_num, day_name in enumerate(days, 1):
            # Django uses 1=Sunday, we want 1=Monday
            django_day = (day_num % 7) + 1
            count = calls_query.filter(created_at__week_day=django_day).count()
            weekly_data.append(
                {
                    "day": day_name,
                    "count": count,
                }
            )
        return weekly_data

    def _get_call_reasons(self, calls_query) -> List[Dict]:
        """Get top call reasons/tags.

        Args:
            calls_query: Filtered call queryset

        Returns:
            List of reasons with counts

        """
        # Get from metadata tags
        reasons = {}
        for call in calls_query.filter(metadata__tags__isnull=False):
            tags = call.metadata.get("tags", [])
            for tag in tags:
                reasons[tag] = reasons.get(tag, 0) + 1

        # Sort by count and return top 10
        sorted_reasons = sorted(reasons.items(), key=lambda x: x[1], reverse=True)[:10]

        return [{"reason": reason, "count": count} for reason, count in sorted_reasons]

    def _calculate_fcr(self, calls_query) -> float:
        """Calculate first call resolution rate.

        Args:
            calls_query: Filtered call queryset

        Returns:
            FCR percentage

        """
        # Simplified: calls not followed by another call from same number within 7 days
        completed_calls = calls_query.filter(status=Call.Status.COMPLETED)
        fcr_count = 0

        for call in completed_calls[:100]:  # Sample for performance
            follow_up = Call.objects.filter(
                from_number=call.from_number,
                created_at__gt=call.created_at,
                created_at__lt=call.created_at + timedelta(days=7),
            ).exists()

            if not follow_up:
                fcr_count += 1

        total_sampled = min(100, completed_calls.count())
        return (fcr_count / total_sampled * 100) if total_sampled > 0 else 0

    def _calculate_agent_status_time(self, agent: Agent, start_date: datetime, end_date: datetime) -> Dict[str, int]:
        """Calculate time spent in each status.

        Args:
            agent: Agent object
            start_date: Start of period
            end_date: End of period

        Returns:
            Dict of status durations in seconds

        """
        # Get status changes from activity log
        from ..models import AgentActivity

        activities = AgentActivity.objects.filter(
            agent=agent,
            timestamp__gte=start_date,
            timestamp__lte=end_date,
        ).order_by("timestamp")

        status_time = {
            "available": 0,
            "busy": 0,
            "on_break": 0,
            "offline": 0,
        }

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

    def _calculate_occupancy_rate(self, agent: Agent, start_date: datetime, end_date: datetime) -> float:
        """Calculate agent occupancy rate.

        Args:
            agent: Agent object
            start_date: Start of period
            end_date: End of period

        Returns:
            Occupancy rate percentage

        """
        status_time = self._calculate_agent_status_time(agent, start_date, end_date)

        productive_time = status_time["busy"]
        available_time = status_time["available"] + status_time["busy"]

        return (productive_time / available_time * 100) if available_time > 0 else 0


# Create service instance
analytics_service = AnalyticsService()

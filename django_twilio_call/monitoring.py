"""Task monitoring and metrics collection system."""

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional

from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.utils import timezone


@dataclass
class TaskMetrics:
    """Task performance metrics."""

    task_name: str
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    average_duration: float = 0.0
    min_duration: float = float("inf")
    max_duration: float = 0.0
    last_execution: float = 0.0
    active_tasks: int = 0


class TaskMonitor:
    """Comprehensive task monitoring and metrics collection."""

    def __init__(self):
        """Initialize task monitor."""
        self.task_metrics: Dict[str, TaskMetrics] = defaultdict(TaskMetrics)
        self.execution_history = deque(maxlen=10000)  # Keep last 10k executions
        self.active_tasks = {}
        self.queue_metrics = defaultdict(lambda: {"length": 0, "consumers": 0})

    def record_task_start(self, task_id: str, task_name: str, queue_name: str):
        """Record task execution start.

        Args:
            task_id: Celery task ID
            task_name: Task name
            queue_name: Queue name

        """
        start_time = time.time()

        self.active_tasks[task_id] = {"task_name": task_name, "queue_name": queue_name, "start_time": start_time}

        # Update metrics
        metrics = self.task_metrics[task_name]
        metrics.task_name = task_name
        metrics.active_tasks += 1

        # Update database record
        try:
            from .models import TaskExecution

            TaskExecution.objects.update_or_create(
                task_id=task_id,
                defaults={
                    "task_name": task_name,
                    "status": TaskExecution.Status.STARTED,
                    "queue_name": queue_name,
                    "started_at": timezone.now(),
                },
            )
        except Exception:
            # Don't fail if database update fails
            pass

    def record_task_completion(self, task_id: str, success: bool = True, result=None):
        """Record task completion.

        Args:
            task_id: Celery task ID
            success: Whether task completed successfully
            result: Task result or error information

        """
        if task_id not in self.active_tasks:
            return

        task_info = self.active_tasks.pop(task_id)
        completion_time = time.time()
        duration = completion_time - task_info["start_time"]

        # Update metrics
        metrics = self.task_metrics[task_info["task_name"]]
        metrics.total_executions += 1
        metrics.active_tasks = max(0, metrics.active_tasks - 1)
        metrics.last_execution = completion_time

        if success:
            metrics.successful_executions += 1
        else:
            metrics.failed_executions += 1

        # Update duration statistics
        if metrics.total_executions == 1:
            metrics.average_duration = duration
            metrics.min_duration = duration
            metrics.max_duration = duration
        else:
            # Running average
            total_duration = metrics.average_duration * (metrics.total_executions - 1) + duration
            metrics.average_duration = total_duration / metrics.total_executions
            metrics.min_duration = min(metrics.min_duration, duration)
            metrics.max_duration = max(metrics.max_duration, duration)

        # Store in execution history
        self.execution_history.append(
            {
                "task_id": task_id,
                "task_name": task_info["task_name"],
                "queue_name": task_info["queue_name"],
                "start_time": task_info["start_time"],
                "completion_time": completion_time,
                "duration": duration,
                "success": success,
                "result": result,
            }
        )

        # Update database record
        try:
            from .models import TaskExecution

            TaskExecution.objects.filter(task_id=task_id).update(
                status=TaskExecution.Status.SUCCESS if success else TaskExecution.Status.FAILURE,
                completed_at=timezone.now(),
                duration_seconds=duration,
                result=result,
            )
        except Exception:
            # Don't fail if database update fails
            pass

    def get_task_statistics(self, task_name: Optional[str] = None) -> Dict:
        """Get comprehensive task statistics.

        Args:
            task_name: Specific task name or None for all tasks

        Returns:
            Task statistics dictionary

        """
        if task_name:
            if task_name in self.task_metrics:
                return self._format_task_metrics(self.task_metrics[task_name])
            return None

        # Return all metrics
        return {name: self._format_task_metrics(metrics) for name, metrics in self.task_metrics.items()}

    def get_system_health(self) -> Dict:
        """Get overall system health metrics.

        Returns:
            System health statistics

        """
        total_active = sum(metrics.active_tasks for metrics in self.task_metrics.values())
        total_executions = sum(metrics.total_executions for metrics in self.task_metrics.values())
        total_failures = sum(metrics.failed_executions for metrics in self.task_metrics.values())

        overall_success_rate = (
            ((total_executions - total_failures) / total_executions * 100) if total_executions > 0 else 100
        )

        # Calculate recent performance (last hour)
        recent_time = time.time() - 3600  # 1 hour ago
        recent_executions = [exec for exec in self.execution_history if exec["completion_time"] > recent_time]

        recent_success_rate = (
            (sum(1 for exec in recent_executions if exec["success"]) / len(recent_executions) * 100)
            if recent_executions
            else 100
        )

        return {
            "total_active_tasks": total_active,
            "total_executions": total_executions,
            "overall_success_rate": round(overall_success_rate, 2),
            "recent_success_rate": round(recent_success_rate, 2),
            "recent_executions": len(recent_executions),
            "average_execution_time": (
                sum(exec["duration"] for exec in recent_executions) / len(recent_executions) if recent_executions else 0
            ),
            "timestamp": timezone.now().isoformat(),
        }

    def get_slow_tasks(self, threshold_seconds: int = 30) -> List[Dict]:
        """Identify slow-running tasks.

        Args:
            threshold_seconds: Threshold for considering a task slow

        Returns:
            List of slow task information

        """
        current_time = time.time()
        slow_tasks = []

        for task_id, task_info in self.active_tasks.items():
            duration = current_time - task_info["start_time"]
            if duration > threshold_seconds:
                slow_tasks.append(
                    {
                        "task_id": task_id,
                        "task_name": task_info["task_name"],
                        "queue_name": task_info["queue_name"],
                        "duration": duration,
                    }
                )

        return sorted(slow_tasks, key=lambda x: x["duration"], reverse=True)

    def get_failure_analysis(self, hours: int = 24) -> Dict:
        """Analyze recent failures.

        Args:
            hours: Number of hours to analyze

        Returns:
            Failure analysis data

        """
        cutoff_time = time.time() - (hours * 3600)
        recent_failures = [
            exec for exec in self.execution_history if not exec["success"] and exec["completion_time"] > cutoff_time
        ]

        failure_by_task = defaultdict(int)
        failure_by_queue = defaultdict(int)

        for failure in recent_failures:
            failure_by_task[failure["task_name"]] += 1
            failure_by_queue[failure["queue_name"]] += 1

        return {
            "total_failures": len(recent_failures),
            "failure_by_task": dict(failure_by_task),
            "failure_by_queue": dict(failure_by_queue),
            "failure_rate": len(recent_failures) / hours if hours > 0 else 0,
            "period_hours": hours,
        }

    def get_queue_metrics(self) -> Dict:
        """Get queue performance metrics.

        Returns:
            Queue metrics data

        """
        try:
            from .models import TaskExecution

            # Get active tasks by queue
            active_by_queue = (
                TaskExecution.objects.filter(status__in=[TaskExecution.Status.PENDING, TaskExecution.Status.STARTED])
                .values("queue_name")
                .annotate(count=Count("id"))
            )

            # Get recent performance by queue (last 24 hours)
            yesterday = timezone.now() - timedelta(hours=24)
            queue_performance = (
                TaskExecution.objects.filter(created_at__gte=yesterday)
                .values("queue_name")
                .annotate(
                    total_tasks=Count("id"),
                    success_rate=Count("id", filter=Q(status=TaskExecution.Status.SUCCESS)) * 100.0 / Count("id"),
                    avg_duration=Avg("duration_seconds", filter=Q(status=TaskExecution.Status.SUCCESS)),
                )
            )

            queue_metrics = {}

            # Combine active and performance data
            for queue_data in queue_performance:
                queue_name = queue_data["queue_name"]
                queue_metrics[queue_name] = {
                    "name": queue_name,
                    "active_tasks": 0,
                    "total_tasks_24h": queue_data["total_tasks"],
                    "success_rate_24h": round(queue_data["success_rate"] or 0, 2),
                    "avg_duration_24h": round(queue_data["avg_duration"] or 0, 2),
                }

            # Add active task counts
            for queue_data in active_by_queue:
                queue_name = queue_data["queue_name"]
                if queue_name in queue_metrics:
                    queue_metrics[queue_name]["active_tasks"] = queue_data["count"]
                else:
                    queue_metrics[queue_name] = {
                        "name": queue_name,
                        "active_tasks": queue_data["count"],
                        "total_tasks_24h": 0,
                        "success_rate_24h": 0,
                        "avg_duration_24h": 0,
                    }

            return queue_metrics

        except Exception:
            # Return cached metrics if database query fails
            return self.queue_metrics

    def get_task_performance_trends(self, task_name: str, days: int = 7) -> Dict:
        """Get performance trends for a specific task.

        Args:
            task_name: Task name to analyze
            days: Number of days to analyze

        Returns:
            Performance trend data

        """
        try:
            from .models import TaskExecution

            since_date = timezone.now() - timedelta(days=days)

            # Get daily statistics
            daily_stats = []
            for day in range(days):
                day_start = since_date + timedelta(days=day)
                day_end = day_start + timedelta(days=1)

                day_data = TaskExecution.objects.filter(
                    task_name=task_name,
                    created_at__gte=day_start,
                    created_at__lt=day_end,
                ).aggregate(
                    total_executions=Count("id"),
                    successful_executions=Count("id", filter=Q(status=TaskExecution.Status.SUCCESS)),
                    avg_duration=Avg("duration_seconds", filter=Q(status=TaskExecution.Status.SUCCESS)),
                    max_duration=Count("duration_seconds", filter=Q(status=TaskExecution.Status.SUCCESS)),
                )

                daily_stats.append(
                    {
                        "date": day_start.date().isoformat(),
                        "total_executions": day_data["total_executions"] or 0,
                        "successful_executions": day_data["successful_executions"] or 0,
                        "success_rate": (
                            (day_data["successful_executions"] / day_data["total_executions"] * 100)
                            if day_data["total_executions"] > 0
                            else 0
                        ),
                        "avg_duration": round(day_data["avg_duration"] or 0, 2),
                        "max_duration": day_data["max_duration"] or 0,
                    }
                )

            return {
                "task_name": task_name,
                "period_days": days,
                "daily_stats": daily_stats,
            }

        except Exception:
            return {"task_name": task_name, "error": "Unable to fetch trend data"}

    def _format_task_metrics(self, metrics: TaskMetrics) -> Dict:
        """Format task metrics for output.

        Args:
            metrics: TaskMetrics object

        Returns:
            Formatted metrics dictionary

        """
        success_rate = (
            (metrics.successful_executions / metrics.total_executions * 100) if metrics.total_executions > 0 else 0
        )

        return {
            "task_name": metrics.task_name,
            "total_executions": metrics.total_executions,
            "successful_executions": metrics.successful_executions,
            "failed_executions": metrics.failed_executions,
            "success_rate": round(success_rate, 2),
            "average_duration": round(metrics.average_duration, 2),
            "min_duration": metrics.min_duration if metrics.min_duration != float("inf") else 0,
            "max_duration": metrics.max_duration,
            "active_tasks": metrics.active_tasks,
            "last_execution": metrics.last_execution,
        }


# Global task monitor instance
task_monitor = TaskMonitor()


def get_system_status() -> Dict:
    """Get comprehensive system status.

    Returns:
        Complete system status including health, queues, and performance

    """
    cache_key = "system_status"
    cached_status = cache.get(cache_key)

    if cached_status:
        return cached_status

    try:
        status = {
            "health": task_monitor.get_system_health(),
            "queues": task_monitor.get_queue_metrics(),
            "slow_tasks": task_monitor.get_slow_tasks(),
            "failures": task_monitor.get_failure_analysis(),
            "top_tasks": _get_top_tasks_by_volume(),
        }

        # Cache for 30 seconds
        cache.set(cache_key, status, 30)
        return status

    except Exception as e:
        return {
            "error": f"Unable to fetch system status: {e!s}",
            "timestamp": timezone.now().isoformat(),
        }


def _get_top_tasks_by_volume(limit: int = 10) -> List[Dict]:
    """Get top tasks by execution volume.

    Args:
        limit: Number of top tasks to return

    Returns:
        List of top task statistics

    """
    try:
        from .models import TaskExecution

        yesterday = timezone.now() - timedelta(hours=24)

        top_tasks = (
            TaskExecution.objects.filter(created_at__gte=yesterday)
            .values("task_name")
            .annotate(
                total_executions=Count("id"),
                success_rate=Count("id", filter=Q(status=TaskExecution.Status.SUCCESS)) * 100.0 / Count("id"),
                avg_duration=Avg("duration_seconds", filter=Q(status=TaskExecution.Status.SUCCESS)),
            )
            .order_by("-total_executions")[:limit]
        )

        return [
            {
                "task_name": task["task_name"],
                "total_executions": task["total_executions"],
                "success_rate": round(task["success_rate"] or 0, 2),
                "avg_duration": round(task["avg_duration"] or 0, 2),
            }
            for task in top_tasks
        ]

    except Exception:
        return []

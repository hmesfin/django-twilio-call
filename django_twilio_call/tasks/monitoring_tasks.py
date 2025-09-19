"""Monitoring and health check tasks for django-twilio-call.

Handles system health monitoring, alerting, and performance tracking.
"""

import logging
from datetime import timedelta
from typing import Any, Dict

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="system_health_check")
def system_health_check():
    """Perform comprehensive system health check.

    Checks database connectivity, Twilio API, queue status, and other critical components.
    """
    health_results = {"timestamp": timezone.now().isoformat(), "overall_status": "healthy", "checks": {}}

    # Database connectivity check
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health_results["checks"]["database"] = {"status": "healthy", "response_time_ms": 0}
    except Exception as e:
        health_results["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
        health_results["overall_status"] = "unhealthy"

    # Twilio API connectivity check
    try:
        from ..services import twilio_service

        # Make a simple API call to check connectivity
        account = twilio_service.get_account_info()
        health_results["checks"]["twilio_api"] = {
            "status": "healthy",
            "account_sid": account.get("sid", "unknown")[:8] + "...",
        }
    except Exception as e:
        health_results["checks"]["twilio_api"] = {"status": "unhealthy", "error": str(e)}
        health_results["overall_status"] = "degraded"

    # Cache connectivity check
    try:
        cache_key = "health_check_test"
        cache.set(cache_key, "test_value", 60)
        retrieved_value = cache.get(cache_key)
        if retrieved_value == "test_value":
            health_results["checks"]["cache"] = {"status": "healthy"}
        else:
            health_results["checks"]["cache"] = {"status": "degraded", "error": "Cache value mismatch"}
            health_results["overall_status"] = "degraded"
        cache.delete(cache_key)
    except Exception as e:
        health_results["checks"]["cache"] = {"status": "unhealthy", "error": str(e)}
        health_results["overall_status"] = "degraded"

    # Active calls check
    try:
        from ..models import Call

        active_calls_count = Call.objects.filter(
            status__in=[Call.Status.QUEUED, Call.Status.RINGING, Call.Status.IN_PROGRESS]
        ).count()
        health_results["checks"]["active_calls"] = {"status": "healthy", "count": active_calls_count}
    except Exception as e:
        health_results["checks"]["active_calls"] = {"status": "unhealthy", "error": str(e)}
        health_results["overall_status"] = "unhealthy"

    # Queue status check
    try:
        from ..models import Agent, Queue

        active_queues = Queue.objects.filter(is_active=True).count()
        available_agents = Agent.objects.filter(status=Agent.Status.AVAILABLE, is_active=True).count()

        health_results["checks"]["queues"] = {
            "status": "healthy",
            "active_queues": active_queues,
            "available_agents": available_agents,
        }

        if available_agents == 0 and active_queues > 0:
            health_results["checks"]["queues"]["status"] = "warning"
            health_results["checks"]["queues"]["warning"] = "No available agents for active queues"
            if health_results["overall_status"] == "healthy":
                health_results["overall_status"] = "degraded"

    except Exception as e:
        health_results["checks"]["queues"] = {"status": "unhealthy", "error": str(e)}
        health_results["overall_status"] = "unhealthy"

    # Store health check results
    cache.set("system_health_status", health_results, timeout=300)  # Cache for 5 minutes

    # Send alert if unhealthy
    if health_results["overall_status"] == "unhealthy":
        send_critical_alert.delay(
            "System Health Check Failed",
            f"System health check failed with status: {health_results['overall_status']}",
            health_results,
        )

    return health_results


@shared_task(name="send_critical_alert")
def send_critical_alert(subject: str, message: str, context: Dict[str, Any] = None):
    """Send critical alert notification.

    Args:
        subject: Alert subject
        message: Alert message
        context: Additional context data

    Returns:
        Dictionary with send results

    """
    try:
        alert_recipients = getattr(settings, "ALERT_EMAIL_RECIPIENTS", [])
        if not alert_recipients:
            logger.warning("No alert email recipients configured")
            return {"success": False, "error": "No alert recipients configured"}

        # Prepare email content
        context = context or {}
        context.update(
            {
                "subject": subject,
                "message": message,
                "timestamp": timezone.now(),
                "environment": getattr(settings, "ENVIRONMENT", "unknown"),
            }
        )

        # Render email template
        try:
            email_body = render_to_string("django_twilio_call/alert_email.html", context)
        except Exception:
            # Fallback to plain text if template not found
            email_body = f"""
            CRITICAL ALERT: {subject}

            {message}

            Environment: {context.get("environment", "unknown")}
            Time: {context.get("timestamp", "unknown")}

            Context: {context}
            """

        # Send email
        send_mail(
            subject=f"[ALERT] {subject}",
            message=email_body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
            recipient_list=alert_recipients,
            fail_silently=False,
        )

        return {"success": True, "recipients_count": len(alert_recipients), "subject": subject}

    except Exception as e:
        logger.error(f"Failed to send critical alert: {e}")
        return {"success": False, "error": str(e), "subject": subject}


@shared_task(name="update_all_agent_metrics")
def update_all_agent_metrics():
    """Update metrics for all active agents.

    This task calculates and caches performance metrics for all agents.
    """
    try:
        from ..models import Agent
        from ..tasks.reporting_tasks import calculate_agent_metrics

        active_agents = Agent.objects.filter(is_active=True)
        total_agents = active_agents.count()
        processed_count = 0
        failed_count = 0

        for agent in active_agents:
            try:
                # Calculate metrics for last 30 days
                calculate_agent_metrics.delay(agent.id)
                processed_count += 1
            except Exception as e:
                logger.error(f"Failed to queue metrics calculation for agent {agent.id}: {e}")
                failed_count += 1

        return {
            "success": True,
            "total_agents": total_agents,
            "processed_count": processed_count,
            "failed_count": failed_count,
        }

    except Exception as e:
        logger.error(f"Error updating agent metrics: {e}")
        return {"success": False, "error": str(e)}


@shared_task(name="optimize_queue_routing")
def optimize_queue_routing():
    """Optimize queue routing performance.

    Analyzes queue performance and suggests optimizations.
    """
    try:
        from django.db.models import Avg, Count

        from ..models import Agent, Call, Queue

        optimization_results = {"timestamp": timezone.now().isoformat(), "queues_analyzed": 0, "recommendations": []}

        # Analyze each active queue
        active_queues = Queue.objects.filter(is_active=True)

        for queue in active_queues:
            optimization_results["queues_analyzed"] += 1

            # Calculate queue metrics
            recent_calls = Call.objects.filter(queue=queue, created_at__gte=timezone.now() - timedelta(days=7))

            queue_metrics = recent_calls.aggregate(
                avg_queue_time=Avg("queue_time"), total_calls=Count("id"), avg_duration=Avg("duration")
            )

            # Generate recommendations based on metrics
            if queue_metrics["avg_queue_time"] and queue_metrics["avg_queue_time"] > 300:  # 5 minutes
                optimization_results["recommendations"].append(
                    {
                        "queue_name": queue.name,
                        "type": "high_wait_time",
                        "message": f"Queue {queue.name} has high average wait time: {queue_metrics['avg_queue_time']:.1f} seconds",
                        "suggestion": "Consider adding more agents or adjusting queue priority",
                    }
                )

            # Check agent availability for the queue
            available_agents = queue.agents.filter(status=Agent.Status.AVAILABLE, is_active=True).count()

            if available_agents == 0 and queue_metrics["total_calls"] > 0:
                optimization_results["recommendations"].append(
                    {
                        "queue_name": queue.name,
                        "type": "no_available_agents",
                        "message": f"Queue {queue.name} has no available agents but receives calls",
                        "suggestion": "Assign more agents to this queue or check agent schedules",
                    }
                )

        # Cache optimization results
        cache.set("queue_optimization_results", optimization_results, timeout=3600)

        return optimization_results

    except Exception as e:
        logger.error(f"Error optimizing queue routing: {e}")
        return {"success": False, "error": str(e)}


@shared_task(bind=True, name="monitor_system_performance")
def monitor_system_performance(self):
    """Monitor system performance metrics.

    Tracks CPU, memory, database performance, and other system metrics.
    """
    try:
        import psutil
        from django.db import connection

        performance_metrics = {"timestamp": timezone.now().isoformat(), "system": {}, "database": {}, "application": {}}

        # System metrics
        try:
            performance_metrics["system"] = {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_usage_percent": psutil.disk_usage("/").percent,
            }
        except Exception as e:
            logger.warning(f"Could not collect system metrics: {e}")

        # Database metrics
        try:
            with connection.cursor() as cursor:
                start_time = timezone.now()
                cursor.execute("SELECT COUNT(*) FROM django_twilio_call_call")
                db_response_time = (timezone.now() - start_time).total_seconds() * 1000

                performance_metrics["database"] = {
                    "response_time_ms": db_response_time,
                    "active_connections": len(connection.queries),
                }
        except Exception as e:
            logger.warning(f"Could not collect database metrics: {e}")

        # Application metrics
        try:
            from ..models import Agent, Call

            performance_metrics["application"] = {
                "active_calls": Call.objects.filter(
                    status__in=[Call.Status.QUEUED, Call.Status.RINGING, Call.Status.IN_PROGRESS]
                ).count(),
                "available_agents": Agent.objects.filter(status=Agent.Status.AVAILABLE, is_active=True).count(),
                "total_agents": Agent.objects.filter(is_active=True).count(),
            }
        except Exception as e:
            logger.warning(f"Could not collect application metrics: {e}")

        # Cache performance metrics
        cache.set("system_performance_metrics", performance_metrics, timeout=300)

        # Check for performance issues and alert if necessary
        if performance_metrics["system"].get("cpu_percent", 0) > 90:
            send_critical_alert.delay(
                "High CPU Usage",
                f"CPU usage is at {performance_metrics['system']['cpu_percent']:.1f}%",
                performance_metrics,
            )

        if performance_metrics["system"].get("memory_percent", 0) > 90:
            send_critical_alert.delay(
                "High Memory Usage",
                f"Memory usage is at {performance_metrics['system']['memory_percent']:.1f}%",
                performance_metrics,
            )

        return performance_metrics

    except Exception as e:
        logger.error(f"Error monitoring system performance: {e}")
        return {"success": False, "error": str(e)}

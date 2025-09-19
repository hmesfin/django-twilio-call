"""Health check system for monitoring service dependencies."""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, Optional

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health check status enumeration."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    name: str
    status: HealthStatus
    message: str
    duration_ms: float
    timestamp: datetime
    details: Dict[str, Any]


class HealthCheck(ABC):
    """Abstract base class for health checks."""

    def __init__(self, name: str, timeout: float = 5.0):
        self.name = name
        self.timeout = timeout

    @abstractmethod
    def check(self) -> HealthCheckResult:
        """Perform the health check."""
        pass

    def _execute_with_timeout(self, check_func: Callable) -> HealthCheckResult:
        """Execute check function with timeout."""
        start_time = time.time()

        try:
            result = check_func()
            duration_ms = (time.time() - start_time) * 1000

            if duration_ms > self.timeout * 1000:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.DEGRADED,
                    message=f"Check completed but took {duration_ms:.2f}ms (timeout: {self.timeout * 1000}ms)",
                    duration_ms=duration_ms,
                    timestamp=timezone.now(),
                    details=result if isinstance(result, dict) else {},
                )

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message="OK",
                duration_ms=duration_ms,
                timestamp=timezone.now(),
                details=result if isinstance(result, dict) else {},
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                duration_ms=duration_ms,
                timestamp=timezone.now(),
                details={"error": str(e)},
            )


class DatabaseHealthCheck(HealthCheck):
    """Health check for database connectivity."""

    def __init__(self, timeout: float = 5.0):
        super().__init__("database", timeout)

    def check(self) -> HealthCheckResult:
        """Check database connectivity and performance."""
        return self._execute_with_timeout(self._check_database)

    def _check_database(self) -> Dict[str, Any]:
        """Perform database health check."""
        # Test basic connectivity
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        # Get connection pool info
        db_settings = connection.settings_dict

        # Check for slow queries if debug is enabled
        slow_queries = 0
        if settings.DEBUG:
            slow_queries = len([query for query in connection.queries if float(query.get("time", 0)) > 0.1])

        return {
            "database": db_settings.get("NAME", "unknown"),
            "engine": db_settings.get("ENGINE", "unknown"),
            "connection_count": len(connection.queries) if settings.DEBUG else None,
            "slow_queries": slow_queries,
        }


class RedisHealthCheck(HealthCheck):
    """Health check for Redis connectivity."""

    def __init__(self, timeout: float = 3.0):
        super().__init__("redis", timeout)

    def check(self) -> HealthCheckResult:
        """Check Redis connectivity and performance."""
        return self._execute_with_timeout(self._check_redis)

    def _check_redis(self) -> Dict[str, Any]:
        """Perform Redis health check."""
        # Test Django cache
        test_key = "health_check_test"
        test_value = str(time.time())

        cache.set(test_key, test_value, 30)
        retrieved_value = cache.get(test_key)

        if retrieved_value != test_value:
            raise Exception("Redis cache test failed")

        # Get Redis info if using django-redis
        redis_info = {}
        try:
            if hasattr(cache, "_cache") and hasattr(cache._cache, "_client"):
                redis_client = cache._cache._client.get_client()
                if hasattr(redis_client, "info"):
                    info = redis_client.info()
                    redis_info = {
                        "used_memory_human": info.get("used_memory_human", "unknown"),
                        "connected_clients": info.get("connected_clients", 0),
                        "uptime_in_seconds": info.get("uptime_in_seconds", 0),
                        "redis_version": info.get("redis_version", "unknown"),
                    }
        except Exception as e:
            logger.warning(f"Could not get Redis info: {e}")

        return {
            "cache_test": "passed",
            "redis_info": redis_info,
        }


class CeleryHealthCheck(HealthCheck):
    """Health check for Celery workers and queues."""

    def __init__(self, timeout: float = 5.0):
        super().__init__("celery", timeout)

    def check(self) -> HealthCheckResult:
        """Check Celery workers and queue health."""
        return self._execute_with_timeout(self._check_celery)

    def _check_celery(self) -> Dict[str, Any]:
        """Perform Celery health check."""
        try:
            from celery import current_app

            # Get active workers
            inspect = current_app.control.inspect()
            active_workers = inspect.active()

            if not active_workers:
                raise Exception("No active Celery workers found")

            # Get queue stats
            stats = inspect.stats()

            # Check for failed tasks
            failed_tasks = 0
            try:
                from ...models import TaskExecution

                yesterday = timezone.now() - timedelta(hours=24)
                failed_tasks = TaskExecution.objects.filter(
                    status=TaskExecution.Status.FAILURE, created_at__gte=yesterday
                ).count()
            except Exception:
                pass

            return {
                "active_workers": len(active_workers) if active_workers else 0,
                "worker_names": list(active_workers.keys()) if active_workers else [],
                "failed_tasks_24h": failed_tasks,
                "stats": stats,
            }

        except ImportError:
            raise Exception("Celery not properly configured")


class TwilioHealthCheck(HealthCheck):
    """Health check for Twilio API connectivity."""

    def __init__(self, timeout: float = 10.0):
        super().__init__("twilio", timeout)

    def check(self) -> HealthCheckResult:
        """Check Twilio API connectivity."""
        return self._execute_with_timeout(self._check_twilio)

    def _check_twilio(self) -> Dict[str, Any]:
        """Perform Twilio API health check."""
        try:
            from ...services.twilio_service import twilio_service

            # Test API connectivity by fetching account info
            account_info = twilio_service.get_account_info()

            # Check for recent API errors
            api_errors = 0
            try:
                from ...models import WebhookLog

                yesterday = timezone.now() - timedelta(hours=24)
                api_errors = WebhookLog.objects.filter(
                    status=WebhookLog.Status.FAILED, created_at__gte=yesterday
                ).count()
            except Exception:
                pass

            return {
                "account_sid": account_info.get("sid", "unknown")[:8] + "...",
                "account_status": account_info.get("status", "unknown"),
                "api_errors_24h": api_errors,
            }

        except Exception as e:
            raise Exception(f"Twilio API check failed: {e}")


class CallCenterHealthCheck(HealthCheck):
    """Health check for call center specific functionality."""

    def __init__(self, timeout: float = 5.0):
        super().__init__("call_center", timeout)

    def check(self) -> HealthCheckResult:
        """Check call center operational health."""
        return self._execute_with_timeout(self._check_call_center)

    def _check_call_center(self) -> Dict[str, Any]:
        """Perform call center health check."""
        try:
            from ...models import Agent, Call, Queue

            # Check active agents
            active_agents = Agent.objects.filter(is_active=True, status=Agent.Status.AVAILABLE).count()

            # Check active queues
            active_queues = Queue.objects.filter(is_active=True).count()

            # Check calls in progress
            active_calls = Call.objects.filter(
                status__in=[Call.Status.QUEUED, Call.Status.RINGING, Call.Status.IN_PROGRESS]
            ).count()

            # Check for stuck calls (in queue for > 10 minutes)
            ten_minutes_ago = timezone.now() - timedelta(minutes=10)
            stuck_calls = Call.objects.filter(status=Call.Status.QUEUED, created_at__lt=ten_minutes_ago).count()

            # Warn if no agents available
            status = HealthStatus.HEALTHY
            message = "OK"

            if active_agents == 0:
                status = HealthStatus.DEGRADED
                message = "No agents available"
            elif stuck_calls > 0:
                status = HealthStatus.DEGRADED
                message = f"{stuck_calls} calls stuck in queue"

            result = HealthCheckResult(
                name=self.name,
                status=status,
                message=message,
                duration_ms=0,  # Will be set by caller
                timestamp=timezone.now(),
                details={
                    "active_agents": active_agents,
                    "active_queues": active_queues,
                    "active_calls": active_calls,
                    "stuck_calls": stuck_calls,
                },
            )

            return result.details

        except Exception as e:
            raise Exception(f"Call center check failed: {e}")


class HealthCheckRegistry:
    """Registry for managing health checks."""

    def __init__(self):
        self.checks: Dict[str, HealthCheck] = {}
        self._register_default_checks()

    def _register_default_checks(self) -> None:
        """Register default health checks."""
        self.register(DatabaseHealthCheck())
        self.register(RedisHealthCheck())
        self.register(CeleryHealthCheck())
        self.register(TwilioHealthCheck())
        self.register(CallCenterHealthCheck())

    def register(self, health_check: HealthCheck) -> None:
        """Register a health check."""
        self.checks[health_check.name] = health_check
        logger.debug(f"Registered health check: {health_check.name}")

    def unregister(self, name: str) -> None:
        """Unregister a health check."""
        if name in self.checks:
            del self.checks[name]
            logger.debug(f"Unregistered health check: {name}")

    def run_check(self, name: str) -> Optional[HealthCheckResult]:
        """Run a specific health check."""
        if name not in self.checks:
            return None

        return self.checks[name].check()

    def run_all_checks(self) -> Dict[str, HealthCheckResult]:
        """Run all registered health checks."""
        results = {}

        for name, check in self.checks.items():
            try:
                results[name] = check.check()
            except Exception as e:
                logger.error(f"Health check {name} failed with exception: {e}")
                results[name] = HealthCheckResult(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {e}",
                    duration_ms=0,
                    timestamp=timezone.now(),
                    details={"error": str(e)},
                )

        return results

    def get_overall_status(self, results: Optional[Dict[str, HealthCheckResult]] = None) -> HealthStatus:
        """Get overall system health status."""
        if results is None:
            results = self.run_all_checks()

        if not results:
            return HealthStatus.UNHEALTHY

        # If any check is unhealthy, system is unhealthy
        if any(result.status == HealthStatus.UNHEALTHY for result in results.values()):
            return HealthStatus.UNHEALTHY

        # If any check is degraded, system is degraded
        if any(result.status == HealthStatus.DEGRADED for result in results.values()):
            return HealthStatus.DEGRADED

        return HealthStatus.HEALTHY


# Global health check registry
health_check_registry = HealthCheckRegistry()

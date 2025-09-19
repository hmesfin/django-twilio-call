"""
Production health check endpoints for Django-Twilio-Call.
Provides comprehensive health monitoring for production deployment.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any

from django.conf import settings
from django.core.cache import cache
from django.db import connection, connections
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

import redis
from celery import current_app as celery_app
from twilio.rest import Client as TwilioClient

logger = logging.getLogger(__name__)


class HealthCheckStatus:
    """Health check status constants."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"


class HealthChecker:
    """Comprehensive health checker for all application components."""

    def __init__(self):
        self.checks = {
            'database': self._check_database,
            'cache': self._check_cache,
            'celery': self._check_celery,
            'twilio': self._check_twilio,
            'storage': self._check_storage,
            'external_deps': self._check_external_dependencies,
        }

    def run_all_checks(self) -> Dict[str, Any]:
        """Run all health checks and return comprehensive status."""
        start_time = time.time()
        results = {}
        overall_status = HealthCheckStatus.HEALTHY

        for check_name, check_func in self.checks.items():
            try:
                check_start = time.time()
                result = check_func()
                check_duration = time.time() - check_start

                results[check_name] = {
                    **result,
                    'duration_ms': round(check_duration * 1000, 2)
                }

                # Determine overall status
                if result['status'] == HealthCheckStatus.UNHEALTHY:
                    overall_status = HealthCheckStatus.UNHEALTHY
                elif result['status'] == HealthCheckStatus.DEGRADED and overall_status == HealthCheckStatus.HEALTHY:
                    overall_status = HealthCheckStatus.DEGRADED

            except Exception as e:
                logger.exception(f"Health check failed for {check_name}")
                results[check_name] = {
                    'status': HealthCheckStatus.UNHEALTHY,
                    'error': str(e),
                    'duration_ms': 0
                }
                overall_status = HealthCheckStatus.UNHEALTHY

        total_duration = time.time() - start_time

        return {
            'status': overall_status,
            'timestamp': timezone.now().isoformat(),
            'version': getattr(settings, 'VERSION', 'unknown'),
            'environment': getattr(settings, 'ENVIRONMENT', 'unknown'),
            'checks': results,
            'total_duration_ms': round(total_duration * 1000, 2),
        }

    def _check_database(self) -> Dict[str, Any]:
        """Check database connectivity and performance."""
        try:
            start_time = time.time()

            # Test connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

            # Check connection pool status
            db_status = {
                'status': HealthCheckStatus.HEALTHY,
                'connection_count': len(connections.all()),
            }

            # Test query performance
            query_time = time.time() - start_time
            if query_time > 1.0:  # Slow query threshold
                db_status['status'] = HealthCheckStatus.DEGRADED
                db_status['warning'] = f'Slow database response: {query_time:.2f}s'

            db_status['query_time_ms'] = round(query_time * 1000, 2)

            return db_status

        except Exception as e:
            return {
                'status': HealthCheckStatus.UNHEALTHY,
                'error': str(e)
            }

    def _check_cache(self) -> Dict[str, Any]:
        """Check Redis cache connectivity and performance."""
        try:
            start_time = time.time()

            # Test cache operations
            test_key = f"health_check_{int(time.time())}"
            test_value = "test_value"

            cache.set(test_key, test_value, timeout=10)
            retrieved_value = cache.get(test_key)
            cache.delete(test_key)

            if retrieved_value != test_value:
                return {
                    'status': HealthCheckStatus.UNHEALTHY,
                    'error': 'Cache value mismatch'
                }

            # Check Redis connection info
            redis_client = redis.from_url(settings.REDIS_URL)
            info = redis_client.info()

            cache_time = time.time() - start_time
            cache_status = {
                'status': HealthCheckStatus.HEALTHY,
                'redis_version': info.get('redis_version'),
                'connected_clients': info.get('connected_clients'),
                'used_memory_mb': round(info.get('used_memory', 0) / 1024 / 1024, 2),
                'response_time_ms': round(cache_time * 1000, 2)
            }

            # Check memory usage
            if info.get('used_memory_peak', 0) > info.get('maxmemory', float('inf')) * 0.9:
                cache_status['status'] = HealthCheckStatus.DEGRADED
                cache_status['warning'] = 'High memory usage'

            return cache_status

        except Exception as e:
            return {
                'status': HealthCheckStatus.UNHEALTHY,
                'error': str(e)
            }

    def _check_celery(self) -> Dict[str, Any]:
        """Check Celery worker and broker status."""
        try:
            # Check broker connectivity
            broker_status = celery_app.control.inspect().ping()

            if not broker_status:
                return {
                    'status': HealthCheckStatus.UNHEALTHY,
                    'error': 'No Celery workers responding'
                }

            # Get worker statistics
            stats = celery_app.control.inspect().stats()
            active_tasks = celery_app.control.inspect().active()

            worker_count = len(broker_status)
            total_active_tasks = sum(len(tasks) for tasks in active_tasks.values()) if active_tasks else 0

            celery_status = {
                'status': HealthCheckStatus.HEALTHY,
                'worker_count': worker_count,
                'active_tasks': total_active_tasks,
                'workers': list(broker_status.keys())
            }

            # Check for overloaded workers
            if total_active_tasks > worker_count * 10:  # Threshold: 10 tasks per worker
                celery_status['status'] = HealthCheckStatus.DEGRADED
                celery_status['warning'] = 'High task load'

            return celery_status

        except Exception as e:
            return {
                'status': HealthCheckStatus.UNHEALTHY,
                'error': str(e)
            }

    def _check_twilio(self) -> Dict[str, Any]:
        """Check Twilio API connectivity and account status."""
        try:
            client = TwilioClient(
                settings.TWILIO_ACCOUNT_SID,
                settings.TWILIO_AUTH_TOKEN
            )

            # Test API connectivity
            account = client.api.accounts(settings.TWILIO_ACCOUNT_SID).fetch()

            twilio_status = {
                'status': HealthCheckStatus.HEALTHY,
                'account_sid': account.sid,
                'account_status': account.status,
                'account_type': account.type,
            }

            # Check account status
            if account.status != 'active':
                twilio_status['status'] = HealthCheckStatus.DEGRADED
                twilio_status['warning'] = f'Account status: {account.status}'

            return twilio_status

        except Exception as e:
            return {
                'status': HealthCheckStatus.UNHEALTHY,
                'error': str(e)
            }

    def _check_storage(self) -> Dict[str, Any]:
        """Check storage backend availability."""
        try:
            from django.core.files.storage import default_storage

            # Test storage operations
            test_filename = f"health_check_{int(time.time())}.txt"
            test_content = b"health check test"

            start_time = time.time()

            # Write test file
            saved_path = default_storage.save(test_filename,
                                            ContentFile(test_content))

            # Read test file
            if default_storage.exists(saved_path):
                with default_storage.open(saved_path, 'rb') as f:
                    read_content = f.read()

                # Clean up
                default_storage.delete(saved_path)

                if read_content == test_content:
                    storage_time = time.time() - start_time
                    return {
                        'status': HealthCheckStatus.HEALTHY,
                        'backend': default_storage.__class__.__name__,
                        'response_time_ms': round(storage_time * 1000, 2)
                    }

            return {
                'status': HealthCheckStatus.UNHEALTHY,
                'error': 'Storage operation failed'
            }

        except Exception as e:
            return {
                'status': HealthCheckStatus.UNHEALTHY,
                'error': str(e)
            }

    def _check_external_dependencies(self) -> Dict[str, Any]:
        """Check external service dependencies."""
        dependencies = []
        overall_status = HealthCheckStatus.HEALTHY

        # Add checks for external services as needed
        # Example: API endpoints, third-party services, etc.

        return {
            'status': overall_status,
            'dependencies_checked': len(dependencies),
            'details': dependencies
        }


# Global health checker instance
health_checker = HealthChecker()


@never_cache
@csrf_exempt
@require_http_methods(["GET"])
def health_check(request):
    """
    Basic health check endpoint.
    Returns 200 if healthy, 503 if unhealthy.
    """
    try:
        # Quick database check
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        return JsonResponse({
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
        })
    except Exception as e:
        logger.exception("Health check failed")
        return JsonResponse({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': timezone.now().isoformat(),
        }, status=503)


@never_cache
@csrf_exempt
@require_http_methods(["GET"])
def health_check_detailed(request):
    """
    Detailed health check endpoint.
    Returns comprehensive status of all components.
    """
    try:
        results = health_checker.run_all_checks()

        status_code = 200
        if results['status'] == HealthCheckStatus.UNHEALTHY:
            status_code = 503
        elif results['status'] == HealthCheckStatus.DEGRADED:
            status_code = 200  # Still functional but degraded

        return JsonResponse(results, status=status_code)

    except Exception as e:
        logger.exception("Detailed health check failed")
        return JsonResponse({
            'status': HealthCheckStatus.UNHEALTHY,
            'error': str(e),
            'timestamp': timezone.now().isoformat(),
        }, status=503)


@never_cache
@csrf_exempt
@require_http_methods(["GET"])
def readiness_check(request):
    """
    Kubernetes readiness probe endpoint.
    Checks if the service is ready to receive traffic.
    """
    try:
        # Check critical services only
        critical_checks = ['database', 'cache']

        for check_name in critical_checks:
            check_func = health_checker.checks[check_name]
            result = check_func()

            if result['status'] == HealthCheckStatus.UNHEALTHY:
                return JsonResponse({
                    'status': 'not_ready',
                    'failed_check': check_name,
                    'timestamp': timezone.now().isoformat(),
                }, status=503)

        return JsonResponse({
            'status': 'ready',
            'timestamp': timezone.now().isoformat(),
        })

    except Exception as e:
        logger.exception("Readiness check failed")
        return JsonResponse({
            'status': 'not_ready',
            'error': str(e),
            'timestamp': timezone.now().isoformat(),
        }, status=503)


@never_cache
@csrf_exempt
@require_http_methods(["GET"])
def liveness_check(request):
    """
    Kubernetes liveness probe endpoint.
    Checks if the service is alive and should not be restarted.
    """
    try:
        # Basic application liveness check
        return JsonResponse({
            'status': 'alive',
            'timestamp': timezone.now().isoformat(),
            'uptime_seconds': int(time.time() - getattr(settings, 'START_TIME', time.time())),
        })

    except Exception as e:
        logger.exception("Liveness check failed")
        return JsonResponse({
            'status': 'dead',
            'error': str(e),
            'timestamp': timezone.now().isoformat(),
        }, status=503)


# Import required modules
try:
    from django.core.files.base import ContentFile
except ImportError:
    ContentFile = None
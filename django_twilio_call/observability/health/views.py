"""Health check API endpoints."""

import logging

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .checks import HealthStatus, health_check_registry

logger = logging.getLogger(__name__)


@method_decorator(never_cache, name="dispatch")
class HealthCheckView(View):
    """Simple health check endpoint for load balancers."""

    def get(self, request):
        """Basic health check endpoint."""
        try:
            # Run essential checks only
            essential_checks = ["database", "redis"]
            results = {}

            for check_name in essential_checks:
                if check_name in health_check_registry.checks:
                    results[check_name] = health_check_registry.run_check(check_name)

            # Determine overall status
            overall_status = health_check_registry.get_overall_status(results)

            # Return appropriate HTTP status
            if overall_status == HealthStatus.HEALTHY:
                http_status = 200
            elif overall_status == HealthStatus.DEGRADED:
                http_status = 200  # Still considered up for load balancer
            else:
                http_status = 503

            return JsonResponse(
                {
                    "status": overall_status.value,
                    "timestamp": results[list(results.keys())[0]].timestamp.isoformat() if results else None,
                },
                status=http_status,
            )

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return JsonResponse({"status": "unhealthy", "error": str(e)}, status=503)


@api_view(["GET"])
@permission_classes([AllowAny])
@never_cache
def detailed_health_check(request):
    """Detailed health check with all components."""
    try:
        # Run all health checks
        results = health_check_registry.run_all_checks()
        overall_status = health_check_registry.get_overall_status(results)

        # Format results for response
        formatted_results = {}
        for name, result in results.items():
            formatted_results[name] = {
                "status": result.status.value,
                "message": result.message,
                "duration_ms": round(result.duration_ms, 2),
                "timestamp": result.timestamp.isoformat(),
                "details": result.details,
            }

        response_data = {
            "overall_status": overall_status.value,
            "checks": formatted_results,
            "summary": {
                "total_checks": len(results),
                "healthy": sum(1 for r in results.values() if r.status == HealthStatus.HEALTHY),
                "degraded": sum(1 for r in results.values() if r.status == HealthStatus.DEGRADED),
                "unhealthy": sum(1 for r in results.values() if r.status == HealthStatus.UNHEALTHY),
            },
        }

        # Return appropriate HTTP status
        if overall_status == HealthStatus.HEALTHY:
            http_status = status.HTTP_200_OK
        elif overall_status == HealthStatus.DEGRADED:
            http_status = status.HTTP_200_OK
        else:
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE

        return Response(response_data, status=http_status)

    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        return Response({"overall_status": "unhealthy", "error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(["GET"])
@permission_classes([AllowAny])
@never_cache
def readiness_check(request):
    """Kubernetes readiness probe endpoint."""
    try:
        # Check if the application is ready to serve traffic
        essential_checks = ["database", "redis"]
        results = {}

        for check_name in essential_checks:
            if check_name in health_check_registry.checks:
                result = health_check_registry.run_check(check_name)
                if result.status == HealthStatus.UNHEALTHY:
                    return Response(
                        {"ready": False, "failed_check": check_name, "message": result.message},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )

        return Response({"ready": True, "message": "Application is ready to serve traffic"}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return Response({"ready": False, "error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(["GET"])
@permission_classes([AllowAny])
@never_cache
def liveness_check(request):
    """Kubernetes liveness probe endpoint."""
    try:
        # Basic liveness check - just verify the app is running
        return Response({"alive": True, "message": "Application is alive"}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Liveness check failed: {e}")
        return Response({"alive": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([AllowAny])
@never_cache
def metrics_health_check(request):
    """Health check specifically for metrics collection."""
    try:
        from ..metrics.collectors import call_center_metrics

        # Test metrics collection
        kpi_metrics = call_center_metrics.collect_real_time_metrics()

        return Response(
            {
                "metrics_healthy": True,
                "sample_metrics": {
                    "service_level": kpi_metrics.service_level,
                    "queue_depth": kpi_metrics.queue_depth,
                    "calls_handled": kpi_metrics.calls_handled,
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.error(f"Metrics health check failed: {e}")
        return Response({"metrics_healthy": False, "error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

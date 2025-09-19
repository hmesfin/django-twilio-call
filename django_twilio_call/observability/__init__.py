"""Observability package for django-twilio-call.

This package provides comprehensive monitoring, logging, and performance tracking
for call center operations, including:

- Application Performance Monitoring (APM)
- Business metrics collection (call center KPIs)
- Infrastructure monitoring
- Real-time dashboards
- Intelligent alerting
- Structured logging
"""

from .health.checks import health_check_registry
from .logging.formatters import StructuredJsonFormatter
from .metrics.collectors import CallCenterMetrics, TwilioMetrics
from .middleware.business import BusinessMetricsMiddleware
from .middleware.performance import PerformanceMonitoringMiddleware

__version__ = "1.0.0"
__all__ = [
    "BusinessMetricsMiddleware",
    "CallCenterMetrics",
    "PerformanceMonitoringMiddleware",
    "StructuredJsonFormatter",
    "TwilioMetrics",
    "health_check_registry",
]

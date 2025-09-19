"""Service layer for business logic."""

import warnings

from .agent_service import AgentService, agent_service

# DEPRECATED SERVICES - Import for backwards compatibility with deprecation warning
from .analytics_service import AnalyticsService, analytics_service
from .call_service import CallService, call_service
from .callback_service import CallbackService, callback_service
from .conference_service import ConferenceService, conference_service
from .ivr_service import IVRService, ivr_service

# NEW UNIFIED SERVICE - Replaces analytics_service and reporting_service
from .metrics_service import MetricsService, metrics_service
from .queue_service import QueueService, queue_service
from .recording_service import RecordingService, recording_service
from .reporting_service import ReportingService, reporting_service
from .routing_service import AdvancedRoutingService, routing_service
from .twilio_service import TwilioService, twilio_service


# Warn users about deprecated services
def _deprecated_analytics_service():
    warnings.warn(
        "analytics_service is deprecated. Use metrics_service instead. "
        "The new service combines analytics and reporting functionality.",
        DeprecationWarning,
        stacklevel=2,
    )
    return analytics_service


def _deprecated_reporting_service():
    warnings.warn(
        "reporting_service is deprecated. Use metrics_service instead. "
        "The new service combines analytics and reporting functionality.",
        DeprecationWarning,
        stacklevel=2,
    )
    return reporting_service


__all__ = [
    "AdvancedRoutingService",
    "AgentService",
    "CallService",
    "CallbackService",
    "ConferenceService",
    "IVRService",
    "QueueService",
    "RecordingService",
    "TwilioService",
    # New unified service
    "MetricsService",
    "metrics_service",
    # Service instances
    "agent_service",
    "call_service",
    "callback_service",
    "conference_service",
    "ivr_service",
    "queue_service",
    "recording_service",
    "routing_service",
    "twilio_service",
    # Deprecated services - maintain backwards compatibility
    "AnalyticsService",
    "ReportingService",
    "analytics_service",
    "reporting_service",
]

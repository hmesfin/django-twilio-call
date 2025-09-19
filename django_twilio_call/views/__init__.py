"""Views module for django-twilio-call.

This module provides backwards compatibility by importing all ViewSets
from their respective domain modules. This ensures that existing imports
like `from django_twilio_call.views import CallViewSet` continue to work.
"""

# Import base classes and mixins
from .agent_views import AgentViewSet
from .base import (
    AgentAccessMixin,
    BaseCallCenterViewSet,
    ErrorHandlingMixin,
    PaginatedResponseMixin,
    PermissionFilterMixin,
    ReadOnlyCallCenterViewSet,
    TwilioServiceMixin,
)

# Import all ViewSets from domain modules
from .call_views import CallViewSet
from .phone_views import PhoneNumberViewSet
from .queue_views import QueueViewSet

# Import task views if they exist
try:
    from .task_views import *  # noqa
except ImportError:
    # Task views might not exist yet or might be in a different structure
    pass

# Export all ViewSets for backwards compatibility
__all__ = [
    # ViewSets
    "CallViewSet",
    "AgentViewSet",
    "QueueViewSet",
    "PhoneNumberViewSet",
    # Base classes
    "BaseCallCenterViewSet",
    "ReadOnlyCallCenterViewSet",
    # Mixins
    "ErrorHandlingMixin",
    "PermissionFilterMixin",
    "AgentAccessMixin",
    "TwilioServiceMixin",
    "PaginatedResponseMixin",
]

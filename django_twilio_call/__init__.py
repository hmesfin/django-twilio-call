"""Django-Twilio-Call: Enterprise-grade Django package for call center functionality using Twilio."""

__version__ = "0.1.0"
__author__ = "Gojjo Tech"
__email__ = "admin@gojjotech.com"
__license__ = "MIT"

# Public API exports
from .models import Agent, Call, CallLog, CallRecording, PhoneNumber, Queue
from .services import (
    call_service,
    queue_service,
    agent_service,
    twilio_service,
    recording_service,
    ivr_service,
)

__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__email__",
    "__license__",
    # Models
    "Agent",
    "Call",
    "CallLog",
    "CallRecording",
    "PhoneNumber",
    "Queue",
    # Services
    "call_service",
    "queue_service",
    "agent_service",
    "twilio_service",
    "recording_service",
    "ivr_service",
]

default_app_config = "django_twilio_call.apps.DjangoTwilioCallConfig"

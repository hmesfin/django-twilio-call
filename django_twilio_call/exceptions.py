"""Custom exceptions for django-twilio-call package."""

from typing import Any, Dict, Optional


class DjangoTwilioCallError(Exception):
    """Base exception for all django-twilio-call errors."""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code or "DJANGO_TWILIO_ERROR"
        self.details = details or {}
        super().__init__(self.message)


class TwilioServiceError(DjangoTwilioCallError):
    """Exception raised for Twilio service errors."""

    def __init__(
        self,
        message: str,
        twilio_code: Optional[int] = None,
        twilio_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.twilio_code = twilio_code
        self.twilio_message = twilio_message
        details = details or {}
        if twilio_code:
            details["twilio_code"] = twilio_code
        if twilio_message:
            details["twilio_message"] = twilio_message
        super().__init__(message, code="TWILIO_SERVICE_ERROR", details=details)


class TwilioConnectionError(TwilioServiceError):
    """Exception raised when unable to connect to Twilio."""

    def __init__(self, message: str = "Unable to connect to Twilio service"):
        super().__init__(message, code="TWILIO_CONNECTION_ERROR")


class TwilioAuthenticationError(TwilioServiceError):
    """Exception raised for Twilio authentication failures."""

    def __init__(self, message: str = "Twilio authentication failed"):
        super().__init__(message, code="TWILIO_AUTH_ERROR")


class TwilioRateLimitError(TwilioServiceError):
    """Exception raised when Twilio rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Twilio rate limit exceeded",
        retry_after: Optional[int] = None,
    ):
        details = {}
        if retry_after:
            details["retry_after"] = retry_after
        super().__init__(message, code="TWILIO_RATE_LIMIT", details=details)


class CallServiceError(DjangoTwilioCallError):
    """Exception raised for call service errors."""

    def __init__(
        self,
        message: str,
        call_sid: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.call_sid = call_sid
        details = details or {}
        if call_sid:
            details["call_sid"] = call_sid
        super().__init__(message, code="CALL_SERVICE_ERROR", details=details)


class QueueServiceError(DjangoTwilioCallError):
    """Exception raised for queue service errors."""

    def __init__(
        self,
        message: str,
        queue_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.queue_id = queue_id
        details = details or {}
        if queue_id:
            details["queue_id"] = queue_id
        super().__init__(message, code="QUEUE_SERVICE_ERROR", details=details)


class AgentNotAvailableError(DjangoTwilioCallError):
    """Exception raised when no agent is available."""

    def __init__(
        self,
        message: str = "No agent available to handle the call",
        queue_id: Optional[str] = None,
    ):
        details = {}
        if queue_id:
            details["queue_id"] = queue_id
        super().__init__(message, code="AGENT_NOT_AVAILABLE", details=details)


class WebhookValidationError(DjangoTwilioCallError):
    """Exception raised when webhook signature validation fails."""

    def __init__(
        self,
        message: str = "Webhook signature validation failed",
        request_url: Optional[str] = None,
    ):
        details = {}
        if request_url:
            details["request_url"] = request_url
        super().__init__(message, code="WEBHOOK_VALIDATION_ERROR", details=details)


class ConfigurationError(DjangoTwilioCallError):
    """Exception raised for configuration errors."""

    def __init__(
        self,
        message: str,
        missing_setting: Optional[str] = None,
    ):
        details = {}
        if missing_setting:
            details["missing_setting"] = missing_setting
        super().__init__(message, code="CONFIGURATION_ERROR", details=details)


class RecordingError(DjangoTwilioCallError):
    """Exception raised for recording-related errors."""

    def __init__(
        self,
        message: str,
        recording_sid: Optional[str] = None,
        call_sid: Optional[str] = None,
    ):
        details = {}
        if recording_sid:
            details["recording_sid"] = recording_sid
        if call_sid:
            details["call_sid"] = call_sid
        super().__init__(message, code="RECORDING_ERROR", details=details)

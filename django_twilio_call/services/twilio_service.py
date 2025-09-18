"""Twilio service layer with connection pooling and retry logic."""

import logging
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar

from django.core.cache import cache
from twilio.base.exceptions import TwilioException, TwilioRestException
from twilio.request_validator import RequestValidator
from twilio.rest import Client

from ..exceptions import (
    TwilioAuthenticationError,
    TwilioConnectionError,
    TwilioRateLimitError,
    TwilioServiceError,
    WebhookValidationError,
)
from ..settings import (
    DJANGO_TWILIO_CACHE_TIMEOUT,
    DJANGO_TWILIO_LOG_API_REQUESTS,
    TWILIO_ACCOUNT_SID,
    TWILIO_API_KEY,
    TWILIO_API_SECRET,
    TWILIO_AUTH_TOKEN,
    TWILIO_CONNECTION_POOL_MAXSIZE,
    TWILIO_CONNECTION_POOL_SIZE,
    TWILIO_MAX_RETRIES,
    TWILIO_REQUEST_TIMEOUT,
    TWILIO_RETRY_BACKOFF_BASE,
    TWILIO_RETRY_BACKOFF_MAX,
    TWILIO_WEBHOOK_AUTH_TOKEN,
    TWILIO_WEBHOOK_VALIDATE,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def exponential_backoff(
    func: Callable[..., T],
    max_retries: int = TWILIO_MAX_RETRIES,
    base_delay: float = 1.0,
    max_delay: float = TWILIO_RETRY_BACKOFF_MAX,
    backoff_base: float = TWILIO_RETRY_BACKOFF_BASE,
) -> Callable[..., T]:
    """Decorator for exponential backoff retry logic."""

    @wraps(func)
    def wrapper(*args, **kwargs) -> T:
        last_exception = None
        delay = base_delay

        for attempt in range(max_retries):
            try:
                if DJANGO_TWILIO_LOG_API_REQUESTS and attempt > 0:
                    logger.info(f"Retry attempt {attempt + 1}/{max_retries} for {func.__name__}")

                return func(*args, **kwargs)

            except TwilioRestException as e:
                last_exception = e

                # Don't retry on client errors (4xx)
                if 400 <= e.code < 500:
                    if e.code == 401:
                        raise TwilioAuthenticationError(str(e))
                    elif e.code == 429:
                        retry_after = int(e.msg.get("retry_after", delay))
                        raise TwilioRateLimitError(str(e), retry_after=retry_after)
                    else:
                        raise TwilioServiceError(
                            str(e),
                            twilio_code=e.code,
                            twilio_message=e.msg,
                        )

                # Retry on server errors (5xx) and network errors
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay = min(delay * backoff_base, max_delay)

            except (ConnectionError, TimeoutError) as e:
                last_exception = e
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay = min(delay * backoff_base, max_delay)

            except Exception as e:
                logger.error(f"Unexpected error in {func.__name__}: {e}")
                raise

        # All retries exhausted
        if isinstance(last_exception, TwilioException):
            raise TwilioConnectionError(f"Failed after {max_retries} attempts: {last_exception}")
        else:
            raise TwilioConnectionError(f"Connection failed after {max_retries} attempts")

    return wrapper


class TwilioService:
    """Singleton service for managing Twilio client with connection pooling."""

    _instance: Optional["TwilioService"] = None
    _client: Optional[Client] = None
    _validator: Optional[RequestValidator] = None

    def __new__(cls) -> "TwilioService":
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize Twilio service."""
        if self._client is None:
            self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize Twilio client with connection pooling."""
        try:
            # Use API Key/Secret if available, otherwise use Auth Token
            if TWILIO_API_KEY and TWILIO_API_SECRET:
                self._client = Client(
                    TWILIO_API_KEY,
                    TWILIO_API_SECRET,
                    TWILIO_ACCOUNT_SID,
                    http_client=self._get_http_client(),
                )
            else:
                self._client = Client(
                    TWILIO_ACCOUNT_SID,
                    TWILIO_AUTH_TOKEN,
                    http_client=self._get_http_client(),
                )

            # Initialize webhook validator
            self._validator = RequestValidator(TWILIO_WEBHOOK_AUTH_TOKEN or TWILIO_AUTH_TOKEN)

            logger.info("Twilio client initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Twilio client: {e}")
            raise TwilioConnectionError(f"Failed to initialize Twilio client: {e}")

    def _get_http_client(self) -> Dict[str, Any]:
        """Get HTTP client configuration with connection pooling."""
        return {
            "pool_connections": TWILIO_CONNECTION_POOL_SIZE,
            "pool_maxsize": TWILIO_CONNECTION_POOL_MAXSIZE,
            "max_retries": 0,  # We handle retries ourselves
            "timeout": TWILIO_REQUEST_TIMEOUT,
        }

    @property
    def client(self) -> Client:
        """Get Twilio client instance."""
        if self._client is None:
            self._initialize_client()
        return self._client

    def validate_webhook(
        self,
        url: str,
        params: Dict[str, Any],
        signature: str,
    ) -> bool:
        """Validate Twilio webhook signature.

        Args:
            url: The full URL of the webhook
            params: The POST parameters from the request
            signature: The X-Twilio-Signature header value

        Returns:
            bool: True if signature is valid

        Raises:
            WebhookValidationError: If validation is required and fails

        """
        if not TWILIO_WEBHOOK_VALIDATE:
            return True

        if not self._validator:
            self._validator = RequestValidator(TWILIO_WEBHOOK_AUTH_TOKEN or TWILIO_AUTH_TOKEN)

        is_valid = self._validator.validate(url, params, signature)

        if not is_valid and TWILIO_WEBHOOK_VALIDATE:
            logger.warning(f"Webhook validation failed for URL: {url}")
            raise WebhookValidationError(request_url=url)

        return is_valid

    @exponential_backoff
    def make_call(
        self,
        to: str,
        from_: str,
        url: Optional[str] = None,
        twiml: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make an outbound call.

        Args:
            to: The phone number to call
            from_: The phone number to call from
            url: The URL for TwiML instructions
            twiml: Direct TwiML instructions
            **kwargs: Additional Twilio call parameters

        Returns:
            Dict containing call details

        """
        if DJANGO_TWILIO_LOG_API_REQUESTS:
            logger.info(f"Making call from {from_} to {to}")

        try:
            call = self.client.calls.create(
                to=to,
                from_=from_,
                url=url,
                twiml=twiml,
                **kwargs,
            )

            return {
                "sid": call.sid,
                "status": call.status,
                "from": call.from_,
                "to": call.to,
                "direction": call.direction,
                "duration": call.duration,
                "price": call.price,
                "price_unit": call.price_unit,
            }

        except TwilioRestException as e:
            logger.error(f"Failed to make call: {e}")
            raise TwilioServiceError(
                f"Failed to make call: {e}",
                twilio_code=e.code,
                twilio_message=str(e),
            )

    @exponential_backoff
    def get_call(self, call_sid: str) -> Dict[str, Any]:
        """Get call details.

        Args:
            call_sid: The Twilio Call SID

        Returns:
            Dict containing call details

        """
        cache_key = f"twilio_call_{call_sid}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        try:
            call = self.client.calls(call_sid).fetch()

            result = {
                "sid": call.sid,
                "parent_call_sid": call.parent_call_sid,
                "account_sid": call.account_sid,
                "to": call.to,
                "to_formatted": call.to_formatted,
                "from": call.from_,
                "from_formatted": call.from_formatted,
                "status": call.status,
                "start_time": call.start_time,
                "end_time": call.end_time,
                "duration": call.duration,
                "price": call.price,
                "price_unit": call.price_unit,
                "direction": call.direction,
                "answered_by": call.answered_by,
                "forwarded_from": call.forwarded_from,
                "caller_name": call.caller_name,
                "queue_time": call.queue_time,
            }

            # Cache completed calls longer
            timeout = DJANGO_TWILIO_CACHE_TIMEOUT * 10 if call.status == "completed" else DJANGO_TWILIO_CACHE_TIMEOUT
            cache.set(cache_key, result, timeout)

            return result

        except TwilioRestException as e:
            logger.error(f"Failed to get call {call_sid}: {e}")
            raise TwilioServiceError(
                f"Failed to get call: {e}",
                twilio_code=e.code,
                twilio_message=str(e),
            )

    @exponential_backoff
    def update_call(self, call_sid: str, **kwargs) -> Dict[str, Any]:
        """Update an active call.

        Args:
            call_sid: The Twilio Call SID
            **kwargs: Parameters to update (status, url, method, etc.)

        Returns:
            Dict containing updated call details

        """
        if DJANGO_TWILIO_LOG_API_REQUESTS:
            logger.info(f"Updating call {call_sid} with params: {kwargs}")

        try:
            call = self.client.calls(call_sid).update(**kwargs)

            # Invalidate cache
            cache.delete(f"twilio_call_{call_sid}")

            return {
                "sid": call.sid,
                "status": call.status,
                "duration": call.duration,
            }

        except TwilioRestException as e:
            logger.error(f"Failed to update call {call_sid}: {e}")
            raise TwilioServiceError(
                f"Failed to update call: {e}",
                twilio_code=e.code,
                twilio_message=str(e),
            )

    @exponential_backoff
    def end_call(self, call_sid: str) -> Dict[str, Any]:
        """End an active call.

        Args:
            call_sid: The Twilio Call SID

        Returns:
            Dict containing call details

        """
        return self.update_call(call_sid, status="completed")

    @exponential_backoff
    def hold_call(self, call_sid: str, hold_url: Optional[str] = None) -> Dict[str, Any]:
        """Put a call on hold.

        Args:
            call_sid: The Twilio Call SID
            hold_url: Optional URL for hold music/message

        Returns:
            Dict containing call details

        """
        from ..settings import DEFAULT_HOLD_MUSIC_URL

        hold_url = hold_url or DEFAULT_HOLD_MUSIC_URL
        twiml = f"<Response><Play loop='0'>{hold_url}</Play></Response>"

        return self.update_call(call_sid, twiml=twiml)

    @exponential_backoff
    def transfer_call(
        self,
        call_sid: str,
        to: str,
        from_: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Transfer a call to another number.

        Args:
            call_sid: The Twilio Call SID
            to: The phone number to transfer to
            from_: Optional caller ID for the transfer

        Returns:
            Dict containing call details

        """
        from ..settings import DEFAULT_CALLER_ID

        from_ = from_ or DEFAULT_CALLER_ID
        twiml = f"<Response><Dial callerId='{from_}'>{to}</Dial></Response>"

        return self.update_call(call_sid, twiml=twiml)

    @exponential_backoff
    def list_phone_numbers(self) -> list:
        """List all phone numbers in the account.

        Returns:
            List of phone number details

        """
        cache_key = "twilio_phone_numbers"
        cached = cache.get(cache_key)
        if cached:
            return cached

        try:
            numbers = self.client.incoming_phone_numbers.list()

            result = [
                {
                    "sid": number.sid,
                    "phone_number": number.phone_number,
                    "friendly_name": number.friendly_name,
                    "capabilities": {
                        "voice": number.capabilities.voice,
                        "sms": number.capabilities.sms,
                        "mms": number.capabilities.mms,
                        "fax": number.capabilities.fax,
                    },
                }
                for number in numbers
            ]

            cache.set(cache_key, result, DJANGO_TWILIO_CACHE_TIMEOUT * 60)  # Cache for longer
            return result

        except TwilioRestException as e:
            logger.error(f"Failed to list phone numbers: {e}")
            raise TwilioServiceError(
                f"Failed to list phone numbers: {e}",
                twilio_code=e.code,
                twilio_message=str(e),
            )


# Create singleton instance
twilio_service = TwilioService()

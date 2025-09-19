"""Webhook handlers for Twilio callbacks."""

import logging
import time
from typing import Any, Dict, Optional

from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from twilio.twiml.voice_response import Dial, Gather, VoiceResponse

from ..models import Agent, Call, Queue
from ..serializers import WebhookDataSerializer
from ..services import call_service, queue_service, twilio_service
from ..settings import TWILIO_WEBHOOK_URL, TWILIO_WEBHOOK_VALIDATE

logger = logging.getLogger(__name__)


class TwiMLResponse:
    """Helper class for generating TwiML responses."""

    @staticmethod
    def say(message: str, voice: str = "alice", language: str = "en-US") -> VoiceResponse:
        """Generate TwiML with text-to-speech."""
        response = VoiceResponse()
        response.say(message, voice=voice, language=language)
        return response

    @staticmethod
    def play(url: str, loop: int = 1) -> VoiceResponse:
        """Generate TwiML to play audio."""
        response = VoiceResponse()
        response.play(url, loop=loop)
        return response

    @staticmethod
    def gather_input(
        prompt: str,
        action_url: str,
        num_digits: int = 1,
        timeout: int = 5,
        method: str = "POST",
    ) -> VoiceResponse:
        """Generate TwiML for gathering input."""
        response = VoiceResponse()
        gather = Gather(
            num_digits=num_digits,
            action=action_url,
            method=method,
            timeout=timeout,
        )
        gather.say(prompt)
        response.append(gather)
        # Add a fallback message
        response.say("We didn't receive any input. Goodbye!")
        return response

    @staticmethod
    def dial(
        number: str,
        caller_id: Optional[str] = None,
        record: bool = False,
        action_url: Optional[str] = None,
    ) -> VoiceResponse:
        """Generate TwiML for dialing."""
        response = VoiceResponse()
        dial_params = {}
        if caller_id:
            dial_params["caller_id"] = caller_id
        if record:
            dial_params["record"] = "record-from-answer"
        if action_url:
            dial_params["action"] = action_url

        dial = Dial(**dial_params)
        dial.number(number)
        response.append(dial)
        return response

    @staticmethod
    def queue(
        queue_name: str,
        wait_url: Optional[str] = None,
        wait_method: str = "POST",
    ) -> VoiceResponse:
        """Generate TwiML to place caller in queue."""
        response = VoiceResponse()
        response.say("Please wait while we connect you to the next available agent.")

        enqueue_params = {"wait_url": wait_url} if wait_url else {}
        response.enqueue(queue_name, **enqueue_params)
        return response

    @staticmethod
    def hold_music(music_url: Optional[str] = None) -> VoiceResponse:
        """Generate TwiML for hold music."""
        from ..settings import DEFAULT_HOLD_MUSIC_URL

        response = VoiceResponse()
        response.play(music_url or DEFAULT_HOLD_MUSIC_URL, loop=0)
        return response


@method_decorator(csrf_exempt, name="dispatch")
class BaseWebhookView(View):
    """Base class for Twilio webhook handlers."""

    def validate_request(self, request) -> bool:
        """Validate webhook request from Twilio with replay attack prevention."""
        if not TWILIO_WEBHOOK_VALIDATE:
            return True

        # Import security validator
        from ..security import WebhookValidator
        validator = WebhookValidator()

        # Validate signature
        if not validator.validate_request(request):
            logger.warning(f"Invalid webhook signature from {request.META.get('REMOTE_ADDR')}")
            return False

        # Validate timestamp to prevent replay attacks
        if not validator.validate_timestamp(request, max_age=300):  # 5 minutes
            logger.warning(f"Webhook timestamp validation failed from {request.META.get('REMOTE_ADDR')}")
            return False

        # Check for duplicate webhook (idempotency)
        if not self._check_webhook_idempotency(request):
            logger.warning(f"Duplicate webhook detected from {request.META.get('REMOTE_ADDR')}")
            return False

        return True

    def _check_webhook_idempotency(self, request) -> bool:
        """Check webhook idempotency to prevent duplicate processing.

        Args:
            request: HTTP request

        Returns:
            bool: True if webhook is unique, False if duplicate
        """
        # Generate idempotency key from webhook data
        call_sid = request.POST.get('CallSid', '')
        event_type = request.POST.get('CallStatus', '')
        timestamp = request.POST.get('Timestamp', str(int(time.time())))

        if not call_sid:
            # If no CallSid, use request signature as key
            call_sid = request.META.get('HTTP_X_TWILIO_SIGNATURE', 'unknown')

        idempotency_key = f"webhook:idempotent:{call_sid}:{event_type}:{timestamp}"

        # Check if this webhook was already processed
        if cache.get(idempotency_key):
            logger.info(f"Duplicate webhook ignored: {idempotency_key}")
            return False

        # Mark webhook as processed (keep for 1 hour)
        cache.set(idempotency_key, True, 3600)
        return True

    def parse_webhook_data(self, request) -> Dict[str, Any]:
        """Parse and validate webhook data."""
        serializer = WebhookDataSerializer(data=request.POST)
        if serializer.is_valid():
            return serializer.validated_data
        else:
            logger.warning(f"Invalid webhook data: {serializer.errors}")
            return request.POST.dict()


@method_decorator(csrf_exempt, name="dispatch")
class VoiceWebhookView(BaseWebhookView):
    """Handle Twilio voice webhooks."""

    def post(self, request, *args, **kwargs):
        """Handle incoming voice webhook."""
        # Validate request
        if not self.validate_request(request):
            return HttpResponseForbidden("Invalid signature")

        # Parse data
        data = self.parse_webhook_data(request)

        # Route based on call status
        call_status = data.get("CallStatus", "").lower()

        if call_status == "ringing":
            return self.handle_incoming_call(data)
        elif call_status == "in-progress":
            return self.handle_call_in_progress(data)
        elif call_status in ["completed", "failed", "busy", "no-answer"]:
            return self.handle_call_ended(data)
        else:
            # Default response
            response = TwiMLResponse.say("Thank you for calling. Goodbye!")
            return HttpResponse(str(response), content_type="text/xml")

    def handle_incoming_call(self, data: Dict[str, Any]) -> HttpResponse:
        """Handle incoming call."""
        try:
            # Create or update call record
            call = call_service.handle_inbound_call(
                call_sid=data["CallSid"],
                from_number=data["From"],
                to_number=data["To"],
                account_sid=data["AccountSid"],
                metadata={"caller_name": data.get("CallerName", "")},
            )

            # Check if we should route to IVR menu
            if self.should_use_ivr(call):
                return self.handle_ivr_menu(call, data)

            # Try to find an available agent or queue
            agent = self.find_available_agent(call)
            if agent:
                # Direct to agent
                return self.route_to_agent(call, agent)
            else:
                # Add to default queue
                return self.route_to_queue(call)

        except Exception as e:
            logger.error(f"Error handling incoming call: {e}")
            response = TwiMLResponse.say("We're experiencing technical difficulties. Please try again later.")
            return HttpResponse(str(response), content_type="text/xml")

    def handle_call_in_progress(self, data: Dict[str, Any]) -> HttpResponse:
        """Handle call in progress status."""
        try:
            call_sid = data["CallSid"]
            call_service.update_call_status(
                call_sid=call_sid,
                status=Call.Status.IN_PROGRESS,
            )

            # Return empty response to continue call
            response = VoiceResponse()
            return HttpResponse(str(response), content_type="text/xml")

        except Exception as e:
            logger.error(f"Error handling call in progress: {e}")
            response = VoiceResponse()
            return HttpResponse(str(response), content_type="text/xml")

    def handle_call_ended(self, data: Dict[str, Any]) -> HttpResponse:
        """Handle call ended status."""
        try:
            call_sid = data["CallSid"]
            status_map = {
                "completed": Call.Status.COMPLETED,
                "failed": Call.Status.FAILED,
                "busy": Call.Status.BUSY,
                "no-answer": Call.Status.NO_ANSWER,
            }

            call_status = status_map.get(data.get("CallStatus", "").lower(), Call.Status.FAILED)

            duration = int(data.get("Duration", 0))
            call_service.update_call_status(
                call_sid=call_sid,
                status=call_status,
                duration=duration,
            )

            # Empty response for status callbacks
            return HttpResponse("", content_type="text/plain")

        except Exception as e:
            logger.error(f"Error handling call ended: {e}")
            return HttpResponse("", content_type="text/plain")

    def should_use_ivr(self, call: Call) -> bool:
        """Determine if call should use IVR menu."""
        # You can customize this logic based on business hours, phone number, etc.
        return False  # Default to no IVR for now

    def handle_ivr_menu(self, call: Call, data: Dict[str, Any]) -> HttpResponse:
        """Handle IVR menu for incoming call."""
        base_url = TWILIO_WEBHOOK_URL.rstrip("/")
        response = TwiMLResponse.gather_input(
            prompt=(
                "Welcome to our call center. Press 1 for sales. Press 2 for support. Press 3 to speak with an operator."
            ),
            action_url=f"{base_url}/webhooks/ivr/",
            num_digits=1,
        )
        return HttpResponse(str(response), content_type="text/xml")

    def find_available_agent(self, call: Call) -> Optional[Agent]:
        """Find an available agent for the call."""
        # Simple implementation - get first available agent
        return Agent.objects.filter(
            status=Agent.Status.AVAILABLE,
            is_active=True,
        ).first()

    def route_to_agent(self, call: Call, agent: Agent) -> HttpResponse:
        """Route call to specific agent."""
        # Update call assignment
        call.agent = agent
        call.save(update_fields=["agent"])

        # Update agent status
        agent.status = Agent.Status.BUSY
        agent.save(update_fields=["status"])

        # Generate TwiML to dial agent
        response = TwiMLResponse.dial(
            number=agent.phone_number or agent.extension,
            record=call.is_recorded,
        )

        return HttpResponse(str(response), content_type="text/xml")

    def route_to_queue(self, call: Call) -> HttpResponse:
        """Route call to default queue."""
        # Get or create default queue
        queue, _ = Queue.objects.get_or_create(
            name="default",
            defaults={
                "description": "Default queue for incoming calls",
                "max_size": 100,
                "timeout_seconds": 300,
            },
        )

        # Add call to queue
        try:
            queue_service.add_call_to_queue(call, queue.id)

            # Generate TwiML for queue
            base_url = TWILIO_WEBHOOK_URL.rstrip("/")
            response = TwiMLResponse.queue(
                queue_name=queue.name,
                wait_url=f"{base_url}/webhooks/queue/wait/",
            )

            return HttpResponse(str(response), content_type="text/xml")

        except Exception as e:
            logger.error(f"Error adding call to queue: {e}")
            response = TwiMLResponse.say("All agents are currently busy. Please try again later.")
            return HttpResponse(str(response), content_type="text/xml")


@method_decorator(csrf_exempt, name="dispatch")
class StatusCallbackView(BaseWebhookView):
    """Handle Twilio status callbacks."""

    def post(self, request, *args, **kwargs):
        """Handle status callback."""
        # Validate request
        if not self.validate_request(request):
            return HttpResponseForbidden("Invalid signature")

        # Parse data
        data = self.parse_webhook_data(request)

        try:
            call_sid = data.get("CallSid")
            call_status = data.get("CallStatus")
            duration = data.get("Duration", 0)

            if call_sid and call_status:
                # Map Twilio status to our status
                status_map = {
                    "queued": Call.Status.QUEUED,
                    "ringing": Call.Status.RINGING,
                    "in-progress": Call.Status.IN_PROGRESS,
                    "completed": Call.Status.COMPLETED,
                    "failed": Call.Status.FAILED,
                    "busy": Call.Status.BUSY,
                    "no-answer": Call.Status.NO_ANSWER,
                    "canceled": Call.Status.CANCELED,
                }

                mapped_status = status_map.get(call_status.lower())
                if mapped_status:
                    call_service.update_call_status(
                        call_sid=call_sid,
                        status=mapped_status,
                        duration=int(duration) if duration else None,
                    )

            return HttpResponse("", content_type="text/plain")

        except Exception as e:
            logger.error(f"Error processing status callback: {e}")
            return HttpResponse("", content_type="text/plain")


@method_decorator(csrf_exempt, name="dispatch")
class RecordingCallbackView(BaseWebhookView):
    """Handle Twilio recording callbacks."""

    def post(self, request, *args, **kwargs):
        """Handle recording callback."""
        # Validate request
        if not self.validate_request(request):
            return HttpResponseForbidden("Invalid signature")

        # Parse data
        data = self.parse_webhook_data(request)

        try:
            from ..models import CallRecording

            call_sid = data.get("CallSid")
            recording_sid = data.get("RecordingSid")
            recording_url = data.get("RecordingUrl")
            recording_status = data.get("RecordingStatus")
            recording_duration = data.get("RecordingDuration", 0)

            if call_sid and recording_sid:
                # Get the call
                call = Call.objects.filter(twilio_sid=call_sid).first()
                if call:
                    # Create or update recording
                    CallRecording.objects.update_or_create(
                        twilio_sid=recording_sid,
                        defaults={
                            "call": call,
                            "status": recording_status,
                            "duration": int(recording_duration) if recording_duration else 0,
                            "url": recording_url,
                        },
                    )

                    # Update call recording status
                    if not call.is_recorded:
                        call.is_recorded = True
                        call.recording_url = recording_url
                        call.save(update_fields=["is_recorded", "recording_url"])

            return HttpResponse("", content_type="text/plain")

        except Exception as e:
            logger.error(f"Error processing recording callback: {e}")
            return HttpResponse("", content_type="text/plain")


@method_decorator(csrf_exempt, name="dispatch")
class IVRMenuView(BaseWebhookView):
    """Handle IVR menu selections."""

    def post(self, request, *args, **kwargs):
        """Handle IVR input."""
        # Validate request
        if not self.validate_request(request):
            return HttpResponseForbidden("Invalid signature")

        # Parse data
        data = self.parse_webhook_data(request)
        digits = data.get("Digits", "")
        call_sid = data.get("CallSid")

        try:
            call = Call.objects.filter(twilio_sid=call_sid).first()
            if not call:
                response = TwiMLResponse.say("Sorry, we couldn't find your call.")
                return HttpResponse(str(response), content_type="text/xml")

            # Route based on input
            if digits == "1":
                # Sales
                return self.route_to_department(call, "sales")
            elif digits == "2":
                # Support
                return self.route_to_department(call, "support")
            elif digits == "3":
                # Operator
                return self.route_to_department(call, "operator")
            else:
                # Invalid input - replay menu
                base_url = TWILIO_WEBHOOK_URL.rstrip("/")
                response = TwiMLResponse.gather_input(
                    prompt="Invalid selection. Please press 1 for sales, 2 for support, or 3 for an operator.",
                    action_url=f"{base_url}/webhooks/ivr/",
                    num_digits=1,
                )
                return HttpResponse(str(response), content_type="text/xml")

        except Exception as e:
            logger.error(f"Error handling IVR input: {e}")
            response = TwiMLResponse.say("Sorry, an error occurred. Please try again.")
            return HttpResponse(str(response), content_type="text/xml")

    def route_to_department(self, call: Call, department: str) -> HttpResponse:
        """Route call to specific department queue."""
        # Get or create department queue
        queue, _ = Queue.objects.get_or_create(
            name=f"{department}_queue",
            defaults={
                "description": f"Queue for {department} department",
                "max_size": 50,
                "timeout_seconds": 300,
            },
        )

        try:
            # Add call to department queue
            queue_service.add_call_to_queue(call, queue.id)

            # Generate response
            response = VoiceResponse()
            response.say(f"Connecting you to {department}. Please hold.")
            response.enqueue(queue.name)

            return HttpResponse(str(response), content_type="text/xml")

        except Exception as e:
            logger.error(f"Error routing to {department}: {e}")
            response = TwiMLResponse.say(f"All {department} agents are currently busy. Please try again later.")
            return HttpResponse(str(response), content_type="text/xml")


@method_decorator(csrf_exempt, name="dispatch")
class QueueWaitView(BaseWebhookView):
    """Handle queue wait experience."""

    def post(self, request, *args, **kwargs):
        """Handle queue wait callback."""
        # Validate request
        if not self.validate_request(request):
            return HttpResponseForbidden("Invalid signature")

        # Parse data
        data = self.parse_webhook_data(request)
        call_sid = data.get("CallSid")
        queue_time = data.get("QueueTime", "0")

        try:
            call = Call.objects.filter(twilio_sid=call_sid).first()
            if not call or not call.queue:
                response = TwiMLResponse.hold_music()
                return HttpResponse(str(response), content_type="text/xml")

            # Get queue position
            position = queue_service.get_queue_position(call)
            estimated_wait = queue_service.estimate_wait_time(call)

            # Generate wait message
            response = VoiceResponse()

            # Announce position every 30 seconds
            if int(queue_time) % 30 == 0 and position > 0:
                minutes = estimated_wait // 60
                response.say(f"You are number {position} in the queue. Your estimated wait time is {minutes} minutes.")

            # Play hold music
            response.play(call.queue.music_url or DEFAULT_HOLD_MUSIC_URL)

            return HttpResponse(str(response), content_type="text/xml")

        except Exception as e:
            logger.error(f"Error handling queue wait: {e}")
            response = TwiMLResponse.hold_music()
            return HttpResponse(str(response), content_type="text/xml")

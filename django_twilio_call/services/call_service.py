"""Call service layer for managing call operations."""

import logging
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.utils import timezone as django_timezone

from ..exceptions import AgentNotAvailableError, CallServiceError
from ..models import Agent, Call, CallLog, PhoneNumber, Queue
from .twilio_service import twilio_service

logger = logging.getLogger(__name__)


class CallService:
    """Service for managing call operations."""

    def __init__(self):
        """Initialize call service."""
        self.twilio = twilio_service

    @transaction.atomic
    def create_outbound_call(
        self,
        to_number: str,
        from_number: Optional[str] = None,
        agent_id: Optional[int] = None,
        queue_id: Optional[int] = None,
        url: Optional[str] = None,
        twiml: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **twilio_params,
    ) -> Call:
        """Create an outbound call.

        Args:
            to_number: The phone number to call
            from_number: The phone number to call from
            agent_id: Optional agent ID making the call
            queue_id: Optional queue ID for the call
            url: URL for TwiML instructions
            twiml: Direct TwiML instructions
            metadata: Additional metadata for the call
            **twilio_params: Additional Twilio parameters

        Returns:
            Call object

        Raises:
            CallServiceError: If call creation fails

        """
        try:
            # Get default from number if not provided
            if not from_number:
                from ..settings import DEFAULT_CALLER_ID

                from_number = DEFAULT_CALLER_ID

            # Get phone number object if it exists
            phone_number = None
            try:
                phone_number = PhoneNumber.objects.get(phone_number=from_number)
            except PhoneNumber.DoesNotExist:
                logger.warning(f"Phone number {from_number} not found in database")

            # Make the Twilio call
            twilio_call = self.twilio.make_call(
                to=to_number,
                from_=from_number,
                url=url,
                twiml=twiml,
                **twilio_params,
            )

            # Create call record
            call = Call.objects.create(
                twilio_sid=twilio_call["sid"],
                account_sid=self.twilio.client.account_sid,
                from_number=from_number,
                to_number=to_number,
                phone_number_used=phone_number,
                direction=Call.Direction.OUTBOUND,
                status=twilio_call["status"],
                agent_id=agent_id,
                queue_id=queue_id,
                metadata=metadata or {},
            )

            # Create initial call log
            CallLog.objects.create(
                call=call,
                event_type=CallLog.EventType.INITIATED,
                description=f"Outbound call initiated from {from_number} to {to_number}",
                agent_id=agent_id,
            )

            logger.info(f"Created outbound call {call.twilio_sid}")
            return call

        except Exception as e:
            logger.error(f"Failed to create outbound call: {e}")
            raise CallServiceError(f"Failed to create outbound call: {e}")

    @transaction.atomic
    def handle_inbound_call(
        self,
        call_sid: str,
        from_number: str,
        to_number: str,
        account_sid: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Call:
        """Handle an inbound call from webhook.

        Args:
            call_sid: Twilio call SID
            from_number: Caller's phone number
            to_number: Called phone number
            account_sid: Twilio account SID
            metadata: Additional call metadata

        Returns:
            Call object

        """
        try:
            # Check if call already exists
            call, created = Call.objects.get_or_create(
                twilio_sid=call_sid,
                defaults={
                    "account_sid": account_sid,
                    "from_number": from_number,
                    "to_number": to_number,
                    "direction": Call.Direction.INBOUND,
                    "status": Call.Status.RINGING,
                    "metadata": metadata or {},
                },
            )

            if created:
                # Try to match phone number
                try:
                    phone_number = PhoneNumber.objects.get(phone_number=to_number)
                    call.phone_number_used = phone_number
                    call.save(update_fields=["phone_number_used"])
                except PhoneNumber.DoesNotExist:
                    pass

                CallLog.objects.create(
                    call=call,
                    event_type=CallLog.EventType.INITIATED,
                    description=f"Inbound call received from {from_number} to {to_number}",
                )

                logger.info(f"Created inbound call record {call.twilio_sid}")

            return call

        except Exception as e:
            logger.error(f"Failed to handle inbound call: {e}")
            raise CallServiceError(f"Failed to handle inbound call: {e}", call_sid=call_sid)

    @transaction.atomic
    def update_call_status(
        self,
        call_sid: str,
        status: str,
        duration: Optional[int] = None,
        **additional_fields,
    ) -> Call:
        """Update call status from webhook.

        Args:
            call_sid: Twilio call SID
            status: New call status
            duration: Call duration in seconds
            **additional_fields: Additional fields to update

        Returns:
            Updated Call object

        """
        try:
            call = Call.objects.get(twilio_sid=call_sid)
            call.status = status

            if duration is not None:
                call.duration = duration

            # Update additional fields
            for field, value in additional_fields.items():
                if hasattr(call, field):
                    setattr(call, field, value)

            # Update timestamps based on status
            if status == Call.Status.IN_PROGRESS and not call.answered_at:
                call.answered_at = django_timezone.now()
                call.start_time = django_timezone.now()

            elif status in [Call.Status.COMPLETED, Call.Status.FAILED, Call.Status.NO_ANSWER]:
                if not call.end_time:
                    call.end_time = django_timezone.now()

            call.save()

            # Log status change
            event_type_map = {
                Call.Status.QUEUED: CallLog.EventType.QUEUED,
                Call.Status.RINGING: CallLog.EventType.RINGING,
                Call.Status.IN_PROGRESS: CallLog.EventType.ANSWERED,
                Call.Status.COMPLETED: CallLog.EventType.COMPLETED,
                Call.Status.FAILED: CallLog.EventType.FAILED,
            }

            if status in event_type_map:
                CallLog.objects.create(
                    call=call,
                    event_type=event_type_map[status],
                    description=f"Call status changed to {status}",
                    agent=call.agent,
                )

            logger.info(f"Updated call {call_sid} status to {status}")
            return call

        except Call.DoesNotExist:
            logger.error(f"Call {call_sid} not found")
            raise CallServiceError("Call not found", call_sid=call_sid)
        except Exception as e:
            logger.error(f"Failed to update call status: {e}")
            raise CallServiceError(f"Failed to update call status: {e}", call_sid=call_sid)

    def hold_call(self, call_sid: str, hold_music_url: Optional[str] = None) -> Call:
        """Put a call on hold.

        Args:
            call_sid: Twilio call SID
            hold_music_url: Optional custom hold music URL

        Returns:
            Updated Call object

        """
        try:
            # Update call in Twilio
            self.twilio.hold_call(call_sid, hold_music_url)

            # Update local record
            call = Call.objects.get(twilio_sid=call_sid)

            CallLog.objects.create(
                call=call,
                event_type=CallLog.EventType.HOLD,
                description="Call placed on hold",
                agent=call.agent,
            )

            logger.info(f"Call {call_sid} placed on hold")
            return call

        except Call.DoesNotExist:
            raise CallServiceError("Call not found", call_sid=call_sid)
        except Exception as e:
            logger.error(f"Failed to hold call: {e}")
            raise CallServiceError(f"Failed to hold call: {e}", call_sid=call_sid)

    def resume_call(self, call_sid: str, resume_url: str) -> Call:
        """Resume a call from hold.

        Args:
            call_sid: Twilio call SID
            resume_url: URL to resume call flow

        Returns:
            Updated Call object

        """
        try:
            # Update call in Twilio
            self.twilio.update_call(call_sid, url=resume_url)

            # Update local record
            call = Call.objects.get(twilio_sid=call_sid)

            CallLog.objects.create(
                call=call,
                event_type=CallLog.EventType.UNHOLD,
                description="Call resumed from hold",
                agent=call.agent,
            )

            logger.info(f"Call {call_sid} resumed from hold")
            return call

        except Call.DoesNotExist:
            raise CallServiceError("Call not found", call_sid=call_sid)
        except Exception as e:
            logger.error(f"Failed to resume call: {e}")
            raise CallServiceError(f"Failed to resume call: {e}", call_sid=call_sid)

    @transaction.atomic
    def transfer_call(
        self,
        call_sid: str,
        to_number: Optional[str] = None,
        to_agent_id: Optional[int] = None,
        to_queue_id: Optional[int] = None,
    ) -> Call:
        """Transfer a call to another number, agent, or queue.

        Args:
            call_sid: Twilio call SID
            to_number: Phone number to transfer to
            to_agent_id: Agent ID to transfer to
            to_queue_id: Queue ID to transfer to

        Returns:
            Updated Call object

        """
        try:
            call = Call.objects.get(twilio_sid=call_sid)

            # Determine transfer destination
            if to_agent_id:
                agent = Agent.objects.get(id=to_agent_id)
                if not agent.is_available:
                    raise AgentNotAvailableError(f"Agent {agent.extension} is not available")
                to_number = agent.phone_number or agent.extension

                # Update call assignment
                call.agent = agent
                call.save(update_fields=["agent"])

                description = f"Call transferred to agent {agent.extension}"

            elif to_queue_id:
                queue = Queue.objects.get(id=to_queue_id)
                call.queue_id = to_queue_id
                call.save(update_fields=["queue_id"])

                description = f"Call transferred to queue {queue.name}"
                # Queue routing will be handled by queue service

            elif to_number:
                description = f"Call transferred to {to_number}"

            else:
                raise CallServiceError("Transfer destination not specified", call_sid=call_sid)

            # Perform transfer in Twilio
            if to_number:
                self.twilio.transfer_call(call_sid, to_number)

            # Log transfer
            CallLog.objects.create(
                call=call,
                event_type=CallLog.EventType.TRANSFER,
                description=description,
                agent=call.agent,
                data={"to_number": to_number, "to_agent_id": to_agent_id, "to_queue_id": to_queue_id},
            )

            logger.info(f"Call {call_sid} transferred: {description}")
            return call

        except Call.DoesNotExist:
            raise CallServiceError("Call not found", call_sid=call_sid)
        except Agent.DoesNotExist:
            raise CallServiceError("Agent not found", call_sid=call_sid)
        except Queue.DoesNotExist:
            raise CallServiceError("Queue not found", call_sid=call_sid)
        except Exception as e:
            logger.error(f"Failed to transfer call: {e}")
            raise CallServiceError(f"Failed to transfer call: {e}", call_sid=call_sid)

    def end_call(self, call_sid: str) -> Call:
        """End an active call.

        Args:
            call_sid: Twilio call SID

        Returns:
            Updated Call object

        """
        try:
            # End call in Twilio
            self.twilio.end_call(call_sid)

            # Update local record
            return self.update_call_status(call_sid, Call.Status.COMPLETED)

        except Exception as e:
            logger.error(f"Failed to end call: {e}")
            raise CallServiceError(f"Failed to end call: {e}", call_sid=call_sid)

    def get_active_calls(
        self,
        agent_id: Optional[int] = None,
        queue_id: Optional[int] = None,
    ) -> List[Call]:
        """Get active calls, optionally filtered by agent or queue.

        Args:
            agent_id: Optional agent ID filter
            queue_id: Optional queue ID filter

        Returns:
            List of active Call objects

        """
        filters = {
            "status__in": [
                Call.Status.QUEUED,
                Call.Status.RINGING,
                Call.Status.IN_PROGRESS,
            ]
        }

        if agent_id:
            filters["agent_id"] = agent_id

        if queue_id:
            filters["queue_id"] = queue_id

        return list(Call.objects.filter(**filters).order_by("-created_at"))


# Create service instance
call_service = CallService()

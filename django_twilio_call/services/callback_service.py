"""Callback service for managing call callbacks."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from ..models import Agent, Call, CallLog, Queue

logger = logging.getLogger(__name__)


class CallbackRequest:
    """Represents a callback request."""

    def __init__(
        self,
        phone_number: str,
        queue_id: Optional[int] = None,
        preferred_time: Optional[datetime] = None,
        notes: Optional[str] = None,
        original_call_id: Optional[int] = None,
        priority: str = "normal",
    ):
        self.phone_number = phone_number
        self.queue_id = queue_id
        self.preferred_time = preferred_time
        self.notes = notes
        self.original_call_id = original_call_id
        self.priority = priority
        self.created_at = timezone.now()
        self.attempts = 0
        self.status = "pending"


class CallbackService:
    """Service for managing callback requests."""

    def __init__(self):
        """Initialize callback service."""
        self.pending_callbacks: List[CallbackRequest] = []

    @transaction.atomic
    def request_callback(
        self,
        call: Call,
        preferred_time: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> CallbackRequest:
        """Request a callback for a call.

        Args:
            call: Original call requesting callback
            preferred_time: Preferred callback time
            notes: Optional notes about the callback

        Returns:
            CallbackRequest object

        """
        # Create callback request
        callback = CallbackRequest(
            phone_number=call.from_number,
            queue_id=call.queue.id if call.queue else None,
            preferred_time=preferred_time,
            notes=notes,
            original_call_id=call.id,
            priority=call.metadata.get("priority", "normal"),
        )

        # Update call metadata
        call.metadata["callback_requested"] = True
        call.metadata["callback_time"] = preferred_time.isoformat() if preferred_time else None
        call.metadata["callback_notes"] = notes
        call.save(update_fields=["metadata", "updated_at"])

        # Log callback request
        CallLog.objects.create(
            call=call,
            event_type=CallLog.EventType.VOICEMAIL,  # Using VOICEMAIL as placeholder
            description="Callback requested",
            data={
                "preferred_time": preferred_time.isoformat() if preferred_time else None,
                "notes": notes,
            },
        )

        # Add to pending callbacks (in production, this would be stored in DB)
        self.pending_callbacks.append(callback)

        logger.info(f"Callback requested for {callback.phone_number} from call {call.twilio_sid}")
        return callback

    def get_pending_callbacks(
        self,
        queue_id: Optional[int] = None,
        due_only: bool = False,
    ) -> List[CallbackRequest]:
        """Get pending callback requests.

        Args:
            queue_id: Optional queue filter
            due_only: Only return callbacks due now

        Returns:
            List of CallbackRequest objects

        """
        callbacks = [cb for cb in self.pending_callbacks if cb.status == "pending"]

        if queue_id:
            callbacks = [cb for cb in callbacks if cb.queue_id == queue_id]

        if due_only:
            now = timezone.now()
            callbacks = [cb for cb in callbacks if not cb.preferred_time or cb.preferred_time <= now]

        return sorted(callbacks, key=lambda x: x.priority == "high", reverse=True)

    @transaction.atomic
    def process_callback(
        self,
        callback: CallbackRequest,
        agent_id: Optional[int] = None,
    ) -> Optional[Call]:
        """Process a callback request by initiating an outbound call.

        Args:
            callback: CallbackRequest to process
            agent_id: Optional agent to handle the callback

        Returns:
            Created Call object or None if failed

        """
        from .call_service import call_service

        try:
            # Update callback status
            callback.status = "processing"
            callback.attempts += 1

            # Get agent if specified
            agent = None
            if agent_id:
                try:
                    agent = Agent.objects.get(id=agent_id, is_active=True)
                except Agent.DoesNotExist:
                    logger.warning(f"Agent {agent_id} not found for callback")

            # Create metadata for the callback call
            metadata = {
                "is_callback": True,
                "original_call_id": callback.original_call_id,
                "callback_attempt": callback.attempts,
                "callback_notes": callback.notes,
            }

            # Create outbound call
            call = call_service.create_outbound_call(
                to_number=callback.phone_number,
                agent_id=agent.id if agent else None,
                queue_id=callback.queue_id,
                metadata=metadata,
                url=f"{TWILIO_WEBHOOK_URL}/webhooks/callback/connect/",
            )

            # Update callback status
            callback.status = "completed"

            # Remove from pending list
            self.pending_callbacks.remove(callback)

            logger.info(f"Callback processed for {callback.phone_number}")
            return call

        except Exception as e:
            logger.error(f"Failed to process callback: {e}")

            # Mark as failed after max attempts
            if callback.attempts >= 3:
                callback.status = "failed"
                self.pending_callbacks.remove(callback)
            else:
                callback.status = "pending"

            return None

    def schedule_callbacks(self, time_window_hours: int = 1) -> List[Call]:
        """Schedule and process callbacks within the time window.

        Args:
            time_window_hours: Hours ahead to look for scheduled callbacks

        Returns:
            List of created Call objects

        """
        now = timezone.now()
        window_end = now + timedelta(hours=time_window_hours)

        # Get callbacks due in the window
        due_callbacks = [
            cb
            for cb in self.pending_callbacks
            if cb.status == "pending"
            and (not cb.preferred_time or (cb.preferred_time >= now and cb.preferred_time <= window_end))
        ]

        processed_calls = []

        for callback in due_callbacks:
            # Find available agent for the queue
            agent = None
            if callback.queue_id:
                try:
                    queue = Queue.objects.get(id=callback.queue_id)
                    agent = Agent.objects.filter(
                        queues=queue,
                        status=Agent.Status.AVAILABLE,
                        is_active=True,
                    ).first()
                except Queue.DoesNotExist:
                    pass

            # Process the callback
            call = self.process_callback(callback, agent.id if agent else None)
            if call:
                processed_calls.append(call)

        return processed_calls

    def cancel_callback(self, phone_number: str) -> bool:
        """Cancel a pending callback.

        Args:
            phone_number: Phone number to cancel callback for

        Returns:
            True if cancelled, False if not found

        """
        for callback in self.pending_callbacks:
            if callback.phone_number == phone_number and callback.status == "pending":
                callback.status = "cancelled"
                self.pending_callbacks.remove(callback)
                logger.info(f"Callback cancelled for {phone_number}")
                return True

        return False

    def get_callback_stats(self, queue_id: Optional[int] = None) -> Dict:
        """Get callback statistics.

        Args:
            queue_id: Optional queue filter

        Returns:
            Dictionary of callback statistics

        """
        callbacks = self.pending_callbacks

        if queue_id:
            callbacks = [cb for cb in callbacks if cb.queue_id == queue_id]

        total = len(callbacks)
        pending = len([cb for cb in callbacks if cb.status == "pending"])
        processing = len([cb for cb in callbacks if cb.status == "processing"])
        completed = len([cb for cb in callbacks if cb.status == "completed"])
        failed = len([cb for cb in callbacks if cb.status == "failed"])

        # Calculate average wait time for pending callbacks
        now = timezone.now()
        pending_callbacks = [cb for cb in callbacks if cb.status == "pending"]

        if pending_callbacks:
            total_wait = sum((now - cb.created_at).total_seconds() for cb in pending_callbacks)
            avg_wait = total_wait / len(pending_callbacks)
        else:
            avg_wait = 0

        return {
            "total": total,
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
            "average_wait_time": avg_wait,
            "high_priority": len([cb for cb in pending_callbacks if cb.priority == "high"]),
        }


# Create service instance
callback_service = CallbackService()

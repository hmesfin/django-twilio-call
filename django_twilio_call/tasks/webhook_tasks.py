"""Webhook processing tasks for django-twilio-call.

Handles webhook callbacks, retries, and webhook-related operations.
"""

import logging
from typing import Any, Dict

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from ..constants import DefaultValues

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="process_webhook_callback")
def process_webhook_callback(self, webhook_data: Dict[str, Any], webhook_type: str):
    """Process incoming webhook callback from Twilio.

    Args:
        webhook_data: The webhook payload data
        webhook_type: Type of webhook (call-status, recording, etc.)

    Returns:
        Dictionary with processing results

    """
    try:
        from ..models import WebhookLog

        # Create webhook log entry
        webhook_log = WebhookLog.objects.create(
            webhook_type=webhook_type,
            url=webhook_data.get("AccountSid", "unknown"),
            payload=webhook_data,
            status=WebhookLog.Status.PENDING,
        )

        if hasattr(self, "update_state"):
            self.update_state(
                state="PROGRESS", meta={"current": 1, "total": 4, "status": f"Processing {webhook_type} webhook"}
            )

        # Process based on webhook type
        if webhook_type == "call-status":
            result = _process_call_status_webhook(webhook_data, webhook_log)
        elif webhook_type == "recording":
            result = _process_recording_webhook(webhook_data, webhook_log)
        elif webhook_type == "transcription":
            result = _process_transcription_webhook(webhook_data, webhook_log)
        else:
            result = {"success": False, "error": f"Unknown webhook type: {webhook_type}"}

        if hasattr(self, "update_state"):
            self.update_state(
                state="PROGRESS", meta={"current": 4, "total": 4, "status": "Webhook processing completed"}
            )

        # Update webhook log
        webhook_log.status = WebhookLog.Status.DELIVERED if result["success"] else WebhookLog.Status.FAILED
        webhook_log.delivered_at = timezone.now()
        if not result["success"]:
            webhook_log.error_message = result.get("error", "Unknown error")
        webhook_log.save()

        return result

    except Exception as e:
        logger.error(f"Error processing webhook callback: {e}")
        return {"success": False, "error": str(e), "webhook_type": webhook_type}


@shared_task(bind=True, name="retry_failed_webhook")
def retry_failed_webhook(self, webhook_log_id: int, max_retries: int = 3):
    """Retry processing a failed webhook.

    Args:
        webhook_log_id: WebhookLog ID to retry
        max_retries: Maximum number of retry attempts

    Returns:
        Dictionary with retry results

    """
    try:
        from ..models import WebhookLog

        webhook_log = WebhookLog.objects.get(id=webhook_log_id)

        if webhook_log.retry_count >= max_retries:
            webhook_log.status = WebhookLog.Status.ABANDONED
            webhook_log.abandoned_at = timezone.now()
            webhook_log.save()
            return {"success": False, "error": "Maximum retries exceeded", "retry_count": webhook_log.retry_count}

        if hasattr(self, "update_state"):
            self.update_state(
                state="PROGRESS",
                meta={"current": 1, "total": 3, "status": f"Retrying webhook (attempt {webhook_log.retry_count + 1})"},
            )

        # Increment retry count
        webhook_log.retry_count += 1
        webhook_log.status = WebhookLog.Status.RETRYING
        webhook_log.save()

        # Retry processing
        result = process_webhook_callback.apply_async(
            args=[webhook_log.payload, webhook_log.webhook_type],
            countdown=60,  # Wait 1 minute before retry
        )

        if hasattr(self, "update_state"):
            self.update_state(state="PROGRESS", meta={"current": 3, "total": 3, "status": "Retry queued"})

        return {"success": True, "retry_count": webhook_log.retry_count, "task_id": result.id}

    except Exception as e:
        logger.error(f"Error retrying webhook: {e}")
        return {"success": False, "error": str(e)}


@shared_task(name="check_failed_webhooks")
def check_failed_webhooks():
    """Check for failed webhooks that need to be retried.

    This task should be run periodically to ensure webhook reliability.
    """
    try:
        from datetime import timedelta

        from ..models import WebhookLog

        # Find failed webhooks that haven't exceeded max retries
        cutoff_time = timezone.now() - timedelta(minutes=5)  # Wait 5 minutes before retry
        failed_webhooks = WebhookLog.objects.filter(
            status=WebhookLog.Status.FAILED, retry_count__lt=3, next_retry_at__lte=timezone.now()
        ).filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=cutoff_time))

        retry_count = 0
        for webhook_log in failed_webhooks:
            try:
                # Calculate next retry time with exponential backoff
                retry_delay = min(60 * (2**webhook_log.retry_count), 3600)  # Max 1 hour
                next_retry_at = timezone.now() + timedelta(seconds=retry_delay)

                webhook_log.next_retry_at = next_retry_at
                webhook_log.save()

                # Queue retry
                retry_failed_webhook.apply_async(args=[webhook_log.id], countdown=retry_delay)

                retry_count += 1

            except Exception as e:
                logger.error(f"Failed to queue retry for webhook {webhook_log.id}: {e}")

        return {"success": True, "failed_webhooks_found": failed_webhooks.count(), "retries_queued": retry_count}

    except Exception as e:
        logger.error(f"Error checking failed webhooks: {e}")
        return {"success": False, "error": str(e)}


@shared_task(bind=True, name="send_webhook_notification")
def send_webhook_notification(self, webhook_data: Dict[str, Any], notification_url: str):
    """Send webhook notification to external system.

    Args:
        webhook_data: Data to send in webhook
        notification_url: URL to send webhook to

    Returns:
        Dictionary with send results

    """
    try:
        if hasattr(self, "update_state"):
            self.update_state(
                state="PROGRESS", meta={"current": 1, "total": 3, "status": "Preparing webhook notification"}
            )

        # Prepare headers
        headers = {"Content-Type": "application/json", "User-Agent": "django-twilio-call-webhook/1.0"}

        # Add authentication if configured
        webhook_secret = getattr(settings, "WEBHOOK_SECRET", None)
        if webhook_secret:
            import hashlib
            import hmac
            import json

            payload_string = json.dumps(webhook_data, sort_keys=True)
            signature = hmac.new(webhook_secret.encode(), payload_string.encode(), hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        if hasattr(self, "update_state"):
            self.update_state(
                state="PROGRESS", meta={"current": 2, "total": 3, "status": "Sending webhook notification"}
            )

        # Send webhook
        response = requests.post(notification_url, json=webhook_data, headers=headers, timeout=DefaultValues.RECORDING_TIMEOUT)

        if hasattr(self, "update_state"):
            self.update_state(state="PROGRESS", meta={"current": 3, "total": 3, "status": "Webhook notification sent"})

        success = 200 <= response.status_code < 300

        return {
            "success": success,
            "status_code": response.status_code,
            "response_body": response.text[:1000],  # Limit response size
            "url": notification_url,
        }

    except Exception as e:
        logger.error(f"Error sending webhook notification: {e}")
        return {"success": False, "error": str(e), "url": notification_url}


def _process_call_status_webhook(webhook_data: Dict[str, Any], webhook_log) -> Dict[str, Any]:
    """Process call status webhook.

    Args:
        webhook_data: Webhook payload
        webhook_log: WebhookLog instance

    Returns:
        Processing result dictionary

    """
    try:
        from ..models import Call, CallLog

        call_sid = webhook_data.get("CallSid")
        if not call_sid:
            return {"success": False, "error": "CallSid missing from webhook data"}

        # Find the call
        try:
            call = Call.objects.get(twilio_sid=call_sid)
            webhook_log.related_call = call
        except Call.DoesNotExist:
            return {"success": False, "error": f"Call not found: {call_sid}"}

        # Update call status
        new_status = webhook_data.get("CallStatus", "").lower().replace("-", "_")
        if new_status and hasattr(Call.Status, new_status.upper()):
            call.status = new_status
            call.save()

        # Create call log entry
        CallLog.objects.create(
            call=call,
            event_type=CallLog.EventType.COMPLETED,  # Map status to event type
            description=f"Call status updated to {new_status}",
            data=webhook_data,
        )

        return {"success": True, "call_sid": call_sid, "new_status": new_status}

    except Exception as e:
        logger.error(f"Error processing call status webhook: {e}")
        return {"success": False, "error": str(e)}


def _process_recording_webhook(webhook_data: Dict[str, Any], webhook_log) -> Dict[str, Any]:
    """Process recording webhook.

    Args:
        webhook_data: Webhook payload
        webhook_log: WebhookLog instance

    Returns:
        Processing result dictionary

    """
    try:
        from ..models import Call
        from ..tasks.recording_tasks import process_call_recording

        call_sid = webhook_data.get("CallSid")
        recording_sid = webhook_data.get("RecordingSid")

        if not call_sid or not recording_sid:
            return {"success": False, "error": "CallSid or RecordingSid missing"}

        # Find the call
        try:
            call = Call.objects.get(twilio_sid=call_sid)
            webhook_log.related_call = call
        except Call.DoesNotExist:
            return {"success": False, "error": f"Call not found: {call_sid}"}

        # Queue recording processing
        process_call_recording.delay(call.id, webhook_data)

        return {"success": True, "call_sid": call_sid, "recording_sid": recording_sid, "processing_queued": True}

    except Exception as e:
        logger.error(f"Error processing recording webhook: {e}")
        return {"success": False, "error": str(e)}


def _process_transcription_webhook(webhook_data: Dict[str, Any], webhook_log) -> Dict[str, Any]:
    """Process transcription webhook.

    Args:
        webhook_data: Webhook payload
        webhook_log: WebhookLog instance

    Returns:
        Processing result dictionary

    """
    try:
        from ..models import CallRecording

        recording_sid = webhook_data.get("RecordingSid")
        transcription_text = webhook_data.get("TranscriptionText", "")
        transcription_status = webhook_data.get("TranscriptionStatus", "")

        if not recording_sid:
            return {"success": False, "error": "RecordingSid missing from webhook data"}

        # Find the recording
        try:
            recording = CallRecording.objects.get(twilio_sid=recording_sid)
        except CallRecording.DoesNotExist:
            return {"success": False, "error": f"Recording not found: {recording_sid}"}

        # Update recording with transcription
        recording.transcription = transcription_text
        recording.transcription_status = transcription_status
        recording.save()

        return {
            "success": True,
            "recording_sid": recording_sid,
            "transcription_length": len(transcription_text),
            "status": transcription_status,
        }

    except Exception as e:
        logger.error(f"Error processing transcription webhook: {e}")
        return {"success": False, "error": str(e)}

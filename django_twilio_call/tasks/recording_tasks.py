"""Recording and transcription tasks for django-twilio-call.

Handles call recording processing, transcription, and related operations.
"""

import logging
from typing import Dict, Optional

from celery import shared_task

from .base import BaseCallCenterTask

logger = logging.getLogger(__name__)


class RecordingProcessor(BaseCallCenterTask):
    """Task class for processing call recordings."""

    def __init__(self):
        super().__init__("process_call_recording")

    def execute(self, call_id: int, recording_data: Optional[Dict] = None):
        """Process and store call recording with transcription.

        Args:
            call_id: Call ID to process recording for
            recording_data: Optional recording data from webhook

        Returns:
            Dictionary with processing results

        """
        from ..models import Call
        from ..services.recording_service import recording_service

        call = Call.objects.get(id=call_id)

        self.track_progress(1, 5, "Starting recording processing")

        # If recording_data provided, create/update recording from webhook
        if recording_data:
            self.track_progress(2, 5, "Processing webhook data")
            recording = recording_service.process_webhook_recording(call, recording_data)
        else:
            # Fetch recording data from Twilio
            self.track_progress(2, 5, "Fetching recording from Twilio")
            recordings = recording_service.fetch_call_recordings(call.twilio_sid)
            if not recordings:
                return {"success": False, "message": "No recordings found"}
            recording = recordings[0]

        self.track_progress(3, 5, "Downloading recording file")
        # Download and store recording file
        file_data = recording_service.download_recording(recording.url)
        recording_service.store_recording_file(recording, file_data)

        self.track_progress(4, 5, "Processing transcription")
        # Start transcription if enabled
        if getattr(settings, "TWILIO_CALL_TRANSCRIPTION_ENABLED", True):
            transcribe_recording.delay(recording.id)

        self.track_progress(5, 5, "Recording processing completed")

        return {
            "success": True,
            "recording_id": recording.id,
            "recording_sid": recording.twilio_sid,
            "call_sid": call.twilio_sid,
            "duration": recording.duration,
            "transcription_started": getattr(settings, "TWILIO_CALL_TRANSCRIPTION_ENABLED", True),
        }


class TranscriptionProcessor(BaseCallCenterTask):
    """Task class for processing recording transcriptions."""

    def __init__(self):
        super().__init__("transcribe_recording")

    def execute(self, recording_id: int, force_retranscribe: bool = False):
        """Transcribe a call recording.

        Args:
            recording_id: CallRecording ID to transcribe
            force_retranscribe: Force re-transcription even if already done

        Returns:
            Dictionary with transcription results

        """
        from ..models import CallRecording
        from ..services.transcription_service import transcription_service

        recording = CallRecording.objects.get(id=recording_id)

        # Skip if already transcribed (unless forced)
        if recording.transcription and not force_retranscribe:
            return {
                "success": True,
                "message": "Recording already transcribed",
                "recording_id": recording_id,
                "transcription_length": len(recording.transcription),
            }

        self.track_progress(1, 4, "Starting transcription")

        # Check if recording file is available
        if not recording.url:
            raise ValueError("Recording URL not available for transcription")

        self.track_progress(2, 4, "Sending to transcription service")
        # Send to transcription service
        transcription_result = transcription_service.transcribe_recording(recording.url)

        self.track_progress(3, 4, "Processing transcription result")
        # Update recording with transcription
        recording.transcription = transcription_result.get("text", "")
        recording.transcription_status = transcription_result.get("status", "completed")
        recording.save()

        self.track_progress(4, 4, "Transcription completed")

        return {
            "success": True,
            "recording_id": recording_id,
            "transcription_length": len(recording.transcription),
            "confidence_score": transcription_result.get("confidence", 0),
            "processing_time": transcription_result.get("processing_time", 0),
        }


@shared_task(bind=True, name="process_call_recording")
def process_call_recording(self, call_id: int, recording_data: Optional[Dict] = None):
    """Process and store call recording with transcription.

    Args:
        call_id: Call ID to process recording for
        recording_data: Optional recording data from webhook

    Returns:
        Dictionary with processing results

    """
    processor = RecordingProcessor()
    return processor.run_with_monitoring(self, call_id, recording_data)


@shared_task(bind=True, name="transcribe_recording")
def transcribe_recording(self, recording_id: int, force_retranscribe: bool = False):
    """Transcribe a call recording.

    Args:
        recording_id: CallRecording ID to transcribe
        force_retranscribe: Force re-transcription even if already done

    Returns:
        Dictionary with transcription results

    """
    processor = TranscriptionProcessor()
    return processor.run_with_monitoring(self, recording_id, force_retranscribe)


@shared_task(name="process_pending_recordings")
def process_pending_recordings():
    """Process all pending recordings that need processing.

    This task is typically run on a schedule to catch any recordings
    that may have been missed by webhook processing.
    """
    from ..models import Call

    # Find calls that should have recordings but don't
    calls_needing_recordings = Call.objects.filter(
        is_recorded=True, recordings__isnull=True, status=Call.Status.COMPLETED
    ).exclude(twilio_sid__isnull=True)

    processed_count = 0
    failed_count = 0

    for call in calls_needing_recordings:
        try:
            process_call_recording.delay(call.id)
            processed_count += 1
        except Exception as e:
            logger.error(f"Failed to queue recording processing for call {call.id}: {e}")
            failed_count += 1

    return {
        "success": True,
        "processed_count": processed_count,
        "failed_count": failed_count,
        "total_calls_checked": calls_needing_recordings.count(),
    }


@shared_task(name="transcribe_pending_recordings")
def transcribe_pending_recordings():
    """Transcribe all recordings that don't have transcriptions yet.

    This task is typically run on a schedule to ensure all recordings
    are transcribed.
    """
    from ..models import CallRecording

    # Find recordings without transcriptions
    recordings_needing_transcription = CallRecording.objects.filter(
        transcription__isnull=True, status=CallRecording.Status.COMPLETED
    ).exclude(url__isnull=True)

    processed_count = 0
    failed_count = 0

    for recording in recordings_needing_transcription:
        try:
            transcribe_recording.delay(recording.id)
            processed_count += 1
        except Exception as e:
            logger.error(f"Failed to queue transcription for recording {recording.id}: {e}")
            failed_count += 1

    return {
        "success": True,
        "processed_count": processed_count,
        "failed_count": failed_count,
        "total_recordings_checked": recordings_needing_transcription.count(),
    }


@shared_task(bind=True, name="batch_transcribe_recordings")
def batch_transcribe_recordings(self, recording_ids: list, force_retranscribe: bool = False):
    """Batch transcribe multiple recordings.

    Args:
        recording_ids: List of CallRecording IDs to transcribe
        force_retranscribe: Force re-transcription even if already done

    Returns:
        Dictionary with batch transcription results

    """
    results = {
        "success": True,
        "total_recordings": len(recording_ids),
        "processed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }

    for idx, recording_id in enumerate(recording_ids):
        try:
            # Update progress
            if hasattr(self, "update_state"):
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "current": idx + 1,
                        "total": len(recording_ids),
                        "status": f"Processing recording {recording_id}",
                    },
                )

            # Process transcription
            result = transcribe_recording(recording_id, force_retranscribe)

            if result.get("success"):
                if "already transcribed" in result.get("message", ""):
                    results["skipped"] += 1
                else:
                    results["processed"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({"recording_id": recording_id, "error": result.get("error", "Unknown error")})

        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"recording_id": recording_id, "error": str(e)})
            logger.error(f"Failed to transcribe recording {recording_id}: {e}")

    return results


@shared_task(name="cleanup_failed_recordings")
def cleanup_failed_recordings():
    """Clean up recordings that have failed processing.

    Removes or marks as failed recordings that cannot be processed.
    """
    from datetime import timedelta

    from django.utils import timezone

    from ..models import CallRecording

    # Find recordings that have been in processing state for too long
    cutoff_time = timezone.now() - timedelta(hours=24)
    stuck_recordings = CallRecording.objects.filter(status=CallRecording.Status.IN_PROGRESS, created_at__lt=cutoff_time)

    cleaned_count = 0
    for recording in stuck_recordings:
        try:
            recording.status = CallRecording.Status.FAILED
            recording.save()
            cleaned_count += 1
        except Exception as e:
            logger.error(f"Failed to mark recording {recording.id} as failed: {e}")

    return {"success": True, "cleaned_count": cleaned_count, "total_stuck_recordings": stuck_recordings.count()}

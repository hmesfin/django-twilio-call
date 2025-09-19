"""Recording service for managing call recordings."""

import hashlib
import logging
from datetime import timedelta
from typing import Any, Dict, Optional

import boto3
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from ..exceptions import RecordingError
from ..models import Call, CallLog, CallRecording

logger = logging.getLogger(__name__)


class RecordingService:
    """Service for managing call recordings."""

    def __init__(self):
        """Initialize recording service."""
        from ..settings import RECORDING_STORAGE_BACKEND

        self.storage_backend = RECORDING_STORAGE_BACKEND
        self._init_storage()

    def _init_storage(self):
        """Initialize storage backend."""
        if self.storage_backend == "s3":
            self.s3_client = boto3.client(
                "s3",
                aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", None),
                aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", None),
                region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-east-1"),
            )
            self.s3_bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)

    @transaction.atomic
    def start_recording(self, call_id: int, **kwargs) -> CallRecording:
        """Start recording a call.

        Args:
            call_id: Call ID to record
            **kwargs: Additional recording parameters

        Returns:
            CallRecording object

        """
        try:
            from ..services import twilio_service

            call = Call.objects.get(id=call_id)

            # Check if recording is already in progress
            existing = CallRecording.objects.filter(call=call, status=CallRecording.Status.IN_PROGRESS).first()

            if existing:
                logger.warning(f"Recording already in progress for call {call.twilio_sid}")
                return existing

            # Start recording via Twilio
            twilio_service.update_call(call.twilio_sid, record=True)

            # Create recording record
            recording = CallRecording.objects.create(
                call=call,
                status=CallRecording.Status.IN_PROGRESS,
                source="API",
                metadata=kwargs,
            )

            # Update call
            call.is_recorded = True
            call.save(update_fields=["is_recorded"])

            # Log recording start
            CallLog.objects.create(
                call=call,
                event_type=CallLog.EventType.RECORDING_START,
                description="Recording started",
                agent=call.agent,
            )

            logger.info(f"Recording started for call {call.twilio_sid}")
            return recording

        except Call.DoesNotExist:
            raise RecordingError(f"Call {call_id} not found")
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            raise RecordingError(f"Failed to start recording: {e}")

    @transaction.atomic
    def stop_recording(self, call_id: int) -> Optional[CallRecording]:
        """Stop recording a call.

        Args:
            call_id: Call ID

        Returns:
            CallRecording object or None

        """
        try:
            from ..services import twilio_service

            call = Call.objects.get(id=call_id)

            # Get active recording
            recording = CallRecording.objects.filter(call=call, status=CallRecording.Status.IN_PROGRESS).first()

            if not recording:
                logger.warning(f"No active recording for call {call.twilio_sid}")
                return None

            # Stop recording via Twilio
            twilio_service.update_call(call.twilio_sid, record=False)

            # Update recording status
            recording.status = CallRecording.Status.COMPLETED
            recording.save(update_fields=["status"])

            # Log recording stop
            CallLog.objects.create(
                call=call,
                event_type=CallLog.EventType.RECORDING_STOP,
                description="Recording stopped",
                agent=call.agent,
            )

            logger.info(f"Recording stopped for call {call.twilio_sid}")
            return recording

        except Call.DoesNotExist:
            raise RecordingError(f"Call {call_id} not found")
        except Exception as e:
            logger.error(f"Failed to stop recording: {e}")
            raise RecordingError(f"Failed to stop recording: {e}")

    @transaction.atomic
    def process_recording_callback(self, data: Dict[str, Any]) -> CallRecording:
        """Process recording callback from Twilio.

        Args:
            data: Webhook data from Twilio

        Returns:
            Updated CallRecording object

        """
        try:
            recording_sid = data.get("RecordingSid")
            call_sid = data.get("CallSid")
            recording_url = data.get("RecordingUrl")
            duration = int(data.get("RecordingDuration", 0))
            status = data.get("RecordingStatus", "completed")

            # Get or create recording
            recording, created = CallRecording.objects.update_or_create(
                twilio_sid=recording_sid,
                defaults={
                    "call_id": Call.objects.get(twilio_sid=call_sid).id,
                    "status": CallRecording.Status.COMPLETED,
                    "duration": duration,
                    "url": recording_url,
                },
            )

            # Schedule async processing instead of synchronous processing
            if status == "completed":
                from ..tasks import process_call_recording

                process_call_recording.delay(recording.call.id, data)

            logger.info(f"Processed recording {recording_sid}, scheduled async processing")
            return recording

        except Exception as e:
            logger.error(f"Failed to process recording callback: {e}")
            raise RecordingError(f"Failed to process recording callback: {e}")

    def _store_recording(self, recording: CallRecording, url: str):
        """Store recording in configured backend.

        Args:
            recording: CallRecording object
            url: URL to download recording from

        """
        try:
            import requests

            # Download recording
            response = requests.get(url + ".mp3")
            if response.status_code != 200:
                raise RecordingError(f"Failed to download recording from {url}")

            content = response.content
            filename = f"recordings/{recording.call.id}/{recording.twilio_sid}.mp3"

            if self.storage_backend == "s3":
                # Store in S3
                self.s3_client.put_object(
                    Bucket=self.s3_bucket,
                    Key=filename,
                    Body=content,
                    ContentType="audio/mpeg",
                    ServerSideEncryption="AES256",
                )
                recording.url = f"https://{self.s3_bucket}.s3.amazonaws.com/{filename}"

            else:
                # Store locally
                file = ContentFile(content)
                path = default_storage.save(filename, file)
                recording.url = default_storage.url(path)

            recording.file_size = len(content)
            recording.save(update_fields=["url", "file_size"])

            logger.info(f"Stored recording {recording.twilio_sid} in {self.storage_backend}")

        except Exception as e:
            logger.error(f"Failed to store recording: {e}")

    def _apply_compliance(self, recording: CallRecording):
        """Apply compliance features to recording.

        Args:
            recording: CallRecording object

        """
        from ..settings import RECORDING_ENCRYPTION_KEY, RECORDING_RETENTION_DAYS

        # Apply encryption if configured
        if RECORDING_ENCRYPTION_KEY:
            recording.encryption_details = {
                "encrypted": True,
                "algorithm": "AES256",
                "key_hash": hashlib.sha256(RECORDING_ENCRYPTION_KEY.encode()).hexdigest()[:8],
            }

        # Set retention date
        if RECORDING_RETENTION_DAYS:
            recording.metadata["retention_date"] = (
                timezone.now() + timedelta(days=RECORDING_RETENTION_DAYS)
            ).isoformat()

        # Check for PCI compliance
        if recording.call.metadata.get("pci_mode"):
            # Pause recording during sensitive data collection
            recording.metadata["pci_compliant"] = True
            recording.metadata["paused_segments"] = recording.call.metadata.get("pci_segments", [])

        recording.save(update_fields=["encryption_details", "metadata"])

    def delete_recording(self, recording_id: int, reason: str = "") -> bool:
        """Delete a recording (GDPR compliance).

        Args:
            recording_id: Recording ID
            reason: Deletion reason

        Returns:
            Success boolean

        """
        try:
            recording = CallRecording.objects.get(id=recording_id)

            # Delete from storage
            if self.storage_backend == "s3" and recording.url:
                key = recording.url.split(".com/")[-1]
                self.s3_client.delete_object(Bucket=self.s3_bucket, Key=key)
            elif self.storage_backend == "local" and recording.url:
                default_storage.delete(recording.url)

            # Mark as deleted
            recording.status = CallRecording.Status.DELETED
            recording.deleted_at = timezone.now()
            recording.metadata["deletion_reason"] = reason
            recording.url = ""
            recording.save()

            logger.info(f"Deleted recording {recording.twilio_sid}, reason: {reason}")
            return True

        except CallRecording.DoesNotExist:
            logger.error(f"Recording {recording_id} not found")
            return False
        except Exception as e:
            logger.error(f"Failed to delete recording: {e}")
            return False

    def get_recording_url(self, recording_id: int, expiry_seconds: int = 3600) -> Optional[str]:
        """Get a secure URL for accessing recording.

        Args:
            recording_id: Recording ID
            expiry_seconds: URL expiry time

        Returns:
            Secure URL or None

        """
        try:
            recording = CallRecording.objects.get(id=recording_id)

            if recording.status == CallRecording.Status.DELETED:
                return None

            if self.storage_backend == "s3":
                # Generate presigned URL
                key = recording.url.split(".com/")[-1]
                url = self.s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.s3_bucket, "Key": key},
                    ExpiresIn=expiry_seconds,
                )
                return url

            return recording.url

        except CallRecording.DoesNotExist:
            return None

    def transcribe_recording(self, recording_id: int, language: str = "en-US") -> Optional[str]:
        """Transcribe a recording.

        Args:
            recording_id: Recording ID
            language: Language code

        Returns:
            Transcription text or None

        """
        from ..settings import ENABLE_TRANSCRIPTION

        if not ENABLE_TRANSCRIPTION:
            logger.warning("Transcription is not enabled")
            return None

        try:
            recording = CallRecording.objects.get(id=recording_id)

            # Check if already transcribed
            if recording.transcription:
                return recording.transcription

            # Use Twilio transcription or other service
            # This is a placeholder for actual implementation
            transcription = self._perform_transcription(recording, language)

            # Save transcription
            recording.transcription = transcription
            recording.transcription_status = "completed"
            recording.save(update_fields=["transcription", "transcription_status"])

            return transcription

        except CallRecording.DoesNotExist:
            logger.error(f"Recording {recording_id} not found")
            return None

    def transcribe_recording_async(self, recording_id: int, language: str = "en-US") -> str:
        """Schedule transcription of a recording asynchronously.

        Args:
            recording_id: Recording ID
            language: Language code

        Returns:
            Task ID for the transcription job

        """
        from ..tasks import transcribe_recording

        # Schedule async transcription
        task = transcribe_recording.delay(recording_id, language)

        # Update recording status to pending
        try:
            recording = CallRecording.objects.get(id=recording_id)
            recording.transcription_status = "pending"
            recording.metadata = recording.metadata or {}
            recording.metadata["transcription_task_id"] = task.id
            recording.save(update_fields=["transcription_status", "metadata"])
        except CallRecording.DoesNotExist:
            logger.error(f"Recording {recording_id} not found")

        return task.id

    def _perform_transcription(self, recording: CallRecording, language: str) -> str:
        """Perform actual transcription.

        Args:
            recording: CallRecording object
            language: Language code

        Returns:
            Transcription text

        """
        # Placeholder for actual transcription implementation
        # Could use Twilio, AWS Transcribe, Google Speech-to-Text, etc.
        return "Transcription placeholder"

    def apply_pci_compliance(self, call_id: int, enabled: bool = True):
        """Enable/disable PCI compliance mode for a call.

        Args:
            call_id: Call ID
            enabled: Enable or disable PCI mode

        """
        try:
            call = Call.objects.get(id=call_id)
            call.metadata["pci_mode"] = enabled

            if enabled:
                # Pause recording if active
                recording = CallRecording.objects.filter(call=call, status=CallRecording.Status.IN_PROGRESS).first()

                if recording:
                    from ..services import twilio_service

                    # Pause recording
                    twilio_service.update_call(call.twilio_sid, pauseRecording=True)

                    # Track PCI segment
                    if "pci_segments" not in call.metadata:
                        call.metadata["pci_segments"] = []

                    call.metadata["pci_segments"].append(
                        {
                            "start": timezone.now().isoformat(),
                            "type": "pci_pause",
                        }
                    )
            else:
                # Resume recording if paused
                if call.metadata.get("pci_segments"):
                    call.metadata["pci_segments"][-1]["end"] = timezone.now().isoformat()

                    from ..services import twilio_service

                    twilio_service.update_call(call.twilio_sid, pauseRecording=False)

            call.save(update_fields=["metadata"])
            logger.info(f"PCI compliance {'enabled' if enabled else 'disabled'} for call {call.twilio_sid}")

        except Call.DoesNotExist:
            raise RecordingError(f"Call {call_id} not found")


# Create service instance
recording_service = RecordingService()

"""Cleanup and archival tasks for django-twilio-call.

Handles cleanup of old data, archival of recordings, and maintenance tasks.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="cleanup_old_call_logs")
def cleanup_old_call_logs(self, days_to_keep: int = None):
    """Clean up old call logs to maintain database performance.

    Args:
        days_to_keep: Number of days to keep logs (default from settings)

    Returns:
        Dictionary with cleanup results

    """
    if days_to_keep is None:
        days_to_keep = getattr(settings, "CALL_LOGS_RETENTION_DAYS", 90)

    cutoff_date = timezone.now() - timedelta(days=days_to_keep)

    try:
        from ..models import CallLog

        # Update progress
        if hasattr(self, "update_state"):
            self.update_state(state="PROGRESS", meta={"current": 1, "total": 3, "status": "Identifying old call logs"})

        # Find old logs
        old_logs = CallLog.objects.filter(created_at__lt=cutoff_date)
        total_count = old_logs.count()

        if hasattr(self, "update_state"):
            self.update_state(
                state="PROGRESS", meta={"current": 2, "total": 3, "status": f"Deleting {total_count} old call logs"}
            )

        # Delete in batches to avoid overwhelming the database
        batch_size = 1000
        deleted_count = 0

        while old_logs.exists():
            batch_ids = list(old_logs.values_list("id", flat=True)[:batch_size])
            CallLog.objects.filter(id__in=batch_ids).delete()
            deleted_count += len(batch_ids)

            logger.info(f"Deleted {deleted_count}/{total_count} old call logs")

        if hasattr(self, "update_state"):
            self.update_state(state="PROGRESS", meta={"current": 3, "total": 3, "status": "Cleanup completed"})

        return {
            "success": True,
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat(),
            "days_kept": days_to_keep,
        }

    except Exception as e:
        logger.error(f"Error during call log cleanup: {e}")
        return {"success": False, "error": str(e)}


@shared_task(bind=True, name="archive_old_recordings")
def archive_old_recordings(self, days_to_keep: int = None, archive_to_s3: bool = True):
    """Archive old call recordings to reduce storage costs.

    Args:
        days_to_keep: Number of days to keep recordings locally
        archive_to_s3: Whether to archive to S3 before deleting locally

    Returns:
        Dictionary with archival results

    """
    if days_to_keep is None:
        days_to_keep = getattr(settings, "RECORDINGS_RETENTION_DAYS", 365)

    cutoff_date = timezone.now() - timedelta(days=days_to_keep)

    try:
        from ..models import CallRecording

        if hasattr(self, "update_state"):
            self.update_state(state="PROGRESS", meta={"current": 1, "total": 5, "status": "Identifying old recordings"})

        # Find old recordings that haven't been archived
        old_recordings = CallRecording.objects.filter(
            created_at__lt=cutoff_date, status=CallRecording.Status.COMPLETED
        ).exclude(metadata__archived=True)

        total_count = old_recordings.count()
        archived_count = 0
        failed_count = 0

        if hasattr(self, "update_state"):
            self.update_state(
                state="PROGRESS",
                meta={"current": 2, "total": 5, "status": f"Processing {total_count} recordings for archival"},
            )

        for recording in old_recordings:
            try:
                if archive_to_s3:
                    # Archive to S3 (implement S3 archival logic)
                    archive_result = _archive_recording_to_s3(recording)
                    if archive_result["success"]:
                        # Mark as archived in metadata
                        recording.metadata["archived"] = True
                        recording.metadata["archive_location"] = archive_result["s3_key"]
                        recording.metadata["archived_at"] = timezone.now().isoformat()
                        recording.save()

                        # Optionally delete local file
                        if getattr(settings, "DELETE_LOCAL_AFTER_ARCHIVE", False):
                            _delete_local_recording_file(recording)

                        archived_count += 1
                    else:
                        failed_count += 1
                        logger.error(f"Failed to archive recording {recording.id}: {archive_result['error']}")
                else:
                    # Just mark as archived without S3
                    recording.metadata["archived"] = True
                    recording.metadata["archived_at"] = timezone.now().isoformat()
                    recording.save()
                    archived_count += 1

            except Exception as e:
                failed_count += 1
                logger.error(f"Error archiving recording {recording.id}: {e}")

        if hasattr(self, "update_state"):
            self.update_state(state="PROGRESS", meta={"current": 5, "total": 5, "status": "Archival completed"})

        return {
            "success": True,
            "total_recordings": total_count,
            "archived_count": archived_count,
            "failed_count": failed_count,
            "cutoff_date": cutoff_date.isoformat(),
            "days_kept": days_to_keep,
        }

    except Exception as e:
        logger.error(f"Error during recording archival: {e}")
        return {"success": False, "error": str(e)}


@shared_task(name="cleanup_expired_sessions")
def cleanup_expired_sessions():
    """Clean up expired user sessions and temporary data.

    Returns:
        Dictionary with cleanup results

    """
    try:
        from django.contrib.sessions.models import Session

        # Clean up expired sessions
        expired_sessions = Session.objects.filter(expire_date__lt=timezone.now())
        session_count = expired_sessions.count()
        expired_sessions.delete()

        # Clean up temporary cache entries
        cache_keys_to_delete = []

        # Add logic to identify expired cache keys
        # This is implementation-specific based on your cache usage

        return {
            "success": True,
            "expired_sessions_deleted": session_count,
            "cache_keys_deleted": len(cache_keys_to_delete),
        }

    except Exception as e:
        logger.error(f"Error during session cleanup: {e}")
        return {"success": False, "error": str(e)}


@shared_task(bind=True, name="cleanup_old_task_executions")
def cleanup_old_task_executions(self, days_to_keep: int = 30):
    """Clean up old task execution records.

    Args:
        days_to_keep: Number of days to keep task execution records

    Returns:
        Dictionary with cleanup results

    """
    cutoff_date = timezone.now() - timedelta(days=days_to_keep)

    try:
        from ..models import TaskExecution

        if hasattr(self, "update_state"):
            self.update_state(
                state="PROGRESS", meta={"current": 1, "total": 3, "status": "Identifying old task executions"}
            )

        old_executions = TaskExecution.objects.filter(created_at__lt=cutoff_date)
        total_count = old_executions.count()

        if hasattr(self, "update_state"):
            self.update_state(
                state="PROGRESS",
                meta={"current": 2, "total": 3, "status": f"Deleting {total_count} old task executions"},
            )

        deleted_count, _ = old_executions.delete()

        if hasattr(self, "update_state"):
            self.update_state(state="PROGRESS", meta={"current": 3, "total": 3, "status": "Cleanup completed"})

        return {
            "success": True,
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat(),
            "days_kept": days_to_keep,
        }

    except Exception as e:
        logger.error(f"Error during task execution cleanup: {e}")
        return {"success": False, "error": str(e)}


@shared_task(name="vacuum_database")
def vacuum_database():
    """Perform database maintenance operations.

    This task performs database-specific optimization operations.
    """
    try:
        from django.db import connection

        results = {"success": True, "operations": []}

        # PostgreSQL-specific operations
        if "postgresql" in connection.vendor:
            with connection.cursor() as cursor:
                # Analyze tables to update statistics
                cursor.execute("ANALYZE;")
                results["operations"].append("ANALYZE completed")

                # Vacuum to reclaim space (if supported)
                try:
                    cursor.execute("VACUUM;")
                    results["operations"].append("VACUUM completed")
                except Exception as e:
                    logger.warning(f"VACUUM operation failed: {e}")

        return results

    except Exception as e:
        logger.error(f"Error during database vacuum: {e}")
        return {"success": False, "error": str(e)}


def _archive_recording_to_s3(recording):
    """Helper function to archive a recording to S3.

    Args:
        recording: CallRecording instance

    Returns:
        Dictionary with archive result

    """
    # Implement S3 archival logic here
    # This is a placeholder implementation
    try:
        # Example S3 archival logic
        import boto3
        from django.conf import settings

        s3_client = boto3.client(
            "s3", aws_access_key_id=settings.AWS_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )

        bucket_name = settings.RECORDINGS_S3_BUCKET
        s3_key = f"archived-recordings/{recording.id}/{recording.twilio_sid}.wav"

        # Upload file to S3
        # This would need the actual file content
        # s3_client.upload_file(local_file_path, bucket_name, s3_key)

        return {"success": True, "s3_key": s3_key, "bucket": bucket_name}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _delete_local_recording_file(recording):
    """Helper function to delete local recording file.

    Args:
        recording: CallRecording instance

    """
    # Implement local file deletion logic
    # This would depend on how you store recording files locally
    try:
        # Example: if files are stored in media directory
        # import os
        # if recording.local_file_path and os.path.exists(recording.local_file_path):
        #     os.remove(recording.local_file_path)
        pass
    except Exception as e:
        logger.error(f"Failed to delete local recording file for {recording.id}: {e}")

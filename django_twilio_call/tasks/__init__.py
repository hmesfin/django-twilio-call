"""Tasks module for django-twilio-call.

This module provides backwards compatibility by importing all tasks
from their respective domain modules. This ensures that existing imports
like `from django_twilio_call.tasks import process_call_recording` continue to work.
"""

# Import base classes and utilities
from .base import (
    BaseCallCenterTask,
    BaseTask,
    ProgressTrackingMixin,
    RetryMixin,
    TransactionMixin,
    create_task_execution_record,
    update_task_execution_record,
)

# Cleanup and archival tasks
from .cleanup_tasks import (
    archive_old_recordings,
    cleanup_expired_sessions,
    cleanup_old_call_logs,
    cleanup_old_task_executions,
    vacuum_database,
)

# Monitoring and health check tasks
from .monitoring_tasks import (
    monitor_system_performance,
    optimize_queue_routing,
    send_critical_alert,
    system_health_check,
    update_all_agent_metrics,
)

# Import all tasks from domain modules for backwards compatibility
# Recording and transcription tasks
from .recording_tasks import (
    batch_transcribe_recordings,
    cleanup_failed_recordings,
    process_call_recording,
    process_pending_recordings,
    transcribe_pending_recordings,
    transcribe_recording,
)

# Reporting and analytics tasks
from .reporting_tasks import (
    calculate_agent_metrics,
    calculate_hourly_metrics,
    generate_daily_report,
    generate_monthly_report,
    generate_weekly_report,
)

# Webhook processing tasks
from .webhook_tasks import (
    check_failed_webhooks,
    process_webhook_callback,
    retry_failed_webhook,
    send_webhook_notification,
)

# Export all tasks for backwards compatibility
__all__ = [
    # Base classes
    "BaseTask",
    "BaseCallCenterTask",
    "ProgressTrackingMixin",
    "TransactionMixin",
    "RetryMixin",
    "create_task_execution_record",
    "update_task_execution_record",
    # Recording tasks
    "process_call_recording",
    "transcribe_recording",
    "process_pending_recordings",
    "transcribe_pending_recordings",
    "batch_transcribe_recordings",
    "cleanup_failed_recordings",
    # Reporting tasks
    "generate_daily_report",
    "generate_weekly_report",
    "generate_monthly_report",
    "calculate_agent_metrics",
    "calculate_hourly_metrics",
    # Cleanup tasks
    "cleanup_old_call_logs",
    "archive_old_recordings",
    "cleanup_expired_sessions",
    "cleanup_old_task_executions",
    "vacuum_database",
    # Webhook tasks
    "process_webhook_callback",
    "retry_failed_webhook",
    "check_failed_webhooks",
    "send_webhook_notification",
    # Monitoring tasks
    "system_health_check",
    "send_critical_alert",
    "update_all_agent_metrics",
    "optimize_queue_routing",
    "monitor_system_performance",
]

# Additional tasks that might be in the original tasks.py but not categorized yet
# These would be imported from the original file if they exist

try:
    # Import any remaining tasks from the original tasks.py that weren't categorized
    # This provides a fallback for any tasks we might have missed
    import importlib.util
    import sys

    # Try to import the original tasks module to check for any missing tasks
    original_tasks_path = __file__.replace("tasks/__init__.py", "tasks.py")
    if sys.modules.get("django_twilio_call.tasks_original"):
        original_module = sys.modules["django_twilio_call.tasks_original"]

        # Get all task functions from the original module
        for attr_name in dir(original_module):
            attr = getattr(original_module, attr_name)
            # Check if it's a Celery task
            if hasattr(attr, "delay") and hasattr(attr, "apply_async"):
                # Only import if we don't already have it
                if attr_name not in __all__:
                    globals()[attr_name] = attr
                    __all__.append(attr_name)

except Exception:
    # If we can't import the original module, that's fine
    # It means we've successfully replaced it with our modular structure
    pass

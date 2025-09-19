"""Reporting service for generating and exporting reports."""

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.core.mail import EmailMessage
from django.db.models import Avg, Count, Max, Q, Sum
from django.utils import timezone

from ..models import Agent, Call, Queue
from ..constants import Limits

logger = logging.getLogger(__name__)


class ReportType:
    """Report type constants."""

    CALL_SUMMARY = "call_summary"
    AGENT_PERFORMANCE = "agent_performance"
    QUEUE_PERFORMANCE = "queue_performance"
    ABANDONED_CALLS = "abandoned_calls"
    SERVICE_LEVEL = "service_level"
    CALL_DETAIL = "call_detail"
    AGENT_ACTIVITY = "agent_activity"
    HOURLY_DISTRIBUTION = "hourly_distribution"


class ReportFormat:
    """Report format constants."""

    CSV = "csv"
    JSON = "json"
    PDF = "pdf"
    EXCEL = "excel"


class ReportingService:
    """Service for generating reports."""

    def __init__(self):
        """Initialize reporting service."""
        pass

    def generate_report(
        self,
        report_type: str,
        start_date: datetime,
        end_date: datetime,
        format: str = ReportFormat.CSV,
        filters: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Generate a report.

        Args:
            report_type: Type of report to generate
            start_date: Start of reporting period
            end_date: End of reporting period
            format: Output format
            filters: Additional filters

        Returns:
            Dict with report data and metadata

        """
        filters = filters or {}

        # Get report data based on type
        if report_type == ReportType.CALL_SUMMARY:
            data = self._generate_call_summary(start_date, end_date, filters)
        elif report_type == ReportType.AGENT_PERFORMANCE:
            data = self._generate_agent_performance(start_date, end_date, filters)
        elif report_type == ReportType.QUEUE_PERFORMANCE:
            data = self._generate_queue_performance(start_date, end_date, filters)
        elif report_type == ReportType.ABANDONED_CALLS:
            data = self._generate_abandoned_calls(start_date, end_date, filters)
        elif report_type == ReportType.SERVICE_LEVEL:
            data = self._generate_service_level(start_date, end_date, filters)
        elif report_type == ReportType.CALL_DETAIL:
            data = self._generate_call_detail(start_date, end_date, filters)
        elif report_type == ReportType.AGENT_ACTIVITY:
            data = self._generate_agent_activity(start_date, end_date, filters)
        elif report_type == ReportType.HOURLY_DISTRIBUTION:
            data = self._generate_hourly_distribution(start_date, end_date, filters)
        else:
            raise ValueError(f"Unknown report type: {report_type}")

        # Format report based on requested format
        if format == ReportFormat.CSV:
            output = self._format_as_csv(data)
        elif format == ReportFormat.JSON:
            output = data
        elif format == ReportFormat.PDF:
            output = self._format_as_pdf(data, report_type)
        elif format == ReportFormat.EXCEL:
            output = self._format_as_excel(data)
        else:
            raise ValueError(f"Unknown format: {format}")

        return {
            "report_type": report_type,
            "format": format,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "generated_at": timezone.now().isoformat(),
            "filters": filters,
            "data": output,
        }

    def _generate_call_summary(self, start_date: datetime, end_date: datetime, filters: Dict) -> List[Dict]:
        """Generate call summary report.

        Args:
            start_date: Start date
            end_date: End date
            filters: Additional filters

        Returns:
            List of summary data

        """
        calls_query = Call.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date,
        )

        # Apply filters
        if filters.get("queue_id"):
            calls_query = calls_query.filter(queue_id=filters["queue_id"])
        if filters.get("agent_id"):
            calls_query = calls_query.filter(agent_id=filters["agent_id"])

        # Group by date
        summary = []
        current_date = start_date.date()
        end = end_date.date()

        while current_date <= end:
            day_start = timezone.make_aware(datetime.combine(current_date, datetime.min.time()))
            day_end = timezone.make_aware(datetime.combine(current_date, datetime.max.time()))

            day_calls = calls_query.filter(
                created_at__gte=day_start,
                created_at__lte=day_end,
            )

            metrics = day_calls.aggregate(
                total_calls=Count("id"),
                completed=Count("id", filter=Q(status=Call.Status.COMPLETED)),
                abandoned=Count("id", filter=Q(status=Call.Status.ABANDONED)),
                avg_duration=Avg("duration", filter=Q(status=Call.Status.COMPLETED)),
                avg_queue_time=Avg("queue_time"),
                total_duration=Sum("duration", filter=Q(status=Call.Status.COMPLETED)),
            )

            summary.append(
                {
                    "date": current_date.isoformat(),
                    "total_calls": metrics["total_calls"],
                    "completed_calls": metrics["completed"],
                    "abandoned_calls": metrics["abandoned"],
                    "avg_duration": round(metrics["avg_duration"] or 0, 2),
                    "avg_queue_time": round(metrics["avg_queue_time"] or 0, 2),
                    "total_duration": metrics["total_duration"] or 0,
                    "abandonment_rate": round(
                        (metrics["abandoned"] / metrics["total_calls"] * 100) if metrics["total_calls"] > 0 else 0, 2
                    ),
                }
            )

            current_date += timedelta(days=1)

        return summary

    def _generate_agent_performance(self, start_date: datetime, end_date: datetime, filters: Dict) -> List[Dict]:
        """Generate agent performance report.

        Args:
            start_date: Start date
            end_date: End date
            filters: Additional filters

        Returns:
            List of agent performance data

        """
        agents_query = Agent.objects.filter(is_active=True)

        if filters.get("agent_id"):
            agents_query = agents_query.filter(id=filters["agent_id"])

        performance_data = []

        for agent in agents_query:
            calls = Call.objects.filter(
                agent=agent,
                created_at__gte=start_date,
                created_at__lte=end_date,
            )

            metrics = calls.aggregate(
                total_calls=Count("id"),
                completed=Count("id", filter=Q(status=Call.Status.COMPLETED)),
                avg_duration=Avg("duration", filter=Q(status=Call.Status.COMPLETED)),
                total_duration=Sum("duration", filter=Q(status=Call.Status.COMPLETED)),
            )

            # Get transfer metrics
            transfers = calls.filter(metadata__transferred=True).count()

            # Get hold time
            hold_time = calls.aggregate(avg_hold=Avg("metadata__hold_time"))["avg_hold"] or 0

            performance_data.append(
                {
                    "agent_id": agent.id,
                    "agent_name": f"{agent.first_name} {agent.last_name}",
                    "extension": agent.extension,
                    "total_calls": metrics["total_calls"],
                    "completed_calls": metrics["completed"],
                    "avg_handling_time": round(metrics["avg_duration"] or 0, 2),
                    "total_talk_time": metrics["total_duration"] or 0,
                    "transfers": transfers,
                    "transfer_rate": round(
                        (transfers / metrics["completed"] * 100) if metrics["completed"] > 0 else 0, 2
                    ),
                    "avg_hold_time": round(hold_time, 2),
                }
            )

        return performance_data

    def _generate_queue_performance(self, start_date: datetime, end_date: datetime, filters: Dict) -> List[Dict]:
        """Generate queue performance report.

        Args:
            start_date: Start date
            end_date: End date
            filters: Additional filters

        Returns:
            List of queue performance data

        """
        queues_query = Queue.objects.filter(is_active=True)

        if filters.get("queue_id"):
            queues_query = queues_query.filter(id=filters["queue_id"])

        performance_data = []

        for queue in queues_query:
            calls = Call.objects.filter(
                queue=queue,
                created_at__gte=start_date,
                created_at__lte=end_date,
            )

            metrics = calls.aggregate(
                total_calls=Count("id"),
                completed=Count("id", filter=Q(status=Call.Status.COMPLETED)),
                abandoned=Count("id", filter=Q(status=Call.Status.ABANDONED)),
                avg_queue_time=Avg("queue_time"),
                max_queue_time=Max("queue_time"),
            )

            # Calculate service level
            sl_threshold = queue.service_level_threshold or 20
            calls_within_sl = calls.filter(
                status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS],
                queue_time__lte=sl_threshold,
            ).count()

            service_level = (
                (calls_within_sl / (metrics["completed"] + metrics["abandoned"]) * 100)
                if (metrics["completed"] + metrics["abandoned"]) > 0
                else 0
            )

            performance_data.append(
                {
                    "queue_id": queue.id,
                    "queue_name": queue.name,
                    "priority": queue.priority,
                    "total_calls": metrics["total_calls"],
                    "completed_calls": metrics["completed"],
                    "abandoned_calls": metrics["abandoned"],
                    "avg_wait_time": round(metrics["avg_queue_time"] or 0, 2),
                    "max_wait_time": metrics["max_queue_time"] or 0,
                    "service_level": round(service_level, 2),
                    "service_level_threshold": sl_threshold,
                    "abandonment_rate": round(
                        (metrics["abandoned"] / metrics["total_calls"] * 100) if metrics["total_calls"] > 0 else 0, 2
                    ),
                }
            )

        return performance_data

    def _generate_abandoned_calls(self, start_date: datetime, end_date: datetime, filters: Dict) -> List[Dict]:
        """Generate abandoned calls report.

        Args:
            start_date: Start date
            end_date: End date
            filters: Additional filters

        Returns:
            List of abandoned call data

        """
        calls_query = Call.objects.filter(
            status=Call.Status.ABANDONED,
            created_at__gte=start_date,
            created_at__lte=end_date,
        )

        # Apply filters
        if filters.get("queue_id"):
            calls_query = calls_query.filter(queue_id=filters["queue_id"])
        if filters.get("min_wait_time"):
            calls_query = calls_query.filter(queue_time__gte=filters["min_wait_time"])

        abandoned_data = []

        for call in calls_query.select_related("queue"):
            abandoned_data.append(
                {
                    "call_id": str(call.public_id),
                    "from_number": call.from_number,
                    "to_number": call.to_number,
                    "queue": call.queue.name if call.queue else "N/A",
                    "wait_time": call.queue_time or 0,
                    "created_at": call.created_at.isoformat(),
                    "abandoned_at": call.updated_at.isoformat(),
                }
            )

        return abandoned_data

    def _generate_service_level(self, start_date: datetime, end_date: datetime, filters: Dict) -> List[Dict]:
        """Generate service level report.

        Args:
            start_date: Start date
            end_date: End date
            filters: Additional filters

        Returns:
            List of service level data

        """
        # Group by hour for service level analysis
        service_level_data = []
        current_time = start_date

        while current_time < end_date:
            hour_end = current_time + timedelta(hours=1)

            calls_query = Call.objects.filter(
                created_at__gte=current_time,
                created_at__lt=hour_end,
            )

            if filters.get("queue_id"):
                calls_query = calls_query.filter(queue_id=filters["queue_id"])

            # Calculate metrics
            total_offered = calls_query.count()
            answered = calls_query.filter(status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS]).count()
            abandoned = calls_query.filter(status=Call.Status.ABANDONED).count()

            # Service level calculation (calls answered within threshold)
            threshold = filters.get("service_level_threshold", 20)
            within_sl = calls_query.filter(
                status__in=[Call.Status.COMPLETED, Call.Status.IN_PROGRESS],
                queue_time__lte=threshold,
            ).count()

            service_level = (within_sl / answered * 100) if answered > 0 else 0

            service_level_data.append(
                {
                    "timestamp": current_time.isoformat(),
                    "hour": current_time.hour,
                    "offered": total_offered,
                    "answered": answered,
                    "abandoned": abandoned,
                    "within_service_level": within_sl,
                    "service_level": round(service_level, 2),
                    "threshold_seconds": threshold,
                }
            )

            current_time = hour_end

        return service_level_data

    def _generate_call_detail(self, start_date: datetime, end_date: datetime, filters: Dict) -> List[Dict]:
        """Generate detailed call records.

        Args:
            start_date: Start date
            end_date: End date
            filters: Additional filters

        Returns:
            List of call details

        """
        calls_query = Call.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date,
        ).select_related("agent", "queue")

        # Apply filters
        if filters.get("queue_id"):
            calls_query = calls_query.filter(queue_id=filters["queue_id"])
        if filters.get("agent_id"):
            calls_query = calls_query.filter(agent_id=filters["agent_id"])
        if filters.get("status"):
            calls_query = calls_query.filter(status=filters["status"])

        call_details = []

        for call in calls_query[:Limits.MAX_ANALYTICS_RESULTS]:  # Limit for performance
            call_details.append(
                {
                    "call_id": str(call.public_id),
                    "twilio_sid": call.twilio_sid,
                    "from_number": call.from_number,
                    "to_number": call.to_number,
                    "direction": call.direction,
                    "status": call.status,
                    "queue": call.queue.name if call.queue else "N/A",
                    "agent": f"{call.agent.first_name} {call.agent.last_name}" if call.agent else "N/A",
                    "duration": call.duration or 0,
                    "queue_time": call.queue_time or 0,
                    "created_at": call.created_at.isoformat(),
                    "answered_at": call.answered_at.isoformat() if call.answered_at else None,
                    "ended_at": call.ended_at.isoformat() if call.ended_at else None,
                    "recording_url": call.recording_url,
                    "voicemail_url": call.voicemail_url,
                }
            )

        return call_details

    def _generate_agent_activity(self, start_date: datetime, end_date: datetime, filters: Dict) -> List[Dict]:
        """Generate agent activity report.

        Args:
            start_date: Start date
            end_date: End date
            filters: Additional filters

        Returns:
            List of agent activities

        """
        from ..models import AgentActivity

        activities_query = AgentActivity.objects.filter(
            timestamp__gte=start_date,
            timestamp__lte=end_date,
        ).select_related("agent")

        if filters.get("agent_id"):
            activities_query = activities_query.filter(agent_id=filters["agent_id"])

        activity_data = []

        for activity in activities_query[:Limits.MAX_ANALYTICS_RESULTS]:  # Limit for performance
            activity_data.append(
                {
                    "agent_id": activity.agent.id,
                    "agent_name": f"{activity.agent.first_name} {activity.agent.last_name}",
                    "activity_type": activity.activity_type,
                    "old_status": activity.old_status,
                    "new_status": activity.new_status,
                    "reason": activity.reason,
                    "timestamp": activity.timestamp.isoformat(),
                }
            )

        return activity_data

    def _generate_hourly_distribution(self, start_date: datetime, end_date: datetime, filters: Dict) -> List[Dict]:
        """Generate hourly call distribution report.

        Args:
            start_date: Start date
            end_date: End date
            filters: Additional filters

        Returns:
            List of hourly distribution data

        """
        calls_query = Call.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date,
        )

        if filters.get("queue_id"):
            calls_query = calls_query.filter(queue_id=filters["queue_id"])

        hourly_data = []

        for hour in range(24):
            hour_calls = calls_query.filter(created_at__hour=hour)

            metrics = hour_calls.aggregate(
                total=Count("id"),
                completed=Count("id", filter=Q(status=Call.Status.COMPLETED)),
                abandoned=Count("id", filter=Q(status=Call.Status.ABANDONED)),
                avg_duration=Avg("duration", filter=Q(status=Call.Status.COMPLETED)),
                avg_queue_time=Avg("queue_time"),
            )

            hourly_data.append(
                {
                    "hour": hour,
                    "hour_label": f"{hour:02d}:00",
                    "total_calls": metrics["total"],
                    "completed": metrics["completed"],
                    "abandoned": metrics["abandoned"],
                    "avg_duration": round(metrics["avg_duration"] or 0, 2),
                    "avg_queue_time": round(metrics["avg_queue_time"] or 0, 2),
                }
            )

        return hourly_data

    def _format_as_csv(self, data: List[Dict]) -> str:
        """Format data as CSV.

        Args:
            data: Report data

        Returns:
            CSV string

        """
        if not data:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)

        return output.getvalue()

    def _format_as_pdf(self, data: List[Dict], report_type: str) -> bytes:
        """Format data as PDF.

        Args:
            data: Report data
            report_type: Type of report

        Returns:
            PDF bytes

        """
        # This would require a PDF library like ReportLab
        # For now, return a placeholder
        logger.info(f"PDF generation requested for {report_type}")
        return b"PDF generation not implemented"

    def _format_as_excel(self, data: List[Dict]) -> bytes:
        """Format data as Excel.

        Args:
            data: Report data

        Returns:
            Excel bytes

        """
        # This would require openpyxl or xlsxwriter
        # For now, return CSV as fallback
        return self._format_as_csv(data).encode()

    def schedule_report(
        self,
        report_type: str,
        schedule: str,
        recipients: List[str],
        filters: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Schedule a recurring report.

        Args:
            report_type: Type of report
            schedule: Schedule (daily, weekly, monthly)
            recipients: Email recipients
            filters: Report filters

        Returns:
            Schedule confirmation

        """
        # This would integrate with Celery for scheduling
        # For now, return confirmation
        return {
            "report_type": report_type,
            "schedule": schedule,
            "recipients": recipients,
            "filters": filters or {},
            "status": "scheduled",
            "next_run": timezone.now() + timedelta(days=1),
        }

    def email_report(
        self,
        report_data: Dict[str, Any],
        recipients: List[str],
        subject: Optional[str] = None,
    ) -> bool:
        """Email a report to recipients.

        Args:
            report_data: Generated report data
            recipients: Email addresses
            subject: Email subject

        Returns:
            Success status

        """
        if not subject:
            subject = f"Call Center Report - {report_data['report_type']}"

        try:
            # Create email
            email = EmailMessage(
                subject=subject,
                body=f"Please find attached your {report_data['report_type']} report.",
                to=recipients,
            )

            # Attach report
            if report_data["format"] == ReportFormat.CSV:
                email.attach(
                    f"report_{report_data['report_type']}.csv",
                    report_data["data"],
                    "text/csv",
                )
            elif report_data["format"] == ReportFormat.PDF:
                email.attach(
                    f"report_{report_data['report_type']}.pdf",
                    report_data["data"],
                    "application/pdf",
                )

            # Send email
            email.send()

            logger.info(f"Report emailed to {recipients}")
            return True

        except Exception as e:
            logger.error(f"Failed to email report: {e}")
            return False


# Create service instance
reporting_service = ReportingService()

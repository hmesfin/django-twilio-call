"""CLI command for monitoring and managing alerts."""

import json
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from ...observability.alerts.manager import alert_manager, AlertSeverity


class Command(BaseCommand):
    """Alert monitoring and management command."""

    help = 'Monitor and manage system alerts'

    def add_arguments(self, parser):
        parser.add_argument(
            '--list',
            action='store_true',
            help='List all active alerts'
        )
        parser.add_argument(
            '--resolve',
            type=str,
            help='Resolve alert by ID'
        )
        parser.add_argument(
            '--suppress',
            type=str,
            help='Suppress alert by ID'
        )
        parser.add_argument(
            '--duration',
            type=int,
            default=60,
            help='Suppression duration in minutes (default: 60)'
        )
        parser.add_argument(
            '--statistics',
            action='store_true',
            help='Show alert statistics'
        )
        parser.add_argument(
            '--severity',
            choices=['critical', 'high', 'medium', 'low', 'info'],
            help='Filter alerts by severity'
        )
        parser.add_argument(
            '--format',
            choices=['table', 'json'],
            default='table',
            help='Output format (default: table)'
        )

    def handle(self, *args, **options):
        """Handle the alert command."""
        try:
            if options['resolve']:
                self._resolve_alert(options['resolve'])
            elif options['suppress']:
                self._suppress_alert(options['suppress'], options['duration'])
            elif options['statistics']:
                self._show_statistics(options['format'])
            else:
                self._list_alerts(options['severity'], options['format'])

        except Exception as e:
            raise CommandError(f"Alert command failed: {e}")

    def _list_alerts(self, severity_filter: str, format_type: str) -> None:
        """List active alerts."""
        active_alerts = alert_manager.get_active_alerts()

        # Filter by severity if specified
        if severity_filter:
            severity_enum = AlertSeverity(severity_filter)
            active_alerts = [a for a in active_alerts if a.severity == severity_enum]

        if not active_alerts:
            self.stdout.write(self.style.SUCCESS("No active alerts"))
            return

        if format_type == 'json':
            alert_data = [
                {
                    'id': alert.id,
                    'title': alert.title,
                    'severity': alert.severity.value,
                    'timestamp': alert.timestamp.isoformat(),
                    'description': alert.description,
                    'source': alert.source,
                    'tags': alert.tags,
                    'escalation_count': alert.escalation_count,
                    'metadata': alert.metadata,
                }
                for alert in active_alerts
            ]
            self.stdout.write(json.dumps(alert_data, indent=2))
            return

        # Table format
        self.stdout.write(
            self.style.SUCCESS(f"Active Alerts ({len(active_alerts)}):\n")
        )

        # Sort by severity and timestamp
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
        active_alerts.sort(
            key=lambda a: (severity_order.get(a.severity.value, 5), a.timestamp)
        )

        # Header
        self.stdout.write(
            f"{'ID':<20} {'Severity':<10} {'Title':<30} {'Age':<15} {'Escalations':<12} {'Description':<40}"
        )
        self.stdout.write("-" * 127)

        # Alert rows
        for alert in active_alerts:
            age = datetime.now().replace(tzinfo=alert.timestamp.tzinfo) - alert.timestamp
            age_str = self._format_age(age)

            severity_style = {
                'critical': self.style.ERROR,
                'high': self.style.WARNING,
                'medium': self.style.NOTICE,
                'low': self.style.SUCCESS,
                'info': self.style.HTTP_INFO,
            }.get(alert.severity.value, self.style.NOTICE)

            escalation_display = (
                f"{alert.escalation_count}" if alert.escalation_count > 0
                else "-"
            )

            self.stdout.write(
                f"{alert.id[:19]:<20} "
                f"{severity_style(alert.severity.value.upper():<10)} "
                f"{alert.title[:29]:<30} "
                f"{age_str:<15} "
                f"{escalation_display:<12} "
                f"{alert.description[:39]:<40}"
            )

        self.stdout.write("")

    def _resolve_alert(self, alert_id: str) -> None:
        """Resolve a specific alert."""
        success = alert_manager.resolve_alert(alert_id)

        if success:
            self.stdout.write(
                self.style.SUCCESS(f"Alert {alert_id} resolved successfully")
            )
        else:
            self.stdout.write(
                self.style.ERROR(f"Alert {alert_id} not found or already resolved")
            )

    def _suppress_alert(self, alert_id: str, duration: int) -> None:
        """Suppress a specific alert."""
        success = alert_manager.suppress_alert(alert_id, duration)

        if success:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Alert {alert_id} suppressed for {duration} minutes"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(f"Alert {alert_id} not found")
            )

    def _show_statistics(self, format_type: str) -> None:
        """Show alert statistics."""
        stats = alert_manager.get_alert_statistics()

        if format_type == 'json':
            self.stdout.write(json.dumps(stats, indent=2))
            return

        # Table format
        self.stdout.write(self.style.SUCCESS("Alert Statistics:\n"))

        self.stdout.write(f"Active Alerts: {stats['active_alerts']}")
        self.stdout.write(f"Total Alerts Today: {stats['total_alerts_today']}")

        self.stdout.write("\nAlerts by Severity:")
        for severity, count in stats['alerts_by_severity'].items():
            if count > 0:
                severity_style = {
                    'critical': self.style.ERROR,
                    'high': self.style.WARNING,
                    'medium': self.style.NOTICE,
                    'low': self.style.SUCCESS,
                    'info': self.style.HTTP_INFO,
                }.get(severity, self.style.NOTICE)

                self.stdout.write(f"  {severity_style(severity.capitalize())}: {count}")

        # Show alert rules status
        self.stdout.write(f"\nAlert Rules: {len(alert_manager.rules)} registered")
        enabled_rules = sum(1 for rule in alert_manager.rules.values() if rule.enabled)
        self.stdout.write(f"Enabled Rules: {enabled_rules}")

        # Show notification channels
        self.stdout.write(f"Notification Channels: {len(alert_manager.channels)}")
        for channel in alert_manager.channels:
            self.stdout.write(f"  • {channel.name}")

    def _format_age(self, age) -> str:
        """Format alert age for display."""
        total_seconds = int(age.total_seconds())

        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            return f"{minutes}m"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
"""CLI command for real-time system monitoring."""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ...observability.metrics.collectors import call_center_metrics, twilio_metrics
from ...observability.health.checks import health_check_registry
from ...observability.alerts.manager import alert_manager


class Command(BaseCommand):
    """Real-time system monitoring command."""

    help = 'Monitor call center system in real-time'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=30,
            help='Monitoring interval in seconds (default: 30)'
        )
        parser.add_argument(
            '--format',
            choices=['table', 'json', 'summary'],
            default='table',
            help='Output format (default: table)'
        )
        parser.add_argument(
            '--alerts-only',
            action='store_true',
            help='Show only active alerts'
        )
        parser.add_argument(
            '--health-check',
            action='store_true',
            help='Run health checks'
        )
        parser.add_argument(
            '--metrics',
            action='store_true',
            help='Show detailed metrics'
        )
        parser.add_argument(
            '--continuous',
            action='store_true',
            help='Run continuously (use Ctrl+C to stop)'
        )

    def handle(self, *args, **options):
        """Handle the monitoring command."""
        interval = options['interval']
        format_type = options['format']
        alerts_only = options['alerts_only']
        health_check = options['health_check']
        show_metrics = options['metrics']
        continuous = options['continuous']

        try:
            if continuous:
                self.stdout.write(
                    self.style.SUCCESS(f"Starting continuous monitoring (interval: {interval}s)")
                )
                self.stdout.write("Press Ctrl+C to stop...\n")

                while True:
                    try:
                        self._display_monitoring_data(
                            format_type, alerts_only, health_check, show_metrics
                        )
                        if continuous:
                            time.sleep(interval)
                    except KeyboardInterrupt:
                        self.stdout.write("\nMonitoring stopped.")
                        break
            else:
                self._display_monitoring_data(
                    format_type, alerts_only, health_check, show_metrics
                )

        except Exception as e:
            raise CommandError(f"Monitoring failed: {e}")

    def _display_monitoring_data(self, format_type: str, alerts_only: bool,
                               health_check: bool, show_metrics: bool) -> None:
        """Display monitoring data based on options."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if format_type == 'json':
            data = self._collect_all_data(health_check, show_metrics)
            self.stdout.write(json.dumps(data, indent=2, default=str))
            return

        # Clear screen for continuous monitoring
        if format_type == 'table':
            print("\033[2J\033[H")  # Clear screen and move cursor to top

        self.stdout.write(
            self.style.SUCCESS(f"=== Call Center Monitoring Dashboard - {timestamp} ===\n")
        )

        # Show alerts if requested or if there are active alerts
        active_alerts = alert_manager.get_active_alerts()
        if alerts_only or active_alerts:
            self._display_alerts(active_alerts, format_type)

        if not alerts_only:
            # Show health status
            if health_check:
                self._display_health_status(format_type)

            # Show KPI metrics
            self._display_kpi_metrics(format_type)

            # Show detailed metrics if requested
            if show_metrics:
                self._display_detailed_metrics(format_type)

    def _collect_all_data(self, include_health: bool, include_metrics: bool) -> Dict[str, Any]:
        """Collect all monitoring data for JSON output."""
        data = {
            'timestamp': timezone.now().isoformat(),
            'alerts': {
                'active': [
                    {
                        'id': alert.id,
                        'title': alert.title,
                        'severity': alert.severity.value,
                        'timestamp': alert.timestamp.isoformat(),
                        'description': alert.description,
                    }
                    for alert in alert_manager.get_active_alerts()
                ],
                'statistics': alert_manager.get_alert_statistics(),
            }
        }

        if include_health:
            health_results = health_check_registry.run_all_checks()
            data['health'] = {
                'overall_status': health_check_registry.get_overall_status(health_results).value,
                'checks': {
                    name: {
                        'status': result.status.value,
                        'message': result.message,
                        'duration_ms': result.duration_ms,
                    }
                    for name, result in health_results.items()
                }
            }

        # Always include KPI metrics
        try:
            kpi_metrics = call_center_metrics.collect_real_time_metrics()
            data['kpi_metrics'] = {
                'service_level': kpi_metrics.service_level,
                'abandonment_rate': kpi_metrics.abandonment_rate,
                'average_wait_time': kpi_metrics.average_wait_time,
                'average_talk_time': kpi_metrics.average_talk_time,
                'calls_handled': kpi_metrics.calls_handled,
                'calls_abandoned': kpi_metrics.calls_abandoned,
                'agent_utilization': kpi_metrics.agent_utilization,
                'queue_depth': kpi_metrics.queue_depth,
                'first_call_resolution': kpi_metrics.first_call_resolution,
            }
        except Exception as e:
            data['kpi_metrics'] = {'error': str(e)}

        if include_metrics:
            data['detailed_metrics'] = self._get_detailed_metrics()

        return data

    def _display_alerts(self, alerts, format_type: str) -> None:
        """Display active alerts."""
        if not alerts:
            self.stdout.write(self.style.SUCCESS("✓ No active alerts\n"))
            return

        self.stdout.write(self.style.WARNING(f"⚠ Active Alerts ({len(alerts)}):\n"))

        if format_type == 'table':
            self.stdout.write(f"{'Severity':<10} {'Title':<30} {'Age':<15} {'Description':<50}")
            self.stdout.write("-" * 105)

            for alert in sorted(alerts, key=lambda a: a.severity.value):
                age = timezone.now() - alert.timestamp
                age_str = self._format_duration(age)

                severity_color = {
                    'critical': self.style.ERROR,
                    'high': self.style.WARNING,
                    'medium': self.style.NOTICE,
                    'low': self.style.SUCCESS,
                    'info': self.style.HTTP_INFO,
                }.get(alert.severity.value, self.style.NOTICE)

                self.stdout.write(
                    f"{severity_color(alert.severity.value.upper():<10)} "
                    f"{alert.title[:29]:<30} "
                    f"{age_str:<15} "
                    f"{alert.description[:49]:<50}"
                )
        else:
            for alert in alerts:
                age = timezone.now() - alert.timestamp
                self.stdout.write(f"  • [{alert.severity.value.upper()}] {alert.title} ({self._format_duration(age)} ago)")

        self.stdout.write("")

    def _display_health_status(self, format_type: str) -> None:
        """Display system health status."""
        health_results = health_check_registry.run_all_checks()
        overall_status = health_check_registry.get_overall_status(health_results)

        status_color = {
            'healthy': self.style.SUCCESS,
            'degraded': self.style.WARNING,
            'unhealthy': self.style.ERROR,
        }.get(overall_status.value, self.style.NOTICE)

        self.stdout.write(f"System Health: {status_color(overall_status.value.upper())}")

        if format_type == 'table' and health_results:
            self.stdout.write(f"\n{'Component':<15} {'Status':<10} {'Duration':<10} {'Message':<40}")
            self.stdout.write("-" * 75)

            for name, result in health_results.items():
                status_style = {
                    'healthy': self.style.SUCCESS,
                    'degraded': self.style.WARNING,
                    'unhealthy': self.style.ERROR,
                }.get(result.status.value, self.style.NOTICE)

                self.stdout.write(
                    f"{name:<15} "
                    f"{status_style(result.status.value.upper():<10)} "
                    f"{result.duration_ms:>8.1f}ms "
                    f"{result.message[:39]:<40}"
                )

        self.stdout.write("")

    def _display_kpi_metrics(self, format_type: str) -> None:
        """Display key performance indicators."""
        try:
            kpi_metrics = call_center_metrics.collect_real_time_metrics()

            self.stdout.write(self.style.SUCCESS("Key Performance Indicators:"))

            if format_type == 'table':
                self.stdout.write(f"\n{'Metric':<25} {'Value':<15} {'Status':<10}")
                self.stdout.write("-" * 50)

                metrics_display = [
                    ("Service Level", f"{kpi_metrics.service_level:.1f}%", self._get_sla_status(kpi_metrics.service_level)),
                    ("Abandonment Rate", f"{kpi_metrics.abandonment_rate:.1f}%", self._get_abandonment_status(kpi_metrics.abandonment_rate)),
                    ("Average Wait Time", f"{kpi_metrics.average_wait_time:.1f}s", self._get_wait_time_status(kpi_metrics.average_wait_time)),
                    ("Queue Depth", str(kpi_metrics.queue_depth), self._get_queue_depth_status(kpi_metrics.queue_depth)),
                    ("Calls Handled Today", str(kpi_metrics.calls_handled), "INFO"),
                    ("Agent Utilization", f"{kpi_metrics.agent_utilization:.1f}%", self._get_utilization_status(kpi_metrics.agent_utilization)),
                ]

                for metric, value, status in metrics_display:
                    status_style = {
                        'GOOD': self.style.SUCCESS,
                        'WARNING': self.style.WARNING,
                        'CRITICAL': self.style.ERROR,
                        'INFO': self.style.HTTP_INFO,
                    }.get(status, self.style.NOTICE)

                    self.stdout.write(f"{metric:<25} {value:<15} {status_style(status:<10)}")
            else:
                self.stdout.write(f"  Service Level: {kpi_metrics.service_level:.1f}%")
                self.stdout.write(f"  Abandonment Rate: {kpi_metrics.abandonment_rate:.1f}%")
                self.stdout.write(f"  Queue Depth: {kpi_metrics.queue_depth}")
                self.stdout.write(f"  Calls Handled: {kpi_metrics.calls_handled}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to collect KPI metrics: {e}"))

        self.stdout.write("")

    def _display_detailed_metrics(self, format_type: str) -> None:
        """Display detailed system metrics."""
        self.stdout.write(self.style.SUCCESS("Detailed Metrics:"))

        try:
            # Database metrics
            from django.db import connection
            queries_count = len(connection.queries) if hasattr(connection, 'queries') else 0

            # Agent metrics
            from ...models import Agent
            agent_stats = {
                'total': Agent.objects.filter(is_active=True).count(),
                'available': Agent.objects.filter(is_active=True, status=Agent.Status.AVAILABLE).count(),
                'busy': Agent.objects.filter(is_active=True, status=Agent.Status.BUSY).count(),
            }

            # Call metrics
            from ...models import Call
            today = timezone.now().date()
            call_stats = {
                'active': Call.objects.filter(
                    status__in=[Call.Status.QUEUED, Call.Status.RINGING, Call.Status.IN_PROGRESS]
                ).count(),
                'completed_today': Call.objects.filter(
                    status=Call.Status.COMPLETED,
                    created_at__date=today
                ).count(),
            }

            if format_type == 'table':
                self.stdout.write(f"\n{'Category':<15} {'Metric':<20} {'Value':<10}")
                self.stdout.write("-" * 45)
                self.stdout.write(f"{'Database':<15} {'Query Count':<20} {queries_count:<10}")
                self.stdout.write(f"{'Agents':<15} {'Total Active':<20} {agent_stats['total']:<10}")
                self.stdout.write(f"{'Agents':<15} {'Available':<20} {agent_stats['available']:<10}")
                self.stdout.write(f"{'Agents':<15} {'Busy':<20} {agent_stats['busy']:<10}")
                self.stdout.write(f"{'Calls':<15} {'Currently Active':<20} {call_stats['active']:<10}")
                self.stdout.write(f"{'Calls':<15} {'Completed Today':<20} {call_stats['completed_today']:<10}")
            else:
                self.stdout.write(f"  Agents: {agent_stats['available']}/{agent_stats['total']} available")
                self.stdout.write(f"  Active Calls: {call_stats['active']}")
                self.stdout.write(f"  Completed Today: {call_stats['completed_today']}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to collect detailed metrics: {e}"))

        self.stdout.write("")

    def _get_detailed_metrics(self) -> Dict[str, Any]:
        """Get detailed metrics for JSON output."""
        try:
            from ...models import Agent, Call
            from django.db import connection

            today = timezone.now().date()

            return {
                'database': {
                    'query_count': len(connection.queries) if hasattr(connection, 'queries') else 0,
                },
                'agents': {
                    'total_active': Agent.objects.filter(is_active=True).count(),
                    'available': Agent.objects.filter(is_active=True, status=Agent.Status.AVAILABLE).count(),
                    'busy': Agent.objects.filter(is_active=True, status=Agent.Status.BUSY).count(),
                    'on_break': Agent.objects.filter(is_active=True, status=Agent.Status.ON_BREAK).count(),
                },
                'calls': {
                    'currently_active': Call.objects.filter(
                        status__in=[Call.Status.QUEUED, Call.Status.RINGING, Call.Status.IN_PROGRESS]
                    ).count(),
                    'completed_today': Call.objects.filter(
                        status=Call.Status.COMPLETED,
                        created_at__date=today
                    ).count(),
                    'abandoned_today': Call.objects.filter(
                        status__in=[Call.Status.CANCELED, Call.Status.NO_ANSWER],
                        created_at__date=today
                    ).count(),
                }
            }
        except Exception as e:
            return {'error': str(e)}

    def _format_duration(self, duration: timedelta) -> str:
        """Format duration for display."""
        total_seconds = int(duration.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            return f"{total_seconds // 60}m"
        else:
            return f"{total_seconds // 3600}h"

    def _get_sla_status(self, service_level: float) -> str:
        """Get SLA status indicator."""
        if service_level >= 85:
            return "GOOD"
        elif service_level >= 70:
            return "WARNING"
        else:
            return "CRITICAL"

    def _get_abandonment_status(self, abandonment_rate: float) -> str:
        """Get abandonment rate status."""
        if abandonment_rate <= 5:
            return "GOOD"
        elif abandonment_rate <= 10:
            return "WARNING"
        else:
            return "CRITICAL"

    def _get_wait_time_status(self, wait_time: float) -> str:
        """Get wait time status."""
        if wait_time <= 30:
            return "GOOD"
        elif wait_time <= 60:
            return "WARNING"
        else:
            return "CRITICAL"

    def _get_queue_depth_status(self, queue_depth: int) -> str:
        """Get queue depth status."""
        if queue_depth <= 5:
            return "GOOD"
        elif queue_depth <= 15:
            return "WARNING"
        else:
            return "CRITICAL"

    def _get_utilization_status(self, utilization: float) -> str:
        """Get agent utilization status."""
        if 60 <= utilization <= 85:
            return "GOOD"
        elif 40 <= utilization < 60 or 85 < utilization <= 95:
            return "WARNING"
        else:
            return "CRITICAL"
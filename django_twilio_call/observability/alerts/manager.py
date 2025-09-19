"""Intelligent alerting system for call center operations."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertStatus(Enum):
    """Alert status."""

    FIRING = "firing"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


@dataclass
class Alert:
    """Alert data structure."""

    id: str
    title: str
    description: str
    severity: AlertSeverity
    source: str
    timestamp: datetime
    metadata: Dict[str, Any]
    tags: List[str]
    status: AlertStatus = AlertStatus.FIRING
    resolved_at: Optional[datetime] = None
    escalation_count: int = 0


@dataclass
class AlertRule:
    """Alert rule configuration."""

    name: str
    condition: Callable[[Dict[str, Any]], bool]
    severity: AlertSeverity
    description: str
    cooldown_minutes: int = 5
    escalation_minutes: int = 10
    max_escalations: int = 3
    tags: List[str] = None
    enabled: bool = True


class NotificationChannel:
    """Base class for notification channels."""

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config

    def should_notify(self, alert: Alert) -> bool:
        """Determine if this channel should handle the alert."""
        return True

    def send_notification(self, alert: Alert) -> bool:
        """Send alert notification."""
        raise NotImplementedError


class EmailNotificationChannel(NotificationChannel):
    """Email notification channel."""

    def should_notify(self, alert: Alert) -> bool:
        """Email for medium severity and above."""
        return alert.severity in [AlertSeverity.CRITICAL, AlertSeverity.HIGH, AlertSeverity.MEDIUM]

    def send_notification(self, alert: Alert) -> bool:
        """Send email notification."""
        try:
            from django.core.mail import send_mail

            subject = f"[{alert.severity.value.upper()}] {alert.title}"
            message = f"""
Alert: {alert.title}
Severity: {alert.severity.value}
Source: {alert.source}
Time: {alert.timestamp}

Description: {alert.description}

Metadata: {alert.metadata}
            """

            recipients = self.config.get("recipients", [])
            if not recipients:
                logger.warning("No email recipients configured")
                return False

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=False,
            )

            logger.info(f"Email sent for alert {alert.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email for alert {alert.id}: {e}")
            return False


class SlackNotificationChannel(NotificationChannel):
    """Slack notification channel."""

    def should_notify(self, alert: Alert) -> bool:
        """Slack for high severity and above."""
        return alert.severity in [AlertSeverity.CRITICAL, AlertSeverity.HIGH]

    def send_notification(self, alert: Alert) -> bool:
        """Send Slack notification."""
        try:
            import requests

            webhook_url = self.config.get("webhook_url")
            if not webhook_url:
                logger.warning("No Slack webhook URL configured")
                return False

            # Color coding by severity
            color_map = {
                AlertSeverity.CRITICAL: "#FF0000",
                AlertSeverity.HIGH: "#FF8C00",
                AlertSeverity.MEDIUM: "#FFD700",
                AlertSeverity.LOW: "#00FF00",
                AlertSeverity.INFO: "#87CEEB",
            }

            payload = {
                "attachments": [
                    {
                        "color": color_map.get(alert.severity, "#808080"),
                        "title": alert.title,
                        "text": alert.description,
                        "fields": [
                            {"title": "Severity", "value": alert.severity.value, "short": True},
                            {"title": "Source", "value": alert.source, "short": True},
                            {"title": "Time", "value": alert.timestamp.isoformat(), "short": True},
                        ],
                        "footer": "Call Center Monitoring",
                        "ts": alert.timestamp.timestamp(),
                    }
                ]
            }

            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()

            logger.info(f"Slack notification sent for alert {alert.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send Slack notification for alert {alert.id}: {e}")
            return False


class PagerDutyNotificationChannel(NotificationChannel):
    """PagerDuty notification channel."""

    def should_notify(self, alert: Alert) -> bool:
        """PagerDuty for critical alerts only."""
        return alert.severity == AlertSeverity.CRITICAL

    def send_notification(self, alert: Alert) -> bool:
        """Send PagerDuty notification."""
        try:
            import requests

            routing_key = self.config.get("routing_key")
            if not routing_key:
                logger.warning("No PagerDuty routing key configured")
                return False

            payload = {
                "routing_key": routing_key,
                "event_action": "trigger",
                "dedup_key": alert.id,
                "payload": {
                    "summary": alert.title,
                    "source": alert.source,
                    "severity": alert.severity.value,
                    "timestamp": alert.timestamp.isoformat(),
                    "custom_details": alert.metadata,
                },
            }

            response = requests.post("https://events.pagerduty.com/v2/enqueue", json=payload, timeout=10)
            response.raise_for_status()

            logger.info(f"PagerDuty notification sent for alert {alert.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send PagerDuty notification for alert {alert.id}: {e}")
            return False


class AlertManager:
    """Intelligent alert management system."""

    def __init__(self):
        self.rules: Dict[str, AlertRule] = {}
        self.channels: List[NotificationChannel] = []
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: List[Alert] = []
        self.lock = Lock()

        # Initialize default rules and channels
        self._initialize_default_rules()
        self._initialize_notification_channels()

    def _initialize_default_rules(self) -> None:
        """Initialize default alert rules for call center operations."""
        # Service Level Agreement violations
        self.add_rule(
            AlertRule(
                name="sla_violation",
                condition=lambda metrics: metrics.get("service_level", 100) < 80,
                severity=AlertSeverity.HIGH,
                description="Service Level Agreement below 80%",
                cooldown_minutes=5,
                tags=["sla", "performance"],
            )
        )

        # High abandonment rate
        self.add_rule(
            AlertRule(
                name="high_abandonment_rate",
                condition=lambda metrics: metrics.get("abandonment_rate", 0) > 10,
                severity=AlertSeverity.MEDIUM,
                description="Call abandonment rate above 10%",
                cooldown_minutes=3,
                tags=["abandonment", "customer_experience"],
            )
        )

        # Queue depth alerts
        self.add_rule(
            AlertRule(
                name="queue_depth_critical",
                condition=lambda metrics: metrics.get("queue_depth", 0) > 20,
                severity=AlertSeverity.CRITICAL,
                description="Queue depth critically high",
                cooldown_minutes=2,
                tags=["queue", "capacity"],
            )
        )

        self.add_rule(
            AlertRule(
                name="queue_depth_warning",
                condition=lambda metrics: metrics.get("queue_depth", 0) > 10,
                severity=AlertSeverity.MEDIUM,
                description="Queue depth elevated",
                cooldown_minutes=5,
                tags=["queue", "capacity"],
            )
        )

        # No agents available
        self.add_rule(
            AlertRule(
                name="no_agents_available",
                condition=lambda metrics: metrics.get("available_agents", 0) == 0,
                severity=AlertSeverity.CRITICAL,
                description="No agents available to handle calls",
                cooldown_minutes=1,
                tags=["agents", "availability"],
            )
        )

        # High error rate
        self.add_rule(
            AlertRule(
                name="high_error_rate",
                condition=lambda metrics: metrics.get("error_rate", 0) > 5,
                severity=AlertSeverity.HIGH,
                description="Application error rate above 5%",
                cooldown_minutes=3,
                tags=["errors", "reliability"],
            )
        )

        # Database performance
        self.add_rule(
            AlertRule(
                name="high_db_response_time",
                condition=lambda metrics: metrics.get("db_response_time_ms", 0) > 1000,
                severity=AlertSeverity.MEDIUM,
                description="Database response time above 1 second",
                cooldown_minutes=5,
                tags=["database", "performance"],
            )
        )

        # Celery task failures
        self.add_rule(
            AlertRule(
                name="high_task_failure_rate",
                condition=lambda metrics: metrics.get("task_failure_rate", 0) > 10,
                severity=AlertSeverity.HIGH,
                description="Celery task failure rate above 10%",
                cooldown_minutes=5,
                tags=["celery", "tasks"],
            )
        )

        # Twilio API errors
        self.add_rule(
            AlertRule(
                name="twilio_api_errors",
                condition=lambda metrics: metrics.get("twilio_error_rate", 0) > 5,
                severity=AlertSeverity.HIGH,
                description="High Twilio API error rate",
                cooldown_minutes=3,
                tags=["twilio", "api"],
            )
        )

        # Webhook delivery failures
        self.add_rule(
            AlertRule(
                name="webhook_delivery_failures",
                condition=lambda metrics: metrics.get("webhook_failure_rate", 0) > 20,
                severity=AlertSeverity.MEDIUM,
                description="High webhook delivery failure rate",
                cooldown_minutes=5,
                tags=["webhooks", "integration"],
            )
        )

    def _initialize_notification_channels(self) -> None:
        """Initialize notification channels from settings."""
        alert_config = getattr(settings, "ALERT_CONFIG", {})

        # Email channel
        email_config = alert_config.get("email", {})
        if email_config.get("enabled", False):
            self.add_channel(EmailNotificationChannel("email", email_config))

        # Slack channel
        slack_config = alert_config.get("slack", {})
        if slack_config.get("enabled", False):
            self.add_channel(SlackNotificationChannel("slack", slack_config))

        # PagerDuty channel
        pagerduty_config = alert_config.get("pagerduty", {})
        if pagerduty_config.get("enabled", False):
            self.add_channel(PagerDutyNotificationChannel("pagerduty", pagerduty_config))

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule."""
        with self.lock:
            self.rules[rule.name] = rule
            logger.debug(f"Added alert rule: {rule.name}")

    def remove_rule(self, rule_name: str) -> None:
        """Remove an alert rule."""
        with self.lock:
            if rule_name in self.rules:
                del self.rules[rule_name]
                logger.debug(f"Removed alert rule: {rule_name}")

    def add_channel(self, channel: NotificationChannel) -> None:
        """Add a notification channel."""
        self.channels.append(channel)
        logger.debug(f"Added notification channel: {channel.name}")

    def evaluate_metrics(self, metrics: Dict[str, Any]) -> List[Alert]:
        """Evaluate metrics against alert rules."""
        new_alerts = []

        with self.lock:
            for rule_name, rule in self.rules.items():
                if not rule.enabled:
                    continue

                try:
                    if rule.condition(metrics):
                        alert = self._create_alert(rule, metrics)
                        if self._should_fire_alert(alert):
                            new_alerts.append(alert)
                            self._handle_alert(alert)

                except Exception as e:
                    logger.error(f"Error evaluating rule {rule_name}: {e}")

        return new_alerts

    def _create_alert(self, rule: AlertRule, metrics: Dict[str, Any]) -> Alert:
        """Create an alert from a rule and metrics."""
        alert_id = f"{rule.name}_{int(time.time())}"

        return Alert(
            id=alert_id,
            title=f"Alert: {rule.name}",
            description=rule.description,
            severity=rule.severity,
            source="call_center_monitoring",
            timestamp=timezone.now(),
            metadata=metrics,
            tags=rule.tags or [],
        )

    def _should_fire_alert(self, alert: Alert) -> bool:
        """Determine if alert should be fired based on cooldown."""
        cache_key = f"alert_cooldown_{alert.title}"
        last_fired = cache.get(cache_key)

        if last_fired:
            # Check if we're still in cooldown period
            return False

        # Set cooldown
        rule = self.rules.get(alert.title.replace("Alert: ", ""))
        if rule:
            cooldown_seconds = rule.cooldown_minutes * 60
            cache.set(cache_key, time.time(), cooldown_seconds)

        return True

    def _handle_alert(self, alert: Alert) -> None:
        """Handle a fired alert."""
        # Store alert
        self.active_alerts[alert.id] = alert
        self.alert_history.append(alert)

        # Send notifications
        self._send_notifications(alert)

        # Schedule escalation if needed
        rule = self.rules.get(alert.title.replace("Alert: ", ""))
        if rule and rule.escalation_minutes > 0:
            self._schedule_escalation(alert, rule)

        logger.info(f"Alert fired: {alert.title} (severity: {alert.severity.value})")

    def _send_notifications(self, alert: Alert) -> None:
        """Send alert notifications through all appropriate channels."""
        for channel in self.channels:
            try:
                if channel.should_notify(alert):
                    success = channel.send_notification(alert)
                    if success:
                        logger.debug(f"Notification sent via {channel.name} for alert {alert.id}")
                    else:
                        logger.warning(f"Failed to send notification via {channel.name} for alert {alert.id}")
            except Exception as e:
                logger.error(f"Error sending notification via {channel.name}: {e}")

    def _schedule_escalation(self, alert: Alert, rule: AlertRule) -> None:
        """Schedule alert escalation."""

        def escalate():
            time.sleep(rule.escalation_minutes * 60)

            with self.lock:
                if alert.id in self.active_alerts and alert.status == AlertStatus.FIRING:
                    if alert.escalation_count < rule.max_escalations:
                        alert.escalation_count += 1
                        logger.warning(f"Escalating alert {alert.id} (escalation #{alert.escalation_count})")

                        # Send escalated notifications (could be to different channels)
                        self._send_notifications(alert)

                        # Schedule next escalation
                        if alert.escalation_count < rule.max_escalations:
                            self._schedule_escalation(alert, rule)

        # Run escalation in background thread
        import threading

        threading.Thread(target=escalate, daemon=True).start()

    def resolve_alert(self, alert_id: str) -> bool:
        """Manually resolve an alert."""
        with self.lock:
            if alert_id in self.active_alerts:
                alert = self.active_alerts[alert_id]
                alert.status = AlertStatus.RESOLVED
                alert.resolved_at = timezone.now()

                # Remove from active alerts
                del self.active_alerts[alert_id]

                logger.info(f"Alert resolved: {alert.title}")
                return True

        return False

    def suppress_alert(self, alert_id: str, duration_minutes: int = 60) -> bool:
        """Suppress an alert for a specified duration."""
        with self.lock:
            if alert_id in self.active_alerts:
                alert = self.active_alerts[alert_id]
                alert.status = AlertStatus.SUPPRESSED

                # Set suppression cache
                cache_key = f"alert_suppressed_{alert_id}"
                cache.set(cache_key, True, duration_minutes * 60)

                logger.info(f"Alert suppressed for {duration_minutes} minutes: {alert.title}")
                return True

        return False

    def get_active_alerts(self) -> List[Alert]:
        """Get all active alerts."""
        with self.lock:
            return list(self.active_alerts.values())

    def get_alert_statistics(self) -> Dict[str, Any]:
        """Get alert statistics."""
        with self.lock:
            return {
                "active_alerts": len(self.active_alerts),
                "total_alerts_today": len(
                    [a for a in self.alert_history if a.timestamp.date() == timezone.now().date()]
                ),
                "alerts_by_severity": {
                    severity.value: len([a for a in self.active_alerts.values() if a.severity == severity])
                    for severity in AlertSeverity
                },
                "top_alert_sources": {},  # Could be calculated from history
            }


# Global alert manager instance
alert_manager = AlertManager()

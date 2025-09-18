"""Database models for django-twilio-call package."""

import uuid
from typing import Optional

from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class TimeStampedModel(models.Model):
    """Abstract base model with timestamp fields."""

    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class PhoneNumber(TimeStampedModel):
    """Model for managing Twilio phone numbers."""

    class NumberType(models.TextChoices):
        """Phone number type choices."""

        LOCAL = "local", _("Local")
        TOLL_FREE = "toll_free", _("Toll Free")
        MOBILE = "mobile", _("Mobile")
        INTERNATIONAL = "international", _("International")

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    twilio_sid = models.CharField(
        _("Twilio SID"),
        max_length=50,
        unique=True,
        help_text=_("Twilio Phone Number SID"),
    )
    phone_number = models.CharField(
        _("phone number"),
        max_length=20,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^\+?1?\d{9,15}$",
                message=_("Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed."),
            )
        ],
    )
    friendly_name = models.CharField(_("friendly name"), max_length=100, blank=True)
    number_type = models.CharField(
        _("number type"),
        max_length=20,
        choices=NumberType.choices,
        default=NumberType.LOCAL,
    )
    capabilities = models.JSONField(
        _("capabilities"),
        default=dict,
        help_text=_("Phone number capabilities (voice, SMS, MMS, fax)"),
    )
    is_active = models.BooleanField(_("active"), default=True)
    monthly_cost = models.DecimalField(
        _("monthly cost"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
        blank=True,
        help_text=_("Additional metadata for the phone number"),
    )

    class Meta:
        verbose_name = _("Phone Number")
        verbose_name_plural = _("Phone Numbers")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["phone_number"]),
            models.Index(fields=["is_active", "number_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.friendly_name or self.phone_number}"


class Queue(TimeStampedModel):
    """Model for call queues."""

    class RoutingStrategy(models.TextChoices):
        """Queue routing strategy choices."""

        FIFO = "fifo", _("First In First Out")
        LIFO = "lifo", _("Last In First Out")
        ROUND_ROBIN = "round_robin", _("Round Robin")
        LEAST_BUSY = "least_busy", _("Least Busy Agent")
        SKILLS_BASED = "skills_based", _("Skills Based")

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    name = models.CharField(_("name"), max_length=100, unique=True)
    description = models.TextField(_("description"), blank=True)
    routing_strategy = models.CharField(
        _("routing strategy"),
        max_length=20,
        choices=RoutingStrategy.choices,
        default=RoutingStrategy.FIFO,
    )
    priority = models.IntegerField(
        _("priority"),
        default=0,
        validators=[MinValueValidator(0)],
        help_text=_("Higher priority queues are processed first"),
    )
    max_size = models.IntegerField(
        _("max size"),
        default=100,
        validators=[MinValueValidator(1)],
        help_text=_("Maximum number of calls in queue"),
    )
    timeout_seconds = models.IntegerField(
        _("timeout seconds"),
        default=300,
        validators=[MinValueValidator(30)],
        help_text=_("Time in seconds before call times out in queue"),
    )
    music_url = models.URLField(
        _("hold music URL"),
        blank=True,
        help_text=_("URL for hold music"),
    )
    announcement_url = models.URLField(
        _("announcement URL"),
        blank=True,
        help_text=_("URL for queue position announcement"),
    )
    is_active = models.BooleanField(_("active"), default=True)
    required_skills = models.JSONField(
        _("required skills"),
        default=list,
        blank=True,
        help_text=_("Skills required for agents to handle calls from this queue"),
    )
    business_hours = models.JSONField(
        _("business hours"),
        default=dict,
        blank=True,
        help_text=_("Business hours configuration for the queue"),
    )
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
        blank=True,
    )

    class Meta:
        verbose_name = _("Queue")
        verbose_name_plural = _("Queues")
        ordering = ["-priority", "name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["is_active", "priority"]),
        ]

    def __str__(self) -> str:
        return self.name


class Agent(TimeStampedModel):
    """Model for call center agents."""

    class Status(models.TextChoices):
        """Agent status choices."""

        AVAILABLE = "available", _("Available")
        BUSY = "busy", _("Busy")
        ON_BREAK = "on_break", _("On Break")
        AFTER_CALL_WORK = "after_call_work", _("After Call Work")
        OFFLINE = "offline", _("Offline")

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="agent_profile",
    )
    extension = models.CharField(
        _("extension"),
        max_length=10,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^\d{3,10}$",
                message=_("Extension must be between 3 and 10 digits"),
            )
        ],
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.OFFLINE,
    )
    phone_number = models.CharField(
        _("phone number"),
        max_length=20,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^\+?1?\d{9,15}$",
                message=_("Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed."),
            )
        ],
        help_text=_("Agent's phone number for direct routing"),
    )
    skills = models.JSONField(
        _("skills"),
        default=list,
        blank=True,
        help_text=_("List of agent skills for routing"),
    )
    queues = models.ManyToManyField(
        Queue,
        related_name="agents",
        blank=True,
        help_text=_("Queues this agent can handle"),
    )
    is_active = models.BooleanField(_("active"), default=True)
    max_concurrent_calls = models.IntegerField(
        _("max concurrent calls"),
        default=1,
        validators=[MinValueValidator(1)],
    )
    last_status_change = models.DateTimeField(
        _("last status change"),
        default=timezone.now,
    )
    total_talk_time = models.IntegerField(
        _("total talk time"),
        default=0,
        help_text=_("Total talk time in seconds"),
    )
    calls_handled_today = models.IntegerField(
        _("calls handled today"),
        default=0,
    )
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
        blank=True,
    )

    class Meta:
        verbose_name = _("Agent")
        verbose_name_plural = _("Agents")
        ordering = ["user__first_name", "user__last_name"]
        indexes = [
            models.Index(fields=["extension"]),
            models.Index(fields=["status", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.get_full_name()} ({self.extension})"

    @property
    def is_available(self) -> bool:
        """Check if agent is available to take calls."""
        return self.status == self.Status.AVAILABLE and self.is_active


class Call(TimeStampedModel):
    """Model for tracking calls."""

    class Direction(models.TextChoices):
        """Call direction choices."""

        INBOUND = "inbound", _("Inbound")
        OUTBOUND = "outbound", _("Outbound")

    class Status(models.TextChoices):
        """Call status choices."""

        QUEUED = "queued", _("Queued")
        RINGING = "ringing", _("Ringing")
        IN_PROGRESS = "in-progress", _("In Progress")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")
        BUSY = "busy", _("Busy")
        NO_ANSWER = "no-answer", _("No Answer")
        CANCELED = "canceled", _("Canceled")

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    twilio_sid = models.CharField(
        _("Twilio Call SID"),
        max_length=50,
        unique=True,
        db_index=True,
    )
    parent_call_sid = models.CharField(
        _("Parent Call SID"),
        max_length=50,
        blank=True,
        help_text=_("SID of the parent call for transferred calls"),
    )
    account_sid = models.CharField(
        _("Twilio Account SID"),
        max_length=50,
    )
    from_number = models.CharField(
        _("from number"),
        max_length=20,
        db_index=True,
    )
    from_formatted = models.CharField(
        _("from formatted"),
        max_length=20,
        blank=True,
    )
    to_number = models.CharField(
        _("to number"),
        max_length=20,
        db_index=True,
    )
    to_formatted = models.CharField(
        _("to formatted"),
        max_length=20,
        blank=True,
    )
    phone_number_used = models.ForeignKey(
        PhoneNumber,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calls",
        help_text=_("The Twilio phone number used for this call"),
    )
    direction = models.CharField(
        _("direction"),
        max_length=10,
        choices=Direction.choices,
        db_index=True,
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    agent = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calls",
    )
    queue = models.ForeignKey(
        Queue,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calls",
    )
    answered_by = models.CharField(
        _("answered by"),
        max_length=20,
        blank=True,
        help_text=_("human, machine, or fax"),
    )
    forwarded_from = models.CharField(
        _("forwarded from"),
        max_length=20,
        blank=True,
    )
    caller_name = models.CharField(
        _("caller name"),
        max_length=100,
        blank=True,
    )
    duration = models.IntegerField(
        _("duration"),
        default=0,
        help_text=_("Call duration in seconds"),
    )
    queue_time = models.IntegerField(
        _("queue time"),
        default=0,
        help_text=_("Time spent in queue in seconds"),
    )
    price = models.DecimalField(
        _("price"),
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=_("Call cost in account currency"),
    )
    price_unit = models.CharField(
        _("price unit"),
        max_length=10,
        blank=True,
        default="USD",
    )
    start_time = models.DateTimeField(
        _("start time"),
        null=True,
        blank=True,
    )
    end_time = models.DateTimeField(
        _("end time"),
        null=True,
        blank=True,
    )
    answered_at = models.DateTimeField(
        _("answered at"),
        null=True,
        blank=True,
    )
    is_recorded = models.BooleanField(
        _("recorded"),
        default=False,
    )
    recording_url = models.URLField(
        _("recording URL"),
        blank=True,
    )
    transcription_text = models.TextField(
        _("transcription"),
        blank=True,
    )
    voicemail_url = models.URLField(
        _("voicemail URL"),
        blank=True,
    )
    conference_sid = models.CharField(
        _("conference SID"),
        max_length=50,
        blank=True,
        help_text=_("SID of conference if call is part of a conference"),
    )
    callback_source = models.CharField(
        _("callback source"),
        max_length=20,
        blank=True,
    )
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
        blank=True,
    )

    class Meta:
        verbose_name = _("Call")
        verbose_name_plural = _("Calls")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["twilio_sid"]),
            models.Index(fields=["status", "direction"]),
            models.Index(fields=["from_number", "to_number"]),
            models.Index(fields=["created_at", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.direction} call {self.twilio_sid}"


class CallRecording(TimeStampedModel):
    """Model for call recordings."""

    class Status(models.TextChoices):
        """Recording status choices."""

        IN_PROGRESS = "in-progress", _("In Progress")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")
        DELETED = "deleted", _("Deleted")

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    call = models.ForeignKey(
        Call,
        on_delete=models.CASCADE,
        related_name="recordings",
    )
    twilio_sid = models.CharField(
        _("Twilio Recording SID"),
        max_length=50,
        unique=True,
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )
    duration = models.IntegerField(
        _("duration"),
        default=0,
        help_text=_("Recording duration in seconds"),
    )
    channels = models.IntegerField(
        _("channels"),
        default=1,
        help_text=_("Number of audio channels"),
    )
    source = models.CharField(
        _("source"),
        max_length=20,
        help_text=_("Recording source (e.g., RecordVerb, DialVerb)"),
    )
    url = models.URLField(
        _("recording URL"),
        blank=True,
    )
    file_size = models.IntegerField(
        _("file size"),
        null=True,
        blank=True,
        help_text=_("File size in bytes"),
    )
    price = models.DecimalField(
        _("price"),
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
    )
    price_unit = models.CharField(
        _("price unit"),
        max_length=10,
        blank=True,
        default="USD",
    )
    encryption_details = models.JSONField(
        _("encryption details"),
        default=dict,
        blank=True,
    )
    transcription = models.TextField(
        _("transcription"),
        blank=True,
    )
    transcription_status = models.CharField(
        _("transcription status"),
        max_length=20,
        blank=True,
    )
    deleted_at = models.DateTimeField(
        _("deleted at"),
        null=True,
        blank=True,
    )
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
        blank=True,
    )

    class Meta:
        verbose_name = _("Call Recording")
        verbose_name_plural = _("Call Recordings")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["twilio_sid"]),
            models.Index(fields=["call", "status"]),
        ]

    def __str__(self) -> str:
        return f"Recording {self.twilio_sid} for {self.call.twilio_sid}"


class CallLog(TimeStampedModel):
    """Model for detailed call event logs."""

    class EventType(models.TextChoices):
        """Call event type choices."""

        INITIATED = "initiated", _("Call Initiated")
        QUEUED = "queued", _("Call Queued")
        RINGING = "ringing", _("Call Ringing")
        ANSWERED = "answered", _("Call Answered")
        CONNECTED = "connected", _("Call Connected")
        HOLD = "hold", _("Call On Hold")
        UNHOLD = "unhold", _("Call Resumed")
        TRANSFER = "transfer", _("Call Transferred")
        CONFERENCE = "conference", _("Call Conferenced")
        COMPLETED = "completed", _("Call Completed")
        FAILED = "failed", _("Call Failed")
        RECORDING_START = "recording_start", _("Recording Started")
        RECORDING_STOP = "recording_stop", _("Recording Stopped")
        VOICEMAIL = "voicemail", _("Voicemail Left")
        DTMF = "dtmf", _("DTMF Input")
        SPEECH = "speech", _("Speech Input")
        ERROR = "error", _("Error Occurred")

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    call = models.ForeignKey(
        Call,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    event_type = models.CharField(
        _("event type"),
        max_length=30,
        choices=EventType.choices,
        db_index=True,
    )
    description = models.TextField(
        _("description"),
        blank=True,
    )
    agent = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="call_logs",
    )
    data = models.JSONField(
        _("event data"),
        default=dict,
        blank=True,
        help_text=_("Additional event-specific data"),
    )
    error_code = models.CharField(
        _("error code"),
        max_length=20,
        blank=True,
    )
    error_message = models.TextField(
        _("error message"),
        blank=True,
    )

    class Meta:
        verbose_name = _("Call Log")
        verbose_name_plural = _("Call Logs")
        ordering = ["call", "created_at"]
        indexes = [
            models.Index(fields=["call", "event_type"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} - {self.call.twilio_sid} at {self.created_at}"
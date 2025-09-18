"""DRF serializers for django-twilio-call models."""

from typing import Any, Dict

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Agent, Call, CallLog, CallRecording, PhoneNumber, Queue

User = get_user_model()


class PhoneNumberSerializer(serializers.ModelSerializer):
    """Serializer for PhoneNumber model."""

    class Meta:
        model = PhoneNumber
        fields = [
            "id",
            "public_id",
            "twilio_sid",
            "phone_number",
            "friendly_name",
            "number_type",
            "capabilities",
            "is_active",
            "monthly_cost",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "twilio_sid", "created_at", "updated_at"]


class QueueSerializer(serializers.ModelSerializer):
    """Serializer for Queue model."""

    agent_count = serializers.IntegerField(read_only=True)
    active_calls_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Queue
        fields = [
            "id",
            "public_id",
            "name",
            "description",
            "routing_strategy",
            "priority",
            "max_size",
            "timeout_seconds",
            "music_url",
            "announcement_url",
            "is_active",
            "required_skills",
            "business_hours",
            "metadata",
            "agent_count",
            "active_calls_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]

    def to_representation(self, instance):
        """Add computed fields to representation."""
        data = super().to_representation(instance)
        data["agent_count"] = instance.agents.filter(is_active=True).count()
        data["active_calls_count"] = instance.calls.filter(
            status__in=[Call.Status.QUEUED, Call.Status.RINGING, Call.Status.IN_PROGRESS]
        ).count()
        return data


class QueueSummarySerializer(serializers.ModelSerializer):
    """Lightweight serializer for Queue model."""

    class Meta:
        model = Queue
        fields = ["id", "public_id", "name", "priority", "is_active"]
        read_only_fields = ["id", "public_id"]


class AgentSerializer(serializers.ModelSerializer):
    """Serializer for Agent model."""

    user = serializers.SerializerMethodField()
    queues = QueueSummarySerializer(many=True, read_only=True)
    queue_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Queue.objects.all(),
        source="queues",
        write_only=True,
        required=False,
    )
    is_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Agent
        fields = [
            "id",
            "public_id",
            "user",
            "extension",
            "status",
            "phone_number",
            "skills",
            "queues",
            "queue_ids",
            "is_active",
            "is_available",
            "max_concurrent_calls",
            "last_status_change",
            "total_talk_time",
            "calls_handled_today",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "is_available",
            "last_status_change",
            "total_talk_time",
            "calls_handled_today",
            "created_at",
            "updated_at",
        ]

    def get_user(self, obj):
        """Return user information."""
        return {
            "id": obj.user.id,
            "username": obj.user.username,
            "email": obj.user.email,
            "first_name": obj.user.first_name,
            "last_name": obj.user.last_name,
            "full_name": obj.user.get_full_name(),
        }


class AgentStatusUpdateSerializer(serializers.Serializer):
    """Serializer for updating agent status."""

    status = serializers.ChoiceField(choices=Agent.Status.choices)


class CallSerializer(serializers.ModelSerializer):
    """Serializer for Call model."""

    agent = AgentSerializer(read_only=True)
    queue = QueueSummarySerializer(read_only=True)
    phone_number_used = PhoneNumberSerializer(read_only=True)
    duration_formatted = serializers.SerializerMethodField()

    class Meta:
        model = Call
        fields = [
            "id",
            "public_id",
            "twilio_sid",
            "parent_call_sid",
            "account_sid",
            "from_number",
            "from_formatted",
            "to_number",
            "to_formatted",
            "phone_number_used",
            "direction",
            "status",
            "agent",
            "queue",
            "answered_by",
            "forwarded_from",
            "caller_name",
            "duration",
            "duration_formatted",
            "queue_time",
            "price",
            "price_unit",
            "start_time",
            "end_time",
            "answered_at",
            "is_recorded",
            "recording_url",
            "transcription_text",
            "voicemail_url",
            "conference_sid",
            "callback_source",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "twilio_sid",
            "parent_call_sid",
            "account_sid",
            "duration",
            "queue_time",
            "price",
            "price_unit",
            "start_time",
            "end_time",
            "answered_at",
            "created_at",
            "updated_at",
        ]

    def get_duration_formatted(self, obj):
        """Return formatted duration string."""
        if not obj.duration:
            return None
        minutes, seconds = divmod(obj.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"


class CallCreateSerializer(serializers.Serializer):
    """Serializer for creating outbound calls."""

    to_number = serializers.CharField(max_length=20)
    from_number = serializers.CharField(max_length=20, required=False)
    agent_id = serializers.IntegerField(required=False)
    queue_id = serializers.IntegerField(required=False)
    url = serializers.URLField(required=False)
    twiml = serializers.CharField(required=False)
    metadata = serializers.JSONField(required=False, default=dict)

    # Twilio parameters
    method = serializers.ChoiceField(choices=["GET", "POST"], default="POST", required=False)
    fallback_url = serializers.URLField(required=False)
    status_callback = serializers.URLField(required=False)
    record = serializers.BooleanField(default=False, required=False)
    recording_channels = serializers.ChoiceField(
        choices=["mono", "dual"], default="mono", required=False
    )
    recording_status_callback = serializers.URLField(required=False)
    send_digits = serializers.CharField(max_length=255, required=False)
    timeout = serializers.IntegerField(min_value=1, max_value=600, default=30, required=False)
    time_limit = serializers.IntegerField(min_value=1, max_value=14400, required=False)

    def validate(self, attrs):
        """Validate call creation data."""
        if not attrs.get("url") and not attrs.get("twiml"):
            raise serializers.ValidationError(
                "Either 'url' or 'twiml' must be provided for call instructions."
            )
        return attrs


class CallTransferSerializer(serializers.Serializer):
    """Serializer for transferring calls."""

    to_number = serializers.CharField(max_length=20, required=False)
    to_agent_id = serializers.IntegerField(required=False)
    to_queue_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        """Validate transfer data."""
        if not any([attrs.get("to_number"), attrs.get("to_agent_id"), attrs.get("to_queue_id")]):
            raise serializers.ValidationError(
                "One of 'to_number', 'to_agent_id', or 'to_queue_id' must be provided."
            )
        return attrs


class CallControlSerializer(serializers.Serializer):
    """Serializer for call control operations."""

    action = serializers.ChoiceField(
        choices=["hold", "unhold", "mute", "unmute", "end"],
        required=True,
    )
    hold_music_url = serializers.URLField(required=False)
    resume_url = serializers.URLField(required=False)


class CallRecordingSerializer(serializers.ModelSerializer):
    """Serializer for CallRecording model."""

    call = serializers.StringRelatedField()

    class Meta:
        model = CallRecording
        fields = [
            "id",
            "public_id",
            "call",
            "twilio_sid",
            "status",
            "duration",
            "channels",
            "source",
            "url",
            "file_size",
            "price",
            "price_unit",
            "encryption_details",
            "transcription",
            "transcription_status",
            "deleted_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "twilio_sid",
            "duration",
            "file_size",
            "price",
            "price_unit",
            "created_at",
            "updated_at",
        ]


class CallLogSerializer(serializers.ModelSerializer):
    """Serializer for CallLog model."""

    agent = AgentSerializer(read_only=True)

    class Meta:
        model = CallLog
        fields = [
            "id",
            "public_id",
            "call",
            "event_type",
            "description",
            "agent",
            "data",
            "error_code",
            "error_message",
            "created_at",
        ]
        read_only_fields = ["id", "public_id", "created_at"]


class WebhookDataSerializer(serializers.Serializer):
    """Serializer for Twilio webhook data."""

    CallSid = serializers.CharField()
    AccountSid = serializers.CharField()
    From = serializers.CharField()
    To = serializers.CharField()
    CallStatus = serializers.CharField()
    Direction = serializers.CharField(required=False)
    Duration = serializers.CharField(required=False)
    CallDuration = serializers.CharField(required=False)
    RecordingSid = serializers.CharField(required=False)
    RecordingUrl = serializers.URLField(required=False)
    RecordingStatus = serializers.CharField(required=False)
    RecordingDuration = serializers.CharField(required=False)
    Digits = serializers.CharField(required=False)
    SpeechResult = serializers.CharField(required=False)
    Confidence = serializers.CharField(required=False)

    # Additional optional fields
    CallerName = serializers.CharField(required=False)
    ForwardedFrom = serializers.CharField(required=False)
    ParentCallSid = serializers.CharField(required=False)
    ConferenceSid = serializers.CharField(required=False)
    QueueTime = serializers.CharField(required=False)
    QueueResult = serializers.CharField(required=False)


class QueueStatisticsSerializer(serializers.Serializer):
    """Serializer for queue statistics."""

    queue_id = serializers.IntegerField()
    queue_name = serializers.CharField()
    is_active = serializers.BooleanField()
    calls_in_queue = serializers.IntegerField()
    max_size = serializers.IntegerField()
    available_agents = serializers.IntegerField()
    total_agents = serializers.IntegerField()
    avg_wait_time = serializers.FloatField()
    max_wait_time = serializers.FloatField()
    routing_strategy = serializers.CharField()


class CallPositionSerializer(serializers.Serializer):
    """Serializer for call position in queue."""

    position = serializers.IntegerField()
    estimated_wait_time = serializers.IntegerField()
    queue_name = serializers.CharField()
    queue_size = serializers.IntegerField()
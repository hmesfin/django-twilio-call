"""DRF serializers for django-twilio-call models with enhanced validation."""

import re
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework import serializers

from .models import Agent, Call, CallLog, CallRecording, PhoneNumber, Queue
from .constants import DefaultValues, Limits
from .security import InputValidator

User = get_user_model()


class PhoneNumberSerializer(serializers.ModelSerializer):
    """Serializer for PhoneNumber model with validation."""

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

    def validate_phone_number(self, value):
        """Validate and normalize phone number."""
        try:
            return InputValidator.validate_phone_number(value)
        except ValidationError as e:
            raise serializers.ValidationError(str(e))

    def validate_friendly_name(self, value):
        """Sanitize friendly name to prevent XSS."""
        if value:
            return InputValidator.sanitize_input(value, 'friendly_name')
        return value

    def validate_monthly_cost(self, value):
        """Validate monthly cost is reasonable."""
        if value and value < 0:
            raise serializers.ValidationError("Monthly cost cannot be negative")
        if value and value > 1000:  # Max $1000 per month
            raise serializers.ValidationError("Monthly cost exceeds maximum limit")
        return value


class QueueSerializer(serializers.ModelSerializer):
    """Serializer for Queue model with validation."""

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

    def validate_name(self, value):
        """Validate and sanitize queue name."""
        if not value or not value.strip():
            raise serializers.ValidationError("Queue name is required")
        if len(value) > 100:
            raise serializers.ValidationError("Queue name too long (max 100 characters)")
        # Sanitize to prevent injection
        return InputValidator.sanitize_input(value, 'queue_name')

    def validate_description(self, value):
        """Sanitize description."""
        if value:
            return InputValidator.sanitize_input(value, 'description')
        return value

    def validate_max_size(self, value):
        """Validate queue size limits."""
        if value and value < 1:
            raise serializers.ValidationError("Queue size must be at least 1")
        if value and value > DefaultValues.MAX_QUEUE_SIZE:
            raise serializers.ValidationError(f"Queue size exceeds limit ({DefaultValues.MAX_QUEUE_SIZE})")
        return value

    def validate_timeout_seconds(self, value):
        """Validate timeout is reasonable."""
        if value and value < 30:
            raise serializers.ValidationError("Timeout must be at least 30 seconds")
        if value and value > 3600:  # Max 1 hour
            raise serializers.ValidationError("Timeout cannot exceed 1 hour")
        return value

    def validate_music_url(self, value):
        """Validate music URL format."""
        if value:
            if not value.startswith(('http://', 'https://')):
                raise serializers.ValidationError("Music URL must be a valid HTTP(S) URL")
            if len(value) > 500:
                raise serializers.ValidationError("Music URL too long")
        return value

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
    """Serializer for Agent model with enhanced validation."""

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

    def validate_extension(self, value):
        """Validate agent extension."""
        if value:
            if not value.isdigit():
                raise serializers.ValidationError("Extension must be numeric")
            if len(value) < 3 or len(value) > 6:
                raise serializers.ValidationError("Extension must be 3-6 digits")
        return value

    def validate_phone_number(self, value):
        """Validate agent phone number."""
        if value:
            try:
                return InputValidator.validate_phone_number(value)
            except ValidationError as e:
                raise serializers.ValidationError(str(e))
        return value

    def validate_max_concurrent_calls(self, value):
        """Validate concurrent call limit."""
        if value and value < 1:
            raise serializers.ValidationError("Must handle at least 1 concurrent call")
        if value and value > 10:  # Reasonable limit
            raise serializers.ValidationError("Cannot handle more than 10 concurrent calls")
        return value

    def validate_skills(self, value):
        """Validate and sanitize skills."""
        if value:
            # Ensure skills is a list
            if not isinstance(value, list):
                raise serializers.ValidationError("Skills must be a list")
            # Sanitize each skill
            sanitized_skills = []
            for skill in value:
                if not isinstance(skill, str):
                    raise serializers.ValidationError("Each skill must be a string")
                if len(skill) > 50:
                    raise serializers.ValidationError("Skill name too long (max 50 characters)")
                sanitized = InputValidator.sanitize_input(skill, 'skill')
                sanitized_skills.append(sanitized)
            return sanitized_skills
        return value


class AgentStatusUpdateSerializer(serializers.Serializer):
    """Serializer for updating agent status."""

    status = serializers.ChoiceField(choices=Agent.Status.choices)


class CallSerializer(serializers.ModelSerializer):
    """Serializer for Call model with comprehensive validation."""

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

    def validate_from_number(self, value):
        """Validate from phone number."""
        if value:
            try:
                return InputValidator.validate_phone_number(value)
            except ValidationError as e:
                raise serializers.ValidationError(str(e))
        return value

    def validate_to_number(self, value):
        """Validate to phone number."""
        if value:
            try:
                return InputValidator.validate_phone_number(value)
            except ValidationError as e:
                raise serializers.ValidationError(str(e))
        return value

    def validate_caller_name(self, value):
        """Sanitize caller name."""
        if value:
            if len(value) > 100:
                raise serializers.ValidationError("Caller name too long (max 100 characters)")
            return InputValidator.sanitize_input(value, 'caller_name')
        return value

    def validate_recording_url(self, value):
        """Validate recording URL."""
        if value:
            if not value.startswith(('http://', 'https://')):
                raise serializers.ValidationError("Recording URL must be a valid HTTP(S) URL")
            if len(value) > 500:
                raise serializers.ValidationError("Recording URL too long")
        return value

    def validate_metadata(self, value):
        """Validate metadata JSON."""
        if value:
            # Ensure it's a dictionary
            if not isinstance(value, dict):
                raise serializers.ValidationError("Metadata must be a JSON object")
            # Check size (prevent large payloads)
            import json
            json_str = json.dumps(value)
            if len(json_str) > 10000:  # 10KB limit
                raise serializers.ValidationError("Metadata too large (max 10KB)")
            # Sanitize string values in metadata
            sanitized = {}
            for key, val in value.items():
                if isinstance(val, str):
                    sanitized[key] = InputValidator.sanitize_input(val, f'metadata_{key}')
                else:
                    sanitized[key] = val
            return sanitized
        return value


class CallCreateSerializer(serializers.Serializer):
    """Serializer for creating outbound calls with validation."""

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
    recording_channels = serializers.ChoiceField(choices=["mono", "dual"], default="mono", required=False)
    recording_status_callback = serializers.URLField(required=False)
    send_digits = serializers.CharField(max_length=255, required=False)
    timeout = serializers.IntegerField(min_value=1, max_value=600, default=DefaultValues.RECORDING_TIMEOUT, required=False)
    time_limit = serializers.IntegerField(min_value=1, max_value=14400, required=False)

    def validate_to_number(self, value):
        """Validate to phone number."""
        try:
            return InputValidator.validate_phone_number(value)
        except ValidationError as e:
            raise serializers.ValidationError(str(e))

    def validate_from_number(self, value):
        """Validate from phone number."""
        if value:
            try:
                return InputValidator.validate_phone_number(value)
            except ValidationError as e:
                raise serializers.ValidationError(str(e))
        return value

    def validate_send_digits(self, value):
        """Validate DTMF digits."""
        if value:
            if not re.match(r'^[0-9*#wW]+$', value):
                raise serializers.ValidationError("Send digits can only contain 0-9, *, #, w, or W")
        return value

    def validate_twiml(self, value):
        """Validate and sanitize TwiML."""
        if value:
            # Basic XML validation
            if '<' in value and '>' in value:
                # Check for potential script tags
                if re.search(r'<script[^>]*>', value, re.IGNORECASE):
                    raise serializers.ValidationError("Script tags not allowed in TwiML")
                # Check for javascript: protocol
                if 'javascript:' in value.lower():
                    raise serializers.ValidationError("JavaScript protocol not allowed in TwiML")
        return value

    def validate(self, attrs):
        """Validate call creation data."""
        if not attrs.get("url") and not attrs.get("twiml"):
            raise serializers.ValidationError("Either 'url' or 'twiml' must be provided for call instructions.")

        # Validate metadata size
        if attrs.get('metadata'):
            import json
            json_str = json.dumps(attrs['metadata'])
            if len(json_str) > 10000:  # 10KB limit
                raise serializers.ValidationError("Metadata too large (max 10KB)")

        return attrs


class CallTransferSerializer(serializers.Serializer):
    """Serializer for transferring calls."""

    to_number = serializers.CharField(max_length=20, required=False)
    to_agent_id = serializers.IntegerField(required=False)
    to_queue_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        """Validate transfer data."""
        if not any([attrs.get("to_number"), attrs.get("to_agent_id"), attrs.get("to_queue_id")]):
            raise serializers.ValidationError("One of 'to_number', 'to_agent_id', or 'to_queue_id' must be provided.")
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

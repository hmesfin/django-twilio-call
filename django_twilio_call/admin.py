"""Django admin configurations for django-twilio-call models."""

from django.contrib import admin
from django.db.models import Count, Q
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Agent, Call, CallLog, CallRecording, PhoneNumber, Queue


@admin.register(PhoneNumber)
class PhoneNumberAdmin(admin.ModelAdmin):
    """Admin configuration for PhoneNumber model."""

    list_display = [
        "phone_number",
        "friendly_name",
        "number_type",
        "is_active",
        "monthly_cost",
        "created_at",
    ]
    list_filter = ["number_type", "is_active", "created_at"]
    search_fields = ["phone_number", "friendly_name", "twilio_sid"]
    readonly_fields = ["id", "public_id", "twilio_sid", "created_at", "updated_at"]
    fieldsets = (
        (None, {"fields": ("id", "public_id", "twilio_sid", "phone_number", "friendly_name")}),
        (
            _("Configuration"),
            {"fields": ("number_type", "capabilities", "is_active", "monthly_cost")},
        ),
        (_("Metadata"), {"fields": ("metadata",), "classes": ("collapse",)}),
        (_("Timestamps"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Queue)
class QueueAdmin(admin.ModelAdmin):
    """Admin configuration for Queue model."""

    list_display = [
        "name",
        "routing_strategy",
        "priority",
        "max_size",
        "is_active",
        "agent_count",
        "created_at",
    ]
    list_filter = ["routing_strategy", "is_active", "priority"]
    search_fields = ["name", "description"]
    readonly_fields = ["id", "public_id", "created_at", "updated_at", "agent_count"]
    filter_horizontal = ["agents"]
    fieldsets = (
        (None, {"fields": ("id", "public_id", "name", "description")}),
        (
            _("Routing Configuration"),
            {
                "fields": (
                    "routing_strategy",
                    "priority",
                    "max_size",
                    "timeout_seconds",
                    "required_skills",
                )
            },
        ),
        (
            _("Audio Settings"),
            {"fields": ("music_url", "announcement_url"), "classes": ("collapse",)},
        ),
        (
            _("Schedule"),
            {"fields": ("business_hours", "is_active"), "classes": ("collapse",)},
        ),
        (_("Metadata"), {"fields": ("metadata",), "classes": ("collapse",)}),
        (_("Timestamps"), {"fields": ("created_at", "updated_at")}),
    )

    def agent_count(self, obj):
        """Return the number of agents assigned to this queue."""
        return obj.agents.count()

    agent_count.short_description = _("Assigned Agents")


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    """Admin configuration for Agent model."""

    list_display = [
        "user_full_name",
        "extension",
        "status",
        "status_indicator",
        "is_active",
        "calls_handled_today",
        "last_status_change",
    ]
    list_filter = ["status", "is_active", "last_status_change"]
    search_fields = ["user__username", "user__email", "extension", "phone_number"]
    readonly_fields = [
        "id",
        "public_id",
        "last_status_change",
        "total_talk_time",
        "calls_handled_today",
        "created_at",
        "updated_at",
    ]
    filter_horizontal = ["queues"]
    actions = ["set_available", "set_offline", "reset_daily_stats"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "public_id",
                    "user",
                    "extension",
                    "phone_number",
                )
            },
        ),
        (
            _("Status"),
            {
                "fields": (
                    "status",
                    "is_active",
                    "last_status_change",
                )
            },
        ),
        (
            _("Configuration"),
            {
                "fields": (
                    "skills",
                    "queues",
                    "max_concurrent_calls",
                )
            },
        ),
        (
            _("Statistics"),
            {
                "fields": (
                    "total_talk_time",
                    "calls_handled_today",
                ),
                "classes": ("collapse",),
            },
        ),
        (_("Metadata"), {"fields": ("metadata",), "classes": ("collapse",)}),
        (_("Timestamps"), {"fields": ("created_at", "updated_at")}),
    )

    def user_full_name(self, obj):
        """Return the agent's full name."""
        return obj.user.get_full_name() or obj.user.username

    user_full_name.short_description = _("Agent Name")
    user_full_name.admin_order_field = "user__first_name"

    def status_indicator(self, obj):
        """Return a colored status indicator."""
        colors = {
            "available": "green",
            "busy": "orange",
            "on_break": "yellow",
            "after_call_work": "blue",
            "offline": "gray",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="color: {};">●</span> {}',
            color,
            obj.get_status_display(),
        )

    status_indicator.short_description = _("Status")

    def set_available(self, request, queryset):
        """Set selected agents to available status."""
        updated = queryset.update(status=Agent.Status.AVAILABLE)
        self.message_user(request, f"{updated} agents set to available.")

    set_available.short_description = _("Set status to Available")

    def set_offline(self, request, queryset):
        """Set selected agents to offline status."""
        updated = queryset.update(status=Agent.Status.OFFLINE)
        self.message_user(request, f"{updated} agents set to offline.")

    set_offline.short_description = _("Set status to Offline")

    def reset_daily_stats(self, request, queryset):
        """Reset daily statistics for selected agents."""
        updated = queryset.update(calls_handled_today=0)
        self.message_user(request, f"Daily stats reset for {updated} agents.")

    reset_daily_stats.short_description = _("Reset daily statistics")


class CallRecordingInline(admin.TabularInline):
    """Inline admin for call recordings."""

    model = CallRecording
    extra = 0
    readonly_fields = ["twilio_sid", "status", "duration", "url", "created_at"]
    fields = ["twilio_sid", "status", "duration", "url", "created_at"]


class CallLogInline(admin.TabularInline):
    """Inline admin for call logs."""

    model = CallLog
    extra = 0
    readonly_fields = ["event_type", "description", "agent", "created_at"]
    fields = ["event_type", "description", "agent", "created_at"]


@admin.register(Call)
class CallAdmin(admin.ModelAdmin):
    """Admin configuration for Call model."""

    list_display = [
        "twilio_sid_short",
        "direction_indicator",
        "from_number",
        "to_number",
        "status",
        "agent",
        "duration_formatted",
        "created_at",
    ]
    list_filter = [
        "direction",
        "status",
        "is_recorded",
        "created_at",
        "queue",
    ]
    search_fields = [
        "twilio_sid",
        "from_number",
        "to_number",
        "caller_name",
    ]
    readonly_fields = [
        "id",
        "public_id",
        "twilio_sid",
        "account_sid",
        "duration",
        "price",
        "created_at",
        "updated_at",
    ]
    inlines = [CallRecordingInline, CallLogInline]
    date_hierarchy = "created_at"
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "public_id",
                    "twilio_sid",
                    "parent_call_sid",
                    "account_sid",
                )
            },
        ),
        (
            _("Call Details"),
            {
                "fields": (
                    "direction",
                    "status",
                    "from_number",
                    "from_formatted",
                    "to_number",
                    "to_formatted",
                    "phone_number_used",
                    "caller_name",
                )
            },
        ),
        (
            _("Routing"),
            {
                "fields": (
                    "agent",
                    "queue",
                    "answered_by",
                    "forwarded_from",
                )
            },
        ),
        (
            _("Timing"),
            {
                "fields": (
                    "start_time",
                    "answered_at",
                    "end_time",
                    "duration",
                    "queue_time",
                )
            },
        ),
        (
            _("Recording & Transcription"),
            {
                "fields": (
                    "is_recorded",
                    "recording_url",
                    "transcription_text",
                    "voicemail_url",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            _("Conference"),
            {
                "fields": ("conference_sid",),
                "classes": ("collapse",),
            },
        ),
        (
            _("Billing"),
            {
                "fields": ("price", "price_unit"),
                "classes": ("collapse",),
            },
        ),
        (_("Metadata"), {"fields": ("metadata",), "classes": ("collapse",)}),
        (_("Timestamps"), {"fields": ("created_at", "updated_at")}),
    )

    def twilio_sid_short(self, obj):
        """Return shortened Twilio SID."""
        return obj.twilio_sid[:15] + "..." if len(obj.twilio_sid) > 15 else obj.twilio_sid

    twilio_sid_short.short_description = _("Call SID")

    def direction_indicator(self, obj):
        """Return a direction indicator with icon."""
        if obj.direction == "inbound":
            return format_html('<span style="color: green;">↓</span> Inbound')
        return format_html('<span style="color: blue;">↑</span> Outbound')

    direction_indicator.short_description = _("Direction")

    def duration_formatted(self, obj):
        """Return formatted duration."""
        if obj.duration == 0:
            return "-"
        minutes, seconds = divmod(obj.duration, 60)
        return f"{minutes}:{seconds:02d}"

    duration_formatted.short_description = _("Duration")


@admin.register(CallRecording)
class CallRecordingAdmin(admin.ModelAdmin):
    """Admin configuration for CallRecording model."""

    list_display = [
        "twilio_sid",
        "call",
        "status",
        "duration",
        "file_size",
        "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = ["twilio_sid", "call__twilio_sid"]
    readonly_fields = [
        "id",
        "public_id",
        "twilio_sid",
        "duration",
        "file_size",
        "url",
        "created_at",
        "updated_at",
    ]
    fieldsets = (
        (None, {"fields": ("id", "public_id", "call", "twilio_sid", "status")}),
        (
            _("Recording Details"),
            {
                "fields": (
                    "duration",
                    "channels",
                    "source",
                    "url",
                    "file_size",
                )
            },
        ),
        (
            _("Transcription"),
            {
                "fields": ("transcription", "transcription_status"),
                "classes": ("collapse",),
            },
        ),
        (
            _("Billing"),
            {
                "fields": ("price", "price_unit"),
                "classes": ("collapse",),
            },
        ),
        (
            _("Security"),
            {
                "fields": ("encryption_details", "deleted_at"),
                "classes": ("collapse",),
            },
        ),
        (_("Metadata"), {"fields": ("metadata",), "classes": ("collapse",)}),
        (_("Timestamps"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(CallLog)
class CallLogAdmin(admin.ModelAdmin):
    """Admin configuration for CallLog model."""

    list_display = [
        "call",
        "event_type",
        "agent",
        "description",
        "created_at",
    ]
    list_filter = ["event_type", "created_at"]
    search_fields = ["call__twilio_sid", "description", "error_message"]
    readonly_fields = ["id", "public_id", "created_at", "updated_at"]
    date_hierarchy = "created_at"
    fieldsets = (
        (None, {"fields": ("id", "public_id", "call", "event_type", "agent")}),
        (_("Event Details"), {"fields": ("description", "data")}),
        (
            _("Error Information"),
            {
                "fields": ("error_code", "error_message"),
                "classes": ("collapse",),
            },
        ),
        (_("Timestamps"), {"fields": ("created_at", "updated_at")}),
    )
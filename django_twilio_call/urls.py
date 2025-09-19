"""URL routing for django-twilio-call."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ActiveCallsView,
    AgentAnalyticsView,
    AgentsSummaryView,
    AgentViewSet,
    AvailableAgentsView,
    CallAnalyticsView,
    CallbackStatsView,
    CallbackView,
    CallViewSet,
    ConferenceDetailView,
    ConferenceParticipantView,
    ConferenceView,
    IVRFlowDetailView,
    IVRFlowView,
    PhoneNumberViewSet,
    QueueAnalyticsView,
    QueueViewSet,
    RealTimeMetricsView,
    RecordingComplianceView,
    RecordingView,
    ReportEmailView,
    ReportGenerationView,
    ReportScheduleView,
)
from .webhooks.handlers import (
    IVRMenuView,
    QueueWaitView,
    RecordingCallbackView,
    StatusCallbackView,
    VoiceWebhookView,
)

app_name = "django_twilio_call"

# Create router for ViewSets
router = DefaultRouter()
router.register(r"phone-numbers", PhoneNumberViewSet, basename="phonenumber")
router.register(r"queues", QueueViewSet, basename="queue")
router.register(r"agents", AgentViewSet, basename="agent")
router.register(r"calls", CallViewSet, basename="call")

# API URLs
api_urlpatterns = [
    path("", include(router.urls)),
    path("active-calls/", ActiveCallsView.as_view(), name="active-calls"),
    path("callbacks/", CallbackView.as_view(), name="callbacks"),
    path("callbacks/stats/", CallbackStatsView.as_view(), name="callback-stats"),
    path("agents/available/", AvailableAgentsView.as_view(), name="available-agents"),
    path("agents/summary/", AgentsSummaryView.as_view(), name="agents-summary"),
    # Recording endpoints
    path("recordings/", RecordingView.as_view(), name="recordings"),
    path("recordings/compliance/", RecordingComplianceView.as_view(), name="recording-compliance"),
    # Conference endpoints
    path("conferences/", ConferenceView.as_view(), name="conferences"),
    path("conferences/<str:conference_name>/", ConferenceDetailView.as_view(), name="conference-detail"),
    path(
        "conferences/<str:conference_name>/participants/",
        ConferenceParticipantView.as_view(),
        name="conference-participants",
    ),
    # IVR Flow endpoints
    path("ivr-flows/", IVRFlowView.as_view(), name="ivr-flows"),
    path("ivr-flows/<str:flow_name>/", IVRFlowDetailView.as_view(), name="ivr-flow-detail"),
    # Analytics endpoints
    path("analytics/calls/", CallAnalyticsView.as_view(), name="call-analytics"),
    path("analytics/agents/", AgentAnalyticsView.as_view(), name="agent-analytics"),
    path("analytics/queues/", QueueAnalyticsView.as_view(), name="queue-analytics"),
    path("analytics/real-time/", RealTimeMetricsView.as_view(), name="real-time-metrics"),
    # Reporting endpoints
    path("reports/generate/", ReportGenerationView.as_view(), name="report-generate"),
    path("reports/schedule/", ReportScheduleView.as_view(), name="report-schedule"),
    path("reports/email/", ReportEmailView.as_view(), name="report-email"),
]

# Webhook URLs
webhook_urlpatterns = [
    path("voice/", VoiceWebhookView.as_view(), name="webhook-voice"),
    path("status/", StatusCallbackView.as_view(), name="webhook-status"),
    path("recording/", RecordingCallbackView.as_view(), name="webhook-recording"),
    path("ivr/", IVRMenuView.as_view(), name="webhook-ivr"),
    path("queue/wait/", QueueWaitView.as_view(), name="webhook-queue-wait"),
]

# Main URL patterns
urlpatterns = [
    path("api/v1/", include(api_urlpatterns)),
    path("webhooks/", include(webhook_urlpatterns)),
    path("", include("django_twilio_call.urls.health_urls")),
]

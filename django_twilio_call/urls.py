"""URL routing for django-twilio-call."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ActiveCallsView,
    AgentViewSet,
    CallbackStatsView,
    CallbackView,
    CallViewSet,
    PhoneNumberViewSet,
    QueueViewSet,
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
]
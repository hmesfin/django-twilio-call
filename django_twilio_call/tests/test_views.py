"""Integration tests for API views."""

from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from ..models import Agent, Call, Queue
from .factories import AgentFactory, CallFactory, QueueFactory, UserFactory

User = get_user_model()


class BaseAPITestCase(TestCase):
    """Base test case for API tests."""

    def setUp(self):
        """Set up test client and authentication."""
        self.client = APIClient()
        self.user = UserFactory(username="testuser")
        self.client.force_authenticate(user=self.user)

        # Create supervisor user
        self.supervisor = UserFactory(username="supervisor", is_staff=True)


class PhoneNumberViewSetTest(BaseAPITestCase):
    """Tests for PhoneNumberViewSet."""

    def test_list_phone_numbers(self):
        """Test listing phone numbers."""
        url = reverse("django_twilio_call:phonenumber-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)

    @patch("django_twilio_call.services.twilio_service.client")
    def test_verify_phone_number(self, mock_twilio_client):
        """Test verifying phone number."""
        mock_twilio_client.lookups.v1.phone_numbers.return_value.fetch.return_value = Mock(
            phone_number="+1234567890",
            country_code="US",
            national_format="(123) 456-7890",
        )

        url = reverse("django_twilio_call:phonenumber-verify")
        data = {"number": "+1234567890"}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["valid"])


class QueueViewSetTest(BaseAPITestCase):
    """Tests for QueueViewSet."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.queue = QueueFactory(name="test_queue")

    def test_list_queues(self):
        """Test listing queues."""
        url = reverse("django_twilio_call:queue-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_create_queue(self):
        """Test creating a queue."""
        url = reverse("django_twilio_call:queue-list")
        data = {
            "name": "new_queue",
            "description": "New test queue",
            "priority": 5,
            "max_size": 50,
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Queue.objects.count(), 2)

    def test_get_queue_metrics(self):
        """Test getting queue metrics."""
        # Add some calls to the queue
        CallFactory(queue=self.queue, status=Call.Status.QUEUED)
        CallFactory(queue=self.queue, status=Call.Status.QUEUED)

        url = reverse("django_twilio_call:queue-metrics", kwargs={"pk": self.queue.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["queue_size"], 2)
        self.assertIn("avg_wait_time", response.data)

    def test_clear_queue(self):
        """Test clearing a queue."""
        # Add calls to queue
        CallFactory(queue=self.queue, status=Call.Status.QUEUED)
        CallFactory(queue=self.queue, status=Call.Status.QUEUED)

        # Authenticate as supervisor
        self.client.force_authenticate(user=self.supervisor)

        url = reverse("django_twilio_call:queue-clear", kwargs={"pk": self.queue.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Call.objects.filter(queue=self.queue, status=Call.Status.QUEUED).count(), 0)


class AgentViewSetTest(BaseAPITestCase):
    """Tests for AgentViewSet."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.agent = AgentFactory(user=self.user, extension="1001")

    def test_list_agents(self):
        """Test listing agents."""
        url = reverse("django_twilio_call:agent-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_agent_login(self):
        """Test agent login."""
        url = reverse("django_twilio_call:agent-login", kwargs={"pk": self.agent.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.status, Agent.Status.AVAILABLE)

    def test_agent_logout(self):
        """Test agent logout."""
        self.agent.status = Agent.Status.AVAILABLE
        self.agent.save()

        url = reverse("django_twilio_call:agent-logout", kwargs={"pk": self.agent.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.status, Agent.Status.OFFLINE)

    def test_set_agent_status(self):
        """Test setting agent status."""
        url = reverse("django_twilio_call:agent-set-status", kwargs={"pk": self.agent.pk})
        data = {"status": Agent.Status.ON_BREAK}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.status, Agent.Status.ON_BREAK)

    def test_get_agent_statistics(self):
        """Test getting agent statistics."""
        # Add some calls
        CallFactory(agent=self.agent, status=Call.Status.COMPLETED, duration=120)
        CallFactory(agent=self.agent, status=Call.Status.COMPLETED, duration=180)

        url = reverse("django_twilio_call:agent-statistics", kwargs={"pk": self.agent.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_calls"], 2)


class CallViewSetTest(BaseAPITestCase):
    """Tests for CallViewSet."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.agent = AgentFactory(user=self.user)
        self.call = CallFactory(agent=self.agent)

    def test_list_calls(self):
        """Test listing calls."""
        url = reverse("django_twilio_call:call-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    @patch("django_twilio_call.services.call_service.twilio_service")
    def test_initiate_call(self, mock_twilio):
        """Test initiating a call."""
        mock_twilio.make_call.return_value = Mock(sid="CA123456")

        url = reverse("django_twilio_call:call-initiate")
        data = {
            "to_number": "+1234567890",
            "from_number": "+0987654321",
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Call.objects.count(), 2)

    @patch("django_twilio_call.services.call_service.twilio_service")
    def test_transfer_call(self, mock_twilio):
        """Test transferring a call."""
        mock_twilio.transfer_call.return_value = True

        target_agent = AgentFactory(extension="1002")
        self.call.status = Call.Status.IN_PROGRESS
        self.call.save()

        url = reverse("django_twilio_call:call-transfer", kwargs={"pk": self.call.pk})
        data = {"agent_id": target_agent.id}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_hold_call(self):
        """Test putting call on hold."""
        self.call.status = Call.Status.IN_PROGRESS
        self.call.save()

        url = reverse("django_twilio_call:call-hold", kwargs={"pk": self.call.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, Call.Status.ON_HOLD)


class ActiveCallsViewTest(BaseAPITestCase):
    """Tests for ActiveCallsView."""

    def test_get_active_calls(self):
        """Test getting active calls."""
        # Create active calls
        CallFactory(status=Call.Status.IN_PROGRESS)
        CallFactory(status=Call.Status.RINGING)
        CallFactory(status=Call.Status.COMPLETED)  # Not active

        url = reverse("django_twilio_call:active-calls")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)


class CallAnalyticsViewTest(BaseAPITestCase):
    """Tests for analytics views."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.queue = QueueFactory()
        self.agent = AgentFactory()

        # Create sample calls
        CallFactory(
            queue=self.queue,
            agent=self.agent,
            status=Call.Status.COMPLETED,
            duration=120,
        )
        CallFactory(
            queue=self.queue,
            status=Call.Status.ABANDONED,
        )

    def test_get_call_analytics(self):
        """Test getting call analytics."""
        url = reverse("django_twilio_call:call-analytics")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("volume", response.data)
        self.assertIn("performance", response.data)

    def test_get_agent_analytics(self):
        """Test getting agent analytics."""
        url = reverse("django_twilio_call:agent-analytics")
        response = self.client.get(url, {"agent_id": self.agent.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("agents", response.data)

    def test_get_real_time_metrics(self):
        """Test getting real-time metrics."""
        url = reverse("django_twilio_call:real-time-metrics")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("current_activity", response.data)
        self.assertIn("agents", response.data)


class ReportGenerationViewTest(BaseAPITestCase):
    """Tests for report generation."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        # Use supervisor for report access
        self.client.force_authenticate(user=self.supervisor)

        # Create sample data
        CallFactory(status=Call.Status.COMPLETED)
        CallFactory(status=Call.Status.ABANDONED)

    def test_generate_json_report(self):
        """Test generating JSON report."""
        url = reverse("django_twilio_call:report-generate")
        data = {
            "report_type": "call_summary",
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-12-31T23:59:59Z",
            "format": "json",
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("data", response.data)

    def test_generate_csv_report(self):
        """Test generating CSV report."""
        url = reverse("django_twilio_call:report-generate")
        data = {
            "report_type": "call_detail",
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-12-31T23:59:59Z",
            "format": "csv",
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv")


class WebhookViewTest(TestCase):
    """Tests for webhook views."""

    def setUp(self):
        """Set up test client."""
        self.client = APIClient()

    @patch("django_twilio_call.services.twilio_service.validate_webhook")
    def test_voice_webhook(self, mock_validate):
        """Test voice webhook."""
        mock_validate.return_value = True

        url = reverse("django_twilio_call:webhook-voice")
        data = {
            "CallSid": "CA123",
            "From": "+1234567890",
            "To": "+0987654321",
            "CallStatus": "ringing",
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("xml", response["Content-Type"])

    @patch("django_twilio_call.services.twilio_service.validate_webhook")
    def test_status_callback_webhook(self, mock_validate):
        """Test status callback webhook."""
        mock_validate.return_value = True

        # Create a call
        call = CallFactory(twilio_sid="CA456")

        url = reverse("django_twilio_call:webhook-status")
        data = {
            "CallSid": "CA456",
            "CallStatus": "completed",
            "CallDuration": "120",
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.COMPLETED)

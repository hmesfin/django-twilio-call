"""Unit tests for services."""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from ..exceptions import QueueServiceError
from ..models import Agent, Call, CallLog, Queue
from ..services import (
    agent_service,
    analytics_service,
    call_service,
    queue_service,
    routing_service,
)
from .factories import AgentFactory, CallFactory, QueueFactory


class CallServiceTest(TestCase):
    """Tests for CallService."""

    def setUp(self):
        """Set up test data."""
        self.queue = QueueFactory(name="test_queue")
        self.agent = AgentFactory(extension="1001")
        self.agent.queues.add(self.queue)

    @patch("django_twilio_call.services.call_service.twilio_service")
    def test_initiate_call(self, mock_twilio):
        """Test initiating a call."""
        mock_twilio.make_call.return_value = Mock(sid="CA123")

        call = call_service.initiate_call(
            to_number="+1234567890",
            from_number="+0987654321",
        )

        self.assertEqual(call.twilio_sid, "CA123")
        self.assertEqual(call.status, Call.Status.INITIATED)
        self.assertEqual(call.direction, Call.Direction.OUTBOUND)
        mock_twilio.make_call.assert_called_once()

    def test_handle_incoming_call(self):
        """Test handling incoming call."""
        call_data = {
            "CallSid": "CA456",
            "From": "+1234567890",
            "To": "+0987654321",
            "CallStatus": "ringing",
        }

        call = call_service.handle_incoming_call(call_data)

        self.assertEqual(call.twilio_sid, "CA456")
        self.assertEqual(call.from_number, "+1234567890")
        self.assertEqual(call.to_number, "+0987654321")
        self.assertEqual(call.direction, Call.Direction.INBOUND)

    @patch("django_twilio_call.services.call_service.twilio_service")
    def test_transfer_call(self, mock_twilio):
        """Test transferring a call."""
        call = CallFactory(twilio_sid="CA789", status=Call.Status.IN_PROGRESS)
        target_agent = AgentFactory(extension="1002")

        mock_twilio.transfer_call.return_value = True

        success = call_service.transfer_call(call, target_agent)

        self.assertTrue(success)
        mock_twilio.transfer_call.assert_called_once()

    def test_end_call(self):
        """Test ending a call."""
        call = CallFactory(
            status=Call.Status.IN_PROGRESS,
            answered_at=timezone.now() - timedelta(minutes=5),
        )

        call_service.end_call(call, duration=300)

        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.COMPLETED)
        self.assertEqual(call.duration, 300)
        self.assertIsNotNone(call.ended_at)

    def test_hold_call(self):
        """Test putting call on hold."""
        call = CallFactory(status=Call.Status.IN_PROGRESS)

        call_service.hold_call(call)

        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ON_HOLD)
        self.assertTrue(call.metadata.get("on_hold"))

    def test_unhold_call(self):
        """Test unholding a call."""
        call = CallFactory(
            status=Call.Status.ON_HOLD,
            metadata={"on_hold": True},
        )

        call_service.unhold_call(call)

        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.IN_PROGRESS)
        self.assertFalse(call.metadata.get("on_hold"))


class QueueServiceTest(TestCase):
    """Tests for QueueService."""

    def setUp(self):
        """Set up test data."""
        self.queue = QueueFactory(
            name="test_queue",
            max_size=5,
            is_active=True,
        )
        self.agent = AgentFactory(status=Agent.Status.AVAILABLE)
        self.agent.queues.add(self.queue)

    def test_add_call_to_queue(self):
        """Test adding call to queue."""
        call = CallFactory(queue=None, status=Call.Status.INITIATED)

        updated_call = queue_service.add_call_to_queue(call, self.queue.id)

        self.assertEqual(updated_call.queue, self.queue)
        self.assertEqual(updated_call.status, Call.Status.QUEUED)

        # Verify log entry
        log = CallLog.objects.filter(
            call=call,
            event_type=CallLog.EventType.QUEUED,
        ).first()
        self.assertIsNotNone(log)

    def test_add_call_to_inactive_queue(self):
        """Test adding call to inactive queue throws error."""
        self.queue.is_active = False
        self.queue.save()

        call = CallFactory(queue=None)

        with self.assertRaises(QueueServiceError):
            queue_service.add_call_to_queue(call, self.queue.id)

    def test_add_call_to_full_queue(self):
        """Test adding call to full queue throws error."""
        # Fill the queue
        for _ in range(5):
            CallFactory(queue=self.queue, status=Call.Status.QUEUED)

        call = CallFactory(queue=None)

        with self.assertRaises(QueueServiceError):
            queue_service.add_call_to_queue(call, self.queue.id)

    def test_remove_call_from_queue(self):
        """Test removing call from queue."""
        call = CallFactory(queue=self.queue)

        updated_call = queue_service.remove_call_from_queue(call)

        self.assertIsNone(updated_call.queue)

    def test_get_queue_position(self):
        """Test getting call position in queue."""
        # Add calls to queue
        call1 = CallFactory(queue=self.queue, status=Call.Status.QUEUED)
        call2 = CallFactory(queue=self.queue, status=Call.Status.QUEUED)
        call3 = CallFactory(queue=self.queue, status=Call.Status.QUEUED)

        position = queue_service.get_queue_position(call2)

        # Position should be 2 (second in queue)
        self.assertEqual(position, 2)

    def test_get_queue_statistics(self):
        """Test getting queue statistics."""
        # Add some calls
        CallFactory(queue=self.queue, status=Call.Status.QUEUED)
        CallFactory(queue=self.queue, status=Call.Status.QUEUED)
        CallFactory(
            queue=self.queue,
            status=Call.Status.COMPLETED,
            queue_time=30,
        )

        stats = queue_service.get_queue_statistics(self.queue.id)

        self.assertEqual(stats["calls_in_queue"], 2)
        self.assertEqual(stats["available_agents"], 1)
        self.assertIn("avg_wait_time", stats)


class AgentServiceTest(TestCase):
    """Tests for AgentService."""

    def setUp(self):
        """Set up test data."""
        self.agent = AgentFactory(
            extension="1001",
            status=Agent.Status.OFFLINE,
        )
        self.queue = QueueFactory(name="test_queue")
        self.agent.queues.add(self.queue)

    def test_agent_login(self):
        """Test agent login."""
        agent_service.login(self.agent.id)

        self.agent.refresh_from_db()
        self.assertEqual(self.agent.status, Agent.Status.AVAILABLE)

        # Check activity log
        activity = self.agent.activities.first()
        self.assertEqual(activity.activity_type, "login")

    def test_agent_logout(self):
        """Test agent logout."""
        self.agent.status = Agent.Status.AVAILABLE
        self.agent.save()

        agent_service.logout(self.agent.id)

        self.agent.refresh_from_db()
        self.assertEqual(self.agent.status, Agent.Status.OFFLINE)

    def test_set_agent_available(self):
        """Test setting agent available."""
        self.agent.status = Agent.Status.ON_BREAK
        self.agent.save()

        agent_service.set_available(self.agent.id)

        self.agent.refresh_from_db()
        self.assertEqual(self.agent.status, Agent.Status.AVAILABLE)

    def test_set_agent_busy(self):
        """Test setting agent busy."""
        self.agent.status = Agent.Status.AVAILABLE
        self.agent.save()

        agent_service.set_busy(self.agent.id)

        self.agent.refresh_from_db()
        self.assertEqual(self.agent.status, Agent.Status.BUSY)

    def test_start_break(self):
        """Test starting break."""
        self.agent.status = Agent.Status.AVAILABLE
        self.agent.save()

        agent_service.start_break(self.agent.id, reason="lunch")

        self.agent.refresh_from_db()
        self.assertEqual(self.agent.status, Agent.Status.ON_BREAK)

        # Check activity log
        activity = self.agent.activities.first()
        self.assertEqual(activity.reason, "lunch")

    def test_get_agent_statistics(self):
        """Test getting agent statistics."""
        # Add some calls for the agent
        CallFactory(
            agent=self.agent,
            status=Call.Status.COMPLETED,
            duration=120,
        )
        CallFactory(
            agent=self.agent,
            status=Call.Status.COMPLETED,
            duration=180,
        )

        stats = agent_service.get_agent_statistics(self.agent.id)

        self.assertEqual(stats["total_calls"], 2)
        self.assertEqual(stats["avg_handling_time"], 150)


class RoutingServiceTest(TestCase):
    """Tests for AdvancedRoutingService."""

    def setUp(self):
        """Set up test data."""
        self.queue = QueueFactory(
            name="test_queue",
            routing_strategy=Queue.RoutingStrategy.ROUND_ROBIN,
        )
        self.agent1 = AgentFactory(
            extension="1001",
            status=Agent.Status.AVAILABLE,
        )
        self.agent2 = AgentFactory(
            extension="1002",
            status=Agent.Status.AVAILABLE,
        )
        self.agent1.queues.add(self.queue)
        self.agent2.queues.add(self.queue)

    def test_route_call_round_robin(self):
        """Test round robin routing."""
        call = CallFactory(queue=self.queue)

        # First call should go to first available agent
        agent = routing_service.route_call(call, self.queue)

        self.assertIn(agent, [self.agent1, self.agent2])
        call.refresh_from_db()
        self.assertEqual(call.agent, agent)
        self.assertEqual(call.status, Call.Status.RINGING)

    def test_route_call_no_available_agents(self):
        """Test routing when no agents available."""
        # Make all agents busy
        self.agent1.status = Agent.Status.BUSY
        self.agent1.save()
        self.agent2.status = Agent.Status.BUSY
        self.agent2.save()

        call = CallFactory(queue=self.queue)

        agent = routing_service.route_call(call, self.queue)

        self.assertIsNone(agent)

    def test_skills_based_routing(self):
        """Test skills-based routing."""
        self.queue.routing_strategy = Queue.RoutingStrategy.SKILLS_BASED
        self.queue.required_skills = ["spanish"]
        self.queue.save()

        self.agent1.skills = ["english"]
        self.agent1.save()
        self.agent2.skills = ["spanish", "english"]
        self.agent2.save()

        call = CallFactory(queue=self.queue)

        agent = routing_service.route_call(call, self.queue)

        # Only agent2 has Spanish skill
        self.assertEqual(agent, self.agent2)

    def test_get_queue_metrics(self):
        """Test getting queue metrics."""
        # Add some calls
        CallFactory(queue=self.queue, status=Call.Status.QUEUED)
        CallFactory(queue=self.queue, status=Call.Status.IN_PROGRESS)

        metrics = routing_service.get_queue_metrics(self.queue)

        self.assertEqual(metrics["calls_in_queue"], 1)
        self.assertEqual(metrics["available_agents"], 2)
        self.assertIn("estimated_wait_time", metrics)


class AnalyticsServiceTest(TestCase):
    """Tests for AnalyticsService."""

    def setUp(self):
        """Set up test data."""
        self.queue = QueueFactory(name="test_queue")
        self.agent = AgentFactory(extension="1001")

        # Create sample calls
        self.completed_call = CallFactory(
            queue=self.queue,
            agent=self.agent,
            status=Call.Status.COMPLETED,
            duration=120,
            queue_time=15,
        )
        self.abandoned_call = CallFactory(
            queue=self.queue,
            status=Call.Status.ABANDONED,
            queue_time=60,
        )

    @patch("django_twilio_call.services.analytics_service.cache")
    def test_get_call_analytics(self, mock_cache):
        """Test getting call analytics."""
        mock_cache.get.return_value = None  # No cached data

        analytics = analytics_service.get_call_analytics(
            start_date=timezone.now() - timedelta(days=7),
            end_date=timezone.now(),
        )

        self.assertIn("volume", analytics)
        self.assertIn("duration", analytics)
        self.assertIn("performance", analytics)
        self.assertEqual(analytics["volume"]["total_calls"], 2)
        self.assertEqual(analytics["volume"]["completed_calls"], 1)
        self.assertEqual(analytics["volume"]["abandoned_calls"], 1)

    @patch("django_twilio_call.services.analytics_service.cache")
    def test_get_agent_analytics(self, mock_cache):
        """Test getting agent analytics."""
        mock_cache.get.return_value = None  # No cached data

        analytics = analytics_service.get_agent_analytics(
            agent_id=self.agent.id,
            start_date=timezone.now() - timedelta(hours=24),
            end_date=timezone.now(),
        )

        self.assertIn("agents", analytics)
        self.assertEqual(len(analytics["agents"]), 1)
        agent_data = analytics["agents"][0]
        self.assertEqual(agent_data["agent_id"], self.agent.id)
        self.assertEqual(agent_data["calls"]["total"], 1)

    @patch("django_twilio_call.services.analytics_service.cache")
    def test_get_real_time_metrics(self, mock_cache):
        """Test getting real-time metrics."""
        mock_cache.get.return_value = None  # No cached data

        # Add an active call
        CallFactory(
            status=Call.Status.IN_PROGRESS,
            agent=self.agent,
        )

        metrics = analytics_service.get_real_time_metrics()

        self.assertIn("current_activity", metrics)
        self.assertIn("agents", metrics)
        self.assertIn("today_summary", metrics)
        self.assertEqual(metrics["current_activity"]["active_calls"], 1)

    def test_hourly_distribution(self):
        """Test hourly call distribution."""
        # Create calls at different hours
        for hour in [9, 10, 11, 14, 15]:
            call = CallFactory()
            call.created_at = call.created_at.replace(hour=hour)
            call.save()

        analytics = analytics_service.get_call_analytics()
        hourly = analytics["distribution"]["hourly"]

        # Check that we have 24 hours
        self.assertEqual(len(hourly), 24)
        # Check specific hours have calls
        hour_9 = next(h for h in hourly if h["hour"] == 9)
        self.assertGreater(hour_9["count"], 0)

"""Unit tests for models."""

import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ..models import Agent, Call, CallLog, Queue
from .factories import (
    AgentFactory,
    CallFactory,
    CallLogFactory,
    PhoneNumberFactory,
    QueueFactory,
)

User = get_user_model()


class PhoneNumberModelTest(TestCase):
    """Tests for PhoneNumber model."""

    def test_create_phone_number(self):
        """Test creating a phone number."""
        phone = PhoneNumberFactory()
        self.assertIsNotNone(phone.public_id)
        self.assertTrue(phone.is_active)
        self.assertEqual(phone.capabilities["voice"], True)

    def test_string_representation(self):
        """Test string representation of phone number."""
        phone = PhoneNumberFactory(
            number="+1234567890",
            friendly_name="Test Number",
        )
        self.assertEqual(str(phone), "+1234567890 (Test Number)")

    def test_public_id_is_uuid(self):
        """Test that public_id is a valid UUID."""
        phone = PhoneNumberFactory()
        self.assertIsInstance(phone.public_id, uuid.UUID)

    def test_unique_twilio_sid(self):
        """Test that twilio_sid must be unique."""
        phone1 = PhoneNumberFactory(twilio_sid="PN123")
        with self.assertRaises(Exception):
            PhoneNumberFactory(twilio_sid="PN123")


class QueueModelTest(TestCase):
    """Tests for Queue model."""

    def test_create_queue(self):
        """Test creating a queue."""
        queue = QueueFactory()
        self.assertIsNotNone(queue.public_id)
        self.assertTrue(queue.is_active)
        self.assertEqual(queue.max_size, 100)

    def test_string_representation(self):
        """Test string representation of queue."""
        queue = QueueFactory(name="support_queue")
        self.assertEqual(str(queue), "support_queue")

    def test_routing_strategy_choices(self):
        """Test routing strategy choices."""
        strategies = [
            Queue.RoutingStrategy.FIFO,
            Queue.RoutingStrategy.LIFO,
            Queue.RoutingStrategy.ROUND_ROBIN,
            Queue.RoutingStrategy.LEAST_BUSY,
            Queue.RoutingStrategy.SKILLS_BASED,
        ]
        for strategy in strategies:
            queue = QueueFactory(routing_strategy=strategy)
            self.assertEqual(queue.routing_strategy, strategy)

    def test_overflow_queue_relationship(self):
        """Test overflow queue relationship."""
        main_queue = QueueFactory(name="main")
        overflow_queue = QueueFactory(name="overflow")
        main_queue.overflow_queue = overflow_queue
        main_queue.save()

        self.assertEqual(main_queue.overflow_queue, overflow_queue)


class AgentModelTest(TestCase):
    """Tests for Agent model."""

    def test_create_agent(self):
        """Test creating an agent."""
        agent = AgentFactory()
        self.assertIsNotNone(agent.public_id)
        self.assertTrue(agent.is_active)
        self.assertEqual(agent.status, Agent.Status.AVAILABLE)

    def test_string_representation(self):
        """Test string representation of agent."""
        agent = AgentFactory(
            first_name="John",
            last_name="Doe",
            extension="1001",
        )
        self.assertEqual(str(agent), "John Doe (1001)")

    def test_agent_status_choices(self):
        """Test agent status choices."""
        statuses = [
            Agent.Status.AVAILABLE,
            Agent.Status.BUSY,
            Agent.Status.OFFLINE,
            Agent.Status.ON_BREAK,
        ]
        for status in statuses:
            agent = AgentFactory(status=status)
            self.assertEqual(agent.status, status)

    def test_agent_queue_assignment(self):
        """Test assigning agent to queues."""
        agent = AgentFactory()
        queue1 = QueueFactory(name="sales")
        queue2 = QueueFactory(name="support")

        agent.queues.add(queue1, queue2)

        self.assertEqual(agent.queues.count(), 2)
        self.assertIn(queue1, agent.queues.all())
        self.assertIn(queue2, agent.queues.all())

    def test_unique_extension(self):
        """Test that extension must be unique."""
        agent1 = AgentFactory(extension="1001")
        with self.assertRaises(Exception):
            AgentFactory(extension="1001")

    def test_skills_json_field(self):
        """Test skills JSON field."""
        skills = ["english", "spanish", "technical"]
        agent = AgentFactory(skills=skills)

        self.assertEqual(agent.skills, skills)
        self.assertIsInstance(agent.skills, list)


class CallModelTest(TestCase):
    """Tests for Call model."""

    def test_create_call(self):
        """Test creating a call."""
        call = CallFactory()
        self.assertIsNotNone(call.public_id)
        self.assertEqual(call.status, Call.Status.QUEUED)
        self.assertEqual(call.direction, Call.Direction.INBOUND)

    def test_string_representation(self):
        """Test string representation of call."""
        call = CallFactory(
            twilio_sid="CA123",
            from_number="+1234567890",
        )
        self.assertEqual(str(call), "CA123 - +1234567890")

    def test_call_status_transitions(self):
        """Test call status transitions."""
        call = CallFactory(status=Call.Status.QUEUED)

        # Transition to ringing
        call.status = Call.Status.RINGING
        call.save()
        self.assertEqual(call.status, Call.Status.RINGING)

        # Transition to in progress
        call.status = Call.Status.IN_PROGRESS
        call.answered_at = timezone.now()
        call.save()
        self.assertEqual(call.status, Call.Status.IN_PROGRESS)

        # Complete the call
        call.status = Call.Status.COMPLETED
        call.ended_at = timezone.now()
        call.duration = 120
        call.save()
        self.assertEqual(call.status, Call.Status.COMPLETED)
        self.assertEqual(call.duration, 120)

    def test_call_agent_assignment(self):
        """Test assigning call to agent."""
        agent = AgentFactory()
        call = CallFactory(agent=agent)

        self.assertEqual(call.agent, agent)
        self.assertIn(call, agent.calls.all())

    def test_call_queue_assignment(self):
        """Test assigning call to queue."""
        queue = QueueFactory()
        call = CallFactory(queue=queue)

        self.assertEqual(call.queue, queue)
        self.assertIn(call, queue.calls.all())

    def test_unique_twilio_sid(self):
        """Test that twilio_sid must be unique."""
        call1 = CallFactory(twilio_sid="CA123")
        with self.assertRaises(Exception):
            CallFactory(twilio_sid="CA123")


class CallLogModelTest(TestCase):
    """Tests for CallLog model."""

    def test_create_call_log(self):
        """Test creating a call log."""
        call = CallFactory()
        log = CallLogFactory(call=call)

        self.assertIsNotNone(log.public_id)
        self.assertEqual(log.call, call)
        self.assertEqual(log.event_type, CallLog.EventType.INITIATED)

    def test_string_representation(self):
        """Test string representation of call log."""
        call = CallFactory(twilio_sid="CA123")
        log = CallLogFactory(
            call=call,
            event_type=CallLog.EventType.QUEUED,
        )
        expected = f"CA123 - {CallLog.EventType.QUEUED} at {log.timestamp}"
        self.assertEqual(str(log), expected)

    def test_call_log_with_agent(self):
        """Test call log with agent."""
        agent = AgentFactory()
        call = CallFactory()
        log = CallLogFactory(
            call=call,
            agent=agent,
            event_type=CallLog.EventType.CONNECTED,
        )

        self.assertEqual(log.agent, agent)

    def test_multiple_logs_per_call(self):
        """Test multiple logs for a single call."""
        call = CallFactory()

        log1 = CallLogFactory(
            call=call,
            event_type=CallLog.EventType.INITIATED,
        )
        log2 = CallLogFactory(
            call=call,
            event_type=CallLog.EventType.QUEUED,
        )
        log3 = CallLogFactory(
            call=call,
            event_type=CallLog.EventType.CONNECTED,
        )

        self.assertEqual(call.logs.count(), 3)
        self.assertIn(log1, call.logs.all())
        self.assertIn(log2, call.logs.all())
        self.assertIn(log3, call.logs.all())

    def test_log_data_json_field(self):
        """Test data JSON field."""
        data = {
            "queue_id": 1,
            "wait_time": 30,
            "agent_id": 5,
        }
        log = CallLogFactory(data=data)

        self.assertEqual(log.data, data)
        self.assertIsInstance(log.data, dict)

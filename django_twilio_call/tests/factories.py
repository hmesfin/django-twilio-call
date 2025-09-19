"""Factory classes for generating test data."""

import random
from typing import Any, Dict, List

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone
from factory import fuzzy

from ..models import Agent, Call, CallLog, PhoneNumber, Queue

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    """Factory for User model."""

    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    is_active = True


class PhoneNumberFactory(factory.django.DjangoModelFactory):
    """Factory for PhoneNumber model."""

    class Meta:
        model = PhoneNumber

    number = factory.Faker("phone_number")
    friendly_name = factory.Faker("company")
    twilio_sid = factory.Sequence(lambda n: f"PN{n:032d}")
    is_active = True
    capabilities = {"voice": True, "sms": True}
    metadata = {}


class QueueFactory(factory.django.DjangoModelFactory):
    """Factory for Queue model."""

    class Meta:
        model = Queue

    name = factory.Sequence(lambda n: f"queue_{n}")
    description = factory.Faker("sentence")
    priority = fuzzy.FuzzyInteger(1, 10)
    max_size = 100
    max_wait_time = 300
    service_level_threshold = 20
    routing_strategy = Queue.RoutingStrategy.FIFO
    is_active = True
    metadata = {}


class AgentFactory(factory.django.DjangoModelFactory):
    """Factory for Agent model."""

    class Meta:
        model = Agent

    user = factory.SubFactory(UserFactory)
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.LazyAttribute(lambda obj: f"{obj.first_name.lower()}.{obj.last_name.lower()}@example.com")
    extension = factory.Sequence(lambda n: f"{1000 + n}")
    status = Agent.Status.AVAILABLE
    is_active = True
    max_concurrent_calls = 1
    skills = []
    metadata = {}

    @factory.post_generation
    def queues(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted:
            for queue in extracted:
                self.queues.add(queue)


class CallFactory(factory.django.DjangoModelFactory):
    """Factory for Call model."""

    class Meta:
        model = Call

    twilio_sid = factory.Sequence(lambda n: f"CA{n:032d}")
    from_number = factory.Faker("phone_number")
    to_number = factory.Faker("phone_number")
    direction = Call.Direction.INBOUND
    status = Call.Status.QUEUED
    queue = factory.SubFactory(QueueFactory)
    agent = None
    duration = None
    queue_time = None
    created_at = factory.LazyFunction(timezone.now)
    metadata = {}


class CallLogFactory(factory.django.DjangoModelFactory):
    """Factory for CallLog model."""

    class Meta:
        model = CallLog

    call = factory.SubFactory(CallFactory)
    event_type = CallLog.EventType.INITIATED
    description = factory.Faker("sentence")
    agent = None
    timestamp = factory.LazyFunction(timezone.now)
    data = {}


# ===========================================
# FACTORY TRAITS
# ===========================================


class AgentTraits:
    """Traits for Agent factory to create agents in specific states."""

    @factory.trait
    def busy(self):
        """Agent in busy status."""
        self.status = Agent.Status.BUSY

    @factory.trait
    def on_break(self):
        """Agent on break."""
        self.status = Agent.Status.ON_BREAK

    @factory.trait
    def offline(self):
        """Agent offline."""
        self.status = Agent.Status.OFFLINE
        self.is_active = False

    @factory.trait
    def senior(self):
        """Senior agent with advanced skills."""
        self.skills = ["senior", "escalation", "technical"]
        self.max_concurrent_calls = 3

    @factory.trait
    def supervisor(self):
        """Supervisor agent."""
        self.skills = ["supervisor", "management", "escalation"]
        self.max_concurrent_calls = 5

    @factory.trait
    def new_hire(self):
        """New hire agent with basic skills."""
        self.skills = ["basic"]
        self.max_concurrent_calls = 1


class CallTraits:
    """Traits for Call factory to create calls in specific states."""

    @factory.trait
    def in_progress(self):
        """Active call in progress."""
        self.status = Call.Status.IN_PROGRESS
        self.agent = factory.SubFactory(AgentFactory, busy=True)
        self.duration = fuzzy.FuzzyInteger(10, 300)
        self.answered_at = factory.LazyFunction(timezone.now)

    @factory.trait
    def completed(self):
        """Completed call."""
        self.status = Call.Status.COMPLETED
        self.agent = factory.SubFactory(AgentFactory)
        self.duration = fuzzy.FuzzyInteger(30, 600)
        self.answered_at = factory.LazyFunction(timezone.now)
        self.ended_at = factory.LazyFunction(timezone.now)

    @factory.trait
    def abandoned(self):
        """Abandoned call."""
        self.status = Call.Status.ABANDONED
        self.queue_time = fuzzy.FuzzyInteger(60, 300)
        self.ended_at = factory.LazyFunction(timezone.now)

    @factory.trait
    def failed(self):
        """Failed call."""
        self.status = Call.Status.FAILED
        self.metadata = {"error": "Call failed to connect"}

    @factory.trait
    def outbound(self):
        """Outbound call."""
        self.direction = Call.Direction.OUTBOUND
        self.agent = factory.SubFactory(AgentFactory)

    @factory.trait
    def long_duration(self):
        """Long duration call."""
        self.duration = fuzzy.FuzzyInteger(600, 1800)  # 10-30 minutes

    @factory.trait
    def short_duration(self):
        """Short duration call."""
        self.duration = fuzzy.FuzzyInteger(10, 60)  # 10-60 seconds


class QueueTraits:
    """Traits for Queue factory."""

    @factory.trait
    def high_priority(self):
        """High priority queue."""
        self.priority = 10
        self.service_level_threshold = 10

    @factory.trait
    def low_priority(self):
        """Low priority queue."""
        self.priority = 1
        self.service_level_threshold = 60

    @factory.trait
    def skills_based(self):
        """Skills-based routing queue."""
        self.routing_strategy = Queue.RoutingStrategy.SKILLS_BASED
        self.required_skills = ["technical", "escalation"]


# Update existing factories to use traits
AgentFactory._traits = AgentTraits
CallFactory._traits = CallTraits
QueueFactory._traits = QueueTraits


# ===========================================
# RELATIONSHIP FACTORIES
# ===========================================


class AgentWithQueuesFactory(AgentFactory):
    """Agent factory that automatically creates queue relationships."""

    @factory.post_generation
    def setup_queues(self, create, extracted, **kwargs):
        if not create:
            return

        # Create 2-3 queues for this agent if none provided
        if not extracted:
            queue_count = random.randint(2, 3)
            queues = QueueFactory.create_batch(queue_count)
        else:
            queues = extracted

        for queue in queues:
            self.queues.add(queue)


class CallWithFullContextFactory(CallFactory):
    """Call factory that creates a complete call context with agent, queue, and logs."""

    agent = factory.SubFactory(AgentFactory, busy=True)
    queue = factory.SubFactory(QueueFactory)

    @factory.post_generation
    def create_call_logs(self, create, extracted, **kwargs):
        if not create:
            return

        # Create standard call logs
        CallLogFactory(call=self, event_type=CallLog.EventType.INITIATED, description="Call initiated")

        if self.agent:
            CallLogFactory(
                call=self,
                event_type=CallLog.EventType.ANSWERED,
                description=f"Call answered by {self.agent.first_name}",
                agent=self.agent,
            )

        if self.status == Call.Status.COMPLETED:
            CallLogFactory(call=self, event_type=CallLog.EventType.ENDED, description="Call completed normally")


class QueueWithAgentsFactory(QueueFactory):
    """Queue factory that automatically creates agent relationships."""

    @factory.post_generation
    def setup_agents(self, create, extracted, **kwargs):
        if not create:
            return

        # Create 3-5 agents for this queue if none provided
        if not extracted:
            agent_count = random.randint(3, 5)
            agents = AgentFactory.create_batch(agent_count)
        else:
            agents = extracted

        for agent in agents:
            self.agents.add(agent)


# ===========================================
# SCENARIO-BASED FACTORIES
# ===========================================


def create_active_call_center_scenario():
    """Create a realistic active call center scenario."""
    # Create queues
    support_queue = QueueFactory(name="Customer Support", priority=5, routing_strategy=Queue.RoutingStrategy.FIFO)

    technical_queue = QueueFactory(
        name="Technical Support",
        priority=8,
        routing_strategy=Queue.RoutingStrategy.SKILLS_BASED,
        required_skills=["technical"],
    )

    escalation_queue = QueueFactory(
        name="Escalation",
        priority=10,
        routing_strategy=Queue.RoutingStrategy.SKILLS_BASED,
        required_skills=["senior", "escalation"],
    )

    # Create agents with different skill levels
    junior_agents = AgentFactory.create_batch(5, skills=["basic", "customer_service"], max_concurrent_calls=1)

    senior_agents = AgentFactory.create_batch(3, skills=["technical", "senior", "escalation"], max_concurrent_calls=2)

    supervisor = AgentFactory(skills=["supervisor", "management", "escalation"], max_concurrent_calls=3)

    # Assign agents to queues
    all_agents = junior_agents + senior_agents + [supervisor]

    for agent in all_agents:
        agent.queues.add(support_queue)

    for agent in senior_agents + [supervisor]:
        agent.queues.add(technical_queue)
        agent.queues.add(escalation_queue)

    # Create various call states
    active_calls = []

    # Some agents are busy
    for i, agent in enumerate(all_agents[:4]):
        agent.status = Agent.Status.BUSY
        agent.save()

        call = CallFactory(
            status=Call.Status.IN_PROGRESS,
            agent=agent,
            queue=random.choice([support_queue, technical_queue]),
            duration=random.randint(60, 300),
        )
        active_calls.append(call)

    # Some calls waiting in queue
    queued_calls = []
    for i in range(6):
        queue = random.choice([support_queue, technical_queue, escalation_queue])
        call = CallFactory(status=Call.Status.QUEUED, queue=queue, queue_time=random.randint(10, 120))
        queued_calls.append(call)

    # Recent completed calls
    completed_calls = []
    for i in range(10):
        agent = random.choice(all_agents)
        queue = random.choice([support_queue, technical_queue])
        call = CallFactory(
            status=Call.Status.COMPLETED, agent=agent, queue=queue, duration=random.randint(60, 600), completed=True
        )
        completed_calls.append(call)

    return {
        "queues": {"support": support_queue, "technical": technical_queue, "escalation": escalation_queue},
        "agents": {"junior": junior_agents, "senior": senior_agents, "supervisor": supervisor, "all": all_agents},
        "calls": {"active": active_calls, "queued": queued_calls, "completed": completed_calls},
    }


def create_peak_hour_scenario():
    """Create a peak hour scenario with high call volume."""
    queue = QueueFactory(name="Peak Hour Queue", max_size=50)

    # Create agents - some busy, some available
    agents = AgentFactory.create_batch(8)
    for agent in agents:
        agent.queues.add(queue)

    # Make most agents busy
    busy_agents = agents[:6]
    available_agents = agents[6:]

    for agent in busy_agents:
        agent.status = Agent.Status.BUSY
        agent.save()
        CallFactory(status=Call.Status.IN_PROGRESS, agent=agent, queue=queue)

    # Create many queued calls
    queued_calls = CallFactory.create_batch(15, status=Call.Status.QUEUED, queue=queue)

    return {
        "queue": queue,
        "busy_agents": busy_agents,
        "available_agents": available_agents,
        "queued_calls": queued_calls,
    }


def create_agent_performance_scenario():
    """Create scenario for testing agent performance metrics."""
    agent = AgentFactory(senior=True)
    queue = QueueFactory()
    agent.queues.add(queue)

    # Create calls with various outcomes
    completed_calls = CallFactory.create_batch(15, agent=agent, queue=queue, completed=True)

    # Some short calls
    short_calls = CallFactory.create_batch(5, agent=agent, queue=queue, completed=True, short_duration=True)

    # Some long calls
    long_calls = CallFactory.create_batch(3, agent=agent, queue=queue, completed=True, long_duration=True)

    # Some abandoned calls in their queue
    abandoned_calls = CallFactory.create_batch(2, queue=queue, abandoned=True)

    return {
        "agent": agent,
        "queue": queue,
        "completed_calls": completed_calls + short_calls + long_calls,
        "abandoned_calls": abandoned_calls,
    }


# ===========================================
# BULK FACTORY METHODS
# ===========================================


class BulkFactoryMixin:
    """Mixin to add bulk creation methods to factories."""

    @classmethod
    def create_batch_with_relationships(cls, size: int, **kwargs) -> List:
        """Create a batch of objects with automatic relationship setup."""
        objects = []
        for i in range(size):
            obj = cls(**kwargs)
            objects.append(obj)
        return objects

    @classmethod
    def create_realistic_batch(cls, size: int, **kwargs) -> List:
        """Create a batch with realistic data distribution."""
        # Override in specific factories for custom logic
        return cls.create_batch(size, **kwargs)


class BulkAgentFactory(AgentFactory, BulkFactoryMixin):
    """Agent factory with bulk creation capabilities."""

    @classmethod
    def create_realistic_batch(cls, size: int, **kwargs) -> List[Agent]:
        """Create agents with realistic skill distribution."""
        agents = []

        # 60% junior agents
        junior_count = int(size * 0.6)
        agents.extend(cls.create_batch(junior_count, skills=["basic"], **kwargs))

        # 30% senior agents
        senior_count = int(size * 0.3)
        agents.extend(cls.create_batch(senior_count, skills=["senior", "technical"], max_concurrent_calls=2, **kwargs))

        # 10% supervisors
        supervisor_count = size - junior_count - senior_count
        if supervisor_count > 0:
            agents.extend(
                cls.create_batch(
                    supervisor_count, skills=["supervisor", "management"], max_concurrent_calls=3, **kwargs
                )
            )

        return agents

    @classmethod
    def create_team_with_queues(cls, team_size: int, queue_count: int = 3) -> Dict[str, Any]:
        """Create a complete team setup with agents and queues."""
        # Create queues
        queues = QueueFactory.create_batch(queue_count)

        # Create agents
        agents = cls.create_realistic_batch(team_size)

        # Assign agents to queues
        for agent in agents:
            # Each agent gets assigned to 1-2 random queues
            agent_queues = random.sample(queues, random.randint(1, min(2, len(queues))))
            for queue in agent_queues:
                agent.queues.add(queue)

        return {"agents": agents, "queues": queues, "team_size": team_size}


class BulkCallFactory(CallFactory, BulkFactoryMixin):
    """Call factory with bulk creation capabilities."""

    @classmethod
    def create_realistic_batch(cls, size: int, **kwargs) -> List[Call]:
        """Create calls with realistic status distribution."""
        calls = []

        # 70% completed calls
        completed_count = int(size * 0.7)
        calls.extend(cls.create_batch(completed_count, completed=True, **kwargs))

        # 15% active calls
        active_count = int(size * 0.15)
        calls.extend(cls.create_batch(active_count, in_progress=True, **kwargs))

        # 10% abandoned calls
        abandoned_count = int(size * 0.1)
        calls.extend(cls.create_batch(abandoned_count, abandoned=True, **kwargs))

        # 5% queued calls
        queued_count = size - completed_count - active_count - abandoned_count
        if queued_count > 0:
            calls.extend(cls.create_batch(queued_count, status=Call.Status.QUEUED, **kwargs))

        return calls

    @classmethod
    def create_historical_data(cls, days: int = 30, calls_per_day: int = 50) -> List[Call]:
        """Create historical call data spanning multiple days."""
        calls = []

        for day in range(days):
            # Vary call volume by day (more on weekdays)
            if day % 7 in [5, 6]:  # Weekend
                daily_calls = int(calls_per_day * 0.3)
            else:  # Weekday
                daily_calls = calls_per_day

            # Create calls for this day
            from datetime import timedelta

            day_offset = timezone.now() - timedelta(days=day)

            day_calls = cls.create_realistic_batch(daily_calls, created_at=day_offset)
            calls.extend(day_calls)

        return calls


# ===========================================
# FACTORY HELPER FUNCTIONS
# ===========================================


def setup_test_call_center(agent_count: int = 10, queue_count: int = 3, call_count: int = 50) -> Dict[str, Any]:
    """Set up a complete test call center environment."""
    # Create the team
    team_data = BulkAgentFactory.create_team_with_queues(agent_count, queue_count)

    # Create calls distributed across queues
    calls = []
    for queue in team_data["queues"]:
        queue_calls = BulkCallFactory.create_realistic_batch(call_count // queue_count, queue=queue)
        calls.extend(queue_calls)

    return {**team_data, "calls": calls, "total_calls": len(calls)}


def create_stress_test_data(scale_factor: int = 1) -> Dict[str, Any]:
    """Create large-scale test data for stress testing."""
    base_agents = 50 * scale_factor
    base_queues = 10 * scale_factor
    base_calls = 1000 * scale_factor

    return setup_test_call_center(agent_count=base_agents, queue_count=base_queues, call_count=base_calls)


def cleanup_test_data():
    """Clean up all test data (useful for test teardown)."""
    models_to_clean = [Call, CallLog, Agent, Queue, PhoneNumber, User]

    for model in models_to_clean:
        if hasattr(model.objects, "filter"):
            # Only delete test data (avoid deleting real data)
            test_filter = {}

            # Add filters to identify test data
            if hasattr(model, "email") and hasattr(model, "username"):
                # User model
                test_filter = {"email__contains": "@example.com"}
            elif hasattr(model, "twilio_sid"):
                # Twilio-related models
                test_filter = {"twilio_sid__startswith": "CA"}
            elif hasattr(model, "name"):
                # Named models
                test_filter = {"name__contains": "test"}

            if test_filter:
                model.objects.filter(**test_filter).delete()
            else:
                # Be very careful - only delete if we're sure it's test data
                pass

"""Factory classes for generating test data."""

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
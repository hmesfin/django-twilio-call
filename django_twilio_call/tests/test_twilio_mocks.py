"""Mock Twilio responses for testing."""

from unittest.mock import Mock


class MockTwilioCall:
    """Mock Twilio Call object."""

    def __init__(self, **kwargs):
        """Initialize mock call."""
        self.sid = kwargs.get("sid", "CA1234567890abcdef1234567890abcdef")
        self.from_ = kwargs.get("from_", "+1234567890")
        self.to = kwargs.get("to", "+0987654321")
        self.status = kwargs.get("status", "queued")
        self.direction = kwargs.get("direction", "inbound")
        self.duration = kwargs.get("duration", None)
        self.price = kwargs.get("price", None)
        self.price_unit = kwargs.get("price_unit", "USD")

    def update(self, **kwargs):
        """Update mock call properties."""
        for key, value in kwargs.items():
            setattr(self, key, value)
        return self

    def fetch(self):
        """Fetch call details."""
        return self

    def delete(self):
        """Delete (end) the call."""
        self.status = "completed"
        return True


class MockTwilioRecording:
    """Mock Twilio Recording object."""

    def __init__(self, **kwargs):
        """Initialize mock recording."""
        self.sid = kwargs.get("sid", "RE1234567890abcdef1234567890abcdef")
        self.call_sid = kwargs.get("call_sid", "CA1234567890abcdef1234567890abcdef")
        self.status = kwargs.get("status", "processing")
        self.duration = kwargs.get("duration", "120")
        self.channels = kwargs.get("channels", 1)
        self.source = kwargs.get("source", "RecordVerb")
        self.uri = kwargs.get("uri", "/2010-04-01/Accounts/AC123/Recordings/RE123.json")

    def delete(self):
        """Delete the recording."""
        return True


class MockTwilioConference:
    """Mock Twilio Conference object."""

    def __init__(self, **kwargs):
        """Initialize mock conference."""
        self.sid = kwargs.get("sid", "CF1234567890abcdef1234567890abcdef")
        self.friendly_name = kwargs.get("friendly_name", "Test Conference")
        self.status = kwargs.get("status", "in-progress")
        self.region = kwargs.get("region", "us1")
        self.participants = MockConferenceParticipants()

    def update(self, **kwargs):
        """Update conference properties."""
        for key, value in kwargs.items():
            setattr(self, key, value)
        return self


class MockConferenceParticipants:
    """Mock conference participants manager."""

    def __init__(self):
        """Initialize participants manager."""
        self._participants = {}

    def create(self, **kwargs):
        """Add a participant to conference."""
        participant = Mock()
        participant.call_sid = kwargs.get("from", "CA123")
        participant.muted = kwargs.get("muted", False)
        participant.coaching = kwargs.get("coaching", False)
        self._participants[participant.call_sid] = participant
        return participant

    def get(self, call_sid):
        """Get a participant."""
        return self._participants.get(call_sid)

    def update(self, call_sid, **kwargs):
        """Update participant properties."""
        if call_sid in self._participants:
            for key, value in kwargs.items():
                setattr(self._participants[call_sid], key, value)
        return self._participants.get(call_sid)

    def delete(self, call_sid):
        """Remove participant from conference."""
        if call_sid in self._participants:
            del self._participants[call_sid]
        return True

    def list(self):
        """List all participants."""
        return list(self._participants.values())


class MockTwilioClient:
    """Mock Twilio Client."""

    def __init__(self, account_sid="AC123", auth_token="auth123"):
        """Initialize mock client."""
        self.account_sid = account_sid
        self.auth_token = auth_token

        # Mock services
        self.calls = MockCallsService()
        self.recordings = MockRecordingsService()
        self.conferences = MockConferencesService()
        self.messages = MockMessagesService()
        self.lookups = MockLookupsService()

    def validate_request(self, url, params, signature):
        """Mock webhook validation."""
        return True


class MockCallsService:
    """Mock calls service."""

    def __init__(self):
        """Initialize calls service."""
        self._calls = {}

    def create(self, **kwargs):
        """Create a new call."""
        call = MockTwilioCall(**kwargs)
        self._calls[call.sid] = call
        return call

    def get(self, sid):
        """Get a call by SID."""
        return self._calls.get(sid, MockTwilioCall(sid=sid))

    def update(self, sid, **kwargs):
        """Update a call."""
        if sid in self._calls:
            return self._calls[sid].update(**kwargs)
        return MockTwilioCall(sid=sid, **kwargs)

    def list(self, **filters):
        """List calls with filters."""
        return list(self._calls.values())


class MockRecordingsService:
    """Mock recordings service."""

    def __init__(self):
        """Initialize recordings service."""
        self._recordings = {}

    def get(self, sid):
        """Get a recording by SID."""
        return self._recordings.get(sid, MockTwilioRecording(sid=sid))

    def delete(self, sid):
        """Delete a recording."""
        if sid in self._recordings:
            del self._recordings[sid]
        return True

    def list(self, **filters):
        """List recordings with filters."""
        return list(self._recordings.values())


class MockConferencesService:
    """Mock conferences service."""

    def __init__(self):
        """Initialize conferences service."""
        self._conferences = {}

    def get(self, sid):
        """Get a conference by SID."""
        return self._conferences.get(sid, MockTwilioConference(sid=sid))

    def create(self, **kwargs):
        """Create a conference."""
        conference = MockTwilioConference(**kwargs)
        self._conferences[conference.sid] = conference
        return conference

    def update(self, sid, **kwargs):
        """Update a conference."""
        if sid in self._conferences:
            return self._conferences[sid].update(**kwargs)
        return MockTwilioConference(sid=sid, **kwargs)

    def list(self, **filters):
        """List conferences with filters."""
        return list(self._conferences.values())


class MockMessagesService:
    """Mock messages service."""

    def create(self, **kwargs):
        """Send an SMS message."""
        message = Mock()
        message.sid = "SM1234567890abcdef1234567890abcdef"
        message.from_ = kwargs.get("from_", "+1234567890")
        message.to = kwargs.get("to", "+0987654321")
        message.body = kwargs.get("body", "Test message")
        message.status = "sent"
        return message


class MockLookupsService:
    """Mock lookups service."""

    def __init__(self):
        """Initialize lookups service."""
        self.v1 = Mock()
        self.v1.phone_numbers = self._phone_numbers

    def _phone_numbers(self, number):
        """Mock phone number lookup."""
        lookup = Mock()
        lookup.fetch = lambda: Mock(
            phone_number=number,
            country_code="US",
            national_format="(123) 456-7890",
            carrier={"name": "Test Carrier", "type": "mobile"},
            caller_name={"caller_name": "John Doe", "caller_type": "CONSUMER"},
        )
        return lookup


def create_mock_twilio_client():
    """Create a mock Twilio client for testing.

    Returns:
        MockTwilioClient: Configured mock client

    """
    return MockTwilioClient()


def mock_twilio_webhook_data():
    """Generate mock webhook data.

    Returns:
        dict: Sample webhook data

    """
    return {
        "voice_incoming": {
            "CallSid": "CA1234567890abcdef1234567890abcdef",
            "AccountSid": "ACtest1234567890test1234567890test",
            "From": "+14155551234",
            "To": "+14155555678",
            "CallStatus": "ringing",
            "ApiVersion": "2010-04-01",
            "Direction": "inbound",
            "CallerName": "John Doe",
        },
        "status_callback": {
            "CallSid": "CA1234567890abcdef1234567890abcdef",
            "CallStatus": "completed",
            "CallDuration": "120",
            "RecordingUrl": "https://api.twilio.com/recording.mp3",
            "RecordingSid": "RE1234567890abcdef1234567890abcdef",
            "RecordingDuration": "118",
        },
        "recording_callback": {
            "RecordingSid": "RE1234567890abcdef1234567890abcdef",
            "RecordingUrl": "https://api.twilio.com/recording.mp3",
            "RecordingStatus": "completed",
            "RecordingDuration": "120",
            "RecordingChannels": "1",
            "RecordingSource": "RecordVerb",
        },
        "conference_event": {
            "ConferenceSid": "CF1234567890abcdef1234567890abcdef",
            "FriendlyName": "Test Conference",
            "StatusCallbackEvent": "participant-join",
            "CallSid": "CA1234567890abcdef1234567890abcdef",
            "Muted": "false",
            "Coaching": "false",
        },
        "gather_input": {
            "CallSid": "CA1234567890abcdef1234567890abcdef",
            "Digits": "1",
            "From": "+14155551234",
            "To": "+14155555678",
            "CallStatus": "in-progress",
        },
    }


def mock_twiml_response(action="voice"):
    """Generate mock TwiML responses.

    Args:
        action: Type of TwiML response

    Returns:
        str: TwiML XML string

    """
    responses = {
        "voice": """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Thank you for calling. Please wait while we connect you.</Say>
    <Enqueue waitUrl="/queue/wait">support</Enqueue>
</Response>""",
        "gather": """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather numDigits="1" action="/ivr/process" method="POST">
        <Say>Press 1 for sales, 2 for support.</Say>
    </Gather>
    <Say>We didn't receive any input. Goodbye!</Say>
</Response>""",
        "conference": """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial>
        <Conference>MyConference</Conference>
    </Dial>
</Response>""",
        "record": """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Please leave a message after the beep.</Say>
    <Record maxLength="120" action="/recording/complete" />
</Response>""",
    }
    return responses.get(action, "<Response></Response>")

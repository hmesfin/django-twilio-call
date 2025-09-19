"""Swagger/OpenAPI configuration for django-twilio-call."""

from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema

# Common parameters used across multiple endpoints
PAGINATION_PARAMETERS = [
    OpenApiParameter(
        name="page",
        type=int,
        location=OpenApiParameter.QUERY,
        description="Page number for pagination",
        default=1,
    ),
    OpenApiParameter(
        name="page_size",
        type=int,
        location=OpenApiParameter.QUERY,
        description="Number of results per page",
        default=20,
    ),
]

DATE_FILTER_PARAMETERS = [
    OpenApiParameter(
        name="start_date",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Start date for filtering (ISO 8601 format)",
        examples=[
            OpenApiExample(
                "Example",
                value="2024-01-01T00:00:00Z",
            ),
        ],
    ),
    OpenApiParameter(
        name="end_date",
        type=str,
        location=OpenApiParameter.QUERY,
        description="End date for filtering (ISO 8601 format)",
        examples=[
            OpenApiExample(
                "Example",
                value="2024-12-31T23:59:59Z",
            ),
        ],
    ),
]

# Schema decorators for views
call_schemas = {
    "list": extend_schema(
        summary="List calls",
        description="""
        Retrieve a paginated list of calls with optional filtering.

        **Use Cases:**
        - View call history for reporting
        - Filter calls by status, agent, or queue
        - Search for specific calls by phone number

        **Important Notes:**
        - Results are ordered by creation date (newest first)
        - Only calls visible to the authenticated user are returned
        - Use the status filter to find active calls
        """,
        parameters=[
            *PAGINATION_PARAMETERS,
            OpenApiParameter(
                name="status",
                type=str,
                location=OpenApiParameter.QUERY,
                enum=["initiated", "queued", "ringing", "in_progress", "on_hold", "completed", "failed", "abandoned"],
                description="Filter by call status",
            ),
            OpenApiParameter(
                name="agent_id",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Filter by agent ID",
            ),
            OpenApiParameter(
                name="queue_id",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Filter by queue ID",
            ),
        ],
        examples=[
            OpenApiExample(
                "Success Response",
                value={
                    "count": 150,
                    "next": "http://api.example.com/api/v1/calls/?page=2",
                    "previous": None,
                    "results": [
                        {
                            "id": 1,
                            "public_id": "550e8400-e29b-41d4-a716-446655440000",
                            "twilio_sid": "CA1234567890abcdef1234567890abcdef",
                            "from_number": "+14155551234",
                            "to_number": "+14155555678",
                            "direction": "inbound",
                            "status": "completed",
                            "duration": 120,
                            "queue_time": 15,
                            "agent": {"id": 5, "name": "John Doe", "extension": "1001"},
                            "queue": {"id": 2, "name": "support"},
                            "created_at": "2024-01-15T10:30:00Z",
                            "answered_at": "2024-01-15T10:30:15Z",
                            "ended_at": "2024-01-15T10:32:15Z",
                        }
                    ],
                },
                response_only=True,
            ),
        ],
    ),
    "initiate": extend_schema(
        summary="Initiate an outbound call",
        description="""
        Start a new outbound call using Twilio.

        **Prerequisites:**
        - Valid Twilio account with calling capabilities
        - Verified phone numbers (for trial accounts)
        - Agent must be available to handle the call

        **Process Flow:**
        1. Call is initiated via Twilio API
        2. Call status is set to 'initiated'
        3. When answered, call can be connected to an agent
        4. Call events are tracked via webhooks

        **Common Issues:**
        - Invalid phone number format (use E.164 format: +1234567890)
        - Insufficient Twilio account balance
        - Number not verified (for trial accounts)
        """,
        request={
            "application/json": {
                "type": "object",
                "required": ["to_number", "from_number"],
                "properties": {
                    "to_number": {
                        "type": "string",
                        "description": "Destination phone number in E.164 format",
                        "example": "+14155551234",
                    },
                    "from_number": {
                        "type": "string",
                        "description": "Caller ID number (must be a Twilio number)",
                        "example": "+14155555678",
                    },
                    "agent_id": {
                        "type": "integer",
                        "description": "Optional agent to assign the call to",
                        "example": 5,
                    },
                    "url": {
                        "type": "string",
                        "description": "TwiML URL for call instructions",
                        "example": "https://api.example.com/webhooks/voice/",
                    },
                },
            }
        },
        responses={
            201: OpenApiResponse(
                description="Call initiated successfully",
                response={
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "public_id": {"type": "string"},
                        "twilio_sid": {"type": "string"},
                        "status": {"type": "string"},
                    },
                },
            ),
            400: OpenApiResponse(
                description="Invalid request data",
                response={"type": "object", "properties": {"error": {"type": "string"}}},
            ),
        },
        examples=[
            OpenApiExample(
                "Basic Call",
                value={"to_number": "+14155551234", "from_number": "+14155555678"},
                request_only=True,
            ),
            OpenApiExample(
                "Call with Agent Assignment",
                value={
                    "to_number": "+14155551234",
                    "from_number": "+14155555678",
                    "agent_id": 5,
                    "url": "https://api.example.com/webhooks/voice/",
                },
                request_only=True,
            ),
        ],
    ),
    "transfer": extend_schema(
        summary="Transfer a call to another agent",
        description="""
        Transfer an active call to a different agent or queue.

        **Transfer Types:**
        - Warm transfer: Agent speaks with target before transferring
        - Cold transfer: Direct transfer without introduction
        - Queue transfer: Send call to a different queue

        **Requirements:**
        - Call must be in 'in_progress' status
        - Target agent must be available
        - User must have permission to transfer calls

        **What Happens:**
        1. Original agent is disconnected
        2. Call is placed on hold briefly
        3. Call is connected to new agent
        4. Transfer is logged in call history
        """,
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "integer",
                        "description": "Target agent ID",
                    },
                    "queue_id": {
                        "type": "integer",
                        "description": "Target queue ID (alternative to agent_id)",
                    },
                    "warm_transfer": {
                        "type": "boolean",
                        "description": "Whether to perform warm transfer",
                        "default": False,
                    },
                },
            }
        },
    ),
}

agent_schemas = {
    "login": extend_schema(
        summary="Agent login",
        description="""
        Log an agent into the call center system.

        **State Changes:**
        - Status changes from 'offline' to 'available'
        - Agent becomes eligible to receive calls
        - Login time is recorded for reporting

        **Prerequisites:**
        - Agent account must be active
        - Agent must not already be logged in

        **Post-Login:**
        - Agent will receive calls based on queue assignment
        - Agent status can be changed (available, busy, break)
        - All agent activities are tracked
        """,
        responses={
            200: OpenApiResponse(
                description="Login successful",
                response={
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "message": {"type": "string"},
                        "agent": {"type": "object"},
                    },
                },
            ),
        },
    ),
    "set_status": extend_schema(
        summary="Update agent status",
        description="""
        Change an agent's availability status.

        **Status Options:**
        - `available`: Ready to receive calls
        - `busy`: On a call or unavailable temporarily
        - `on_break`: Break time (tracked for reporting)
        - `offline`: Logged out

        **Impact:**
        - Available agents receive calls
        - Busy agents don't receive new calls
        - Break time is tracked for productivity metrics

        **Best Practices:**
        - Always set proper status to ensure accurate reporting
        - Use 'on_break' for scheduled breaks
        - Set 'offline' before ending shift
        """,
        request={
            "application/json": {
                "type": "object",
                "required": ["status"],
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["available", "busy", "on_break", "offline"],
                        "description": "New agent status",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional reason for status change",
                        "example": "Lunch break",
                    },
                },
            }
        },
    ),
}

queue_schemas = {
    "metrics": extend_schema(
        summary="Get real-time queue metrics",
        description="""
        Retrieve current queue statistics and performance metrics.

        **Metrics Included:**
        - Current queue size
        - Average wait time
        - Longest wait time
        - Available agents
        - Service level percentage
        - Abandoned call rate

        **Use Cases:**
        - Real-time dashboard display
        - Queue monitoring
        - Overflow decision making
        - Performance tracking

        **Refresh Rate:**
        - Metrics are cached for 10 seconds
        - Real-time updates via WebSocket available
        """,
        responses={
            200: OpenApiResponse(
                description="Queue metrics",
                response={
                    "type": "object",
                    "properties": {
                        "queue_size": {"type": "integer", "example": 5},
                        "avg_wait_time": {"type": "number", "example": 45.5},
                        "max_wait_time": {"type": "number", "example": 120},
                        "available_agents": {"type": "integer", "example": 3},
                        "total_agents": {"type": "integer", "example": 8},
                        "service_level": {"type": "number", "example": 85.5},
                        "abandoned_rate": {"type": "number", "example": 5.2},
                    },
                },
            ),
        },
    ),
}

analytics_schemas = {
    "call_analytics": extend_schema(
        summary="Get call analytics",
        description="""
        Generate comprehensive call analytics for the specified period.

        **Metrics Calculated:**
        - Call volume (total, completed, abandoned)
        - Average call duration
        - Average queue time
        - Service level achievement
        - Peak hours analysis
        - Call distribution patterns

        **Filtering Options:**
        - Date range (default: last 30 days)
        - Specific queue
        - Specific agent

        **Performance Notes:**
        - Results are cached for 5 minutes
        - Large date ranges may take longer to process
        - Consider using scheduled reports for regular analytics
        """,
        parameters=[
            *DATE_FILTER_PARAMETERS,
            OpenApiParameter(
                name="queue_id",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Filter by specific queue",
            ),
            OpenApiParameter(
                name="agent_id",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Filter by specific agent",
            ),
        ],
    ),
}

# Webhook documentation
webhook_schemas = {
    "voice": extend_schema(
        summary="Handle incoming voice call webhook",
        description="""
        Twilio webhook endpoint for incoming calls.

        **When Twilio Calls This:**
        - When a call comes to your Twilio number
        - URL configured in Twilio Console

        **Expected Response:**
        - TwiML XML instructions for call handling
        - Common responses: Enqueue, Dial, Gather

        **Security:**
        - Webhook signature validation enabled
        - Only accepts requests from Twilio

        **Troubleshooting:**
        - Check Twilio Console debugger
        - Verify webhook URL is publicly accessible
        - Ensure signature validation is configured
        """,
        parameters=[
            OpenApiParameter(
                name="CallSid",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Unique identifier for the call",
                required=True,
            ),
            OpenApiParameter(
                name="From",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Caller's phone number",
                required=True,
            ),
            OpenApiParameter(
                name="To",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Called phone number",
                required=True,
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="TwiML response",
                content={"application/xml": {"schema": {"type": "string"}}},
            ),
        },
    ),
}

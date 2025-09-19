"""Call management views for django-twilio-call.

Handles call operations, transfers, recordings, and call control.
"""

import logging

from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action

from ..exceptions import CallServiceError
from ..models import Call, CallLog, CallRecording
from ..permissions import CanManageCalls
from ..serializers import (
    CallControlSerializer,
    CallCreateSerializer,
    CallLogSerializer,
    CallPositionSerializer,
    CallRecordingSerializer,
    CallSerializer,
    CallTransferSerializer,
)
from ..services import call_service
from .base import BaseCallCenterViewSet, TwilioServiceMixin

logger = logging.getLogger(__name__)


class CallViewSet(BaseCallCenterViewSet, TwilioServiceMixin):
    """ViewSet for Call model with comprehensive call management functionality."""

    queryset = Call.objects.all()
    serializer_class = CallSerializer
    permission_classes = [CanManageCalls]

    def get_queryset(self):
        """Filter queryset based on user permissions and query parameters."""
        queryset = super().get_queryset().select_related("agent__user", "queue", "phone_number_used")

        # Filter by status if requested
        call_status = self.request.query_params.get("status")
        if call_status:
            queryset = queryset.filter(status=call_status)

        # Filter by direction if requested
        direction = self.request.query_params.get("direction")
        if direction:
            queryset = queryset.filter(direction=direction)

        # Filter by agent if requested
        agent_id = self.request.query_params.get("agent_id")
        if agent_id:
            queryset = queryset.filter(agent__public_id=agent_id)

        # Filter by queue if requested
        queue_id = self.request.query_params.get("queue_id")
        if queue_id:
            queryset = queryset.filter(queue__public_id=queue_id)

        # Filter by phone number
        phone_number = self.request.query_params.get("phone_number")
        if phone_number:
            queryset = queryset.filter(Q(from_number__icontains=phone_number) | Q(to_number__icontains=phone_number))

        # Active calls filter
        if self.request.query_params.get("active") == "true":
            queryset = queryset.filter(status__in=[Call.Status.QUEUED, Call.Status.RINGING, Call.Status.IN_PROGRESS])

        return queryset

    def get_serializer_class(self):
        """Return the appropriate serializer class based on action."""
        if self.action == "create":
            return CallCreateSerializer
        return CallSerializer

    def perform_create(self, serializer):
        """Handle call creation with additional processing."""
        try:
            call = serializer.save()

            # If this is an outbound call, initiate it through the service
            if call.direction == Call.Direction.OUTBOUND:
                call_service.initiate_outbound_call(call.id)

            logger.info(f"Call {call.twilio_sid} created successfully")
        except Exception as e:
            logger.error(f"Error creating call: {e}")
            raise

    @action(detail=True, methods=["post"])
    def control(self, request, public_id=None):
        """Control call actions (hold, unhold, mute, unmute, etc.).

        Supported actions: hold, unhold, mute, unmute, record, stop_recording
        """
        call = self.get_object()
        serializer = CallControlSerializer(data=request.data)

        if not serializer.is_valid():
            return self.handle_error(
                ValueError(serializer.errors), "call control", status_code=status.HTTP_400_BAD_REQUEST
            )

        action_type = serializer.validated_data["action"]

        try:
            result = call_service.control_call(call.id, action_type)

            return self.success_response(data=result, message=f"Call {action_type} action executed successfully")
        except CallServiceError as e:
            return self.handle_error(e, f"control call {call.twilio_sid}")
        except Exception as e:
            return self.handle_error(e, f"control call {call.twilio_sid}")

    @action(detail=True, methods=["post"])
    def transfer(self, request, public_id=None):
        """Transfer call to another agent, queue, or phone number.

        Transfer types: agent, queue, external
        """
        call = self.get_object()
        serializer = CallTransferSerializer(data=request.data)

        if not serializer.is_valid():
            return self.handle_error(
                ValueError(serializer.errors), "transfer call", status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            transfer_result = call_service.transfer_call(call.id, serializer.validated_data)

            return self.success_response(data=transfer_result, message="Call transferred successfully")
        except CallServiceError as e:
            return self.handle_error(e, f"transfer call {call.twilio_sid}")
        except Exception as e:
            return self.handle_error(e, f"transfer call {call.twilio_sid}")

    @action(detail=True, methods=["get"])
    def position(self, request, public_id=None):
        """Get call position in queue.

        Returns the position and estimated wait time for queued calls.
        """
        call = self.get_object()

        if call.status != Call.Status.QUEUED or not call.queue:
            return self.handle_error(
                ValueError("Call is not currently queued"), "get call position", status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            position_data = call_service.get_call_position(call.id)
            serializer = CallPositionSerializer(position_data)

            return self.success_response(
                data=serializer.data, message=f"Position information for call {call.twilio_sid}"
            )
        except Exception as e:
            return self.handle_error(e, f"get position for call {call.twilio_sid}")

    @action(detail=True, methods=["get"])
    def recordings(self, request, public_id=None):
        """Get all recordings for this call."""
        call = self.get_object()

        try:
            recordings = CallRecording.objects.filter(call=call)
            serializer = CallRecordingSerializer(recordings, many=True)

            return self.success_response(
                data={"recordings": serializer.data, "total": recordings.count()},
                message=f"Retrieved recordings for call {call.twilio_sid}",
            )
        except Exception as e:
            return self.handle_error(e, f"get recordings for call {call.twilio_sid}")

    @action(detail=True, methods=["get"])
    def logs(self, request, public_id=None):
        """Get all logs/events for this call."""
        call = self.get_object()

        try:
            logs = CallLog.objects.filter(call=call).order_by("created_at")
            serializer = CallLogSerializer(logs, many=True)

            return self.success_response(
                data={"logs": serializer.data, "total": logs.count()},
                message=f"Retrieved logs for call {call.twilio_sid}",
            )
        except Exception as e:
            return self.handle_error(e, f"get logs for call {call.twilio_sid}")

    @action(detail=True, methods=["post"])
    def hangup(self, request, public_id=None):
        """Hang up the call.

        Terminates the call immediately.
        """
        call = self.get_object()

        try:
            call_service.hangup_call(call.id)

            return self.success_response(message=f"Call {call.twilio_sid} hung up successfully")
        except CallServiceError as e:
            return self.handle_error(e, f"hang up call {call.twilio_sid}")
        except Exception as e:
            return self.handle_error(e, f"hang up call {call.twilio_sid}")

    @action(detail=True, methods=["post"])
    def answer(self, request, public_id=None):
        """Answer an incoming call.

        Connects the call to the specified agent.
        """
        call = self.get_object()
        agent_id = request.data.get("agent_id")

        if not agent_id:
            return self.handle_error(
                ValueError("agent_id is required"), "answer call", status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            from ..models import Agent

            agent = Agent.objects.get(public_id=agent_id)

            result = call_service.answer_call(call.id, agent.id)

            return self.success_response(data=result, message=f"Call answered by agent {agent.extension}")
        except Agent.DoesNotExist:
            return self.handle_error(
                ValueError("Agent not found"), "answer call", status_code=status.HTTP_404_NOT_FOUND
            )
        except CallServiceError as e:
            return self.handle_error(e, f"answer call {call.twilio_sid}")
        except Exception as e:
            return self.handle_error(e, f"answer call {call.twilio_sid}")

    @action(detail=True, methods=["post"])
    def start_recording(self, request, public_id=None):
        """Start recording the call."""
        call = self.get_object()

        try:
            recording = call_service.start_recording(call.id)

            return self.success_response(
                data=CallRecordingSerializer(recording).data, message=f"Recording started for call {call.twilio_sid}"
            )
        except CallServiceError as e:
            return self.handle_error(e, f"start recording for call {call.twilio_sid}")
        except Exception as e:
            return self.handle_error(e, f"start recording for call {call.twilio_sid}")

    @action(detail=True, methods=["post"])
    def stop_recording(self, request, public_id=None):
        """Stop recording the call."""
        call = self.get_object()

        try:
            call_service.stop_recording(call.id)

            return self.success_response(message=f"Recording stopped for call {call.twilio_sid}")
        except CallServiceError as e:
            return self.handle_error(e, f"stop recording for call {call.twilio_sid}")
        except Exception as e:
            return self.handle_error(e, f"stop recording for call {call.twilio_sid}")

    @action(detail=True, methods=["post"])
    def add_to_conference(self, request, public_id=None):
        """Add call to a conference.

        Creates or joins an existing conference.
        """
        call = self.get_object()
        conference_name = request.data.get("conference_name")

        if not conference_name:
            return self.handle_error(
                ValueError("conference_name is required"), "add to conference", status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            result = call_service.add_to_conference(call.id, conference_name)

            return self.success_response(data=result, message=f"Call added to conference {conference_name}")
        except CallServiceError as e:
            return self.handle_error(e, f"add call {call.twilio_sid} to conference")
        except Exception as e:
            return self.handle_error(e, f"add call {call.twilio_sid} to conference")

    @action(detail=False, methods=["get"])
    def active_calls(self, request):
        """Get all currently active calls.

        Returns calls that are ringing, in progress, or queued.
        """
        try:
            active_calls = (
                Call.objects.filter(status__in=[Call.Status.QUEUED, Call.Status.RINGING, Call.Status.IN_PROGRESS])
                .select_related("agent__user", "queue")
                .order_by("-created_at")
            )

            # Apply any additional filters
            agent_id = request.query_params.get("agent_id")
            if agent_id:
                active_calls = active_calls.filter(agent__public_id=agent_id)

            queue_id = request.query_params.get("queue_id")
            if queue_id:
                active_calls = active_calls.filter(queue__public_id=queue_id)

            serializer = CallSerializer(active_calls, many=True)

            return self.success_response(
                data={"calls": serializer.data, "total": active_calls.count()},
                message=f"Retrieved {active_calls.count()} active calls",
            )
        except Exception as e:
            return self.handle_error(e, "get active calls")

    @action(detail=False, methods=["post"])
    def create_outbound(self, request):
        """Create and initiate an outbound call.

        Requires: to_number, from_number (or phone_number_id), agent_id
        """
        try:
            serializer = CallCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return self.handle_error(
                    ValueError(serializer.errors), "create outbound call", status_code=status.HTTP_400_BAD_REQUEST
                )

            call = call_service.create_outbound_call(serializer.validated_data)

            return self.success_response(
                data=CallSerializer(call).data,
                message="Outbound call created and initiated",
                status_code=status.HTTP_201_CREATED,
            )
        except CallServiceError as e:
            return self.handle_error(e, "create outbound call")
        except Exception as e:
            return self.handle_error(e, "create outbound call")

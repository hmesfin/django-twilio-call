"""API views for django-twilio-call."""

import logging

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import CallServiceError, QueueServiceError
from .models import Agent, Call, CallLog, CallRecording, PhoneNumber, Queue
from .permissions import CanAccessQueue, CanManageCalls, IsAgentOrAdmin
from .serializers import (
    AgentSerializer,
    AgentStatusUpdateSerializer,
    CallControlSerializer,
    CallCreateSerializer,
    CallLogSerializer,
    CallPositionSerializer,
    CallRecordingSerializer,
    CallSerializer,
    CallTransferSerializer,
    PhoneNumberSerializer,
    QueueSerializer,
    QueueStatisticsSerializer,
)
from .services import call_service, queue_service, twilio_service

logger = logging.getLogger(__name__)


class PhoneNumberViewSet(viewsets.ModelViewSet):
    """ViewSet for PhoneNumber model."""

    queryset = PhoneNumber.objects.all()
    serializer_class = PhoneNumberSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "public_id"

    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()

        # Filter by active status if requested
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == "true")

        # Filter by number type if requested
        number_type = self.request.query_params.get("number_type")
        if number_type:
            queryset = queryset.filter(number_type=number_type)

        return queryset.order_by("-created_at")

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def sync_from_twilio(self, request):
        """Sync phone numbers from Twilio account."""
        try:
            numbers = twilio_service.list_phone_numbers()
            created_count = 0
            updated_count = 0

            for number_data in numbers:
                phone_number, created = PhoneNumber.objects.update_or_create(
                    twilio_sid=number_data["sid"],
                    defaults={
                        "phone_number": number_data["phone_number"],
                        "friendly_name": number_data["friendly_name"],
                        "capabilities": number_data["capabilities"],
                    },
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

            return Response(
                {
                    "success": True,
                    "created": created_count,
                    "updated": updated_count,
                    "total": len(numbers),
                }
            )

        except Exception as e:
            logger.error(f"Failed to sync phone numbers: {e}")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class QueueViewSet(viewsets.ModelViewSet):
    """ViewSet for Queue model."""

    queryset = Queue.objects.all()
    serializer_class = QueueSerializer
    permission_classes = [CanAccessQueue]
    lookup_field = "public_id"

    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset().prefetch_related("agents__user")

        # Non-admins only see active queues they're assigned to
        if not self.request.user.is_staff:
            if hasattr(self.request.user, "agent_profile"):
                agent = self.request.user.agent_profile
                queryset = queryset.filter(agents=agent, is_active=True)
            else:
                queryset = queryset.none()

        # Filter by active status if requested
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == "true")

        return queryset.order_by("-priority", "name")

    @action(detail=True, methods=["get"])
    def statistics(self, request, public_id=None):
        """Get queue statistics."""
        queue = self.get_object()
        try:
            stats = queue_service.get_queue_statistics(queue.id)
            serializer = QueueStatisticsSerializer(stats)
            return Response(serializer.data)
        except QueueServiceError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def activate(self, request, public_id=None):
        """Activate a queue."""
        queue = self.get_object()
        try:
            queue_service.activate_queue(queue.id)
            return Response({"success": True, "message": f"Queue {queue.name} activated"})
        except QueueServiceError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def deactivate(self, request, public_id=None):
        """Deactivate a queue."""
        queue = self.get_object()
        try:
            queue_service.deactivate_queue(queue.id)
            return Response({"success": True, "message": f"Queue {queue.name} deactivated"})
        except QueueServiceError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["get"])
    def metrics(self, request, public_id=None):
        """Get real-time queue metrics."""
        from .services import routing_service

        queue = self.get_object()
        try:
            metrics = routing_service.get_queue_metrics(queue)
            return Response(metrics)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"])
    def route_next(self, request, public_id=None):
        """Manually trigger routing of next call in queue."""
        queue = self.get_object()
        try:
            routed_call = queue_service.route_next_call(queue.id)
            if routed_call:
                serializer = CallSerializer(routed_call)
                return Response({"success": True, "message": "Call routed successfully", "call": serializer.data})
            else:
                return Response({"success": False, "message": "No calls to route or no agents available"})
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AgentViewSet(viewsets.ModelViewSet):
    """ViewSet for Agent model."""

    queryset = Agent.objects.all()
    serializer_class = AgentSerializer
    permission_classes = [IsAgentOrAdmin]
    lookup_field = "public_id"

    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset().select_related("user").prefetch_related("queues")

        # Non-admins only see their own profile
        if not self.request.user.is_staff:
            if hasattr(self.request.user, "agent_profile"):
                queryset = queryset.filter(user=self.request.user)
            else:
                queryset = queryset.none()

        # Filter by status if requested
        agent_status = self.request.query_params.get("status")
        if agent_status:
            queryset = queryset.filter(status=agent_status)

        # Filter by queue if requested
        queue_id = self.request.query_params.get("queue_id")
        if queue_id:
            queryset = queryset.filter(queues__id=queue_id)

        return queryset.order_by("user__first_name", "user__last_name")

    @action(detail=True, methods=["post"])
    def update_status(self, request, public_id=None):
        """Update agent status."""
        agent = self.get_object()
        serializer = AgentStatusUpdateSerializer(data=request.data)

        if serializer.is_valid():
            agent.status = serializer.validated_data["status"]
            agent.save(update_fields=["status", "last_status_change"])

            # Log status change
            logger.info(f"Agent {agent.extension} status changed to {agent.status}")

            return Response(
                {
                    "success": True,
                    "status": agent.status,
                    "message": f"Status updated to {agent.get_status_display()}",
                }
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"])
    def calls(self, request, public_id=None):
        """Get agent's call history."""
        agent = self.get_object()
        calls = Call.objects.filter(agent=agent).order_by("-created_at")

        # Filter by status if requested
        call_status = request.query_params.get("status")
        if call_status:
            calls = calls.filter(status=call_status)

        # Filter by date range if requested
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            calls = calls.filter(created_at__gte=date_from)
        if date_to:
            calls = calls.filter(created_at__lte=date_to)

        # Paginate results
        page = self.paginate_queryset(calls)
        if page is not None:
            serializer = CallSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = CallSerializer(calls, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def login(self, request, public_id=None):
        """Log in an agent."""
        from .services import agent_service

        agent = self.get_object()
        extension = request.data.get("extension")
        phone_number = request.data.get("phone_number")

        try:
            updated_agent = agent_service.login_agent(
                agent.id,
                extension=extension,
                phone_number=phone_number,
            )
            serializer = AgentSerializer(updated_agent)
            return Response(
                {
                    "success": True,
                    "message": "Agent logged in successfully",
                    "agent": serializer.data,
                }
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def logout(self, request, public_id=None):
        """Log out an agent."""
        from .services import agent_service

        agent = self.get_object()

        try:
            updated_agent = agent_service.logout_agent(agent.id)
            serializer = AgentSerializer(updated_agent)
            return Response(
                {
                    "success": True,
                    "message": "Agent logged out successfully",
                    "agent": serializer.data,
                }
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def start_break(self, request, public_id=None):
        """Start agent break."""
        from .services import agent_service

        agent = self.get_object()
        break_type = request.data.get("break_type", "standard")
        duration_minutes = request.data.get("duration_minutes")

        try:
            updated_agent, expected_return = agent_service.start_break(
                agent.id,
                break_type=break_type,
                duration_minutes=duration_minutes,
            )
            serializer = AgentSerializer(updated_agent)
            return Response(
                {
                    "success": True,
                    "message": "Break started",
                    "expected_return": expected_return.isoformat(),
                    "agent": serializer.data,
                }
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def end_break(self, request, public_id=None):
        """End agent break."""
        from .services import agent_service

        agent = self.get_object()

        try:
            updated_agent = agent_service.end_break(agent.id)
            serializer = AgentSerializer(updated_agent)
            return Response(
                {
                    "success": True,
                    "message": "Break ended",
                    "agent": serializer.data,
                }
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def update_skills(self, request, public_id=None):
        """Update agent skills."""
        from .services import agent_service

        agent = self.get_object()
        skills = request.data.get("skills", [])
        append = request.data.get("append", False)

        try:
            updated_agent = agent_service.update_agent_skills(
                agent.id,
                skills=skills,
                append=append,
            )
            serializer = AgentSerializer(updated_agent)
            return Response(
                {
                    "success": True,
                    "message": "Skills updated",
                    "agent": serializer.data,
                }
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["get"])
    def performance(self, request, public_id=None):
        """Get agent performance metrics."""
        from datetime import datetime

        from .services import agent_service

        agent = self.get_object()
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        # Parse dates if provided
        if date_from:
            date_from = datetime.fromisoformat(date_from)
        if date_to:
            date_to = datetime.fromisoformat(date_to)

        try:
            metrics = agent_service.get_agent_performance(
                agent.id,
                date_from=date_from,
                date_to=date_to,
            )
            return Response(metrics)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"])
    def dashboard(self, request, public_id=None):
        """Get agent dashboard data."""
        from .services import agent_service

        agent = self.get_object()

        try:
            dashboard_data = agent_service.get_agent_dashboard(agent.id)
            return Response(dashboard_data)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CallViewSet(viewsets.ModelViewSet):
    """ViewSet for Call model."""

    queryset = Call.objects.all()
    serializer_class = CallSerializer
    permission_classes = [CanManageCalls]
    lookup_field = "public_id"

    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = (
            super()
            .get_queryset()
            .select_related("agent__user", "queue", "phone_number_used")
            .prefetch_related("recordings", "logs")
        )

        # Non-admins only see calls they're involved in
        if not self.request.user.is_staff:
            if hasattr(self.request.user, "agent_profile"):
                agent = self.request.user.agent_profile
                queryset = queryset.filter(agent=agent)
            else:
                queryset = queryset.none()

        # Apply filters
        filters = {}

        # Filter by status
        call_status = self.request.query_params.get("status")
        if call_status:
            filters["status"] = call_status

        # Filter by direction
        direction = self.request.query_params.get("direction")
        if direction:
            filters["direction"] = direction

        # Filter by agent
        agent_id = self.request.query_params.get("agent_id")
        if agent_id:
            filters["agent_id"] = agent_id

        # Filter by queue
        queue_id = self.request.query_params.get("queue_id")
        if queue_id:
            filters["queue_id"] = queue_id

        # Filter by phone number
        phone_number = self.request.query_params.get("phone_number")
        if phone_number:
            queryset = queryset.filter(Q(from_number__contains=phone_number) | Q(to_number__contains=phone_number))

        # Filter by date range
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            filters["created_at__gte"] = date_from
        if date_to:
            filters["created_at__lte"] = date_to

        return queryset.filter(**filters).order_by("-created_at")

    def create(self, request, *args, **kwargs):
        """Create an outbound call."""
        serializer = CallCreateSerializer(data=request.data)

        if serializer.is_valid():
            try:
                # Get agent ID from user if not provided
                agent_id = serializer.validated_data.get("agent_id")
                if not agent_id and hasattr(request.user, "agent_profile"):
                    agent_id = request.user.agent_profile.id

                # Create the call
                call = call_service.create_outbound_call(
                    to_number=serializer.validated_data["to_number"],
                    from_number=serializer.validated_data.get("from_number"),
                    agent_id=agent_id,
                    queue_id=serializer.validated_data.get("queue_id"),
                    url=serializer.validated_data.get("url"),
                    twiml=serializer.validated_data.get("twiml"),
                    metadata=serializer.validated_data.get("metadata", {}),
                    **{
                        k: v
                        for k, v in serializer.validated_data.items()
                        if k
                        not in [
                            "to_number",
                            "from_number",
                            "agent_id",
                            "queue_id",
                            "url",
                            "twiml",
                            "metadata",
                        ]
                    },
                )

                # Return created call
                response_serializer = CallSerializer(call)
                return Response(response_serializer.data, status=status.HTTP_201_CREATED)

            except CallServiceError as e:
                return Response(
                    {"error": str(e), "details": e.details},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def control(self, request, public_id=None):
        """Control an active call (hold, mute, end)."""
        call = self.get_object()
        serializer = CallControlSerializer(data=request.data)

        if serializer.is_valid():
            try:
                action_type = serializer.validated_data["action"]

                if action_type == "hold":
                    call_service.hold_call(
                        call.twilio_sid,
                        serializer.validated_data.get("hold_music_url"),
                    )
                    message = "Call placed on hold"

                elif action_type == "unhold":
                    call_service.resume_call(
                        call.twilio_sid,
                        serializer.validated_data.get("resume_url", ""),
                    )
                    message = "Call resumed"

                elif action_type == "end":
                    call_service.end_call(call.twilio_sid)
                    message = "Call ended"

                else:
                    return Response(
                        {"error": f"Unsupported action: {action_type}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                return Response({"success": True, "message": message})

            except CallServiceError as e:
                return Response(
                    {"error": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def transfer(self, request, public_id=None):
        """Transfer a call."""
        call = self.get_object()
        serializer = CallTransferSerializer(data=request.data)

        if serializer.is_valid():
            try:
                updated_call = call_service.transfer_call(
                    call.twilio_sid,
                    to_number=serializer.validated_data.get("to_number"),
                    to_agent_id=serializer.validated_data.get("to_agent_id"),
                    to_queue_id=serializer.validated_data.get("to_queue_id"),
                )

                response_serializer = CallSerializer(updated_call)
                return Response(response_serializer.data)

            except CallServiceError as e:
                return Response(
                    {"error": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"])
    def position(self, request, public_id=None):
        """Get call's position in queue."""
        call = self.get_object()

        if not call.queue:
            return Response(
                {"error": "Call is not in a queue"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        position = queue_service.get_queue_position(call)
        estimated_wait = queue_service.estimate_wait_time(call)

        data = {
            "position": position,
            "estimated_wait_time": estimated_wait,
            "queue_name": call.queue.name,
            "queue_size": Call.objects.filter(queue=call.queue, status=Call.Status.QUEUED).count(),
        }

        serializer = CallPositionSerializer(data)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def recordings(self, request, public_id=None):
        """Get call recordings."""
        call = self.get_object()
        recordings = CallRecording.objects.filter(call=call).order_by("-created_at")
        serializer = CallRecordingSerializer(recordings, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def logs(self, request, public_id=None):
        """Get call event logs."""
        call = self.get_object()
        logs = CallLog.objects.filter(call=call).order_by("created_at")
        serializer = CallLogSerializer(logs, many=True)
        return Response(serializer.data)


class ActiveCallsView(APIView):
    """View for getting active calls."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get list of active calls."""
        # Get filter parameters
        agent_id = request.query_params.get("agent_id")
        queue_id = request.query_params.get("queue_id")

        # Convert agent_id for non-admin users
        if not request.user.is_staff and hasattr(request.user, "agent_profile"):
            agent_id = request.user.agent_profile.id

        # Get active calls
        calls = call_service.get_active_calls(agent_id=agent_id, queue_id=queue_id)

        # Serialize and return
        serializer = CallSerializer(calls, many=True)
        return Response(serializer.data)


class CallbackView(APIView):
    """View for managing callbacks."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get pending callbacks."""
        from .services import callback_service

        queue_id = request.query_params.get("queue_id")
        due_only = request.query_params.get("due_only", "false").lower() == "true"

        # Non-admins only see callbacks for their queues
        if not request.user.is_staff and hasattr(request.user, "agent_profile"):
            agent = request.user.agent_profile
            agent_queue_ids = list(agent.queues.values_list("id", flat=True))
            if queue_id and int(queue_id) not in agent_queue_ids:
                return Response(
                    {"error": "Access denied to this queue"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        callbacks = callback_service.get_pending_callbacks(
            queue_id=int(queue_id) if queue_id else None,
            due_only=due_only,
        )

        # Convert to serializable format
        data = [
            {
                "phone_number": cb.phone_number,
                "queue_id": cb.queue_id,
                "preferred_time": cb.preferred_time.isoformat() if cb.preferred_time else None,
                "notes": cb.notes,
                "priority": cb.priority,
                "created_at": cb.created_at.isoformat(),
                "attempts": cb.attempts,
                "status": cb.status,
            }
            for cb in callbacks
        ]

        return Response(data)

    def post(self, request):
        """Request a callback."""
        from .services import callback_service

        call_id = request.data.get("call_id")
        preferred_time_str = request.data.get("preferred_time")
        notes = request.data.get("notes")

        try:
            call = Call.objects.get(public_id=call_id)

            # Parse preferred time if provided
            preferred_time = None
            if preferred_time_str:
                from datetime import datetime

                preferred_time = datetime.fromisoformat(preferred_time_str)

            callback = callback_service.request_callback(
                call=call,
                preferred_time=preferred_time,
                notes=notes,
            )

            return Response(
                {
                    "success": True,
                    "message": "Callback requested successfully",
                    "callback": {
                        "phone_number": callback.phone_number,
                        "preferred_time": callback.preferred_time.isoformat() if callback.preferred_time else None,
                        "status": callback.status,
                    },
                }
            )

        except Call.DoesNotExist:
            return Response(
                {"error": "Call not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request):
        """Cancel a callback."""
        from .services import callback_service

        phone_number = request.query_params.get("phone_number")

        if not phone_number:
            return Response(
                {"error": "Phone number is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if callback_service.cancel_callback(phone_number):
            return Response(
                {
                    "success": True,
                    "message": "Callback cancelled successfully",
                }
            )
        else:
            return Response(
                {"error": "Callback not found"},
                status=status.HTTP_404_NOT_FOUND,
            )


class CallbackStatsView(APIView):
    """View for callback statistics."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get callback statistics."""
        from .services import callback_service

        queue_id = request.query_params.get("queue_id")
        stats = callback_service.get_callback_stats(queue_id=int(queue_id) if queue_id else None)
        return Response(stats)


class AvailableAgentsView(APIView):
    """View for getting available agents."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get list of available agents."""
        from .services import agent_service

        queue_id = request.query_params.get("queue_id")
        skills = request.query_params.getlist("skills")

        agents = agent_service.get_available_agents(
            queue_id=int(queue_id) if queue_id else None,
            skills=skills if skills else None,
        )

        serializer = AgentSerializer(agents, many=True)
        return Response(serializer.data)


class AgentsSummaryView(APIView):
    """View for agent summary statistics."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get agents summary."""
        from .services import agent_service

        summary = agent_service.get_agents_summary()
        return Response(summary)


# Recording Views
class RecordingView(APIView):
    """View for managing call recordings."""

    permission_classes = [CanManageCalls]

    def post(self, request):
        """Start or stop recording."""
        from .services import recording_service

        action = request.data.get("action")  # start or stop
        call_id = request.data.get("call_id")

        if not action or not call_id:
            return Response(
                {"error": "action and call_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            call = Call.objects.get(public_id=call_id)

            if action == "start":
                recording = recording_service.start_recording(call.id)
                return Response(
                    {
                        "success": True,
                        "message": "Recording started",
                        "recording_id": recording.public_id,
                    }
                )
            elif action == "stop":
                recording = recording_service.stop_recording(call.id)
                if recording:
                    return Response(
                        {
                            "success": True,
                            "message": "Recording stopped",
                            "recording_id": recording.public_id,
                        }
                    )
                else:
                    return Response(
                        {
                            "success": False,
                            "message": "No active recording found",
                        }
                    )
            else:
                return Response(
                    {"error": "Invalid action. Use 'start' or 'stop'"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Call.DoesNotExist:
            return Response(
                {"error": "Call not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RecordingComplianceView(APIView):
    """View for recording compliance features."""

    permission_classes = [CanManageCalls]

    def post(self, request):
        """Enable/disable PCI compliance mode."""
        from .services import recording_service

        call_id = request.data.get("call_id")
        pci_mode = request.data.get("pci_mode", True)

        if not call_id:
            return Response(
                {"error": "call_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            call = Call.objects.get(public_id=call_id)
            recording_service.apply_pci_compliance(call.id, enabled=pci_mode)

            return Response(
                {
                    "success": True,
                    "message": f"PCI compliance {'enabled' if pci_mode else 'disabled'}",
                }
            )

        except Call.DoesNotExist:
            return Response(
                {"error": "Call not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# Conference Views
class ConferenceView(APIView):
    """View for managing conferences."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List active conferences."""
        from .services import conference_service

        conferences = conference_service.list_active_conferences()
        return Response(conferences)

    def post(self, request):
        """Create a new conference."""
        from .services import conference_service

        name = request.data.get("name")
        friendly_name = request.data.get("friendly_name")
        max_participants = request.data.get("max_participants", 250)
        record = request.data.get("record", False)

        if not name:
            return Response(
                {"error": "Conference name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            conference = conference_service.create_conference(
                name=name,
                friendly_name=friendly_name,
                max_participants=max_participants,
                record=record,
                moderator_id=request.user.agent_profile.id if hasattr(request.user, "agent_profile") else None,
            )

            return Response(
                {
                    "success": True,
                    "conference": {
                        "name": conference.name,
                        "friendly_name": conference.friendly_name,
                        "max_participants": conference.max_participants,
                        "is_recording": conference.record,
                    },
                }
            )

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConferenceDetailView(APIView):
    """View for conference details and management."""

    permission_classes = [IsAuthenticated]

    def get(self, request, conference_name):
        """Get conference status."""
        from .services import conference_service

        status_info = conference_service.get_conference_status(conference_name)

        if status_info:
            return Response(status_info)
        else:
            return Response(
                {"error": "Conference not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

    def delete(self, request, conference_name):
        """End a conference."""
        from .services import conference_service

        if conference_service.end_conference(conference_name):
            return Response(
                {
                    "success": True,
                    "message": f"Conference {conference_name} ended",
                }
            )
        else:
            return Response(
                {"error": "Conference not found or failed to end"},
                status=status.HTTP_404_NOT_FOUND,
            )


class ConferenceParticipantView(APIView):
    """View for managing conference participants."""

    permission_classes = [IsAuthenticated]

    def post(self, request, conference_name):
        """Add participant to conference."""
        from .services import conference_service

        call_sid = request.data.get("call_sid")
        phone_number = request.data.get("phone_number")
        is_muted = request.data.get("is_muted", False)
        is_coach = request.data.get("is_coach", False)
        is_moderator = request.data.get("is_moderator", False)

        if not call_sid or not phone_number:
            return Response(
                {"error": "call_sid and phone_number are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            participant = conference_service.add_participant(
                conference_name=conference_name,
                call_sid=call_sid,
                phone_number=phone_number,
                is_muted=is_muted,
                is_coach=is_coach,
                is_moderator=is_moderator,
            )

            return Response(
                {
                    "success": True,
                    "message": f"Participant {phone_number} added to conference",
                }
            )

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def patch(self, request, conference_name, call_sid):
        """Update participant status."""
        from .services import conference_service

        action = request.data.get("action")

        if action == "mute":
            muted = request.data.get("muted", True)
            if conference_service.mute_participant(conference_name, call_sid, muted):
                return Response(
                    {
                        "success": True,
                        "message": f"Participant {'muted' if muted else 'unmuted'}",
                    }
                )

        elif action == "hold":
            hold = request.data.get("hold", True)
            if conference_service.hold_participant(conference_name, call_sid, hold):
                return Response(
                    {
                        "success": True,
                        "message": f"Participant {'held' if hold else 'unheld'}",
                    }
                )

        elif action == "kick":
            if conference_service.kick_participant(conference_name, call_sid):
                return Response(
                    {
                        "success": True,
                        "message": "Participant removed from conference",
                    }
                )

        elif action == "promote":
            if conference_service.promote_to_moderator(conference_name, call_sid):
                return Response(
                    {
                        "success": True,
                        "message": "Participant promoted to moderator",
                    }
                )

        elif action == "coach":
            coach = request.data.get("coach", True)
            if conference_service.enable_coaching(conference_name, call_sid, coach):
                return Response(
                    {
                        "success": True,
                        "message": f"Coaching {'enabled' if coach else 'disabled'}",
                    }
                )

        else:
            return Response(
                {"error": "Invalid action"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"error": "Operation failed"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# IVR Views
class IVRFlowView(APIView):
    """View for managing IVR flows."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List all IVR flows."""
        from .services import ivr_service

        flows = []
        for flow_name, flow in ivr_service.flows.items():
            flows.append(
                {
                    "name": flow.name,
                    "language": flow.language,
                    "voice": flow.voice,
                    "node_count": len(flow.nodes),
                    "start_node": flow.start_node,
                }
            )

        return Response(flows)

    def post(self, request):
        """Create or import an IVR flow."""
        from .services import ivr_service

        name = request.data.get("name")
        config = request.data.get("config")

        if config:
            # Import flow from config
            try:
                flow = ivr_service.import_flow(config)
                return Response(
                    {
                        "success": True,
                        "message": f"Flow {flow.name} imported",
                        "flow": ivr_service.export_flow(flow.name),
                    }
                )
            except Exception as e:
                return Response(
                    {"error": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        elif name:
            # Create new flow
            language = request.data.get("language", "en-US")
            voice = request.data.get("voice", "alice")

            flow = ivr_service.create_flow(name, language, voice)

            return Response(
                {
                    "success": True,
                    "message": f"Flow {name} created",
                    "flow": {
                        "name": flow.name,
                        "language": flow.language,
                        "voice": flow.voice,
                    },
                }
            )

        else:
            return Response(
                {"error": "Either name or config is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class IVRFlowDetailView(APIView):
    """View for IVR flow details."""

    permission_classes = [IsAuthenticated]

    def get(self, request, flow_name):
        """Export IVR flow."""
        from .services import ivr_service

        flow_config = ivr_service.export_flow(flow_name)

        if flow_config:
            return Response(flow_config)
        else:
            return Response(
                {"error": "Flow not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

    def post(self, request, flow_name):
        """Add node to IVR flow."""
        from .services import ivr_service

        node_id = request.data.get("node_id")
        node_type = request.data.get("node_type")
        message = request.data.get("message")
        options = request.data.get("options")
        action = request.data.get("action")
        next_node = request.data.get("next_node")
        is_start = request.data.get("is_start", False)

        if not node_id or not node_type or not message:
            return Response(
                {"error": "node_id, node_type, and message are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            node = ivr_service.add_custom_node(
                flow_name=flow_name,
                node_id=node_id,
                node_type=node_type,
                message=message,
                options=options,
                action=action,
                next_node=next_node,
                is_start=is_start,
            )

            return Response(
                {
                    "success": True,
                    "message": f"Node {node_id} added to flow {flow_name}",
                    "node": {
                        "id": node.id,
                        "type": node.type,
                        "message": node.message,
                    },
                }
            )

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# Analytics Views
class CallAnalyticsView(APIView):
    """API view for call analytics."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get call analytics.

        Query params:
            start_date: Start of date range (ISO format)
            end_date: End of date range (ISO format)
            queue_id: Filter by queue
            agent_id: Filter by agent

        """
        from datetime import datetime

        from ..services import analytics_service

        # Parse dates
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        if start_date:
            start_date = datetime.fromisoformat(start_date)
        if end_date:
            end_date = datetime.fromisoformat(end_date)

        # Get filters
        queue_id = request.query_params.get("queue_id")
        agent_id = request.query_params.get("agent_id")

        try:
            analytics = analytics_service.get_call_analytics(
                start_date=start_date,
                end_date=end_date,
                queue_id=queue_id,
                agent_id=agent_id,
            )

            return Response(analytics)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AgentAnalyticsView(APIView):
    """API view for agent analytics."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get agent analytics.

        Query params:
            agent_id: Specific agent or all
            start_date: Start of date range (ISO format)
            end_date: End of date range (ISO format)

        """
        from datetime import datetime

        from ..services import analytics_service

        # Parse dates
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        if start_date:
            start_date = datetime.fromisoformat(start_date)
        if end_date:
            end_date = datetime.fromisoformat(end_date)

        agent_id = request.query_params.get("agent_id")

        try:
            analytics = analytics_service.get_agent_analytics(
                agent_id=agent_id,
                start_date=start_date,
                end_date=end_date,
            )

            return Response(analytics)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class QueueAnalyticsView(APIView):
    """API view for queue analytics."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get queue analytics.

        Query params:
            queue_id: Specific queue or all
            start_date: Start of date range (ISO format)
            end_date: End of date range (ISO format)

        """
        from datetime import datetime

        from ..services import analytics_service

        # Parse dates
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        if start_date:
            start_date = datetime.fromisoformat(start_date)
        if end_date:
            end_date = datetime.fromisoformat(end_date)

        queue_id = request.query_params.get("queue_id")

        try:
            analytics = analytics_service.get_queue_analytics(
                queue_id=queue_id,
                start_date=start_date,
                end_date=end_date,
            )

            return Response(analytics)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RealTimeMetricsView(APIView):
    """API view for real-time metrics."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get real-time operational metrics."""
        from ..services import analytics_service

        try:
            metrics = analytics_service.get_real_time_metrics()
            return Response(metrics)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# Reporting Views
class ReportGenerationView(APIView):
    """API view for report generation."""

    permission_classes = [IsAuthenticated, IsSupervisor]

    def post(self, request):
        """Generate a report.

        Request body:
            report_type: Type of report
            start_date: Start date (ISO format)
            end_date: End date (ISO format)
            format: Output format (csv, json, pdf, excel)
            filters: Additional filters

        """
        from datetime import datetime

        from ..services import reporting_service

        report_type = request.data.get("report_type")
        start_date = request.data.get("start_date")
        end_date = request.data.get("end_date")
        format = request.data.get("format", "csv")
        filters = request.data.get("filters", {})

        if not report_type or not start_date or not end_date:
            return Response(
                {"error": "report_type, start_date, and end_date are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Parse dates
            start_date = datetime.fromisoformat(start_date)
            end_date = datetime.fromisoformat(end_date)

            # Generate report
            report = reporting_service.generate_report(
                report_type=report_type,
                start_date=start_date,
                end_date=end_date,
                format=format,
                filters=filters,
            )

            # Return appropriate response based on format
            if format == "csv":
                response = HttpResponse(
                    report["data"],
                    content_type="text/csv",
                )
                response["Content-Disposition"] = f'attachment; filename="report_{report_type}.csv"'
                return response

            elif format == "pdf":
                response = HttpResponse(
                    report["data"],
                    content_type="application/pdf",
                )
                response["Content-Disposition"] = f'attachment; filename="report_{report_type}.pdf"'
                return response

            else:
                return Response(report)

        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ReportScheduleView(APIView):
    """API view for scheduling reports."""

    permission_classes = [IsAuthenticated, IsSupervisor]

    def post(self, request):
        """Schedule a recurring report.

        Request body:
            report_type: Type of report
            schedule: Schedule (daily, weekly, monthly)
            recipients: Email recipients list
            filters: Report filters

        """
        from ..services import reporting_service

        report_type = request.data.get("report_type")
        schedule = request.data.get("schedule")
        recipients = request.data.get("recipients", [])
        filters = request.data.get("filters", {})

        if not report_type or not schedule or not recipients:
            return Response(
                {"error": "report_type, schedule, and recipients are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = reporting_service.schedule_report(
                report_type=report_type,
                schedule=schedule,
                recipients=recipients,
                filters=filters,
            )

            return Response(result, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ReportEmailView(APIView):
    """API view for emailing reports."""

    permission_classes = [IsAuthenticated, IsSupervisor]

    def post(self, request):
        """Email a generated report.

        Request body:
            report_data: Generated report data
            recipients: Email recipients list
            subject: Email subject (optional)

        """
        from ..services import reporting_service

        report_data = request.data.get("report_data")
        recipients = request.data.get("recipients", [])
        subject = request.data.get("subject")

        if not report_data or not recipients:
            return Response(
                {"error": "report_data and recipients are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            success = reporting_service.email_report(
                report_data=report_data,
                recipients=recipients,
                subject=subject,
            )

            if success:
                return Response({"success": True, "message": "Report emailed successfully"})
            else:
                return Response(
                    {"success": False, "message": "Failed to email report"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

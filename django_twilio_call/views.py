"""API views for django-twilio-call."""

import logging
from typing import Any, Dict

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from twilio.twiml.voice_response import VoiceResponse

from .exceptions import CallServiceError, QueueServiceError
from .models import Agent, Call, CallLog, CallRecording, PhoneNumber, Queue
from .permissions import CanAccessQueue, CanManageCalls, IsAgentOrAdmin, IsTwilioWebhook
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
    WebhookDataSerializer,
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
        queryset = super().get_queryset()

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
                return Response({
                    "success": True,
                    "message": "Call routed successfully",
                    "call": serializer.data
                })
            else:
                return Response({
                    "success": False,
                    "message": "No calls to route or no agents available"
                })
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
        queryset = super().get_queryset()

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


class CallViewSet(viewsets.ModelViewSet):
    """ViewSet for Call model."""

    queryset = Call.objects.all()
    serializer_class = CallSerializer
    permission_classes = [CanManageCalls]
    lookup_field = "public_id"

    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()

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
            queryset = queryset.filter(
                Q(from_number__contains=phone_number) | Q(to_number__contains=phone_number)
            )

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
            "queue_size": Call.objects.filter(
                queue=call.queue, status=Call.Status.QUEUED
            ).count(),
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

            return Response({
                "success": True,
                "message": "Callback requested successfully",
                "callback": {
                    "phone_number": callback.phone_number,
                    "preferred_time": callback.preferred_time.isoformat() if callback.preferred_time else None,
                    "status": callback.status,
                }
            })

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
            return Response({
                "success": True,
                "message": "Callback cancelled successfully",
            })
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
        stats = callback_service.get_callback_stats(
            queue_id=int(queue_id) if queue_id else None
        )
        return Response(stats)
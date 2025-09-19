"""Base views and mixins for django-twilio-call.

Provides common functionality and error handling patterns used across
all ViewSets in the call center system.
"""

import csv
import hashlib
import hmac
import json
import logging
from datetime import timedelta
from typing import Any, Dict

from django.db import transaction
from django.db.models import Count, QuerySet
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..exceptions import CallServiceError, QueueServiceError
from ..permissions import IsAgentOrAdmin

logger = logging.getLogger(__name__)


class ErrorHandlingMixin:
    """Mixin to provide centralized error handling for ViewSets.

    Standardizes error responses and logging across all views.
    """

    def handle_error(
        self,
        error: Exception,
        action: str,
        context: Dict[str, Any] = None,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    ) -> Response:
        """Handle errors with consistent logging and response format.

        Args:
            error: The exception that occurred
            action: Description of the action being performed
            context: Additional context for logging
            status_code: HTTP status code to return

        Returns:
            Response: Standardized error response

        """
        context = context or {}
        error_message = str(error)

        # Log the error with context
        logger.error(
            f"Error in {action}: {error_message}",
            extra={
                "error_type": type(error).__name__,
                "action": action,
                "context": context,
                "view_class": self.__class__.__name__,
            },
            exc_info=True,
        )

        # Determine appropriate status code based on error type
        if isinstance(error, (CallServiceError, QueueServiceError)):
            status_code = status.HTTP_400_BAD_REQUEST
        elif isinstance(error, ValueError):
            status_code = status.HTTP_400_BAD_REQUEST
        elif isinstance(error, PermissionError):
            status_code = status.HTTP_403_FORBIDDEN

        return Response(
            {
                "success": False,
                "error": error_message,
                "error_type": type(error).__name__,
                "action": action,
            },
            status=status_code,
        )

    def success_response(
        self, data: Any = None, message: str = None, status_code: int = status.HTTP_200_OK
    ) -> Response:
        """Create a standardized success response.

        Args:
            data: Response data
            message: Success message
            status_code: HTTP status code

        Returns:
            Response: Standardized success response

        """
        response_data = {"success": True}

        if data is not None:
            response_data["data"] = data

        if message:
            response_data["message"] = message

        return Response(response_data, status=status_code)


class PermissionFilterMixin:
    """Mixin to provide common permission-based filtering with IDOR protection.

    Handles filtering querysets based on user permissions and ownership.
    Prevents Insecure Direct Object Reference (IDOR) vulnerabilities.
    """

    def filter_queryset_by_user(self, queryset: QuerySet) -> QuerySet:
        """Filter queryset based on user permissions.

        Args:
            queryset: Base queryset to filter

        Returns:
            QuerySet: Filtered queryset

        """
        user = self.request.user

        # Superusers see everything
        if user.is_superuser:
            return queryset

        # Staff users see everything by default (can be overridden)
        if user.is_staff:
            return queryset

        # Regular users see only their own data - enhanced filtering
        model = queryset.model

        # Check for direct user relationship
        if hasattr(model, "user"):
            return queryset.filter(user=user)

        # Check for owner field
        if hasattr(model, "owner"):
            return queryset.filter(owner=user)

        # Check for created_by field
        if hasattr(model, "created_by"):
            return queryset.filter(created_by=user)

        # For agent-related models
        if hasattr(model, "agent"):
            if hasattr(user, "agent_profile"):
                # User is an agent - can see their own data
                return queryset.filter(agent=user.agent_profile)
            elif hasattr(user, "agent"):
                return queryset.filter(agent=user.agent)
            else:
                # User is not an agent - no access to agent data
                return queryset.none()

        # For queue-related models
        if hasattr(model, "queue") and hasattr(user, "agent_profile"):
            # Filter by queues the agent has access to
            agent = user.agent_profile
            if hasattr(agent, "queues"):
                return queryset.filter(queue__in=agent.queues.all())

        # If no matching ownership field, return empty queryset for safety
        logger.warning(f"No ownership filtering applied for {model.__name__} - returning empty queryset")
        return queryset.none()

    def get_queryset(self) -> QuerySet:
        """Get filtered queryset based on permissions."""
        queryset = super().get_queryset()
        return self.filter_queryset_by_user(queryset)

    def get_object(self):
        """Get object with additional permission check to prevent IDOR."""
        obj = super().get_object()

        # Additional permission check
        if not self.check_object_permissions(self.request, obj):
            raise PermissionDenied("You do not have permission to access this object")

        return obj

    def check_object_permissions(self, request, obj) -> bool:
        """Check if user has permission to access the specific object.

        Args:
            request: HTTP request
            obj: Object to check permissions for

        Returns:
            bool: True if user has permission, False otherwise
        """
        user = request.user

        # Superusers always have access
        if user.is_superuser:
            return True

        # Staff users have access by default (can be overridden)
        if user.is_staff:
            return True

        # Check ownership fields
        ownership_fields = ['user', 'owner', 'created_by', 'agent']
        for field in ownership_fields:
            if hasattr(obj, field):
                owner = getattr(obj, field)
                if owner == user:
                    return True
                # Check if owner is an Agent model with user field
                if hasattr(owner, 'user') and owner.user == user:
                    return True

        # Check if user's agent has access to queue-related objects
        if hasattr(obj, 'queue') and hasattr(user, 'agent_profile'):
            agent = user.agent_profile
            if hasattr(agent, 'queues') and obj.queue in agent.queues.all():
                return True

        # Check if object is related to user's calls
        if hasattr(obj, 'call'):
            call = obj.call
            if hasattr(call, 'agent') and hasattr(user, 'agent_profile'):
                if call.agent == user.agent_profile:
                    return True
            if hasattr(call, 'user') and call.user == user:
                return True

        # No permission found
        logger.warning(f"Access denied for user {user.username} to {obj.__class__.__name__} id={obj.pk}")
        return False


class BaseCallCenterViewSet(ErrorHandlingMixin, PermissionFilterMixin, viewsets.ModelViewSet):
    """Base ViewSet for call center models.

    Combines error handling, permission filtering, and common functionality.
    """

    permission_classes = [IsAuthenticated]
    lookup_field = "public_id"

    def get_queryset(self) -> QuerySet:
        """Get the base queryset for this ViewSet."""
        queryset = super().get_queryset()

        # Apply common filtering
        queryset = self.filter_queryset_by_user(queryset)

        # Order by creation date by default
        if hasattr(queryset.model, "created_at"):
            queryset = queryset.order_by("-created_at")

        return queryset

    def perform_create(self, serializer) -> None:
        """Perform creation with error handling."""
        try:
            with transaction.atomic():
                serializer.save()
        except Exception as e:
            logger.error(f"Error creating {self.get_serializer_class().__name__}: {e}")
            raise

    def perform_update(self, serializer) -> None:
        """Perform update with error handling."""
        try:
            with transaction.atomic():
                serializer.save()
        except Exception as e:
            logger.error(f"Error updating {self.get_serializer_class().__name__}: {e}")
            raise

    def perform_destroy(self, instance) -> None:
        """Perform deletion with error handling."""
        try:
            with transaction.atomic():
                instance.delete()
        except Exception as e:
            logger.error(f"Error deleting {instance.__class__.__name__}: {e}")
            raise


class AgentAccessMixin:
    """Mixin for views that require agent access.

    Provides helper methods for agent-specific functionality.
    """

    permission_classes = [IsAgentOrAdmin]

    def get_current_agent(self):
        """Get the current user's agent profile."""
        if hasattr(self.request.user, "agent_profile"):
            return self.request.user.agent_profile
        return None

    def ensure_agent_access(self):
        """Ensure the current user has agent access."""
        if not self.get_current_agent() and not self.request.user.is_staff:
            raise PermissionError("Agent access required")


class TwilioServiceMixin:
    """Mixin for views that interact with Twilio services.

    Provides error handling specific to Twilio API operations.
    """

    def handle_twilio_error(self, error: Exception, action: str) -> Response:
        """Handle Twilio-specific errors.

        Args:
            error: Twilio error
            action: Action being performed

        Returns:
            Response: Error response

        """
        # Map common Twilio errors to appropriate status codes
        error_message = str(error)

        if "not found" in error_message.lower():
            status_code = status.HTTP_404_NOT_FOUND
        elif "unauthorized" in error_message.lower():
            status_code = status.HTTP_401_UNAUTHORIZED
        elif "rate limit" in error_message.lower():
            status_code = status.HTTP_429_TOO_MANY_REQUESTS
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        return self.handle_error(error, f"Twilio {action}", {"service": "twilio"}, status_code)


class PaginatedResponseMixin:
    """Mixin to provide consistent pagination responses."""

    def get_paginated_response_data(self, data: Any) -> Dict[str, Any]:
        """Get paginated response data in a consistent format.

        Args:
            data: Paginated data

        Returns:
            Dict: Response data with pagination info

        """
        if hasattr(self, "paginator") and self.paginator is not None:
            return self.paginator.get_paginated_response(data).data
        return data


class StatisticsMixin:
    """Mixin to add common statistics endpoints to ViewSets.

    Provides endpoints like /statistics/, /metrics/, and /summary/.
    """

    @action(detail=False, methods=["get"])
    def statistics(self, request):
        """Get basic statistics for this model."""
        try:
            queryset = self.get_queryset()

            # Basic counts
            total_count = queryset.count()

            stats = {
                "total_count": total_count,
                "model": self.queryset.model.__name__.lower(),
            }

            # Add time-based stats if created_at exists
            if hasattr(self.queryset.model, "created_at"):
                now = timezone.now()
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                week_start = now - timedelta(days=7)
                month_start = now - timedelta(days=30)

                stats.update(
                    {
                        "today_count": queryset.filter(created_at__gte=today_start).count(),
                        "week_count": queryset.filter(created_at__gte=week_start).count(),
                        "month_count": queryset.filter(created_at__gte=month_start).count(),
                    }
                )

            # Add status breakdown if status field exists
            if hasattr(self.queryset.model, "status"):
                status_counts = list(queryset.values("status").annotate(count=Count("id")).order_by("-count"))
                stats["status_breakdown"] = status_counts

            return self.success_response(data=stats)

        except Exception as e:
            return self.handle_error(e, "getting statistics")

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Get a summary view of key metrics."""
        try:
            queryset = self.get_queryset()

            summary = {
                "model": self.queryset.model.__name__.lower(),
                "total": queryset.count(),
            }

            # Add model-specific summary logic
            summary.update(self._get_model_specific_summary(queryset))

            return self.success_response(data=summary)

        except Exception as e:
            return self.handle_error(e, "getting summary")

    def _get_model_specific_summary(self, queryset):
        """Override this method in specific ViewSets for custom summaries."""
        return {}


class BulkOperationsMixin:
    """Mixin to add bulk operations support to ViewSets.

    Provides endpoints for bulk create, update, and delete operations.
    """

    @action(detail=False, methods=["post"])
    def bulk_create(self, request):
        """Create multiple objects in a single request."""
        try:
            serializer = self.get_serializer(data=request.data, many=True)
            if serializer.is_valid():
                with transaction.atomic():
                    instances = serializer.save()
                    return self.success_response(
                        data=self.get_serializer(instances, many=True).data,
                        message=f"Created {len(instances)} objects",
                        status_code=status.HTTP_201_CREATED,
                    )
            else:
                return Response(
                    {"success": False, "errors": serializer.errors, "message": "Validation failed for bulk create"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            return self.handle_error(e, "bulk create")

    @action(detail=False, methods=["patch"])
    def bulk_update(self, request):
        """Update multiple objects in a single request."""
        try:
            if not isinstance(request.data, list):
                return Response(
                    {
                        "success": False,
                        "error": "Expected a list of objects with 'id' and update data",
                        "message": "Invalid bulk update format",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            updated_objects = []
            errors = []

            with transaction.atomic():
                for item in request.data:
                    try:
                        obj_id = item.get("id") or item.get("public_id")
                        if not obj_id:
                            errors.append({"error": "Missing id/public_id", "data": item})
                            continue

                        # Get the object
                        lookup_field = self.lookup_field or "pk"
                        lookup_value = obj_id
                        instance = self.get_queryset().get(**{lookup_field: lookup_value})

                        # Update the object
                        serializer = self.get_serializer(instance, data=item, partial=True)
                        if serializer.is_valid():
                            serializer.save()
                            updated_objects.append(serializer.data)
                        else:
                            errors.append({"id": obj_id, "errors": serializer.errors})

                    except self.queryset.model.DoesNotExist:
                        errors.append({"id": obj_id, "error": "Object not found"})
                    except Exception as e:
                        errors.append({"id": obj_id, "error": str(e)})

            response_data = {
                "updated": updated_objects,
                "updated_count": len(updated_objects),
            }

            if errors:
                response_data["errors"] = errors
                response_data["error_count"] = len(errors)

            return self.success_response(data=response_data)

        except Exception as e:
            return self.handle_error(e, "bulk update")

    @action(detail=False, methods=["delete"])
    def bulk_delete(self, request):
        """Delete multiple objects in a single request."""
        try:
            ids = request.data.get("ids", [])
            if not ids:
                return Response(
                    {"success": False, "error": "No IDs provided", "message": "Expected 'ids' array in request body"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            deleted_count = 0
            errors = []

            with transaction.atomic():
                for obj_id in ids:
                    try:
                        lookup_field = self.lookup_field or "pk"
                        instance = self.get_queryset().get(**{lookup_field: obj_id})
                        instance.delete()
                        deleted_count += 1
                    except self.queryset.model.DoesNotExist:
                        errors.append({"id": obj_id, "error": "Object not found"})
                    except Exception as e:
                        errors.append({"id": obj_id, "error": str(e)})

            response_data = {
                "deleted_count": deleted_count,
                "requested_count": len(ids),
            }

            if errors:
                response_data["errors"] = errors
                response_data["error_count"] = len(errors)

            return self.success_response(data=response_data)

        except Exception as e:
            return self.handle_error(e, "bulk delete")


class ExportMixin:
    """Mixin to add CSV/JSON export functionality to ViewSets.

    Provides endpoints for exporting data in various formats.
    """

    @action(detail=False, methods=["get"])
    def export_csv(self, request):
        """Export queryset data as CSV."""
        try:
            queryset = self.filter_queryset(self.get_queryset())

            # Get field names for CSV headers
            model = self.queryset.model
            field_names = self._get_export_fields()

            # Create CSV response
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{model.__name__.lower()}_export.csv"'

            writer = csv.writer(response)

            # Write headers
            headers = [field.replace("_", " ").title() for field in field_names]
            writer.writerow(headers)

            # Write data rows
            for obj in queryset:
                row = []
                for field_name in field_names:
                    value = self._get_field_value(obj, field_name)
                    row.append(str(value) if value is not None else "")
                writer.writerow(row)

            return response

        except Exception as e:
            return self.handle_error(e, "CSV export")

    @action(detail=False, methods=["get"])
    def export_json(self, request):
        """Export queryset data as JSON."""
        try:
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)

            response_data = {
                "export_type": "json",
                "model": self.queryset.model.__name__.lower(),
                "count": len(serializer.data),
                "exported_at": timezone.now().isoformat(),
                "data": serializer.data,
            }

            response = HttpResponse(
                content_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="{self.queryset.model.__name__.lower()}_export.json"'
                },
            )

            json.dump(response_data, response, indent=2, default=str)
            return response

        except Exception as e:
            return self.handle_error(e, "JSON export")

    def _get_export_fields(self):
        """Get fields to include in export. Override for custom fields."""
        model = self.queryset.model
        exclude_fields = {"password", "metadata", "id"}

        fields = []
        for field in model._meta.fields:
            if field.name not in exclude_fields:
                fields.append(field.name)

        return fields

    def _get_field_value(self, obj, field_name):
        """Get field value from object, handling nested attributes."""
        try:
            value = getattr(obj, field_name)

            # Handle foreign key relationships
            if callable(value):
                return None

            # Handle datetime objects
            if hasattr(value, "isoformat"):
                return value.isoformat()

            return value
        except (AttributeError, TypeError):
            return None


class WebhookMixin:
    """Mixin to add webhook handling patterns to ViewSets.

    Provides common webhook validation and processing patterns.
    """

    @action(detail=False, methods=["post"], permission_classes=[])
    def webhook(self, request):
        """Handle incoming webhook requests."""
        try:
            # Validate webhook signature if configured
            if hasattr(self, "webhook_secret") and self.webhook_secret:
                if not self._validate_webhook_signature(request):
                    return Response({"error": "Invalid webhook signature"}, status=status.HTTP_401_UNAUTHORIZED)

            # Process webhook data
            webhook_data = request.data
            result = self._process_webhook(webhook_data, request)

            return self.success_response(data=result, message="Webhook processed successfully")

        except Exception as e:
            return self.handle_error(e, "webhook processing")

    def _validate_webhook_signature(self, request):
        """Validate webhook signature. Override for specific webhook providers."""
        # Generic HMAC validation
        signature_header = request.META.get("HTTP_X_SIGNATURE")
        if not signature_header:
            return False

        expected_signature = hmac.new(self.webhook_secret.encode("utf-8"), request.body, hashlib.sha256).hexdigest()

        return hmac.compare_digest(signature_header, f"sha256={expected_signature}")

    def _process_webhook(self, webhook_data, request):
        """Process webhook data. Override in specific ViewSets."""
        return {"message": "Webhook received"}


class ReadOnlyCallCenterViewSet(
    ErrorHandlingMixin,
    PermissionFilterMixin,
    PaginatedResponseMixin,
    StatisticsMixin,
    ExportMixin,
    viewsets.ReadOnlyModelViewSet,
):
    """Base read-only ViewSet for call center models.

    For models that should only support read operations.
    Includes statistics and export functionality.
    """

    permission_classes = [IsAuthenticated]
    lookup_field = "public_id"

    def get_queryset(self) -> QuerySet:
        """Get the base queryset for this ViewSet."""
        queryset = super().get_queryset()
        queryset = self.filter_queryset_by_user(queryset)

        if hasattr(queryset.model, "created_at"):
            queryset = queryset.order_by("-created_at")

        return queryset


class EnhancedCallCenterViewSet(
    ErrorHandlingMixin,
    PermissionFilterMixin,
    PaginatedResponseMixin,
    StatisticsMixin,
    BulkOperationsMixin,
    ExportMixin,
    WebhookMixin,
    BaseCallCenterViewSet,
):
    """Enhanced ViewSet with all mixins for full-featured endpoints.

    Includes statistics, bulk operations, export, and webhook support.
    """

    def _get_model_specific_summary(self, queryset):
        """Override for model-specific summary data."""
        summary = {}

        # Add common patterns
        if hasattr(self.queryset.model, "status"):
            summary["status_distribution"] = dict(
                queryset.values_list("status", flat=True).annotate(count=Count("id")).values_list("status", "count")
            )

        return summary

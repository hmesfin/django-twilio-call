"""
Base views and mixins for django-twilio-call.

Provides common functionality and error handling patterns used across
all ViewSets in the call center system.
"""

import logging
from typing import Any, Dict, Type

from django.db import transaction
from django.db.models import QuerySet
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from ..exceptions import CallServiceError, QueueServiceError
from ..permissions import IsAgentOrAdmin

logger = logging.getLogger(__name__)


class ErrorHandlingMixin:
    """
    Mixin to provide centralized error handling for ViewSets.

    Standardizes error responses and logging across all views.
    """

    def handle_error(
        self,
        error: Exception,
        action: str,
        context: Dict[str, Any] = None,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    ) -> Response:
        """
        Handle errors with consistent logging and response format.

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
                'error_type': type(error).__name__,
                'action': action,
                'context': context,
                'view_class': self.__class__.__name__,
            },
            exc_info=True
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
        self,
        data: Any = None,
        message: str = None,
        status_code: int = status.HTTP_200_OK
    ) -> Response:
        """
        Create a standardized success response.

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
    """
    Mixin to provide common permission-based filtering.

    Handles filtering querysets based on user permissions and ownership.
    """

    def filter_queryset_by_user(self, queryset: QuerySet) -> QuerySet:
        """
        Filter queryset based on user permissions.

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

        # Regular users see only their own data
        if hasattr(queryset.model, 'user'):
            return queryset.filter(user=user)

        # For agent-related models
        if hasattr(queryset.model, 'agent') and hasattr(user, 'agent_profile'):
            return queryset.filter(agent=user.agent_profile)

        return queryset

    def get_queryset(self) -> QuerySet:
        """Get filtered queryset based on permissions."""
        queryset = super().get_queryset()
        return self.filter_queryset_by_user(queryset)


class BaseCallCenterViewSet(ErrorHandlingMixin, PermissionFilterMixin, viewsets.ModelViewSet):
    """
    Base ViewSet for call center models.

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
        if hasattr(queryset.model, 'created_at'):
            queryset = queryset.order_by('-created_at')

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
    """
    Mixin for views that require agent access.

    Provides helper methods for agent-specific functionality.
    """

    permission_classes = [IsAgentOrAdmin]

    def get_current_agent(self):
        """Get the current user's agent profile."""
        if hasattr(self.request.user, 'agent_profile'):
            return self.request.user.agent_profile
        return None

    def ensure_agent_access(self):
        """Ensure the current user has agent access."""
        if not self.get_current_agent() and not self.request.user.is_staff:
            raise PermissionError("Agent access required")


class TwilioServiceMixin:
    """
    Mixin for views that interact with Twilio services.

    Provides error handling specific to Twilio API operations.
    """

    def handle_twilio_error(self, error: Exception, action: str) -> Response:
        """
        Handle Twilio-specific errors.

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

        return self.handle_error(
            error,
            f"Twilio {action}",
            {"service": "twilio"},
            status_code
        )


class PaginatedResponseMixin:
    """
    Mixin to provide consistent pagination responses.
    """

    def get_paginated_response_data(self, data: Any) -> Dict[str, Any]:
        """
        Get paginated response data in a consistent format.

        Args:
            data: Paginated data

        Returns:
            Dict: Response data with pagination info
        """
        if hasattr(self, 'paginator') and self.paginator is not None:
            return self.paginator.get_paginated_response(data).data
        return data


class ReadOnlyCallCenterViewSet(
    ErrorHandlingMixin,
    PermissionFilterMixin,
    PaginatedResponseMixin,
    viewsets.ReadOnlyModelViewSet
):
    """
    Base read-only ViewSet for call center models.

    For models that should only support read operations.
    """

    permission_classes = [IsAuthenticated]
    lookup_field = "public_id"

    def get_queryset(self) -> QuerySet:
        """Get the base queryset for this ViewSet."""
        queryset = super().get_queryset()
        queryset = self.filter_queryset_by_user(queryset)

        if hasattr(queryset.model, 'created_at'):
            queryset = queryset.order_by('-created_at')

        return queryset
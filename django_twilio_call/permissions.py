"""Custom permissions for django-twilio-call."""

from rest_framework import permissions


class IsAgentOrAdmin(permissions.BasePermission):
    """Custom permission to allow agents to access their own data.
    Admins can access all data.
    """

    def has_permission(self, request, view):
        """Check if user has permission to access the view."""
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """Check if user has permission to access the object."""
        # Admins have full access
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Check if user has an agent profile
        if not hasattr(request.user, "agent_profile"):
            return False

        agent = request.user.agent_profile

        # Agents can access their own data
        if hasattr(obj, "agent") and obj.agent == agent:
            return True

        # Agents can access calls they're involved in
        if hasattr(obj, "agent_id") and obj.agent_id == agent.id:
            return True

        return False


class IsOwnerOrAdmin(permissions.BasePermission):
    """Custom permission to allow users to access their own data.
    Admins can access all data.
    """

    def has_permission(self, request, view):
        """Check if user has permission to access the view."""
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """Check if user has permission to access the object."""
        # Admins have full access
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Check ownership
        if hasattr(obj, "user") and obj.user == request.user:
            return True

        return False


class CanManageCalls(permissions.BasePermission):
    """Permission to check if user can manage calls."""

    def has_permission(self, request, view):
        """Check if user has permission to manage calls."""
        if not request.user or not request.user.is_authenticated:
            return False

        # Admins can manage all calls
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Check if user has agent profile and is active
        if hasattr(request.user, "agent_profile"):
            agent = request.user.agent_profile
            return agent.is_active

        return False


class CanAccessQueue(permissions.BasePermission):
    """Permission to check if user can access queue data."""

    def has_permission(self, request, view):
        """Check if user has permission to access queues."""
        if not request.user or not request.user.is_authenticated:
            return False

        # Read-only access for authenticated users
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write access only for admins
        return request.user.is_staff or request.user.is_superuser

    def has_object_permission(self, request, view, obj):
        """Check if user has permission to access specific queue."""
        # Admins have full access
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Agents can view queues they're assigned to
        if hasattr(request.user, "agent_profile"):
            agent = request.user.agent_profile
            return obj in agent.queues.all()

        return False


class IsTwilioWebhook(permissions.BasePermission):
    """Permission to check if request is from Twilio webhook.
    This should be used with webhook signature validation.
    """

    def has_permission(self, request, view):
        """Check if request is from Twilio."""
        # Check for Twilio signature header
        signature = request.META.get("HTTP_X_TWILIO_SIGNATURE")
        if not signature:
            return False

        # Additional validation should be done in the view
        # using twilio_service.validate_webhook()
        return True

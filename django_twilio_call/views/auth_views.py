"""Authentication views for JWT token management.

Provides endpoints for login, logout, token refresh, and password management.
"""

import logging
from typing import Any, Dict

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from ..security import (
    generate_jwt_token,
    generate_secure_token,
    mask_sensitive_data,
    rate_limit,
)
from ..serializers.auth_serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    LogoutSerializer,
    TokenObtainPairResponseSerializer,
    TokenRefreshResponseSerializer,
    UserRegistrationSerializer,
)

logger = logging.getLogger(__name__)


class EnhancedTokenObtainPairView(TokenObtainPairView):
    """Enhanced JWT login endpoint with additional security features."""

    serializer_class = LoginSerializer
    throttle_scope = 'auth'

    @rate_limit(requests=5, window=300, key_prefix='login')
    def post(self, request: Request, *args, **kwargs) -> Response:
        """Handle login request with rate limiting and audit logging."""
        # Log login attempt
        ip_address = request.META.get('REMOTE_ADDR', 'unknown')
        logger.info(f"Login attempt from IP: {ip_address}")

        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            # Log failed attempt
            username = request.data.get('username', 'unknown')
            logger.warning(f"Failed login attempt for user: {username} from IP: {ip_address}")

            # Track failed attempts for account lockout
            self._track_failed_attempt(username, ip_address)

            return Response(
                {"error": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Get user from validated data
        user = serializer.validated_data['user']

        # Check for account lockout
        if self._is_account_locked(user.username):
            logger.warning(f"Locked account login attempt: {user.username}")
            return Response(
                {"error": "Account temporarily locked due to multiple failed attempts"},
                status=status.HTTP_423_LOCKED
            )

        # Generate tokens with custom claims
        tokens = generate_jwt_token(user, {
            'ip_address': ip_address,
            'login_time': timezone.now().isoformat(),
        })

        # Update last login
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        # Clear failed attempts
        self._clear_failed_attempts(user.username, ip_address)

        # Log successful login
        logger.info(f"Successful login for user: {user.username} from IP: {ip_address}")

        # Return tokens with user info
        response_data = {
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'expires_in': tokens['expires_in'],
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_staff': user.is_staff,
            }
        }

        return Response(response_data, status=status.HTTP_200_OK)

    def _track_failed_attempt(self, username: str, ip_address: str) -> None:
        """Track failed login attempts for rate limiting and lockout."""
        # Track by username
        user_key = f"failed_login:user:{username}"
        user_attempts = cache.get(user_key, 0)
        cache.set(user_key, user_attempts + 1, 900)  # 15 minutes

        # Track by IP
        ip_key = f"failed_login:ip:{ip_address}"
        ip_attempts = cache.get(ip_key, 0)
        cache.set(ip_key, ip_attempts + 1, 900)

        # Lock account after 5 failed attempts
        if user_attempts >= 4:  # This will be the 5th attempt
            lockout_key = f"user_lockout:{username}"
            cache.set(lockout_key, True, 1800)  # 30 minutes lockout
            logger.warning(f"Account locked due to failed attempts: {username}")

    def _is_account_locked(self, username: str) -> bool:
        """Check if account is locked due to failed attempts."""
        lockout_key = f"user_lockout:{username}"
        return bool(cache.get(lockout_key))

    def _clear_failed_attempts(self, username: str, ip_address: str) -> None:
        """Clear failed login attempts after successful login."""
        cache.delete(f"failed_login:user:{username}")
        cache.delete(f"failed_login:ip:{ip_address}")


class EnhancedTokenRefreshView(TokenRefreshView):
    """Enhanced JWT token refresh endpoint."""

    serializer_class = TokenRefreshResponseSerializer
    throttle_scope = 'auth'

    def post(self, request: Request, *args, **kwargs) -> Response:
        """Handle token refresh with additional validation."""
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            logger.warning(f"Token refresh failed: {e}")
            raise InvalidToken(e.args[0])

        # Log token refresh
        user_id = serializer.validated_data.get('user_id')
        if user_id:
            logger.info(f"Token refreshed for user ID: {user_id}")

        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """Logout endpoint that blacklists the refresh token."""

    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    def post(self, request: Request) -> Response:
        """Handle logout by blacklisting the refresh token."""
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)

            refresh_token = serializer.validated_data['refresh']
            token = RefreshToken(refresh_token)
            token.blacklist()

            # Clear any session data
            if hasattr(request, 'session'):
                request.session.flush()

            # Log logout
            logger.info(f"User {request.user.username} logged out")

            return Response(
                {"message": "Successfully logged out"},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Logout error: {e}")
            return Response(
                {"error": "Failed to logout"},
                status=status.HTTP_400_BAD_REQUEST
            )


class UserRegistrationView(generics.CreateAPIView):
    """User registration endpoint with enhanced validation."""

    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]
    throttle_scope = 'registration'

    @rate_limit(requests=3, window=3600, key_prefix='registration')
    def create(self, request: Request, *args, **kwargs) -> Response:
        """Handle user registration with rate limiting."""
        # Mask sensitive data for logging
        log_data = mask_sensitive_data(request.data.copy())
        logger.info(f"Registration attempt with data: {log_data}")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create user
        user = serializer.save()

        # Generate initial tokens
        tokens = generate_jwt_token(user)

        # Log successful registration
        logger.info(f"New user registered: {user.username}")

        # Send welcome email (async task)
        # send_welcome_email.delay(user.id)

        response_data = {
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
            },
            'tokens': tokens,
            'message': 'Registration successful. Please verify your email.',
        }

        return Response(response_data, status=status.HTTP_201_CREATED)


class ChangePasswordView(generics.UpdateAPIView):
    """Change password endpoint with security validation."""

    serializer_class = ChangePasswordSerializer
    permission_classes = [IsAuthenticated]
    throttle_scope = 'password_change'

    def get_object(self):
        """Get the current user."""
        return self.request.user

    @rate_limit(requests=3, window=600, key_prefix='password_change')
    def update(self, request: Request, *args, **kwargs) -> Response:
        """Handle password change with rate limiting."""
        user = self.get_object()
        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            # Check old password
            if not user.check_password(serializer.validated_data['old_password']):
                logger.warning(f"Failed password change attempt for user: {user.username}")
                return Response(
                    {"error": "Invalid old password"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Set new password
            user.set_password(serializer.validated_data['new_password'])
            user.save()

            # Invalidate all existing tokens for security
            # This forces re-authentication with new password
            self._invalidate_user_tokens(user)

            # Log password change
            logger.info(f"Password changed for user: {user.username}")

            # Send notification email (async)
            # send_password_change_notification.delay(user.id)

            return Response(
                {"message": "Password changed successfully. Please login again."},
                status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def _invalidate_user_tokens(self, user: User) -> None:
        """Invalidate all tokens for a user after password change."""
        # Implementation depends on your token blacklisting strategy
        # This is a placeholder for the actual implementation
        cache_key = f"user_tokens_invalid:{user.id}"
        cache.set(cache_key, True, 86400)  # 24 hours


class PasswordResetRequestView(APIView):
    """Request password reset token via email."""

    permission_classes = [AllowAny]
    throttle_scope = 'password_reset'

    @rate_limit(requests=3, window=3600, key_prefix='password_reset')
    def post(self, request: Request) -> Response:
        """Handle password reset request."""
        email = request.data.get('email')

        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(email=email)

            # Generate reset token
            reset_token = generate_secure_token()

            # Store token with expiry
            cache_key = f"password_reset:{reset_token}"
            cache.set(cache_key, user.id, 3600)  # 1 hour expiry

            # Send reset email (async)
            # send_password_reset_email.delay(user.id, reset_token)

            logger.info(f"Password reset requested for email: {email}")

        except User.DoesNotExist:
            # Don't reveal if email exists
            logger.warning(f"Password reset requested for non-existent email: {email}")

        # Always return success to prevent email enumeration
        return Response(
            {"message": "If the email exists, a reset link has been sent."},
            status=status.HTTP_200_OK
        )


class PasswordResetConfirmView(APIView):
    """Confirm password reset with token."""

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        """Handle password reset confirmation."""
        token = request.data.get('token')
        new_password = request.data.get('new_password')

        if not token or not new_password:
            return Response(
                {"error": "Token and new password are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate token
        cache_key = f"password_reset:{token}"
        user_id = cache.get(cache_key)

        if not user_id:
            logger.warning(f"Invalid or expired password reset token used")
            return Response(
                {"error": "Invalid or expired reset token"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(id=user_id)
            user.set_password(new_password)
            user.save()

            # Invalidate the reset token
            cache.delete(cache_key)

            # Invalidate all existing tokens
            # Implementation depends on your token management

            logger.info(f"Password reset completed for user: {user.username}")

            return Response(
                {"message": "Password reset successful. Please login with your new password."},
                status=status.HTTP_200_OK
            )

        except User.DoesNotExist:
            logger.error(f"User not found for password reset: {user_id}")
            return Response(
                {"error": "User not found"},
                status=status.HTTP_400_BAD_REQUEST
            )


class VerifyTokenView(APIView):
    """Verify if a JWT token is valid."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Verify the current token and return user info."""
        user = request.user

        response_data = {
            'valid': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_staff': user.is_staff,
            }
        }

        return Response(response_data, status=status.HTTP_200_OK)
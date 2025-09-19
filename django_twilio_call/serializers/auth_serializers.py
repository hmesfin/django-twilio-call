"""Serializers for authentication and user management."""

import re
from typing import Any, Dict

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework.exceptions import ValidationError


class LoginSerializer(serializers.Serializer):
    """Serializer for user login."""

    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and authenticate user."""
        username = attrs.get('username')
        password = attrs.get('password')

        if username and password:
            user = authenticate(username=username, password=password)

            if not user:
                raise ValidationError('Invalid credentials')

            if not user.is_active:
                raise ValidationError('User account is disabled')

            attrs['user'] = user
            return attrs
        else:
            raise ValidationError('Must include "username" and "password"')


class TokenObtainPairResponseSerializer(serializers.Serializer):
    """Serializer for token pair response."""

    access = serializers.CharField()
    refresh = serializers.CharField()
    expires_in = serializers.IntegerField()
    user = serializers.DictField(required=False)


class TokenRefreshResponseSerializer(serializers.Serializer):
    """Serializer for token refresh response."""

    access = serializers.CharField()
    expires_in = serializers.IntegerField(required=False)
    user_id = serializers.IntegerField(required=False)


class LogoutSerializer(serializers.Serializer):
    """Serializer for logout."""

    refresh = serializers.CharField(required=True)


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration with validation."""

    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=True)
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'password_confirm', 'first_name', 'last_name')

    def validate_email(self, value: str) -> str:
        """Validate email is unique."""
        if User.objects.filter(email=value).exists():
            raise ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_username(self, value: str) -> str:
        """Validate username format and uniqueness."""
        # Check format
        if not re.match(r'^[\w.@+-]+$', value):
            raise ValidationError("Username can only contain letters, digits and @/./+/-/_")

        # Check length
        if len(value) < 3 or len(value) > 30:
            raise ValidationError("Username must be between 3 and 30 characters")

        # Check uniqueness (case-insensitive)
        if User.objects.filter(username__iexact=value).exists():
            raise ValidationError("This username is already taken.")

        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate passwords match."""
        if attrs['password'] != attrs['password_confirm']:
            raise ValidationError({"password": "Password fields didn't match."})

        # Remove password_confirm from attrs
        attrs.pop('password_confirm', None)
        return attrs

    def create(self, validated_data: Dict[str, Any]) -> User:
        """Create user with hashed password."""
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        return user


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for password change."""

    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate new passwords match."""
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise ValidationError({"new_password": "New password fields didn't match."})

        # Check new password is different from old
        if attrs['old_password'] == attrs['new_password']:
            raise ValidationError({"new_password": "New password must be different from old password."})

        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for password reset request."""

    email = serializers.EmailField(required=True)

    def validate_email(self, value: str) -> str:
        """Validate email format."""
        return value.lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for password reset confirmation."""

    token = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, write_only=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(required=True, write_only=True)

    def validate_token(self, value: str) -> str:
        """Validate reset token format."""
        if not re.match(r'^[a-f0-9]{64}$', value):
            raise ValidationError("Invalid token format.")
        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate passwords match."""
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise ValidationError({"new_password": "Password fields didn't match."})
        return attrs


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user details."""

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active', 'date_joined')
        read_only_fields = ('id', 'date_joined')
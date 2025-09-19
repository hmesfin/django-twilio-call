"""Security configuration and utilities for django-twilio-call.

This module provides centralized security settings, authentication backends,
permission classes, and security utilities.
"""

import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, Optional, Union

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, Throttled
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken

from .constants import CacheTimeouts, Limits, SecurityDefaults

logger = logging.getLogger(__name__)


# ==============================================
# ENCRYPTION UTILITIES
# ==============================================

class EncryptionManager:
    """Manages encryption/decryption of sensitive data."""

    def __init__(self):
        """Initialize encryption manager with key from settings."""
        encryption_key = getattr(settings, 'ENCRYPTION_KEY', None)
        if not encryption_key:
            # Generate a key for development, but warn about it
            logger.warning("No ENCRYPTION_KEY found in settings. Generating temporary key.")
            encryption_key = Fernet.generate_key()

        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()

        self.cipher = Fernet(encryption_key)

    def encrypt(self, data: str) -> str:
        """Encrypt string data.

        Args:
            data: Plain text to encrypt

        Returns:
            Encrypted string (base64 encoded)
        """
        if not data:
            return data

        try:
            encrypted = self.cipher.encrypt(data.encode())
            return encrypted.decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise ValidationError("Failed to encrypt data")

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt encrypted data.

        Args:
            encrypted_data: Encrypted string to decrypt

        Returns:
            Decrypted plain text
        """
        if not encrypted_data:
            return encrypted_data

        try:
            decrypted = self.cipher.decrypt(encrypted_data.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise ValidationError("Failed to decrypt data")

    def encrypt_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Encrypt sensitive fields in a dictionary.

        Args:
            data: Dictionary with potential sensitive data

        Returns:
            Dictionary with encrypted sensitive fields
        """
        import json
        sensitive_fields = ['auth_token', 'api_key', 'password', 'secret', 'token', 'credential']

        encrypted_data = data.copy()
        for key, value in data.items():
            if any(field in key.lower() for field in sensitive_fields):
                if isinstance(value, str):
                    encrypted_data[key] = self.encrypt(value)
                elif value is not None:
                    encrypted_data[key] = self.encrypt(json.dumps(value))

        return encrypted_data


# ==============================================
# RATE LIMITING
# ==============================================

class BurstRateThrottle(UserRateThrottle):
    """Rate limiter for burst requests."""
    scope = 'burst'
    rate = '60/min'


class SustainedRateThrottle(UserRateThrottle):
    """Rate limiter for sustained requests."""
    scope = 'sustained'
    rate = '1000/hour'


class CallAPIRateThrottle(UserRateThrottle):
    """Rate limiter specifically for call-related APIs."""
    scope = 'call_api'
    rate = '100/hour'


class WebhookRateThrottle(AnonRateThrottle):
    """Rate limiter for webhook endpoints."""
    scope = 'webhook'
    rate = '1000/min'


class StrictRateThrottle(UserRateThrottle):
    """Strict rate limiter for sensitive operations."""
    scope = 'strict'
    rate = '10/hour'


def rate_limit(requests: int = 60, window: int = 60, key_prefix: str = ''):
    """Decorator for custom rate limiting.

    Args:
        requests: Number of allowed requests
        window: Time window in seconds
        key_prefix: Optional prefix for cache key
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            # Generate rate limit key
            user_id = request.user.id if request.user.is_authenticated else 'anon'
            ip_address = request.META.get('REMOTE_ADDR', 'unknown')
            cache_key = f"rate_limit:{key_prefix}:{func.__name__}:{user_id}:{ip_address}"

            # Check rate limit
            current_count = cache.get(cache_key, 0)
            if current_count >= requests:
                wait_time = cache.ttl(cache_key)
                raise Throttled(detail=f"Rate limit exceeded. Try again in {wait_time} seconds.")

            # Increment counter
            cache.set(cache_key, current_count + 1, window)

            return func(self, request, *args, **kwargs)
        return wrapper
    return decorator


# ==============================================
# AUTHENTICATION & JWT
# ==============================================

class EnhancedJWTAuthentication(JWTAuthentication):
    """Enhanced JWT authentication with additional security checks."""

    def authenticate(self, request):
        """Authenticate request with additional validation."""
        # First perform standard JWT authentication
        result = super().authenticate(request)
        if not result:
            return None

        user, token = result

        # Additional security checks
        self._validate_token_claims(token)
        self._check_user_status(user)
        self._validate_ip_address(request, token)

        return user, token

    def _validate_token_claims(self, token):
        """Validate additional token claims."""
        # Check token type
        if token.get('token_type') != 'access':
            raise AuthenticationFailed('Invalid token type')

        # Check token scope if present
        required_scope = getattr(settings, 'JWT_REQUIRED_SCOPE', None)
        if required_scope and required_scope not in token.get('scope', '').split():
            raise AuthenticationFailed('Insufficient token scope')

    def _check_user_status(self, user):
        """Check if user is allowed to authenticate."""
        if not user.is_active:
            raise AuthenticationFailed('User account is disabled')

        # Check if user has been locked out
        lockout_key = f"user_lockout:{user.id}"
        if cache.get(lockout_key):
            raise AuthenticationFailed('Account temporarily locked due to suspicious activity')

    def _validate_ip_address(self, request, token):
        """Validate request IP against token IP if IP binding is enabled."""
        if not getattr(settings, 'JWT_BIND_TO_IP', False):
            return

        token_ip = token.get('ip_address')
        request_ip = request.META.get('REMOTE_ADDR')

        if token_ip and token_ip != request_ip:
            logger.warning(f"IP mismatch for user {token.get('user_id')}: token={token_ip}, request={request_ip}")
            raise AuthenticationFailed('Token IP address mismatch')


def generate_jwt_token(user: User, include_claims: Dict[str, Any] = None) -> Dict[str, str]:
    """Generate JWT tokens with custom claims.

    Args:
        user: User instance
        include_claims: Additional claims to include in token

    Returns:
        Dictionary with access and refresh tokens
    """
    refresh = RefreshToken.for_user(user)

    # Add custom claims
    claims = {
        'user_id': user.id,
        'username': user.username,
        'email': user.email,
        'is_staff': user.is_staff,
        'token_type': 'access',
        'issued_at': datetime.utcnow().isoformat(),
    }

    if include_claims:
        claims.update(include_claims)

    # Add claims to tokens
    for key, value in claims.items():
        refresh[key] = value
        refresh.access_token[key] = value

    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'expires_in': settings.SIMPLE_JWT.get('ACCESS_TOKEN_LIFETIME').total_seconds(),
    }


# ==============================================
# PERMISSION CLASSES
# ==============================================

class IsOwnerOrAdmin(permissions.BasePermission):
    """Permission class that allows owners and admins."""

    def has_object_permission(self, request, view, obj):
        """Check object-level permission."""
        # Admins have full access
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Check ownership - try different owner field names
        owner_fields = ['user', 'owner', 'created_by', 'agent']
        for field in owner_fields:
            if hasattr(obj, field):
                owner = getattr(obj, field)
                if owner == request.user:
                    return True
                # Check if owner is an Agent model with user field
                if hasattr(owner, 'user') and owner.user == request.user:
                    return True

        return False


class IsAuthenticatedAndVerified(permissions.BasePermission):
    """Permission that requires authenticated and verified users."""

    def has_permission(self, request, view):
        """Check if user is authenticated and verified."""
        if not request.user or not request.user.is_authenticated:
            return False

        # Check if user email is verified (if using email verification)
        if hasattr(request.user, 'email_verified') and not request.user.email_verified:
            return False

        # Check if user has completed profile setup
        if hasattr(request.user, 'profile'):
            profile = request.user.profile
            if hasattr(profile, 'setup_complete') and not profile.setup_complete:
                return False

        return True


class HasAPIKey(permissions.BasePermission):
    """Permission that checks for valid API key."""

    def has_permission(self, request, view):
        """Check if request has valid API key."""
        api_key = request.META.get('HTTP_X_API_KEY')
        if not api_key:
            return False

        # Validate API key (implement your validation logic)
        return self._validate_api_key(api_key)

    def _validate_api_key(self, api_key: str) -> bool:
        """Validate API key against stored keys."""
        # Check cache first
        cache_key = f"api_key_valid:{api_key[:8]}"  # Use prefix for cache key
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        # Validate against database or settings
        valid_keys = getattr(settings, 'VALID_API_KEYS', [])
        is_valid = api_key in valid_keys

        # Cache result
        cache.set(cache_key, is_valid, CacheTimeouts.MEDIUM)

        return is_valid


class RoleBasedPermission(permissions.BasePermission):
    """Permission based on user roles."""

    # Define role hierarchy
    ROLE_HIERARCHY = {
        'superadmin': ['admin', 'supervisor', 'agent', 'viewer'],
        'admin': ['supervisor', 'agent', 'viewer'],
        'supervisor': ['agent', 'viewer'],
        'agent': ['viewer'],
        'viewer': [],
    }

    def has_permission(self, request, view):
        """Check if user has required role."""
        required_role = getattr(view, 'required_role', None)
        if not required_role:
            return True

        user_role = self._get_user_role(request.user)
        if not user_role:
            return False

        # Check if user's role includes the required role
        return required_role in self.ROLE_HIERARCHY.get(user_role, []) or user_role == required_role

    def _get_user_role(self, user) -> Optional[str]:
        """Get user's role."""
        if user.is_superuser:
            return 'superadmin'
        if user.is_staff:
            return 'admin'

        # Check if user has agent profile
        if hasattr(user, 'agent'):
            agent = user.agent
            if hasattr(agent, 'role'):
                return agent.role.lower()
            if hasattr(agent, 'is_supervisor') and agent.is_supervisor:
                return 'supervisor'
            return 'agent'

        return 'viewer'


# ==============================================
# WEBHOOK SECURITY
# ==============================================

class WebhookValidator:
    """Validates webhook requests from Twilio."""

    def __init__(self):
        """Initialize validator with Twilio credentials."""
        self.auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
        if not self.auth_token:
            raise ImproperlyConfigured("TWILIO_AUTH_TOKEN is required for webhook validation")

    def validate_request(self, request: Request) -> bool:
        """Validate Twilio webhook request signature.

        Args:
            request: Django REST framework request

        Returns:
            True if valid, False otherwise
        """
        signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
        if not signature:
            logger.warning("Missing Twilio signature header")
            return False

        # Get the full URL
        url = request.build_absolute_uri()

        # Get POST parameters
        if request.method == 'POST':
            params = request.POST.dict()
        else:
            params = request.GET.dict()

        # Calculate expected signature
        expected_signature = self._calculate_signature(url, params)

        # Compare signatures (timing-safe comparison)
        is_valid = hmac.compare_digest(signature, expected_signature)

        if not is_valid:
            logger.warning(f"Invalid webhook signature from {request.META.get('REMOTE_ADDR')}")

        return is_valid

    def _calculate_signature(self, url: str, params: Dict[str, str]) -> str:
        """Calculate expected signature for webhook.

        Args:
            url: Full URL of webhook endpoint
            params: Request parameters

        Returns:
            Base64 encoded signature
        """
        # Sort parameters by key
        sorted_params = sorted(params.items())

        # Build the string to sign
        data = url
        for key, value in sorted_params:
            data += key + value

        # Calculate HMAC-SHA1
        signature = hmac.new(
            self.auth_token.encode(),
            data.encode(),
            hashlib.sha1
        ).digest()

        # Return base64 encoded signature
        import base64
        return base64.b64encode(signature).decode()

    def validate_timestamp(self, request: Request, max_age: int = 300) -> bool:
        """Validate request timestamp to prevent replay attacks.

        Args:
            request: Django REST framework request
            max_age: Maximum age of request in seconds

        Returns:
            True if timestamp is valid, False otherwise
        """
        timestamp_str = request.data.get('Timestamp') or request.GET.get('Timestamp')
        if not timestamp_str:
            logger.warning("Missing timestamp in webhook request")
            return False

        try:
            timestamp = float(timestamp_str)
            current_time = time.time()

            # Check if timestamp is within acceptable range
            if abs(current_time - timestamp) > max_age:
                logger.warning(f"Webhook timestamp too old: {abs(current_time - timestamp)} seconds")
                return False

            # Check for replay attack using cache
            cache_key = f"webhook_timestamp:{request.path}:{timestamp}"
            if cache.get(cache_key):
                logger.warning(f"Duplicate webhook timestamp detected: {timestamp}")
                return False

            # Store timestamp to prevent replay
            cache.set(cache_key, True, max_age * 2)

            return True

        except (ValueError, TypeError) as e:
            logger.error(f"Invalid webhook timestamp: {e}")
            return False


# ==============================================
# INPUT VALIDATION
# ==============================================

class InputValidator:
    """Validates and sanitizes user input."""

    # Patterns for validation
    PHONE_PATTERN = r'^\+?1?\d{10,15}$'
    UUID_PATTERN = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

    # Dangerous patterns to block
    SQL_INJECTION_PATTERNS = [
        r'(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE)\b)',
        r'(--|#|\/\*|\*\/)',
        r'(\bOR\b.*=.*)',
        r'(\bAND\b.*=.*)',
    ]

    XSS_PATTERNS = [
        r'<script[^>]*>.*?</script>',
        r'javascript:',
        r'on\w+\s*=',
        r'<iframe[^>]*>',
    ]

    @classmethod
    def validate_phone_number(cls, phone: str) -> str:
        """Validate and normalize phone number.

        Args:
            phone: Phone number to validate

        Returns:
            Normalized phone number

        Raises:
            ValidationError: If phone number is invalid
        """
        import re

        # Remove all non-digit characters except +
        cleaned = re.sub(r'[^\d+]', '', phone)

        # Validate pattern
        if not re.match(cls.PHONE_PATTERN, cleaned):
            raise ValidationError(f"Invalid phone number format: {phone}")

        # Ensure E.164 format
        if not cleaned.startswith('+'):
            if cleaned.startswith('1') and len(cleaned) == 11:
                cleaned = '+' + cleaned
            elif len(cleaned) == 10:
                cleaned = '+1' + cleaned
            else:
                cleaned = '+' + cleaned

        return cleaned

    @classmethod
    def validate_uuid(cls, uuid_str: str) -> str:
        """Validate UUID format.

        Args:
            uuid_str: UUID string to validate

        Returns:
            Validated UUID string

        Raises:
            ValidationError: If UUID is invalid
        """
        import re

        if not re.match(cls.UUID_PATTERN, uuid_str.lower()):
            raise ValidationError(f"Invalid UUID format: {uuid_str}")

        return uuid_str.lower()

    @classmethod
    def sanitize_input(cls, text: str, field_name: str = 'input') -> str:
        """Sanitize user input to prevent injection attacks.

        Args:
            text: Input text to sanitize
            field_name: Name of field for error messages

        Returns:
            Sanitized text

        Raises:
            ValidationError: If dangerous patterns detected
        """
        import re

        if not text:
            return text

        # Check for SQL injection patterns
        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning(f"Potential SQL injection in {field_name}: {text[:100]}")
                raise ValidationError(f"Invalid characters in {field_name}")

        # Check for XSS patterns
        for pattern in cls.XSS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning(f"Potential XSS in {field_name}: {text[:100]}")
                raise ValidationError(f"Invalid HTML/JavaScript in {field_name}")

        # HTML escape special characters
        from django.utils.html import escape
        return escape(text)

    @classmethod
    def validate_json_schema(cls, data: Dict, schema: Dict) -> Dict:
        """Validate JSON data against schema.

        Args:
            data: JSON data to validate
            schema: JSON schema for validation

        Returns:
            Validated data

        Raises:
            ValidationError: If validation fails
        """
        try:
            import jsonschema
            jsonschema.validate(instance=data, schema=schema)
            return data
        except jsonschema.ValidationError as e:
            raise ValidationError(f"JSON validation failed: {e.message}")
        except Exception as e:
            raise ValidationError(f"JSON validation error: {str(e)}")


# ==============================================
# SECURITY MIDDLEWARE
# ==============================================

class SecurityHeadersMiddleware:
    """Middleware to add security headers to responses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Add security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        # Add CSP header if not already set
        if 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self' https://api.twilio.com; "
                "frame-ancestors 'none';"
            )

        # Add HSTS header for HTTPS connections
        if request.is_secure():
            response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'

        # Remove server header if present
        response.pop('Server', None)

        # Add permissions policy
        response['Permissions-Policy'] = (
            'geolocation=(), '
            'microphone=(self), '
            'camera=(), '
            'payment=(), '
            'usb=()'
        )

        return response


class AuditLoggingMiddleware:
    """Middleware to log security-relevant events."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.sensitive_paths = ['/api/auth/', '/api/calls/', '/webhooks/']

    def __call__(self, request):
        # Log request if it's sensitive
        if any(request.path.startswith(path) for path in self.sensitive_paths):
            self._log_request(request)

        response = self.get_response(request)

        # Log response for sensitive paths
        if any(request.path.startswith(path) for path in self.sensitive_paths):
            self._log_response(request, response)

        return response

    def _log_request(self, request):
        """Log incoming request details."""
        log_data = {
            'timestamp': timezone.now().isoformat(),
            'method': request.method,
            'path': request.path,
            'user': request.user.username if request.user.is_authenticated else 'anonymous',
            'ip': request.META.get('REMOTE_ADDR'),
            'user_agent': request.META.get('HTTP_USER_AGENT'),
        }

        # Don't log sensitive data
        if request.method in ['POST', 'PUT', 'PATCH']:
            log_data['has_body'] = bool(request.body)

        logger.info(f"Security audit - Request: {log_data}")

    def _log_response(self, request, response):
        """Log response details."""
        log_data = {
            'timestamp': timezone.now().isoformat(),
            'path': request.path,
            'user': request.user.username if request.user.is_authenticated else 'anonymous',
            'status_code': response.status_code,
        }

        # Log failures with more detail
        if response.status_code >= 400:
            log_data['ip'] = request.META.get('REMOTE_ADDR')
            logger.warning(f"Security audit - Failed request: {log_data}")
        else:
            logger.info(f"Security audit - Response: {log_data}")


# ==============================================
# SECRETS MANAGEMENT
# ==============================================

class SecretsManager:
    """Manages application secrets securely."""

    def __init__(self):
        """Initialize secrets manager."""
        self.encryption_manager = EncryptionManager()
        self._secrets_cache = {}

    def get_secret(self, key: str, default: Any = None) -> Any:
        """Get a secret value securely.

        Args:
            key: Secret key
            default: Default value if secret not found

        Returns:
            Secret value
        """
        # Check cache first
        if key in self._secrets_cache:
            return self._secrets_cache[key]

        # Try environment variable
        env_value = os.environ.get(key)
        if env_value:
            self._secrets_cache[key] = env_value
            return env_value

        # Try settings
        settings_value = getattr(settings, key, None)
        if settings_value:
            self._secrets_cache[key] = settings_value
            return settings_value

        # Try encrypted settings (for production)
        encrypted_key = f"ENCRYPTED_{key}"
        encrypted_value = getattr(settings, encrypted_key, None)
        if encrypted_value:
            decrypted = self.encryption_manager.decrypt(encrypted_value)
            self._secrets_cache[key] = decrypted
            return decrypted

        return default

    def set_secret(self, key: str, value: str, encrypt: bool = True) -> None:
        """Set a secret value.

        Args:
            key: Secret key
            value: Secret value
            encrypt: Whether to encrypt the value
        """
        if encrypt:
            encrypted = self.encryption_manager.encrypt(value)
            setattr(settings, f"ENCRYPTED_{key}", encrypted)
        else:
            setattr(settings, key, value)

        # Update cache
        self._secrets_cache[key] = value

    def rotate_secret(self, key: str, new_value: str) -> None:
        """Rotate a secret value.

        Args:
            key: Secret key
            new_value: New secret value
        """
        # Store old value with timestamp
        old_key = f"{key}_OLD_{int(time.time())}"
        old_value = self.get_secret(key)
        if old_value:
            self.set_secret(old_key, old_value)

        # Set new value
        self.set_secret(key, new_value)

        # Clear cache
        self._secrets_cache.pop(key, None)

        logger.info(f"Secret rotated: {key}")


# ==============================================
# SECURITY UTILITIES
# ==============================================

def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token.

    Args:
        length: Token length in bytes

    Returns:
        Hex-encoded token string
    """
    return secrets.token_hex(length)


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash a password with salt.

    Args:
        password: Plain text password
        salt: Optional salt (will be generated if not provided)

    Returns:
        Tuple of (hashed_password, salt)
    """
    if not salt:
        salt = secrets.token_hex(16)

    # Use PBKDF2 with SHA256
    hashed = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode(),
        salt.encode(),
        iterations=100000
    )

    return hashed.hex(), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify a password against its hash.

    Args:
        password: Plain text password
        hashed: Hashed password
        salt: Salt used for hashing

    Returns:
        True if password matches, False otherwise
    """
    test_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(test_hash, hashed)


def mask_sensitive_data(data: Union[str, Dict], fields_to_mask: list = None) -> Union[str, Dict]:
    """Mask sensitive data for logging.

    Args:
        data: Data to mask
        fields_to_mask: List of field names to mask

    Returns:
        Masked data
    """
    if isinstance(data, str):
        # Mask phone numbers
        import re
        data = re.sub(r'\+?\d{10,15}', lambda m: m.group()[:3] + '*' * (len(m.group()) - 6) + m.group()[-3:], data)
        # Mask email addresses
        data = re.sub(r'[\w\.-]+@[\w\.-]+', lambda m: m.group()[:3] + '***@***', data)
        return data

    if isinstance(data, dict):
        masked = data.copy()

        # Default sensitive fields
        default_fields = [
            'password', 'token', 'auth_token', 'api_key', 'secret',
            'phone_number', 'email', 'ssn', 'credit_card'
        ]

        fields = fields_to_mask or default_fields

        for key, value in data.items():
            if any(field in key.lower() for field in fields):
                if isinstance(value, str) and len(value) > 0:
                    masked[key] = value[:3] + '*' * (len(value) - 6) + value[-3:] if len(value) > 6 else '***'
                else:
                    masked[key] = '***'

        return masked

    return data


# Export main components
__all__ = [
    'EncryptionManager',
    'BurstRateThrottle',
    'SustainedRateThrottle',
    'CallAPIRateThrottle',
    'WebhookRateThrottle',
    'StrictRateThrottle',
    'rate_limit',
    'EnhancedJWTAuthentication',
    'generate_jwt_token',
    'IsOwnerOrAdmin',
    'IsAuthenticatedAndVerified',
    'HasAPIKey',
    'RoleBasedPermission',
    'WebhookValidator',
    'InputValidator',
    'SecurityHeadersMiddleware',
    'AuditLoggingMiddleware',
    'SecretsManager',
    'generate_secure_token',
    'hash_password',
    'verify_password',
    'mask_sensitive_data',
]
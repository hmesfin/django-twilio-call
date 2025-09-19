"""Centralized configuration module for django-twilio-call package.

This module provides a single source of truth for all package settings,
loading from Django settings with sensible defaults and validation.
"""

from typing import Any, Dict, Optional, Type, Union
import logging
import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .constants import (
    CacheTimeouts,
    RetryConfig,
    DefaultValues,
    Limits,
    TimeIntervals,
    ErrorThresholds,
    SERVICE_CACHE_TIMEOUTS,
    OPERATION_RETRY_CONFIGS,
    SERVICE_BATCH_SIZES,
)

logger = logging.getLogger(__name__)

class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing."""
    pass

class PackageConfig:
    """Centralized configuration for django-twilio-call package."""

    def __init__(self):
        """Initialize configuration with validation."""
        self._cache = {}
        self._validated = False
        self._load_and_validate()

    def _load_and_validate(self) -> None:
        """Load all configuration and validate settings."""
        if self._validated:
            return

        try:
            # Load all configuration sections
            self._load_twilio_config()
            self._load_cache_config()
            self._load_retry_config()
            self._load_queue_config()
            self._load_agent_config()
            self._load_call_config()
            self._load_recording_config()
            self._load_monitoring_config()
            self._load_performance_config()
            self._load_feature_flags()
            self._load_environment_config()

            # Validate critical settings
            self._validate_critical_settings()
            self._validated = True

            logger.info("Django-Twilio-Call configuration loaded and validated successfully")

        except Exception as e:
            logger.error(f"Configuration loading failed: {e}")
            raise ConfigurationError(f"Failed to load configuration: {e}") from e

    # ===========================================
    # TWILIO CONFIGURATION
    # ===========================================

    def _load_twilio_config(self) -> None:
        """Load Twilio API configuration using SecretsManager."""
        # Import here to avoid circular dependency
        from .security import SecretsManager
        secrets = SecretsManager()

        # Load secrets securely
        self.TWILIO_ACCOUNT_SID = secrets.get_secret("TWILIO_ACCOUNT_SID")
        if not self.TWILIO_ACCOUNT_SID:
            raise ConfigurationError("TWILIO_ACCOUNT_SID is required")

        self.TWILIO_AUTH_TOKEN = secrets.get_secret("TWILIO_AUTH_TOKEN")
        self.TWILIO_API_KEY = secrets.get_secret("TWILIO_API_KEY")
        self.TWILIO_API_SECRET = secrets.get_secret("TWILIO_API_SECRET")
        self.TWILIO_PHONE_NUMBER = self._get_setting("TWILIO_PHONE_NUMBER")
        self.TWILIO_WEBHOOK_URL = self._get_setting("TWILIO_WEBHOOK_URL")

        # Webhook settings
        self.TWILIO_WEBHOOK_VALIDATE = self._get_setting("TWILIO_WEBHOOK_VALIDATE", True)
        self.TWILIO_WEBHOOK_AUTH_TOKEN = self._get_setting(
            "TWILIO_WEBHOOK_AUTH_TOKEN", self.TWILIO_AUTH_TOKEN
        )

        # API settings with constants
        self.TWILIO_MAX_RETRIES = self._get_setting("TWILIO_MAX_RETRIES", RetryConfig.DEFAULT_MAX_RETRIES)
        self.TWILIO_RETRY_BACKOFF_BASE = self._get_setting(
            "TWILIO_RETRY_BACKOFF_BASE", RetryConfig.DEFAULT_BACKOFF_MULTIPLIER
        )
        self.TWILIO_RETRY_BACKOFF_MAX = self._get_setting(
            "TWILIO_RETRY_BACKOFF_MAX", RetryConfig.DEFAULT_MAX_DELAY
        )
        self.TWILIO_REQUEST_TIMEOUT = self._get_setting(
            "TWILIO_REQUEST_TIMEOUT", DefaultValues.RECORDING_TIMEOUT
        )

        # Connection pool settings
        self.TWILIO_CONNECTION_POOL_SIZE = self._get_setting("TWILIO_CONNECTION_POOL_SIZE", 10)
        self.TWILIO_CONNECTION_POOL_MAXSIZE = self._get_setting("TWILIO_CONNECTION_POOL_MAXSIZE", 50)

    # ===========================================
    # CACHE CONFIGURATION
    # ===========================================

    def _load_cache_config(self) -> None:
        """Load caching configuration."""
        self.CACHE_BACKEND = self._get_setting("DJANGO_TWILIO_CACHE_BACKEND", "default")
        self.CACHE_TIMEOUT = self._get_setting("DJANGO_TWILIO_CACHE_TIMEOUT", CacheTimeouts.SHORT)

        # Service-specific cache timeouts
        self.CACHE_TIMEOUTS = {}
        for service_type, default_timeout in SERVICE_CACHE_TIMEOUTS.items():
            setting_name = f"DJANGO_TWILIO_CACHE_TIMEOUT_{service_type.upper()}"
            self.CACHE_TIMEOUTS[service_type] = self._get_setting(setting_name, default_timeout)

        # Cache key settings
        self.CACHE_KEY_PREFIX = self._get_setting("DJANGO_TWILIO_CACHE_KEY_PREFIX", "django_twilio")
        self.CACHE_KEY_VERSION = self._get_setting("DJANGO_TWILIO_CACHE_KEY_VERSION", 1)

    # ===========================================
    # RETRY CONFIGURATION
    # ===========================================

    def _load_retry_config(self) -> None:
        """Load retry configuration for different operation types."""
        self.RETRY_CONFIGS = {}

        for operation_type, default_config in OPERATION_RETRY_CONFIGS.items():
            config = {}
            prefix = f"DJANGO_TWILIO_RETRY_{operation_type.upper()}"

            config["max_retries"] = self._get_setting(
                f"{prefix}_MAX_RETRIES", default_config.get("max_retries", RetryConfig.DEFAULT_MAX_RETRIES)
            )
            config["base_delay"] = self._get_setting(
                f"{prefix}_BASE_DELAY", default_config.get("base_delay", RetryConfig.DEFAULT_BASE_DELAY)
            )
            config["max_delay"] = self._get_setting(
                f"{prefix}_MAX_DELAY", default_config.get("max_delay", RetryConfig.DEFAULT_MAX_DELAY)
            )
            config["multiplier"] = self._get_setting(
                f"{prefix}_MULTIPLIER", default_config.get("multiplier", RetryConfig.DEFAULT_BACKOFF_MULTIPLIER)
            )

            # Special handling for webhook delays
            if "delays" in default_config:
                config["delays"] = self._get_setting(f"{prefix}_DELAYS", default_config["delays"])

            self.RETRY_CONFIGS[operation_type] = config

        # Circuit breaker settings
        self.CIRCUIT_BREAKER_FAILURE_THRESHOLD = self._get_setting(
            "DJANGO_TWILIO_CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5
        )
        self.CIRCUIT_BREAKER_RECOVERY_TIMEOUT = self._get_setting(
            "DJANGO_TWILIO_CIRCUIT_BREAKER_RECOVERY_TIMEOUT", TimeIntervals.FIVE_MINUTES
        )

    # ===========================================
    # QUEUE CONFIGURATION
    # ===========================================

    def _load_queue_config(self) -> None:
        """Load queue configuration."""
        self.MAX_QUEUE_SIZE = self._get_setting("MAX_QUEUE_SIZE", DefaultValues.MAX_QUEUE_SIZE)
        self.DEFAULT_QUEUE_TIMEOUT = self._get_setting("DEFAULT_QUEUE_TIMEOUT", DefaultValues.QUEUE_TIMEOUT_SECONDS)
        self.DEFAULT_HOLD_MUSIC_URL = self._get_setting(
            "DEFAULT_HOLD_MUSIC_URL",
            "http://com.twilio.music.classical.s3.amazonaws.com/ith_brahms-116-4.mp3"
        )

        # Queue performance thresholds
        self.QUEUE_WARNING_TIME = self._get_setting(
            "DJANGO_TWILIO_QUEUE_WARNING_TIME", ErrorThresholds.WARNING_QUEUE_TIME
        )
        self.QUEUE_CRITICAL_TIME = self._get_setting(
            "DJANGO_TWILIO_QUEUE_CRITICAL_TIME", ErrorThresholds.CRITICAL_QUEUE_TIME
        )

        # Service level configuration
        self.SERVICE_LEVEL_THRESHOLD = self._get_setting(
            "DJANGO_TWILIO_SERVICE_LEVEL_THRESHOLD", DefaultValues.SERVICE_LEVEL_THRESHOLD
        )

    # ===========================================
    # AGENT CONFIGURATION
    # ===========================================

    def _load_agent_config(self) -> None:
        """Load agent configuration."""
        self.DEFAULT_AGENT_MAX_CONCURRENT_CALLS = self._get_setting(
            "DEFAULT_AGENT_MAX_CONCURRENT_CALLS", DefaultValues.MAX_CONCURRENT_CALLS
        )
        self.AGENT_STATUS_UPDATE_WEBHOOK = self._get_setting("AGENT_STATUS_UPDATE_WEBHOOK")

        # Agent break durations
        self.AGENT_BREAK_DURATIONS = {
            "lunch": self._get_setting("DJANGO_TWILIO_AGENT_LUNCH_DURATION", DefaultValues.LUNCH_DURATION_MINUTES),
            "training": self._get_setting("DJANGO_TWILIO_AGENT_TRAINING_DURATION", DefaultValues.TRAINING_DURATION_MINUTES),
            "break": self._get_setting("DJANGO_TWILIO_AGENT_BREAK_DURATION", DefaultValues.BREAK_DURATION_MINUTES),
        }

        # Agent performance thresholds
        self.AGENT_PERFORMANCE_THRESHOLD = self._get_setting("DJANGO_TWILIO_AGENT_PERFORMANCE_THRESHOLD", 80.0)

    # ===========================================
    # CALL CONFIGURATION
    # ===========================================

    def _load_call_config(self) -> None:
        """Load call configuration."""
        self.DEFAULT_CALL_TIME_LIMIT = self._get_setting(
            "DEFAULT_CALL_TIME_LIMIT", DefaultValues.CALL_TIME_LIMIT
        )
        self.DEFAULT_RING_TIMEOUT = self._get_setting(
            "DEFAULT_RING_TIMEOUT", DefaultValues.RING_TIMEOUT
        )
        self.DEFAULT_CALLER_ID = self._get_setting("DEFAULT_CALLER_ID", self.TWILIO_PHONE_NUMBER)

        # Call performance thresholds
        self.SLOW_CALL_THRESHOLD = self._get_setting(
            "DJANGO_TWILIO_SLOW_CALL_THRESHOLD", DefaultValues.SLOW_OPERATION_THRESHOLD
        )

    # ===========================================
    # RECORDING CONFIGURATION
    # ===========================================

    def _load_recording_config(self) -> None:
        """Load recording configuration."""
        self.ENABLE_CALL_RECORDING = self._get_setting("ENABLE_CALL_RECORDING", True)
        self.RECORDING_STATUS_CALLBACK_URL = self._get_setting("RECORDING_STATUS_CALLBACK_URL")
        self.RECORDING_STORAGE_BACKEND = self._get_setting("RECORDING_STORAGE_BACKEND", "local")
        self.RECORDING_ENCRYPTION_KEY = self._get_setting("RECORDING_ENCRYPTION_KEY")
        self.RECORDING_RETENTION_DAYS = self._get_setting(
            "RECORDING_RETENTION_DAYS", Limits.RECORDING_RETENTION_DAYS
        )
        self.RECORDING_URL_EXPIRY = self._get_setting(
            "DJANGO_TWILIO_RECORDING_URL_EXPIRY", CacheTimeouts.RECORDING_URLS
        )

    # ===========================================
    # MONITORING CONFIGURATION
    # ===========================================

    def _load_monitoring_config(self) -> None:
        """Load monitoring and alerting configuration."""
        # Health check intervals
        self.HEALTH_CHECK_INTERVAL = self._get_setting(
            "DJANGO_TWILIO_HEALTH_CHECK_INTERVAL", TimeIntervals.HEALTH_CHECK_INTERVAL
        )
        self.METRICS_COLLECTION_INTERVAL = self._get_setting(
            "DJANGO_TWILIO_METRICS_COLLECTION_INTERVAL", TimeIntervals.METRICS_COLLECTION_INTERVAL
        )

        # Error thresholds
        self.WARNING_ERROR_RATE = self._get_setting(
            "DJANGO_TWILIO_WARNING_ERROR_RATE", ErrorThresholds.WARNING_ERROR_RATE
        )
        self.CRITICAL_ERROR_RATE = self._get_setting(
            "DJANGO_TWILIO_CRITICAL_ERROR_RATE", ErrorThresholds.CRITICAL_ERROR_RATE
        )

        # Response time thresholds
        self.WARNING_RESPONSE_TIME = self._get_setting(
            "DJANGO_TWILIO_WARNING_RESPONSE_TIME", ErrorThresholds.WARNING_RESPONSE_TIME
        )
        self.CRITICAL_RESPONSE_TIME = self._get_setting(
            "DJANGO_TWILIO_CRITICAL_RESPONSE_TIME", ErrorThresholds.CRITICAL_RESPONSE_TIME
        )

        # Alert settings
        self.ENABLE_ALERTS = self._get_setting("DJANGO_TWILIO_ENABLE_ALERTS", True)
        self.ALERT_WEBHOOK_URL = self._get_setting("DJANGO_TWILIO_ALERT_WEBHOOK_URL")

    # ===========================================
    # PERFORMANCE CONFIGURATION
    # ===========================================

    def _load_performance_config(self) -> None:
        """Load performance-related configuration."""
        # Batch sizes for different operations
        self.BATCH_SIZES = {}
        for operation_type, default_size in SERVICE_BATCH_SIZES.items():
            setting_name = f"DJANGO_TWILIO_BATCH_SIZE_{operation_type.upper()}"
            self.BATCH_SIZES[operation_type] = self._get_setting(setting_name, default_size)

        # General performance settings
        self.DEFAULT_BATCH_SIZE = self._get_setting(
            "DJANGO_TWILIO_DEFAULT_BATCH_SIZE", DefaultValues.BATCH_SIZE
        )
        self.MAX_PAGE_SIZE = self._get_setting(
            "DJANGO_TWILIO_MAX_PAGE_SIZE", DefaultValues.MAX_PAGE_SIZE
        )
        self.DEFAULT_PAGE_SIZE = self._get_setting(
            "DJANGO_TWILIO_DEFAULT_PAGE_SIZE", DefaultValues.DEFAULT_PAGE_SIZE
        )

        # Operation timeouts
        self.SLOW_OPERATION_THRESHOLD = self._get_setting(
            "DJANGO_TWILIO_SLOW_OPERATION_THRESHOLD", DefaultValues.SLOW_OPERATION_THRESHOLD
        )

    # ===========================================
    # FEATURE FLAGS
    # ===========================================

    def _load_feature_flags(self) -> None:
        """Load feature flag configuration."""
        self.ENABLE_CALL_RECORDING = self._get_setting("ENABLE_CALL_RECORDING", True)
        self.ENABLE_TRANSCRIPTION = self._get_setting("ENABLE_TRANSCRIPTION", False)
        self.ENABLE_VOICEMAIL = self._get_setting("ENABLE_VOICEMAIL", True)
        self.ENABLE_CONFERENCE = self._get_setting("ENABLE_CONFERENCE", True)
        self.ENABLE_IVR = self._get_setting("ENABLE_IVR", True)
        self.ENABLE_QUEUE_CALLBACKS = self._get_setting("ENABLE_QUEUE_CALLBACKS", True)
        self.ENABLE_ANALYTICS = self._get_setting("ENABLE_ANALYTICS", True)
        self.ENABLE_REAL_TIME_METRICS = self._get_setting("ENABLE_REAL_TIME_METRICS", True)

    # ===========================================
    # ENVIRONMENT CONFIGURATION
    # ===========================================

    def _load_environment_config(self) -> None:
        """Load environment-specific configuration."""
        self.DEBUG = getattr(settings, "DEBUG", False)
        self.TESTING = getattr(settings, "TESTING", False)

        # Logging configuration
        self.LOG_LEVEL = self._get_setting("DJANGO_TWILIO_LOG_LEVEL", "INFO")
        self.LOG_API_REQUESTS = self._get_setting("DJANGO_TWILIO_LOG_API_REQUESTS", True)
        self.LOG_WEBHOOKS = self._get_setting("DJANGO_TWILIO_LOG_WEBHOOKS", True)
        self.LOG_PERFORMANCE = self._get_setting("DJANGO_TWILIO_LOG_PERFORMANCE", self.DEBUG)

        # Development settings
        if self.DEBUG:
            self._apply_development_overrides()

        # Testing settings
        if self.TESTING:
            self._apply_testing_overrides()

    def _apply_development_overrides(self) -> None:
        """Apply development-specific configuration overrides."""
        # Shorter cache timeouts for development
        self.CACHE_TIMEOUT = min(self.CACHE_TIMEOUT, CacheTimeouts.VERY_SHORT)

        # More verbose logging
        self.LOG_LEVEL = "DEBUG"

        # Reduced batch sizes for faster development feedback
        for operation_type in self.BATCH_SIZES:
            self.BATCH_SIZES[operation_type] = min(self.BATCH_SIZES[operation_type], 100)

    def _apply_testing_overrides(self) -> None:
        """Apply testing-specific configuration overrides."""
        # Very short cache timeouts for testing
        self.CACHE_TIMEOUT = CacheTimeouts.VERY_SHORT

        # Reduce retry attempts for faster tests
        for operation_type in self.RETRY_CONFIGS:
            self.RETRY_CONFIGS[operation_type]["max_retries"] = 1
            self.RETRY_CONFIGS[operation_type]["base_delay"] = 1
            self.RETRY_CONFIGS[operation_type]["max_delay"] = 5

        # Smaller batch sizes for testing
        for operation_type in self.BATCH_SIZES:
            self.BATCH_SIZES[operation_type] = min(self.BATCH_SIZES[operation_type], 10)

        # Disable external integrations
        self.ENABLE_ALERTS = False
        self.LOG_API_REQUESTS = False

    # ===========================================
    # UTILITY METHODS
    # ===========================================

    def _get_setting(self, name: str, default: Any = None, required: bool = False) -> Any:
        """Get a setting value with caching."""
        if name in self._cache:
            return self._cache[name]

        # Try environment variable first (for Docker deployment)
        env_value = os.environ.get(name)
        if env_value is not None:
            # Convert string values to appropriate types
            value = self._convert_env_value(env_value)
            self._cache[name] = value
            return value

        # Try Django settings
        value = getattr(settings, name, default)

        if required and value is None:
            raise ConfigurationError(f"Required setting {name} is not configured")

        self._cache[name] = value
        return value

    def _convert_env_value(self, value: str) -> Any:
        """Convert environment variable string to appropriate type."""
        # Handle boolean values
        if value.lower() in ("true", "yes", "1", "on"):
            return True
        elif value.lower() in ("false", "no", "0", "off"):
            return False

        # Handle numeric values
        try:
            if "." in value:
                return float(value)
            else:
                return int(value)
        except ValueError:
            pass

        # Handle list values (comma-separated)
        if "," in value:
            return [item.strip() for item in value.split(",")]

        # Return as string
        return value

    def _validate_critical_settings(self) -> None:
        """Validate critical settings that must be properly configured."""
        errors = []

        # Validate Twilio credentials
        if not self.TWILIO_ACCOUNT_SID:
            errors.append("TWILIO_ACCOUNT_SID is required")

        if not self.TWILIO_AUTH_TOKEN and not (self.TWILIO_API_KEY and self.TWILIO_API_SECRET):
            errors.append("Either TWILIO_AUTH_TOKEN or both TWILIO_API_KEY and TWILIO_API_SECRET are required")

        # Validate phone number configuration
        if not self.TWILIO_PHONE_NUMBER and not self.DEFAULT_CALLER_ID:
            errors.append("Either TWILIO_PHONE_NUMBER or DEFAULT_CALLER_ID is required")

        # Validate cache timeouts are positive
        if self.CACHE_TIMEOUT <= 0:
            errors.append("CACHE_TIMEOUT must be positive")

        # Validate retry configurations
        for operation_type, config in self.RETRY_CONFIGS.items():
            if config["max_retries"] < 0:
                errors.append(f"Max retries for {operation_type} must be non-negative")
            if config["base_delay"] <= 0:
                errors.append(f"Base delay for {operation_type} must be positive")

        if errors:
            error_msg = f"Django-Twilio-Call configuration errors: {', '.join(errors)}"
            raise ConfigurationError(error_msg)

    # ===========================================
    # CONFIGURATION ACCESS METHODS
    # ===========================================

    def get_cache_timeout(self, service_type: str = "default") -> int:
        """Get cache timeout for a specific service type."""
        return self.CACHE_TIMEOUTS.get(service_type, self.CACHE_TIMEOUT)

    def get_retry_config(self, operation_type: str = "default") -> Dict[str, Any]:
        """Get retry configuration for a specific operation type."""
        return self.RETRY_CONFIGS.get(operation_type, self.RETRY_CONFIGS["default"])

    def get_batch_size(self, operation_type: str = "default") -> int:
        """Get batch size for a specific operation type."""
        return self.BATCH_SIZES.get(operation_type, self.DEFAULT_BATCH_SIZE)

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if a feature is enabled."""
        feature_attr = f"ENABLE_{feature_name.upper()}"
        return getattr(self, feature_attr, False)

    def get_environment_type(self) -> str:
        """Get the current environment type."""
        if self.TESTING:
            return "testing"
        elif self.DEBUG:
            return "development"
        else:
            return "production"

    def to_dict(self) -> Dict[str, Any]:
        """Export configuration as dictionary (for debugging/inspection)."""
        config_dict = {}

        for attr_name in dir(self):
            if not attr_name.startswith("_") and not callable(getattr(self, attr_name)):
                attr_value = getattr(self, attr_name)
                # Don't expose sensitive values
                if "token" in attr_name.lower() or "secret" in attr_name.lower() or "key" in attr_name.lower():
                    config_dict[attr_name] = "***HIDDEN***"
                else:
                    config_dict[attr_name] = attr_value

        return config_dict


# Singleton instance
_config_instance: Optional[PackageConfig] = None

def get_config() -> PackageConfig:
    """Get the singleton configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = PackageConfig()
    return _config_instance

def reload_config() -> PackageConfig:
    """Reload configuration (useful for testing)."""
    global _config_instance
    _config_instance = None
    return get_config()

# Convenience access to common settings
def get_cache_timeout(service_type: str = "default") -> int:
    """Get cache timeout for a service type."""
    return get_config().get_cache_timeout(service_type)

def get_retry_config(operation_type: str = "default") -> Dict[str, Any]:
    """Get retry configuration for an operation type."""
    return get_config().get_retry_config(operation_type)

def get_batch_size(operation_type: str = "default") -> int:
    """Get batch size for an operation type."""
    return get_config().get_batch_size(operation_type)

def is_feature_enabled(feature_name: str) -> bool:
    """Check if a feature is enabled."""
    return get_config().is_feature_enabled(feature_name)
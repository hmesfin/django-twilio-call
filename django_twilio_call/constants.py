"""Constants for django-twilio-call package.

This module centralizes all hardcoded values used throughout the package,
including cache timeouts, retry configurations, thresholds, and defaults.
"""

from typing import Dict, Any

# ===========================================
# CACHE TIMEOUT CONSTANTS (seconds)
# ===========================================

class CacheTimeouts:
    """Cache timeout constants organized by duration and use case."""

    # Short-term caches (1-5 minutes)
    VERY_SHORT = 60          # 1 minute - for frequently changing data
    SHORT = 300              # 5 minutes - standard service cache

    # Medium-term caches (10-60 minutes)
    MEDIUM = 600             # 10 minutes - for semi-static data
    STANDARD = 1800          # 30 minutes - analytics and reports
    LONG = 3600              # 1 hour - for stable data

    # Long-term caches (hours)
    VERY_LONG = 7200         # 2 hours - for rarely changing data
    EXTENDED = 14400         # 4 hours - configuration and metadata
    DAILY = 86400            # 24 hours - daily aggregates

    # Service-specific timeouts
    AGENT_STATUS = 300       # Agent status cache
    CALL_ANALYTICS = 300     # Call analytics cache
    QUEUE_METRICS = 180      # Queue metrics cache
    IVR_FLOWS = 3600         # IVR flow definitions
    RECORDING_URLS = 1800    # Recording URL cache
    CONFERENCE_DATA = 600    # Conference room data
    ROUTING_RULES = 1800     # Call routing rules

class CacheKeyPrefixes:
    """Cache key prefixes for different service types."""

    AGENT = "agent"
    CALL = "call"
    QUEUE = "queue"
    ANALYTICS = "analytics"
    METRICS = "metrics"
    IVR = "ivr"
    RECORDING = "recording"
    CONFERENCE = "conference"
    ROUTING = "routing"
    REPORTING = "reporting"
    WEBHOOK = "webhook"

    # Combined prefixes for complex operations
    CALL_ANALYTICS = "call_analytics"
    QUEUE_ANALYTICS = "queue_analytics"
    AGENT_PERFORMANCE = "agent_performance"

# ===========================================
# RETRY CONFIGURATION CONSTANTS
# ===========================================

class RetryConfig:
    """Retry configuration constants for different operation types."""

    # Base retry settings
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_BASE_DELAY = 60          # 1 minute
    DEFAULT_MAX_DELAY = 3600         # 1 hour
    DEFAULT_BACKOFF_MULTIPLIER = 2   # Exponential backoff

    # Connection retry settings
    CONNECTION_MAX_RETRIES = 5
    CONNECTION_BASE_DELAY = 60       # 1 minute
    CONNECTION_MAX_DELAY = 3600      # 1 hour

    # Timeout retry settings
    TIMEOUT_BASE_DELAY = 120         # 2 minutes
    TIMEOUT_MAX_DELAY = 1800         # 30 minutes
    TIMEOUT_MULTIPLIER = 1.5         # Progressive increase

    # Rate limit retry settings
    RATE_LIMIT_BASE_DELAY = 60       # 1 minute
    RATE_LIMIT_MAX_DELAY = 3600      # 1 hour
    RATE_LIMIT_MULTIPLIER = 2        # Exponential backoff

    # Database retry settings
    DATABASE_MAX_RETRIES = 3
    DATABASE_BASE_DELAY = 30         # 30 seconds
    DATABASE_MAX_DELAY = 300         # 5 minutes

    # Webhook retry settings
    WEBHOOK_MAX_RETRIES = 3
    WEBHOOK_BASE_DELAY = 60          # 1 minute
    WEBHOOK_DELAYS = [60, 120, 240]  # 1, 2, 4 minutes

class CircuitBreakerConfig:
    """Circuit breaker configuration constants."""

    DEFAULT_FAILURE_THRESHOLD = 5
    DEFAULT_RECOVERY_TIMEOUT = 300   # 5 minutes
    HALF_OPEN_TIMEOUT = 60          # 1 minute

    # Service-specific thresholds
    TWILIO_API_THRESHOLD = 5
    DATABASE_THRESHOLD = 3
    EXTERNAL_SERVICE_THRESHOLD = 5

# ===========================================
# TIME INTERVAL CONSTANTS
# ===========================================

class TimeIntervals:
    """Time interval constants for various operations."""

    # Duration constants (seconds)
    MINUTE = 60
    FIVE_MINUTES = 300
    TEN_MINUTES = 600
    FIFTEEN_MINUTES = 900
    THIRTY_MINUTES = 1800
    HOUR = 3600
    TWO_HOURS = 7200
    FOUR_HOURS = 14400
    SIX_HOURS = 21600
    TWELVE_HOURS = 43200
    DAY = 86400
    WEEK = 604800

    # Task scheduling intervals
    HEALTH_CHECK_INTERVAL = 300      # 5 minutes
    METRICS_COLLECTION_INTERVAL = 60 # 1 minute
    CLEANUP_INTERVAL = 3600          # 1 hour
    REPORT_GENERATION_INTERVAL = 300 # 5 minutes

    # Monitoring intervals
    ALERT_CHECK_INTERVAL = 60        # 1 minute
    PERFORMANCE_CHECK_INTERVAL = 300 # 5 minutes
    SYSTEM_STATUS_INTERVAL = 180     # 3 minutes

# ===========================================
# DEFAULT VALUES AND THRESHOLDS
# ===========================================

class DefaultValues:
    """Default values for various operations."""

    # Queue defaults
    QUEUE_TIMEOUT_SECONDS = 300      # 5 minutes
    MAX_QUEUE_SIZE = 100
    QUEUE_PRIORITY = 1
    MAX_WAIT_TIME = 1800            # 30 minutes

    # Call defaults
    CALL_TIME_LIMIT = 14400         # 4 hours
    RING_TIMEOUT = 30               # 30 seconds
    RECORDING_TIMEOUT = 30          # 30 seconds

    # Agent defaults
    MAX_CONCURRENT_CALLS = 1
    BREAK_DURATION_MINUTES = 30
    TRAINING_DURATION_MINUTES = 60
    LUNCH_DURATION_MINUTES = 30

    # Pagination defaults
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100
    BATCH_SIZE = 1000               # For bulk operations

    # Analytics defaults
    DEFAULT_ANALYSIS_PERIOD_DAYS = 30       # Default period for analytics queries

    # Performance thresholds
    SLOW_OPERATION_THRESHOLD = 1.0   # 1 second
    SERVICE_LEVEL_THRESHOLD = 30     # 30 seconds
    ABANDONMENT_THRESHOLD = 300      # 5 minutes

class Limits:
    """Operational limits and thresholds."""

    # Data processing limits
    MAX_BULK_OPERATIONS = 1000
    MAX_ANALYTICS_RESULTS = 1000
    MAX_REPORT_RECORDS = 10000
    MAX_SEARCH_RESULTS = 500

    # API limits
    MAX_API_REQUESTS_PER_SECOND = 100
    MAX_WEBHOOK_RETRIES = 3
    MAX_CONCURRENT_CALLS = 1000

    # File and storage limits
    MAX_RECORDING_SIZE_MB = 100
    MAX_LOG_FILE_SIZE_MB = 50
    RECORDING_RETENTION_DAYS = 90
    LOG_RETENTION_DAYS = 30

    # Time limits
    MAX_CALL_DURATION = 14400       # 4 hours
    MAX_QUEUE_WAIT_TIME = 3600      # 1 hour
    MAX_CONFERENCE_DURATION = 28800 # 8 hours

# ===========================================
# STATUS AND STATE CONSTANTS
# ===========================================

class CallStatus:
    """Call status constants."""

    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    BUSY = "busy"
    FAILED = "failed"
    NO_ANSWER = "no-answer"
    CANCELED = "canceled"

    # Status groups for filtering
    ACTIVE_STATUSES = {QUEUED, RINGING, IN_PROGRESS}
    COMPLETED_STATUSES = {COMPLETED, BUSY, FAILED, NO_ANSWER, CANCELED}
    UNSUCCESSFUL_STATUSES = {BUSY, FAILED, NO_ANSWER, CANCELED}

class AgentStatus:
    """Agent status constants."""

    AVAILABLE = "available"
    BUSY = "busy"
    ON_BREAK = "on_break"
    TRAINING = "training"
    OFFLINE = "offline"
    LUNCH = "lunch"

    # Status groups
    ACTIVE_STATUSES = {AVAILABLE, BUSY}
    UNAVAILABLE_STATUSES = {ON_BREAK, TRAINING, OFFLINE, LUNCH}

class QueueStatus:
    """Queue status constants."""

    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"
    FULL = "full"

# ===========================================
# ERROR HANDLING CONSTANTS
# ===========================================

class ErrorThresholds:
    """Error threshold constants for monitoring and alerting."""

    # Error rate thresholds (percentage)
    WARNING_ERROR_RATE = 5.0        # 5% error rate warning
    CRITICAL_ERROR_RATE = 10.0      # 10% error rate critical

    # Response time thresholds (seconds)
    WARNING_RESPONSE_TIME = 2.0     # 2 seconds warning
    CRITICAL_RESPONSE_TIME = 5.0    # 5 seconds critical

    # Queue thresholds
    WARNING_QUEUE_TIME = 120        # 2 minutes warning
    CRITICAL_QUEUE_TIME = 300       # 5 minutes critical

    # System thresholds
    WARNING_MEMORY_USAGE = 80.0     # 80% memory warning
    CRITICAL_MEMORY_USAGE = 95.0    # 95% memory critical
    WARNING_CPU_USAGE = 80.0        # 80% CPU warning
    CRITICAL_CPU_USAGE = 95.0       # 95% CPU critical

class HTTPStatusCodes:
    """HTTP status code constants for API responses."""

    # Success codes
    OK = 200
    CREATED = 201
    ACCEPTED = 202
    NO_CONTENT = 204

    # Client error codes
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    CONFLICT = 409
    UNPROCESSABLE_ENTITY = 422
    RATE_LIMITED = 429

    # Server error codes
    INTERNAL_SERVER_ERROR = 500
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504

# ===========================================
# CONFIGURATION MAPPINGS
# ===========================================

# Map service types to their appropriate cache timeouts
SERVICE_CACHE_TIMEOUTS: Dict[str, int] = {
    "agent": CacheTimeouts.AGENT_STATUS,
    "call": CacheTimeouts.SHORT,
    "queue": CacheTimeouts.QUEUE_METRICS,
    "analytics": CacheTimeouts.CALL_ANALYTICS,
    "metrics": CacheTimeouts.STANDARD,
    "ivr": CacheTimeouts.IVR_FLOWS,
    "recording": CacheTimeouts.RECORDING_URLS,
    "conference": CacheTimeouts.CONFERENCE_DATA,
    "routing": CacheTimeouts.ROUTING_RULES,
    "reporting": CacheTimeouts.LONG,
}

# Map operation types to retry configurations
OPERATION_RETRY_CONFIGS: Dict[str, Dict[str, Any]] = {
    "default": {
        "max_retries": RetryConfig.DEFAULT_MAX_RETRIES,
        "base_delay": RetryConfig.DEFAULT_BASE_DELAY,
        "max_delay": RetryConfig.DEFAULT_MAX_DELAY,
        "multiplier": RetryConfig.DEFAULT_BACKOFF_MULTIPLIER,
    },
    "connection": {
        "max_retries": RetryConfig.CONNECTION_MAX_RETRIES,
        "base_delay": RetryConfig.CONNECTION_BASE_DELAY,
        "max_delay": RetryConfig.CONNECTION_MAX_DELAY,
        "multiplier": RetryConfig.DEFAULT_BACKOFF_MULTIPLIER,
    },
    "timeout": {
        "max_retries": RetryConfig.DEFAULT_MAX_RETRIES,
        "base_delay": RetryConfig.TIMEOUT_BASE_DELAY,
        "max_delay": RetryConfig.TIMEOUT_MAX_DELAY,
        "multiplier": RetryConfig.TIMEOUT_MULTIPLIER,
    },
    "rate_limit": {
        "max_retries": RetryConfig.DEFAULT_MAX_RETRIES,
        "base_delay": RetryConfig.RATE_LIMIT_BASE_DELAY,
        "max_delay": RetryConfig.RATE_LIMIT_MAX_DELAY,
        "multiplier": RetryConfig.RATE_LIMIT_MULTIPLIER,
    },
    "database": {
        "max_retries": RetryConfig.DATABASE_MAX_RETRIES,
        "base_delay": RetryConfig.DATABASE_BASE_DELAY,
        "max_delay": RetryConfig.DATABASE_MAX_DELAY,
        "multiplier": RetryConfig.DEFAULT_BACKOFF_MULTIPLIER,
    },
    "webhook": {
        "max_retries": RetryConfig.WEBHOOK_MAX_RETRIES,
        "base_delay": RetryConfig.WEBHOOK_BASE_DELAY,
        "delays": RetryConfig.WEBHOOK_DELAYS,
    },
}

# Map service types to their appropriate batch sizes
SERVICE_BATCH_SIZES: Dict[str, int] = {
    "analytics": DefaultValues.BATCH_SIZE,
    "reporting": Limits.MAX_REPORT_RECORDS,
    "metrics": Limits.MAX_ANALYTICS_RESULTS,
    "search": Limits.MAX_SEARCH_RESULTS,
    "bulk_operations": Limits.MAX_BULK_OPERATIONS,
}
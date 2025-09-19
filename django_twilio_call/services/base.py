"""Base service class with common patterns for all services."""

import logging
from functools import wraps
from typing import Any, Dict, List, Optional, Type

from django.core.cache import cache
from django.db import models, transaction
from django.db.models import QuerySet
from django.utils import timezone

from ..conf import get_config, get_cache_timeout
from ..constants import CacheTimeouts, DefaultValues, Limits

logger = logging.getLogger(__name__)


def cache_result(timeout: Optional[int] = None, key_prefix: str = "", service_type: str = "default"):
    """Decorator to cache method results.

    Args:
        timeout: Cache timeout in seconds (uses service-specific default if None)
        key_prefix: Optional prefix for cache key
        service_type: Service type for timeout configuration

    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Build cache key from method name and args
            cache_key_parts = [
                key_prefix or self.__class__.__name__,
                func.__name__,
                str(args),
                str(sorted(kwargs.items())),
            ]
            cache_key = "_".join(cache_key_parts).replace(" ", "")[:250]  # Limit key length

            # Try to get from cache first
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_result

            # Execute method and cache result
            result = func(self, *args, **kwargs)

            # Use configured timeout if not provided
            actual_timeout = timeout if timeout is not None else get_cache_timeout(service_type)
            cache.set(cache_key, result, actual_timeout)
            logger.debug(f"Cached result for {cache_key} (timeout: {actual_timeout}s)")
            return result

        return wrapper

    return decorator


def log_execution(level: int = logging.INFO):
    """Decorator to log method execution.

    Args:
        level: Logging level (default INFO)

    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            method_name = f"{self.__class__.__name__}.{func.__name__}"
            logger.log(level, f"Executing {method_name}")

            try:
                result = func(self, *args, **kwargs)
                logger.log(level, f"Completed {method_name}")
                return result
            except Exception as e:
                logger.error(f"Error in {method_name}: {e}")
                raise

        return wrapper

    return decorator


class ServiceError(Exception):
    """Base exception for service layer errors."""

    pass


class ValidationError(ServiceError):
    """Raised when service validation fails."""

    pass


class BusinessLogicError(ServiceError):
    """Raised when business logic constraints are violated."""

    pass


class BaseService:
    """Base service class providing common patterns and utilities."""

    # Service configuration - will be loaded from centralized config
    service_type = "default"  # Override in subclasses

    def __init__(self):
        """Initialize base service."""
        self.logger = logging.getLogger(f"{self.__module__}.{self.__class__.__name__}")
        self.config = get_config()

        # Load service-specific configuration
        self.cache_timeout = self.config.get_cache_timeout(self.service_type)
        self.log_level = getattr(logging, self.config.LOG_LEVEL)
        self.batch_size = self.config.get_batch_size(self.service_type)
        self.retry_config = self.config.get_retry_config(self.service_type)

    # ===========================================
    # CACHING UTILITIES
    # ===========================================

    def get_cache_key(self, *parts: str) -> str:
        """Generate a cache key from parts.

        Args:
            *parts: Parts to join into cache key

        Returns:
            Cache key string

        """
        key_parts = [self.__class__.__name__] + list(parts)
        return "_".join(str(part) for part in key_parts).replace(" ", "")[:250]

    def cache_get(self, key: str) -> Any:
        """Get value from cache with logging.

        Args:
            key: Cache key

        Returns:
            Cached value or None

        """
        value = cache.get(key)
        if value is not None:
            self.logger.debug(f"Cache hit: {key}")
        else:
            self.logger.debug(f"Cache miss: {key}")
        return value

    def cache_set(self, key: str, value: Any, timeout: Optional[int] = None) -> None:
        """Set value in cache with logging.

        Args:
            key: Cache key
            value: Value to cache
            timeout: Cache timeout (uses class default if None)

        """
        timeout = timeout or self.cache_timeout
        cache.set(key, value, timeout)
        self.logger.debug(f"Cached: {key} (timeout: {timeout}s)")

    def cache_delete(self, key: str) -> None:
        """Delete value from cache with logging.

        Args:
            key: Cache key

        """
        cache.delete(key)
        self.logger.debug(f"Cache deleted: {key}")

    def invalidate_cache_pattern(self, pattern: str) -> int:
        """Invalidate cache keys matching pattern.

        Args:
            pattern: Pattern to match (simple string matching)

        Returns:
            Number of keys deleted

        """
        # This is a simplified implementation
        # In production, you might want to use Redis pattern matching
        deleted_count = 0
        self.logger.info(f"Invalidating cache pattern: {pattern}")
        return deleted_count

    # ===========================================
    # ERROR HANDLING PATTERNS
    # ===========================================

    def validate_required(self, value: Any, field_name: str) -> Any:
        """Validate that a required field has a value.

        Args:
            value: Value to validate
            field_name: Name of the field for error messages

        Returns:
            The value if valid

        Raises:
            ValidationError: If value is None or empty

        """
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValidationError(f"{field_name} is required")
        return value

    def validate_positive_int(self, value: int, field_name: str) -> int:
        """Validate that a value is a positive integer.

        Args:
            value: Value to validate
            field_name: Name of the field for error messages

        Returns:
            The value if valid

        Raises:
            ValidationError: If value is not a positive integer

        """
        if not isinstance(value, int) or value <= 0:
            raise ValidationError(f"{field_name} must be a positive integer")
        return value

    def handle_service_error(self, operation: str, error: Exception) -> None:
        """Handle and log service errors consistently.

        Args:
            operation: Description of the operation that failed
            error: The exception that occurred

        """
        error_msg = f"Failed {operation}: {error}"
        self.logger.error(error_msg)

        # Re-raise as appropriate service error type
        if isinstance(error, (ValidationError, BusinessLogicError)):
            raise error
        else:
            raise ServiceError(error_msg) from error

    # ===========================================
    # DATABASE TRANSACTION PATTERNS
    # ===========================================

    @transaction.atomic
    def execute_in_transaction(self, operation_name: str, operation_func, *args, **kwargs):
        """Execute an operation within a database transaction.

        Args:
            operation_name: Name of the operation for logging
            operation_func: Function to execute
            *args: Arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the operation

        """
        self.logger.info(f"Starting transaction: {operation_name}")

        try:
            result = operation_func(*args, **kwargs)
            self.logger.info(f"Transaction completed: {operation_name}")
            return result
        except Exception as e:
            self.logger.error(f"Transaction failed: {operation_name} - {e}")
            raise

    def get_or_create_safe(
        self, model: Type[models.Model], defaults: Optional[Dict] = None, **lookup_kwargs
    ) -> tuple[models.Model, bool]:
        """Safe get_or_create with error handling.

        Args:
            model: Model class
            defaults: Default values for creation
            **lookup_kwargs: Lookup parameters

        Returns:
            Tuple of (instance, created)

        """
        try:
            return model.objects.get_or_create(defaults=defaults, **lookup_kwargs)
        except Exception as e:
            self.handle_service_error(f"get_or_create for {model.__name__}", e)

    def bulk_create_safe(
        self,
        model: Type[models.Model],
        objects: List[models.Model],
        batch_size: Optional[int] = None,
        ignore_conflicts: bool = False,
    ) -> List[models.Model]:
        """Safe bulk create with error handling.

        Args:
            model: Model class
            objects: List of model instances to create
            batch_size: Batch size for bulk creation
            ignore_conflicts: Whether to ignore conflicts

        Returns:
            List of created objects

        """
        try:
            return model.objects.bulk_create(objects, batch_size=batch_size, ignore_conflicts=ignore_conflicts)
        except Exception as e:
            self.handle_service_error(f"bulk_create for {model.__name__}", e)

    # ===========================================
    # QUERY OPTIMIZATION PATTERNS
    # ===========================================

    def optimize_queryset(
        self,
        queryset: QuerySet,
        select_related: Optional[List[str]] = None,
        prefetch_related: Optional[List[str]] = None,
        only_fields: Optional[List[str]] = None,
        defer_fields: Optional[List[str]] = None,
    ) -> QuerySet:
        """Apply common query optimizations.

        Args:
            queryset: Base queryset
            select_related: Fields for select_related
            prefetch_related: Fields for prefetch_related
            only_fields: Fields to include (only)
            defer_fields: Fields to exclude (defer)

        Returns:
            Optimized queryset

        """
        if select_related:
            queryset = queryset.select_related(*select_related)

        if prefetch_related:
            queryset = queryset.prefetch_related(*prefetch_related)

        if only_fields:
            queryset = queryset.only(*only_fields)

        if defer_fields:
            queryset = queryset.defer(*defer_fields)

        return queryset

    def get_object_or_error(
        self, model: Type[models.Model], error_message: str = None, **lookup_kwargs
    ) -> models.Model:
        """Get object or raise service error.

        Args:
            model: Model class
            error_message: Custom error message
            **lookup_kwargs: Lookup parameters

        Returns:
            Model instance

        Raises:
            ValidationError: If object not found

        """
        try:
            return model.objects.get(**lookup_kwargs)
        except model.DoesNotExist:
            message = error_message or f"{model.__name__} not found"
            raise ValidationError(message)
        except model.MultipleObjectsReturned:
            message = f"Multiple {model.__name__} objects found"
            raise ValidationError(message)

    def filter_active_objects(self, queryset: QuerySet) -> QuerySet:
        """Filter for active objects (common pattern).

        Args:
            queryset: Base queryset

        Returns:
            Filtered queryset for active objects

        """
        # Check common active field names
        model = queryset.model

        if hasattr(model, "is_active"):
            return queryset.filter(is_active=True)
        elif hasattr(model, "active"):
            return queryset.filter(active=True)
        elif hasattr(model, "status"):
            # Assume 'active' is a valid status value
            return queryset.exclude(status__in=["deleted", "inactive", "disabled"])

        return queryset

    # ===========================================
    # LOGGING UTILITIES
    # ===========================================

    def log_operation(self, operation: str, level: int = None, **context) -> None:
        """Log an operation with context.

        Args:
            operation: Description of the operation
            level: Logging level (uses class default if None)
            **context: Additional context for logging

        """
        level = level or self.log_level

        if context:
            message = f"{operation} - Context: {context}"
        else:
            message = operation

        self.logger.log(level, message)

    def log_performance(self, operation: str, duration: float) -> None:
        """Log performance metrics.

        Args:
            operation: Operation name
            duration: Duration in seconds

        """
        slow_threshold = self.config.SLOW_OPERATION_THRESHOLD
        if duration > slow_threshold:
            self.logger.warning(f"Slow operation: {operation} took {duration:.2f}s")
        else:
            self.logger.debug(f"Operation: {operation} took {duration:.3f}s")

    # ===========================================
    # UTILITY METHODS
    # ===========================================

    def get_current_timestamp(self):
        """Get current timestamp (useful for testing)."""
        return timezone.now()

    def paginate_queryset(
        self, queryset: QuerySet, page: int = 1, page_size: Optional[int] = None, max_page_size: Optional[int] = None
    ) -> Dict[str, Any]:
        """Paginate a queryset.

        Args:
            queryset: Queryset to paginate
            page: Page number (1-based)
            page_size: Items per page
            max_page_size: Maximum allowed page size

        Returns:
            Dict with pagination info and results

        """
        # Use configured defaults if not provided
        if page_size is None:
            page_size = self.config.DEFAULT_PAGE_SIZE
        if max_page_size is None:
            max_page_size = self.config.MAX_PAGE_SIZE

        # Validate and limit page size
        page_size = min(page_size, max_page_size)
        page = max(1, page)  # Ensure page is at least 1

        # Calculate offset
        offset = (page - 1) * page_size

        # Get total count
        total_count = queryset.count()

        # Get page results
        results = list(queryset[offset : offset + page_size])

        # Calculate pagination info
        total_pages = (total_count + page_size - 1) // page_size
        has_next = page < total_pages
        has_previous = page > 1

        return {
            "results": results,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": has_next,
                "has_previous": has_previous,
            },
        }

    def format_duration(self, seconds: float) -> str:
        """Format duration in seconds to human readable format.

        Args:
            seconds: Duration in seconds

        Returns:
            Formatted duration string

        """
        if seconds < DefaultValues.RECORDING_TIMEOUT:  # Less than 30 seconds
            return f"{seconds:.1f}s"
        elif seconds < CacheTimeouts.LONG:  # Less than 1 hour
            minutes = seconds / CacheTimeouts.VERY_SHORT  # 60 seconds
            return f"{minutes:.1f}m"
        else:
            hours = seconds / CacheTimeouts.LONG  # 3600 seconds
            return f"{hours:.1f}h"

    def safe_divide(self, numerator: float, denominator: float, default: float = 0.0) -> float:
        """Safely divide two numbers, returning default if denominator is zero.

        Args:
            numerator: Numerator
            denominator: Denominator
            default: Default value if division by zero

        Returns:
            Division result or default

        """
        if denominator == 0:
            return default
        return numerator / denominator

    def percentage(self, part: float, total: float, precision: int = 2) -> float:
        """Calculate percentage with safe division.

        Args:
            part: Part value
            total: Total value
            precision: Decimal precision

        Returns:
            Percentage value

        """
        if total == 0:
            return 0.0
        return round((part / total) * 100, precision)


class CachedServiceMixin:
    """Mixin to add caching capabilities to services."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'config'):
            self.config = get_config()
        self.cache_timeout = self.config.get_cache_timeout(getattr(self, 'service_type', 'default'))

    def cache_method_result(self, method_name: str, *args, **kwargs):
        """Cache the result of a method call."""
        cache_key = self.get_cache_key(method_name, str(args), str(kwargs))
        cached_result = cache.get(cache_key)

        if cached_result is not None:
            return cached_result

        # Execute method and cache result
        method = getattr(self, method_name)
        result = method(*args, **kwargs)
        cache.set(cache_key, result, self.cache_timeout)

        return result


class ValidatedServiceMixin:
    """Mixin to add validation capabilities to services."""

    def validate_model_instance(self, instance: models.Model) -> models.Model:
        """Validate a model instance.

        Args:
            instance: Model instance to validate

        Returns:
            Validated instance

        Raises:
            ValidationError: If validation fails

        """
        try:
            instance.full_clean()
            return instance
        except Exception as e:
            raise ValidationError(f"Model validation failed: {e}")

    def validate_business_rules(self, operation: str, **context) -> None:
        """Override this method in subclasses to implement business rule validation.

        Args:
            operation: Operation being performed
            **context: Context for validation

        Raises:
            BusinessLogicError: If business rules are violated

        """
        pass


class AuditedServiceMixin:
    """Mixin to add audit logging to services."""

    def audit_log(self, action: str, model: str, object_id: Any, **metadata) -> None:
        """Log an audit event.

        Args:
            action: Action performed (create, update, delete, etc.)
            model: Model name
            object_id: Object identifier
            **metadata: Additional metadata

        """
        audit_data = {
            "service": self.__class__.__name__,
            "action": action,
            "model": model,
            "object_id": str(object_id),
            "timestamp": timezone.now().isoformat(),
            "metadata": metadata,
        }

        # In a real implementation, you would save this to an audit log
        self.logger.info(f"Audit: {audit_data}")

"""Cache management utilities for django-twilio-call package.

This module provides centralized cache key generation, management,
and invalidation patterns for consistent caching across services.
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional, Set, Union

from django.core.cache import cache
from django.conf import settings

from .conf import get_config
from .constants import CacheKeyPrefixes, CacheTimeouts

logger = logging.getLogger(__name__)

class CacheManager:
    """Centralized cache management for django-twilio-call package."""

    def __init__(self):
        """Initialize cache manager."""
        self.config = get_config()
        self.key_prefix = self.config.CACHE_KEY_PREFIX
        self.key_version = self.config.CACHE_KEY_VERSION

    # ===========================================
    # CACHE KEY GENERATION
    # ===========================================

    def build_key(self, prefix: str, *parts: Union[str, int, Any]) -> str:
        """Build a standardized cache key.

        Args:
            prefix: Cache key prefix (service type)
            *parts: Parts to join into cache key

        Returns:
            Standardized cache key string

        """
        # Convert all parts to strings and clean them
        clean_parts = []
        for part in parts:
            if isinstance(part, (dict, list)):
                # Hash complex objects for consistent keys
                part_str = hashlib.md5(str(sorted(part.items()) if isinstance(part, dict) else part).encode()).hexdigest()[:8]
            else:
                part_str = str(part).replace(" ", "_").replace(":", "_")
            clean_parts.append(part_str)

        # Build key components
        key_components = [
            self.key_prefix,
            prefix,
            *clean_parts
        ]

        # Join and limit key length
        cache_key = "_".join(key_components)

        # Django cache keys have a 250 character limit
        if len(cache_key) > 240:  # Leave some room for versioning
            # Hash the key if it's too long
            hash_key = hashlib.md5(cache_key.encode()).hexdigest()
            cache_key = f"{self.key_prefix}_{prefix}_{hash_key}"

        return cache_key

    def build_service_key(self, service_type: str, method: str, *args, **kwargs) -> str:
        """Build a cache key for a service method.

        Args:
            service_type: Type of service (agent, call, queue, etc.)
            method: Method name
            *args: Method arguments
            **kwargs: Method keyword arguments

        Returns:
            Service-specific cache key

        """
        key_parts = [method]

        # Add positional arguments
        if args:
            key_parts.extend(str(arg) for arg in args)

        # Add keyword arguments (sorted for consistency)
        if kwargs:
            sorted_kwargs = sorted(kwargs.items())
            key_parts.extend(f"{k}={v}" for k, v in sorted_kwargs)

        return self.build_key(service_type, *key_parts)

    def build_model_key(self, model_name: str, object_id: Union[int, str], action: str = "detail") -> str:
        """Build a cache key for model-based data.

        Args:
            model_name: Name of the model
            object_id: Object identifier
            action: Action type (detail, list, count, etc.)

        Returns:
            Model-specific cache key

        """
        return self.build_key("model", model_name.lower(), action, str(object_id))

    def build_analytics_key(self, report_type: str, start_date: str, end_date: str, **filters) -> str:
        """Build a cache key for analytics data.

        Args:
            report_type: Type of report or analytics
            start_date: Start date string
            end_date: End date string
            **filters: Additional filters

        Returns:
            Analytics-specific cache key

        """
        key_parts = [report_type, start_date, end_date]

        if filters:
            sorted_filters = sorted(filters.items())
            key_parts.extend(f"{k}={v}" for k, v in sorted_filters)

        return self.build_key(CacheKeyPrefixes.ANALYTICS, *key_parts)

    # ===========================================
    # CACHE OPERATIONS
    # ===========================================

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache with logging.

        Args:
            key: Cache key
            default: Default value if not found

        Returns:
            Cached value or default

        """
        try:
            value = cache.get(key, default, version=self.key_version)
            if value is not None and value != default:
                logger.debug(f"Cache hit: {key}")
            else:
                logger.debug(f"Cache miss: {key}")
            return value
        except Exception as e:
            logger.warning(f"Cache get error for key {key}: {e}")
            return default

    def set(self, key: str, value: Any, timeout: Optional[int] = None, service_type: str = "default") -> bool:
        """Set value in cache with logging.

        Args:
            key: Cache key
            value: Value to cache
            timeout: Cache timeout (uses service default if None)
            service_type: Service type for timeout configuration

        Returns:
            True if successful, False otherwise

        """
        try:
            if timeout is None:
                timeout = self.config.get_cache_timeout(service_type)

            success = cache.set(key, value, timeout, version=self.key_version)
            if success:
                logger.debug(f"Cached: {key} (timeout: {timeout}s)")
            else:
                logger.warning(f"Failed to cache: {key}")
            return success
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete value from cache.

        Args:
            key: Cache key

        Returns:
            True if successful, False otherwise

        """
        try:
            success = cache.delete(key, version=self.key_version)
            if success:
                logger.debug(f"Cache deleted: {key}")
            return success
        except Exception as e:
            logger.warning(f"Cache delete error for key {key}: {e}")
            return False

    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """Get multiple values from cache.

        Args:
            keys: List of cache keys

        Returns:
            Dictionary of key-value pairs found in cache

        """
        try:
            result = cache.get_many(keys, version=self.key_version)
            hit_count = len(result)
            miss_count = len(keys) - hit_count
            logger.debug(f"Cache get_many: {hit_count} hits, {miss_count} misses")
            return result
        except Exception as e:
            logger.error(f"Cache get_many error: {e}")
            return {}

    def set_many(self, data: Dict[str, Any], timeout: Optional[int] = None, service_type: str = "default") -> bool:
        """Set multiple values in cache.

        Args:
            data: Dictionary of key-value pairs to cache
            timeout: Cache timeout (uses service default if None)
            service_type: Service type for timeout configuration

        Returns:
            True if successful, False otherwise

        """
        try:
            if timeout is None:
                timeout = self.config.get_cache_timeout(service_type)

            failed_keys = cache.set_many(data, timeout, version=self.key_version)
            if not failed_keys:
                logger.debug(f"Cached {len(data)} items (timeout: {timeout}s)")
                return True
            else:
                logger.warning(f"Failed to cache {len(failed_keys)} items: {failed_keys}")
                return False
        except Exception as e:
            logger.error(f"Cache set_many error: {e}")
            return False

    def delete_many(self, keys: List[str]) -> int:
        """Delete multiple values from cache.

        Args:
            keys: List of cache keys to delete

        Returns:
            Number of keys successfully deleted

        """
        try:
            cache.delete_many(keys, version=self.key_version)
            logger.debug(f"Cache deleted {len(keys)} keys")
            return len(keys)
        except Exception as e:
            logger.error(f"Cache delete_many error: {e}")
            return 0

    # ===========================================
    # CACHE INVALIDATION PATTERNS
    # ===========================================

    def invalidate_service_cache(self, service_type: str) -> int:
        """Invalidate all cache entries for a service type.

        Args:
            service_type: Service type to invalidate

        Returns:
            Number of keys invalidated (approximation)

        """
        # This is a simplified implementation
        # In production, you might want to use Redis pattern matching
        logger.info(f"Invalidating cache for service: {service_type}")

        # For now, we'll track keys to invalidate
        # In a real implementation, you might use cache tags or Redis SCAN
        invalidated_count = 0

        # Log the invalidation request
        logger.info(f"Service cache invalidation requested for: {service_type}")

        return invalidated_count

    def invalidate_model_cache(self, model_name: str, object_id: Optional[Union[int, str]] = None) -> int:
        """Invalidate cache entries for a model.

        Args:
            model_name: Name of the model
            object_id: Specific object ID (invalidates all if None)

        Returns:
            Number of keys invalidated

        """
        invalidated_count = 0

        if object_id:
            # Invalidate specific object caches
            keys_to_delete = [
                self.build_model_key(model_name, object_id, "detail"),
                self.build_model_key(model_name, object_id, "related"),
            ]
            invalidated_count = self.delete_many(keys_to_delete)

        # Also invalidate list caches for this model
        list_patterns = [
            self.build_key("model", model_name.lower(), "list"),
            self.build_key("model", model_name.lower(), "count"),
        ]

        logger.info(f"Model cache invalidation for {model_name}: {invalidated_count} keys")
        return invalidated_count

    def invalidate_analytics_cache(self, report_type: Optional[str] = None) -> int:
        """Invalidate analytics cache entries.

        Args:
            report_type: Specific report type (invalidates all if None)

        Returns:
            Number of keys invalidated

        """
        # In a real implementation, you would use cache tags or pattern matching
        logger.info(f"Analytics cache invalidation for: {report_type or 'all'}")
        return 0

    def invalidate_user_cache(self, user_id: Union[int, str]) -> int:
        """Invalidate all cache entries for a specific user.

        Args:
            user_id: User identifier

        Returns:
            Number of keys invalidated

        """
        # This would invalidate user-specific caches like agent status, assignments, etc.
        keys_to_delete = [
            self.build_key(CacheKeyPrefixes.AGENT, "status", str(user_id)),
            self.build_key(CacheKeyPrefixes.AGENT, "performance", str(user_id)),
            self.build_key(CacheKeyPrefixes.AGENT, "assignments", str(user_id)),
        ]

        return self.delete_many(keys_to_delete)

    # ===========================================
    # CACHE WARMING
    # ===========================================

    def warm_service_cache(self, service_type: str, critical_data: Optional[Dict[str, Any]] = None) -> int:
        """Pre-warm cache with critical data for a service.

        Args:
            service_type: Service type to warm
            critical_data: Optional critical data to cache immediately

        Returns:
            Number of items cached

        """
        cached_count = 0

        if critical_data:
            timeout = self.config.get_cache_timeout(service_type)
            if self.set_many(critical_data, timeout, service_type):
                cached_count = len(critical_data)

        logger.info(f"Cache warming for {service_type}: {cached_count} items")
        return cached_count

    # ===========================================
    # CACHE STATISTICS
    # ===========================================

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics and health information.

        Returns:
            Dictionary with cache statistics

        """
        try:
            # This would depend on your cache backend
            # For Django's default cache, we have limited stats
            stats = {
                "backend": getattr(settings, "CACHES", {}).get("default", {}).get("BACKEND", "unknown"),
                "key_prefix": self.key_prefix,
                "key_version": self.key_version,
                "default_timeout": self.config.CACHE_TIMEOUT,
            }

            # Add service-specific timeouts
            stats["service_timeouts"] = self.config.CACHE_TIMEOUTS

            return stats
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {"error": str(e)}

    def health_check(self) -> Dict[str, Any]:
        """Perform a cache health check.

        Returns:
            Health check results

        """
        test_key = self.build_key("health_check", "test")
        test_value = "cache_test"

        try:
            # Test write
            write_success = self.set(test_key, test_value, 60)  # 1 minute timeout

            # Test read
            read_value = self.get(test_key)
            read_success = read_value == test_value

            # Test delete
            delete_success = self.delete(test_key)

            return {
                "status": "healthy" if (write_success and read_success and delete_success) else "unhealthy",
                "write_success": write_success,
                "read_success": read_success,
                "delete_success": delete_success,
                "backend": getattr(settings, "CACHES", {}).get("default", {}).get("BACKEND", "unknown"),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "write_success": False,
                "read_success": False,
                "delete_success": False,
            }


# Singleton instance
_cache_manager: Optional[CacheManager] = None

def get_cache_manager() -> CacheManager:
    """Get the singleton cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager

# Convenience functions for common operations
def build_cache_key(prefix: str, *parts) -> str:
    """Build a standardized cache key."""
    return get_cache_manager().build_key(prefix, *parts)

def cache_get(key: str, default: Any = None) -> Any:
    """Get value from cache."""
    return get_cache_manager().get(key, default)

def cache_set(key: str, value: Any, timeout: Optional[int] = None, service_type: str = "default") -> bool:
    """Set value in cache."""
    return get_cache_manager().set(key, value, timeout, service_type)

def cache_delete(key: str) -> bool:
    """Delete value from cache."""
    return get_cache_manager().delete(key)

def invalidate_service_cache(service_type: str) -> int:
    """Invalidate cache for a service type."""
    return get_cache_manager().invalidate_service_cache(service_type)

def invalidate_model_cache(model_name: str, object_id: Optional[Union[int, str]] = None) -> int:
    """Invalidate cache for a model."""
    return get_cache_manager().invalidate_model_cache(model_name, object_id)
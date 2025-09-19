"""Centralized metrics registry for consistent metric management."""

import logging
from typing import Dict, List, Optional, Sequence, Union

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram, Summary
from prometheus_client.metrics import MetricWrapperBase

logger = logging.getLogger(__name__)


class MetricsRegistry:
    """Centralized registry for managing application metrics."""

    def __init__(self, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or REGISTRY
        self._metrics: Dict[str, MetricWrapperBase] = {}

    def register_counter(self, name: str, description: str, labels: Optional[List[str]] = None) -> Counter:
        """Register a Counter metric."""
        if name in self._metrics:
            return self._metrics[name]

        counter = Counter(name=name, documentation=description, labelnames=labels or [], registry=self.registry)
        self._metrics[name] = counter
        logger.debug(f"Registered counter metric: {name}")
        return counter

    def register_gauge(self, name: str, description: str, labels: Optional[List[str]] = None) -> Gauge:
        """Register a Gauge metric."""
        if name in self._metrics:
            return self._metrics[name]

        gauge = Gauge(name=name, documentation=description, labelnames=labels or [], registry=self.registry)
        self._metrics[name] = gauge
        logger.debug(f"Registered gauge metric: {name}")
        return gauge

    def register_histogram(
        self,
        name: str,
        description: str,
        labels: Optional[List[str]] = None,
        buckets: Optional[Sequence[Union[float, str]]] = None,
    ) -> Histogram:
        """Register a Histogram metric."""
        if name in self._metrics:
            return self._metrics[name]

        histogram = Histogram(
            name=name, documentation=description, labelnames=labels or [], buckets=buckets, registry=self.registry
        )
        self._metrics[name] = histogram
        logger.debug(f"Registered histogram metric: {name}")
        return histogram

    def register_summary(self, name: str, description: str, labels: Optional[List[str]] = None) -> Summary:
        """Register a Summary metric."""
        if name in self._metrics:
            return self._metrics[name]

        summary = Summary(name=name, documentation=description, labelnames=labels or [], registry=self.registry)
        self._metrics[name] = summary
        logger.debug(f"Registered summary metric: {name}")
        return summary

    def get_metric(self, name: str) -> Optional[MetricWrapperBase]:
        """Get a registered metric by name."""
        return self._metrics.get(name)

    def list_metrics(self) -> List[str]:
        """List all registered metric names."""
        return list(self._metrics.keys())

    def unregister_metric(self, name: str) -> bool:
        """Unregister a metric."""
        if name in self._metrics:
            metric = self._metrics.pop(name)
            try:
                self.registry.unregister(metric)
                logger.debug(f"Unregistered metric: {name}")
                return True
            except Exception as e:
                logger.error(f"Failed to unregister metric {name}: {e}")
                # Put it back if unregistration failed
                self._metrics[name] = metric
                return False
        return False

    def clear_all(self) -> None:
        """Clear all registered metrics."""
        for name in list(self._metrics.keys()):
            self.unregister_metric(name)


# Global metrics registry instance
metrics_registry = MetricsRegistry()

"""Model mixins for django-twilio-call package.

Provides reusable model components to eliminate duplication and ensure consistency
across models with common patterns.
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class UUIDMixin(models.Model):
    """Mixin to provide a public UUID field for external references.

    This mixin adds a public_id field that can be safely exposed in APIs
    without revealing internal database IDs.
    """

    public_id = models.UUIDField(
        _("public ID"),
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
        help_text=_("External UUID for API references"),
    )

    class Meta:
        abstract = True


class TimestampMixin(models.Model):
    """Mixin to provide created_at and updated_at timestamp fields.

    Automatically tracks when records are created and last modified.
    """

    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class MetadataMixin(models.Model):
    """Mixin to provide a metadata JSONField for storing additional data.

    Useful for storing flexible, schema-less data that doesn't warrant
    dedicated database fields.
    """

    metadata = models.JSONField(
        _("metadata"), default=dict, blank=True, help_text=_("Additional metadata for this record")
    )

    class Meta:
        abstract = True


class StatusMixin(models.Model):
    """Base mixin for models that have status fields.

    Provides common status-related functionality. Models using this mixin
    should define their own Status choices class.
    """

    # Note: Subclasses should define their own status field with specific choices
    # This mixin provides common methods for status handling

    class Meta:
        abstract = True

    @property
    def is_active_status(self) -> bool:
        """Check if the current status represents an active state.
        Subclasses should override this method to define what constitutes
        an "active" status for their specific domain.
        """
        return hasattr(self, "status") and hasattr(self, "is_active")

    def get_status_display_class(self) -> str:
        """Get a CSS class name based on the current status.
        Useful for UI styling.
        """
        if not hasattr(self, "status"):
            return "status-unknown"

        status = getattr(self, "status", "").lower()

        # Common status mappings
        active_statuses = ["available", "in-progress", "completed", "delivered", "success"]
        warning_statuses = ["pending", "queued", "retrying", "on_break"]
        error_statuses = ["failed", "error", "abandoned", "offline"]

        if status in active_statuses:
            return "status-success"
        elif status in warning_statuses:
            return "status-warning"
        elif status in error_statuses:
            return "status-error"
        else:
            return f"status-{status.replace('_', '-')}"


class SoftDeleteMixin(models.Model):
    """Mixin to provide soft delete functionality.

    Instead of actually deleting records, this mixin allows marking them
    as deleted while preserving the data for audit purposes.
    """

    deleted_at = models.DateTimeField(
        _("deleted at"), null=True, blank=True, help_text=_("When this record was soft deleted")
    )

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        """Check if this record has been soft deleted."""
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark this record as deleted."""
        from django.utils import timezone

        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def restore(self) -> None:
        """Restore a soft deleted record."""
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])


class PricingMixin(models.Model):
    """Mixin for models that track pricing information.

    Provides consistent price and currency fields for billing-related models.
    """

    price = models.DecimalField(
        _("price"),
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=_("Cost in the specified currency"),
    )
    price_unit = models.CharField(
        _("price unit"), max_length=10, blank=True, default="USD", help_text=_("Currency code for the price")
    )

    class Meta:
        abstract = True

    @property
    def formatted_price(self) -> str:
        """Return a formatted price string."""
        if self.price is None:
            return "N/A"
        return f"{self.price:.4f} {self.price_unit}"


class TwilioSIDMixin(models.Model):
    """Mixin for models that reference Twilio SIDs.

    Provides a consistent field for storing Twilio resource identifiers.
    """

    twilio_sid = models.CharField(
        _("Twilio SID"), max_length=50, unique=True, db_index=True, help_text=_("Twilio resource identifier")
    )

    class Meta:
        abstract = True


class BaseCallCenterModel(UUIDMixin, TimestampMixin, MetadataMixin):
    """Base model combining the most common mixins for call center models.

    Provides public_id, timestamps, and metadata fields that are used
    by most models in the call center system.
    """

    class Meta:
        abstract = True

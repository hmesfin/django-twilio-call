"""Phone number management views for django-twilio-call.

Handles CRUD operations and Twilio synchronization for phone numbers.
"""

import logging

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from ..models import PhoneNumber
from ..serializers import PhoneNumberSerializer
from ..services import twilio_service
from .base import BaseCallCenterViewSet, TwilioServiceMixin

logger = logging.getLogger(__name__)


class PhoneNumberViewSet(BaseCallCenterViewSet, TwilioServiceMixin):
    """ViewSet for PhoneNumber model with Twilio integration."""

    queryset = PhoneNumber.objects.all()
    serializer_class = PhoneNumberSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter queryset based on user permissions and query parameters."""
        queryset = super().get_queryset()

        # Filter by active status if requested
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == "true")

        # Filter by number type if requested
        number_type = self.request.query_params.get("number_type")
        if number_type:
            queryset = queryset.filter(number_type=number_type)

        return queryset

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def sync_from_twilio(self, request):
        """Sync phone numbers from Twilio account.

        Retrieves all phone numbers from the associated Twilio account
        and creates or updates local records accordingly.
        """
        try:
            numbers = twilio_service.list_phone_numbers()
            created_count = 0
            updated_count = 0

            for number_data in numbers:
                phone_number, created = PhoneNumber.objects.update_or_create(
                    twilio_sid=number_data["sid"],
                    defaults={
                        "phone_number": number_data["phone_number"],
                        "friendly_name": number_data["friendly_name"],
                        "capabilities": number_data["capabilities"],
                    },
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

            return self.success_response(
                data={
                    "created": created_count,
                    "updated": updated_count,
                    "total": len(numbers),
                },
                message=f"Successfully synced {len(numbers)} phone numbers from Twilio",
            )

        except Exception as e:
            return self.handle_twilio_error(e, "sync phone numbers")

    @action(detail=True, methods=["post"])
    def refresh_from_twilio(self, request, public_id=None):
        """Refresh a specific phone number from Twilio.

        Updates the local phone number record with the latest data from Twilio.
        """
        phone_number = self.get_object()

        try:
            twilio_data = twilio_service.get_phone_number(phone_number.twilio_sid)

            # Update local record with Twilio data
            phone_number.friendly_name = twilio_data.get("friendly_name", phone_number.friendly_name)
            phone_number.capabilities = twilio_data.get("capabilities", phone_number.capabilities)
            phone_number.save()

            return self.success_response(
                data=self.get_serializer(phone_number).data,
                message="Phone number refreshed from Twilio successfully",
            )

        except Exception as e:
            return self.handle_twilio_error(e, f"refresh phone number {phone_number.phone_number}")

    @action(detail=True, methods=["patch"])
    def update_friendly_name(self, request, public_id=None):
        """Update the friendly name of a phone number both locally and in Twilio."""
        phone_number = self.get_object()
        friendly_name = request.data.get("friendly_name")

        if not friendly_name:
            return self.handle_error(
                ValueError("friendly_name is required"), "update friendly name", status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Update in Twilio first
            twilio_service.update_phone_number(phone_number.twilio_sid, {"friendly_name": friendly_name})

            # Update local record
            phone_number.friendly_name = friendly_name
            phone_number.save()

            return self.success_response(
                data=self.get_serializer(phone_number).data,
                message="Friendly name updated successfully",
            )

        except Exception as e:
            return self.handle_twilio_error(e, f"update friendly name for {phone_number.phone_number}")

    @action(detail=False, methods=["get"])
    def available_numbers(self, request):
        """Get available phone numbers for purchase from Twilio.

        Query parameters:
        - country_code: ISO country code (default: US)
        - area_code: Area code to search within
        - contains: Number pattern to search for
        - near_lat_long: Latitude,longitude for proximity search
        """
        try:
            search_params = {
                "country_code": request.query_params.get("country_code", "US"),
                "area_code": request.query_params.get("area_code"),
                "contains": request.query_params.get("contains"),
                "near_lat_long": request.query_params.get("near_lat_long"),
            }

            # Remove None values
            search_params = {k: v for k, v in search_params.items() if v is not None}

            available_numbers = twilio_service.search_available_numbers(**search_params)

            return self.success_response(
                data=available_numbers,
                message=f"Found {len(available_numbers)} available numbers",
            )

        except Exception as e:
            return self.handle_twilio_error(e, "search available numbers")

    @action(detail=False, methods=["post"])
    def purchase_number(self, request):
        """Purchase a phone number from Twilio.

        Required data:
        - phone_number: The phone number to purchase
        - friendly_name: Optional friendly name for the number
        """
        phone_number = request.data.get("phone_number")
        friendly_name = request.data.get("friendly_name", "")

        if not phone_number:
            return self.handle_error(
                ValueError("phone_number is required"), "purchase number", status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Purchase the number through Twilio
            twilio_data = twilio_service.purchase_phone_number(phone_number, friendly_name)

            # Create local record
            local_number = PhoneNumber.objects.create(
                twilio_sid=twilio_data["sid"],
                phone_number=twilio_data["phone_number"],
                friendly_name=twilio_data.get("friendly_name", ""),
                capabilities=twilio_data.get("capabilities", {}),
                is_active=True,
            )

            return self.success_response(
                data=self.get_serializer(local_number).data,
                message=f"Successfully purchased phone number {phone_number}",
                status_code=status.HTTP_201_CREATED,
            )

        except Exception as e:
            return self.handle_twilio_error(e, f"purchase number {phone_number}")

    @action(detail=True, methods=["delete"])
    def release_number(self, request, public_id=None):
        """Release a phone number back to Twilio (delete from account).

        This action is irreversible and will remove the number from both
        Twilio and the local database.
        """
        phone_number = self.get_object()

        try:
            # Release from Twilio first
            twilio_service.release_phone_number(phone_number.twilio_sid)

            # Mark as inactive locally (soft delete)
            phone_number.is_active = False
            phone_number.save()

            return self.success_response(
                message=f"Phone number {phone_number.phone_number} released successfully",
            )

        except Exception as e:
            return self.handle_twilio_error(e, f"release number {phone_number.phone_number}")

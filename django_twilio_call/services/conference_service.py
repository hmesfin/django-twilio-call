"""Conference service for managing conference calls."""

import logging
from typing import Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from ..exceptions import CallServiceError
from ..models import Call, CallLog

logger = logging.getLogger(__name__)


class ConferenceParticipant:
    """Represents a conference participant."""

    def __init__(
        self,
        call_sid: str,
        phone_number: str,
        is_muted: bool = False,
        is_coach: bool = False,
        is_moderator: bool = False,
    ):
        self.call_sid = call_sid
        self.phone_number = phone_number
        self.is_muted = is_muted
        self.is_coach = is_coach
        self.is_moderator = is_moderator
        self.joined_at = timezone.now()


class Conference:
    """Represents a conference room."""

    def __init__(
        self,
        name: str,
        friendly_name: Optional[str] = None,
        max_participants: int = 250,
        record: bool = False,
    ):
        self.sid = None  # Will be set by Twilio
        self.name = name
        self.friendly_name = friendly_name or name
        self.max_participants = max_participants
        self.record = record
        self.participants: List[ConferenceParticipant] = []
        self.created_at = timezone.now()
        self.status = "in_progress"
        self.metadata = {}


class ConferenceService:
    """Service for managing conference calls."""

    def __init__(self):
        """Initialize conference service."""
        self.active_conferences: Dict[str, Conference] = {}

    @transaction.atomic
    def create_conference(
        self,
        name: str,
        friendly_name: Optional[str] = None,
        max_participants: int = 250,
        record: bool = False,
        start_on_enter: bool = True,
        end_on_exit: bool = False,
        wait_url: Optional[str] = None,
        moderator_id: Optional[int] = None,
    ) -> Conference:
        """Create a new conference.

        Args:
            name: Unique conference name
            friendly_name: Display name
            max_participants: Maximum number of participants
            record: Whether to record the conference
            start_on_enter: Start conference when first participant joins
            end_on_exit: End conference when moderator leaves
            wait_url: URL for hold music
            moderator_id: Agent ID who is the moderator

        Returns:
            Conference object

        """
        # Check if conference already exists
        if name in self.active_conferences:
            return self.active_conferences[name]

        # Create conference
        conference = Conference(
            name=name,
            friendly_name=friendly_name,
            max_participants=max_participants,
            record=record,
        )

        conference.metadata = {
            "start_on_enter": start_on_enter,
            "end_on_exit": end_on_exit,
            "wait_url": wait_url,
            "moderator_id": moderator_id,
        }

        # Store conference
        self.active_conferences[name] = conference

        logger.info(f"Created conference {name}")
        return conference

    def add_participant(
        self,
        conference_name: str,
        call_sid: str,
        phone_number: str,
        is_muted: bool = False,
        is_coach: bool = False,
        is_moderator: bool = False,
        announce: bool = True,
    ) -> ConferenceParticipant:
        """Add a participant to conference.

        Args:
            conference_name: Conference name
            call_sid: Call SID of participant
            phone_number: Participant's phone number
            is_muted: Start muted
            is_coach: Coach mode (can hear but not be heard)
            is_moderator: Has moderator privileges
            announce: Announce entry/exit

        Returns:
            ConferenceParticipant object

        """
        if conference_name not in self.active_conferences:
            raise CallServiceError(f"Conference {conference_name} not found")

        conference = self.active_conferences[conference_name]

        # Check capacity
        if len(conference.participants) >= conference.max_participants:
            raise CallServiceError(f"Conference {conference_name} is full")

        # Create participant
        participant = ConferenceParticipant(
            call_sid=call_sid,
            phone_number=phone_number,
            is_muted=is_muted,
            is_coach=is_coach,
            is_moderator=is_moderator,
        )

        # Add to conference
        conference.participants.append(participant)

        # Update call record if exists
        try:
            call = Call.objects.get(twilio_sid=call_sid)
            call.conference_sid = conference_name
            call.metadata["conference_role"] = {
                "is_moderator": is_moderator,
                "is_coach": is_coach,
            }
            call.save(update_fields=["conference_sid", "metadata"])

            CallLog.objects.create(
                call=call,
                event_type=CallLog.EventType.CONFERENCE,
                description=f"Joined conference {conference.friendly_name}",
                agent=call.agent,
                data={
                    "conference_name": conference_name,
                    "role": "moderator" if is_moderator else "participant",
                },
            )
        except Call.DoesNotExist:
            pass

        logger.info(f"Added {phone_number} to conference {conference_name}")
        return participant

    def remove_participant(self, conference_name: str, call_sid: str) -> bool:
        """Remove a participant from conference.

        Args:
            conference_name: Conference name
            call_sid: Call SID of participant

        Returns:
            Success boolean

        """
        if conference_name not in self.active_conferences:
            return False

        conference = self.active_conferences[conference_name]

        # Find and remove participant
        for participant in conference.participants:
            if participant.call_sid == call_sid:
                conference.participants.remove(participant)

                # Update call record
                try:
                    call = Call.objects.get(twilio_sid=call_sid)
                    call.conference_sid = ""
                    call.save(update_fields=["conference_sid"])

                    CallLog.objects.create(
                        call=call,
                        event_type=CallLog.EventType.CONFERENCE,
                        description=f"Left conference {conference.friendly_name}",
                        agent=call.agent,
                    )
                except Call.DoesNotExist:
                    pass

                logger.info(f"Removed {participant.phone_number} from conference {conference_name}")

                # End conference if empty or moderator left
                if len(conference.participants) == 0 or (
                    participant.is_moderator and conference.metadata.get("end_on_exit")
                ):
                    self.end_conference(conference_name)

                return True

        return False

    def mute_participant(self, conference_name: str, call_sid: str, muted: bool = True) -> bool:
        """Mute/unmute a participant.

        Args:
            conference_name: Conference name
            call_sid: Call SID of participant
            muted: Mute or unmute

        Returns:
            Success boolean

        """
        from ..services import twilio_service

        if conference_name not in self.active_conferences:
            return False

        conference = self.active_conferences[conference_name]

        for participant in conference.participants:
            if participant.call_sid == call_sid:
                participant.is_muted = muted

                # Update via Twilio
                try:
                    twilio_service.client.conferences(conference_name).participants(call_sid).update(muted=muted)

                    logger.info(f"{'Muted' if muted else 'Unmuted'} {participant.phone_number} in {conference_name}")
                    return True
                except Exception as e:
                    logger.error(f"Failed to mute participant: {e}")

        return False

    def kick_participant(self, conference_name: str, call_sid: str) -> bool:
        """Kick a participant from conference.

        Args:
            conference_name: Conference name
            call_sid: Call SID of participant

        Returns:
            Success boolean

        """
        from ..services import twilio_service

        if conference_name not in self.active_conferences:
            return False

        try:
            # Remove via Twilio
            twilio_service.client.conferences(conference_name).participants(call_sid).delete()

            # Remove from local tracking
            self.remove_participant(conference_name, call_sid)

            logger.info(f"Kicked {call_sid} from conference {conference_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to kick participant: {e}")
            return False

    def hold_participant(self, conference_name: str, call_sid: str, hold: bool = True) -> bool:
        """Put participant on hold.

        Args:
            conference_name: Conference name
            call_sid: Call SID of participant
            hold: Hold or unhold

        Returns:
            Success boolean

        """
        from ..services import twilio_service

        if conference_name not in self.active_conferences:
            return False

        try:
            # Update via Twilio
            twilio_service.client.conferences(conference_name).participants(call_sid).update(hold=hold)

            logger.info(f"{'Held' if hold else 'Unheld'} {call_sid} in {conference_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to hold participant: {e}")
            return False

    def promote_to_moderator(self, conference_name: str, call_sid: str) -> bool:
        """Promote participant to moderator.

        Args:
            conference_name: Conference name
            call_sid: Call SID of participant

        Returns:
            Success boolean

        """
        if conference_name not in self.active_conferences:
            return False

        conference = self.active_conferences[conference_name]

        for participant in conference.participants:
            if participant.call_sid == call_sid:
                participant.is_moderator = True

                # Update call metadata
                try:
                    call = Call.objects.get(twilio_sid=call_sid)
                    call.metadata["conference_role"]["is_moderator"] = True
                    call.save(update_fields=["metadata"])

                    logger.info(f"Promoted {participant.phone_number} to moderator in {conference_name}")
                except Call.DoesNotExist:
                    pass

                return True

        return False

    def enable_coaching(self, conference_name: str, call_sid: str, coach: bool = True) -> bool:
        """Enable/disable coach mode for participant.

        Args:
            conference_name: Conference name
            call_sid: Call SID of participant
            coach: Enable or disable coach mode

        Returns:
            Success boolean

        """
        from ..services import twilio_service

        if conference_name not in self.active_conferences:
            return False

        conference = self.active_conferences[conference_name]

        for participant in conference.participants:
            if participant.call_sid == call_sid:
                participant.is_coach = coach

                try:
                    # Update via Twilio
                    twilio_service.client.conferences(conference_name).participants(call_sid).update(coaching=coach)

                    logger.info(f"{'Enabled' if coach else 'Disabled'} coaching for {participant.phone_number}")
                    return True
                except Exception as e:
                    logger.error(f"Failed to update coaching: {e}")

        return False

    def get_conference_status(self, conference_name: str) -> Optional[Dict]:
        """Get conference status and participants.

        Args:
            conference_name: Conference name

        Returns:
            Conference status dictionary or None

        """
        if conference_name not in self.active_conferences:
            return None

        conference = self.active_conferences[conference_name]

        return {
            "name": conference.name,
            "friendly_name": conference.friendly_name,
            "status": conference.status,
            "created_at": conference.created_at.isoformat(),
            "participant_count": len(conference.participants),
            "max_participants": conference.max_participants,
            "is_recording": conference.record,
            "participants": [
                {
                    "call_sid": p.call_sid,
                    "phone_number": p.phone_number,
                    "is_muted": p.is_muted,
                    "is_coach": p.is_coach,
                    "is_moderator": p.is_moderator,
                    "joined_at": p.joined_at.isoformat(),
                }
                for p in conference.participants
            ],
            "metadata": conference.metadata,
        }

    def end_conference(self, conference_name: str) -> bool:
        """End a conference.

        Args:
            conference_name: Conference name

        Returns:
            Success boolean

        """
        from ..services import twilio_service

        if conference_name not in self.active_conferences:
            return False

        conference = self.active_conferences[conference_name]

        try:
            # End via Twilio
            twilio_service.client.conferences(conference_name).update(status="completed")

            # Update all participant calls
            for participant in conference.participants:
                try:
                    call = Call.objects.get(twilio_sid=participant.call_sid)
                    call.conference_sid = ""
                    call.save(update_fields=["conference_sid"])

                    CallLog.objects.create(
                        call=call,
                        event_type=CallLog.EventType.CONFERENCE,
                        description=f"Conference {conference.friendly_name} ended",
                        agent=call.agent,
                    )
                except Call.DoesNotExist:
                    pass

            # Remove from active conferences
            conference.status = "completed"
            del self.active_conferences[conference_name]

            logger.info(f"Ended conference {conference_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to end conference: {e}")
            return False

    def list_active_conferences(self) -> List[Dict]:
        """List all active conferences.

        Returns:
            List of conference summaries

        """
        return [
            {
                "name": conf.name,
                "friendly_name": conf.friendly_name,
                "participant_count": len(conf.participants),
                "created_at": conf.created_at.isoformat(),
                "is_recording": conf.record,
            }
            for conf in self.active_conferences.values()
        ]


# Create service instance
conference_service = ConferenceService()

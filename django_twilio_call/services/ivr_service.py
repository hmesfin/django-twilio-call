"""IVR (Interactive Voice Response) service."""

import logging
from typing import Any, Dict, Optional

from django.core.cache import cache
from twilio.twiml.voice_response import Gather, VoiceResponse

from ..constants import CacheTimeouts

logger = logging.getLogger(__name__)


class IVRNode:
    """Represents a node in the IVR flow."""

    def __init__(
        self,
        id: str,
        type: str,
        message: str,
        options: Optional[Dict[str, str]] = None,
        action: Optional[str] = None,
        next_node: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        self.id = id
        self.type = type  # menu, message, transfer, queue, hangup
        self.message = message
        self.options = options or {}  # digit -> next_node mapping
        self.action = action  # URL for external action
        self.next_node = next_node  # Default next node
        self.metadata = metadata or {}


class IVRFlow:
    """Represents a complete IVR flow."""

    def __init__(self, name: str, language: str = "en-US", voice: str = "alice"):
        self.name = name
        self.language = language
        self.voice = voice
        self.nodes: Dict[str, IVRNode] = {}
        self.start_node: Optional[str] = None

    def add_node(self, node: IVRNode, is_start: bool = False):
        """Add a node to the flow."""
        self.nodes[node.id] = node
        if is_start:
            self.start_node = node.id

    def get_node(self, node_id: str) -> Optional[IVRNode]:
        """Get a node by ID."""
        return self.nodes.get(node_id)


class IVRService:
    """Service for managing IVR flows."""

    def __init__(self):
        """Initialize IVR service."""
        self.flows: Dict[str, IVRFlow] = {}
        self._load_default_flows()

    def _load_default_flows(self):
        """Load default IVR flows."""
        # Create main menu flow
        main_flow = IVRFlow("main_menu")

        # Welcome node
        welcome = IVRNode(
            id="welcome",
            type="menu",
            message="Welcome to our call center. Press 1 for sales, 2 for support, 3 for billing, or 0 to speak with an operator.",
            options={
                "1": "sales_menu",
                "2": "support_menu",
                "3": "billing_menu",
                "0": "operator_transfer",
            },
        )
        main_flow.add_node(welcome, is_start=True)

        # Sales menu
        sales = IVRNode(
            id="sales_menu",
            type="menu",
            message="Sales department. Press 1 for new orders, 2 for existing orders, or 0 to go back.",
            options={
                "1": "sales_new_queue",
                "2": "sales_existing_queue",
                "0": "welcome",
            },
        )
        main_flow.add_node(sales)

        # Support menu
        support = IVRNode(
            id="support_menu",
            type="menu",
            message="Support department. Press 1 for technical support, 2 for account support, or 0 to go back.",
            options={
                "1": "tech_support_queue",
                "2": "account_support_queue",
                "0": "welcome",
            },
        )
        main_flow.add_node(support)

        # Billing menu
        billing = IVRNode(
            id="billing_menu",
            type="transfer",
            message="Transferring you to billing department.",
            action="billing_queue",
        )
        main_flow.add_node(billing)

        # Queue nodes
        for queue_id in [
            "sales_new_queue",
            "sales_existing_queue",
            "tech_support_queue",
            "account_support_queue",
            "billing_queue",
        ]:
            queue_node = IVRNode(
                id=queue_id,
                type="queue",
                message="Please hold while we connect you to the next available agent.",
                action=queue_id.replace("_queue", ""),
            )
            main_flow.add_node(queue_node)

        # Operator transfer
        operator = IVRNode(
            id="operator_transfer",
            type="transfer",
            message="Transferring you to an operator.",
            action="operator",
        )
        main_flow.add_node(operator)

        # Store flow
        self.flows["main_menu"] = main_flow

        # Create business hours flow
        self._create_business_hours_flow()

        # Create language selection flow
        self._create_language_flow()

    def _create_business_hours_flow(self):
        """Create business hours IVR flow."""
        flow = IVRFlow("business_hours")

        # Check hours node
        check_hours = IVRNode(
            id="check_hours",
            type="message",
            message="Thank you for calling. Our business hours are Monday through Friday, 9 AM to 6 PM Eastern Time.",
            next_node="after_hours_menu",
        )
        flow.add_node(check_hours, is_start=True)

        # After hours menu
        after_hours = IVRNode(
            id="after_hours_menu",
            type="menu",
            message="Press 1 to leave a voicemail, 2 to hear our business hours again, or 3 for emergency support.",
            options={
                "1": "voicemail",
                "2": "check_hours",
                "3": "emergency_transfer",
            },
        )
        flow.add_node(after_hours)

        # Voicemail node
        voicemail = IVRNode(
            id="voicemail",
            type="message",
            message="Please leave your message after the beep. Press pound when finished.",
            action="record_voicemail",
        )
        flow.add_node(voicemail)

        # Emergency transfer
        emergency = IVRNode(
            id="emergency_transfer",
            type="transfer",
            message="Transferring you to emergency support.",
            action="emergency_queue",
        )
        flow.add_node(emergency)

        self.flows["business_hours"] = flow

    def _create_language_flow(self):
        """Create language selection flow."""
        flow = IVRFlow("language_selection")

        # Language menu
        language_menu = IVRNode(
            id="language_menu",
            type="menu",
            message="For English, press 1. Para español, presione 2. Pour le français, appuyez sur 3.",
            options={
                "1": "english_selected",
                "2": "spanish_selected",
                "3": "french_selected",
            },
        )
        flow.add_node(language_menu, is_start=True)

        # Language confirmations
        languages = {
            "english_selected": ("You have selected English.", "en-US"),
            "spanish_selected": ("Ha seleccionado español.", "es-ES"),
            "french_selected": ("Vous avez sélectionné le français.", "fr-FR"),
        }

        for node_id, (message, lang_code) in languages.items():
            node = IVRNode(
                id=node_id,
                type="message",
                message=message,
                next_node="main_menu",
                metadata={"language": lang_code},
            )
            flow.add_node(node)

        self.flows["language_selection"] = flow

    def create_flow(self, name: str, language: str = "en-US", voice: str = "alice") -> IVRFlow:
        """Create a new IVR flow.

        Args:
            name: Flow name
            language: Language code
            voice: TTS voice

        Returns:
            IVRFlow object

        """
        flow = IVRFlow(name, language, voice)
        self.flows[name] = flow
        return flow

    def get_flow(self, name: str) -> Optional[IVRFlow]:
        """Get an IVR flow by name."""
        return self.flows.get(name)

    def process_input(
        self,
        flow_name: str,
        current_node_id: str,
        digits: Optional[str] = None,
        speech: Optional[str] = None,
    ) -> IVRNode:
        """Process user input and return next node.

        Args:
            flow_name: IVR flow name
            current_node_id: Current node ID
            digits: DTMF digits pressed
            speech: Speech input

        Returns:
            Next IVRNode

        """
        flow = self.flows.get(flow_name)
        if not flow:
            raise ValueError(f"Flow {flow_name} not found")

        current_node = flow.get_node(current_node_id)
        if not current_node:
            raise ValueError(f"Node {current_node_id} not found")

        # Process based on node type
        if current_node.type == "menu" and digits:
            # Get next node based on digit pressed
            next_node_id = current_node.options.get(digits)
            if next_node_id:
                return flow.get_node(next_node_id)
            else:
                # Invalid input, stay on current node
                return current_node

        elif current_node.next_node:
            # Follow default path
            return flow.get_node(current_node.next_node)

        return current_node

    def generate_twiml(
        self,
        node: IVRNode,
        flow: IVRFlow,
        base_url: str,
    ) -> VoiceResponse:
        """Generate TwiML for an IVR node.

        Args:
            node: IVR node
            flow: IVR flow
            base_url: Base URL for callbacks

        Returns:
            VoiceResponse object

        """
        response = VoiceResponse()

        if node.type == "menu":
            # Create gather for menu
            gather = Gather(
                num_digits=1,
                action=f"{base_url}/ivr/process/{flow.name}/{node.id}",
                method="POST",
                timeout=5,
            )
            gather.say(node.message, voice=flow.voice, language=flow.language)
            response.append(gather)

            # Add timeout message
            response.say(
                "I didn't receive any input. Please try again.",
                voice=flow.voice,
                language=flow.language,
            )
            # Redirect back to same node
            response.redirect(f"{base_url}/ivr/node/{flow.name}/{node.id}")

        elif node.type == "message":
            # Play message
            response.say(node.message, voice=flow.voice, language=flow.language)

            # Continue to next node if specified
            if node.next_node:
                response.redirect(f"{base_url}/ivr/node/{flow.name}/{node.next_node}")
            elif node.action:
                response.redirect(f"{base_url}/ivr/action/{node.action}")

        elif node.type == "transfer":
            # Transfer to agent or queue
            response.say(node.message, voice=flow.voice, language=flow.language)

            if node.action == "operator":
                response.dial("+1234567890")  # Operator number
            elif node.action:
                response.enqueue(node.action)

        elif node.type == "queue":
            # Add to queue
            response.say(node.message, voice=flow.voice, language=flow.language)
            response.enqueue(
                node.action,
                wait_url=f"{base_url}/queue/wait",
                wait_method="POST",
            )

        elif node.type == "hangup":
            # End call
            response.say(node.message, voice=flow.voice, language=flow.language)
            response.hangup()

        return response

    def add_custom_node(
        self,
        flow_name: str,
        node_id: str,
        node_type: str,
        message: str,
        **kwargs,
    ) -> IVRNode:
        """Add a custom node to a flow.

        Args:
            flow_name: Flow name
            node_id: Node ID
            node_type: Node type
            message: Node message
            **kwargs: Additional node parameters

        Returns:
            Created IVRNode

        """
        flow = self.flows.get(flow_name)
        if not flow:
            flow = self.create_flow(flow_name)

        node = IVRNode(
            id=node_id,
            type=node_type,
            message=message,
            options=kwargs.get("options"),
            action=kwargs.get("action"),
            next_node=kwargs.get("next_node"),
            metadata=kwargs.get("metadata"),
        )

        flow.add_node(node, is_start=kwargs.get("is_start", False))
        return node

    def export_flow(self, flow_name: str) -> Dict[str, Any]:
        """Export a flow as JSON.

        Args:
            flow_name: Flow name

        Returns:
            Flow configuration dictionary

        """
        flow = self.flows.get(flow_name)
        if not flow:
            return {}

        return {
            "name": flow.name,
            "language": flow.language,
            "voice": flow.voice,
            "start_node": flow.start_node,
            "nodes": [
                {
                    "id": node.id,
                    "type": node.type,
                    "message": node.message,
                    "options": node.options,
                    "action": node.action,
                    "next_node": node.next_node,
                    "metadata": node.metadata,
                }
                for node in flow.nodes.values()
            ],
        }

    def import_flow(self, config: Dict[str, Any]) -> IVRFlow:
        """Import a flow from JSON.

        Args:
            config: Flow configuration dictionary

        Returns:
            Imported IVRFlow

        """
        flow = IVRFlow(
            name=config["name"],
            language=config.get("language", "en-US"),
            voice=config.get("voice", "alice"),
        )

        for node_config in config.get("nodes", []):
            node = IVRNode(
                id=node_config["id"],
                type=node_config["type"],
                message=node_config["message"],
                options=node_config.get("options"),
                action=node_config.get("action"),
                next_node=node_config.get("next_node"),
                metadata=node_config.get("metadata"),
            )
            flow.add_node(node, is_start=(node_config["id"] == config.get("start_node")))

        self.flows[flow.name] = flow
        return flow

    def track_ivr_path(self, call_sid: str, node_id: str, input_value: Optional[str] = None):
        """Track IVR path for analytics.

        Args:
            call_sid: Call SID
            node_id: Current node ID
            input_value: User input value

        """
        # Store in cache for quick access
        cache_key = f"ivr_path_{call_sid}"
        path = cache.get(cache_key, [])

        path.append(
            {
                "node_id": node_id,
                "timestamp": timezone.now().isoformat(),
                "input": input_value,
            }
        )

        cache.set(cache_key, path, timeout=CacheTimeouts.LONG)  # Keep for 1 hour
        logger.info(f"IVR path for {call_sid}: {node_id} (input: {input_value})")


# Create service instance
ivr_service = IVRService()

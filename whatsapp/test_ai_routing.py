from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from whatsapp.views import get_ai_general_interpretation


class GeneralIntentRoutingTests(TestCase):

    def setUp(self):
        self.organization = SimpleNamespace(pk=10)

        self.conversation = SimpleNamespace(
            organization_id=10,
            business_request_id=None,
            business_request=None,
        )

        self.state = SimpleNamespace(
            pk=100,
            data={},
            waiting_for=None,
            current_step=None,
            conversation=self.conversation,
        )

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_greeting_returns_reply_intent(self, interpreter):
        interpreter.return_value = {
            "action": "reply",
            "intent": "greeting",
            "answer": "Habari! Karibu.",
        }

        result = get_ai_general_interpretation(
            "Hello",
            self.organization,
            self.state,
            123,
        )

        self.assertEqual(result["intent"], "greeting")
        self.assertEqual(result["action"], "reply")
        self.assertEqual(result["answer"], "Habari! Karibu.")
        interpreter.assert_called_once()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_product_enquiry_routes_to_existing_handler(self, interpreter):
        interpreter.return_value = {
            "action": "route_existing",
            "intent": "product_enquiry",
            "answer": "",
        }

        result = get_ai_general_interpretation(
            "I need a laptop",
            self.organization,
            self.state,
            124,
        )

        self.assertEqual(result["intent"], "product_enquiry")
        self.assertEqual(result["action"], "route_existing")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_service_enquiry_routes_to_category_interpretation(
        self,
        interpreter,
    ):
        interpreter.return_value = {
            "action": "route_existing",
            "intent": "service_enquiry",
            "answer": "",
        }

        result = get_ai_general_interpretation(
            "Nahitaji huduma ya usafi",
            self.organization,
            self.state,
            125,
        )

        self.assertEqual(result["intent"], "service_enquiry")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_business_request_routes_to_existing_handler(self, interpreter):
        interpreter.return_value = {
            "action": "route_existing",
            "intent": "business_request",
            "answer": "",
        }

        result = get_ai_general_interpretation(
            "I want to request a service",
            self.organization,
            self.state,
            126,
        )

        self.assertEqual(result["intent"], "business_request")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_human_support_retains_existing_fallback(self, interpreter):
        interpreter.return_value = {
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
        }

        result = get_ai_general_interpretation(
            "I want to talk to someone",
            self.organization,
            self.state,
            127,
        )

        self.assertEqual(result["intent"], "human_support")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_workflow_input_retains_existing_fallback(self, interpreter):
        interpreter.return_value = {
            "action": "route_existing",
            "intent": "workflow_input",
            "answer": "",
        }

        result = get_ai_general_interpretation(
            "My name is John",
            self.organization,
            self.state,
            128,
        )

        self.assertEqual(result["intent"], "workflow_input")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_general_enquiry_returns_reply(self, interpreter):
        interpreter.return_value = {
            "action": "reply",
            "intent": "general_enquiry",
            "answer": "Naweza kukusaidia vipi?",
        }

        result = get_ai_general_interpretation(
            "Can you help me?",
            self.organization,
            self.state,
            129,
        )

        self.assertEqual(result["intent"], "general_enquiry")
        self.assertEqual(result["action"], "reply")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_unclear_returns_reply(self, interpreter):
        interpreter.return_value = {
            "action": "reply",
            "intent": "unclear",
            "answer": "Unaweza kufafanua zaidi?",
        }

        result = get_ai_general_interpretation(
            "Hmm",
            self.organization,
            self.state,
            130,
        )

        self.assertEqual(result["intent"], "unclear")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_invalid_reply_intent_is_rejected(self, interpreter):
        interpreter.return_value = {
            "action": "reply",
            "intent": "business_request",
            "answer": "I will create it.",
        }

        result = get_ai_general_interpretation(
            "I need help",
            self.organization,
            self.state,
            131,
        )

        self.assertIsNone(result)

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_invalid_route_with_answer_is_rejected(self, interpreter):
        interpreter.return_value = {
            "action": "route_existing",
            "intent": "product_enquiry",
            "answer": "Here is a product.",
        }

        result = get_ai_general_interpretation(
            "I need a product",
            self.organization,
            self.state,
            132,
        )

        self.assertIsNone(result)

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_existing_business_request_blocks_interpreter(self, interpreter):
        self.conversation.business_request_id = 500

        result = get_ai_general_interpretation(
            "Hello",
            self.organization,
            self.state,
            133,
        )

        self.assertIsNone(result)
        interpreter.assert_not_called()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_pending_workflow_blocks_interpreter(self, interpreter):
        self.state.waiting_for = "customer_name"

        result = get_ai_general_interpretation(
            "Hello",
            self.organization,
            self.state,
            134,
        )

        self.assertIsNone(result)
        interpreter.assert_not_called()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_product_selection_blocks_interpreter(self, interpreter):
        self.state.current_step = "whatsapp_product_selection"

        result = get_ai_general_interpretation(
            "Hello",
            self.organization,
            self.state,
            135,
        )

        self.assertIsNone(result)
        interpreter.assert_not_called()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_cross_organization_conversation_is_blocked(self, interpreter):
        self.conversation.organization_id = 99

        result = get_ai_general_interpretation(
            "Hello",
            self.organization,
            self.state,
            136,
        )

        self.assertIsNone(result)
        interpreter.assert_not_called()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_provider_failure_falls_back(self, interpreter):
        interpreter.side_effect = RuntimeError("Provider unavailable")

        result = get_ai_general_interpretation(
            "Hello",
            self.organization,
            self.state,
            137,
        )

        self.assertIsNone(result)

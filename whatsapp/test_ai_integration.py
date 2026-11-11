from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from whatsapp.views import get_ai_product_reply


class WhatsAppAIProductIntegrationTests(TestCase):

    def setUp(self):
        self.organization = SimpleNamespace(pk=10)
        self.state = SimpleNamespace(
            data={"selected_whatsapp_product_id": 25},
            current_step=None,
        )

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_selected_product_question_returns_ai_answer(self, mock_ai):
        mock_ai.return_value = {
            "action": "answer_product",
            "product_id": 25,
            "answer": "This product has the requested features.",
        }

        result = get_ai_product_reply(
            "Tell me more about it",
            self.organization,
            self.state,
            101,
        )

        self.assertEqual(
            result,
            "This product has the requested features.",
        )
        mock_ai.assert_called_once_with(
            "Tell me more about it",
            self.organization,
            self.state,
            current_message_id=101,
        )

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_clarification_answer_is_returned(self, mock_ai):
        mock_ai.return_value = {
            "action": "clarify_product",
            "product_id": None,
            "answer": "Which feature would you like explained?",
        }

        result = get_ai_product_reply(
            "Explain this",
            self.organization,
            self.state,
            102,
        )

        self.assertEqual(
            result,
            "Which feature would you like explained?",
        )

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_workflow_input_uses_existing_fallback(self, mock_ai):
        mock_ai.return_value = {
            "action": "workflow_input",
            "product_id": None,
            "answer": "",
        }

        result = get_ai_product_reply(
            "I need delivery",
            self.organization,
            self.state,
            103,
        )

        self.assertIsNone(result)

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_other_action_uses_existing_fallback(self, mock_ai):
        mock_ai.return_value = {
            "action": "other",
            "product_id": None,
            "answer": "",
        }

        result = get_ai_product_reply(
            "Hello",
            self.organization,
            self.state,
            104,
        )

        self.assertIsNone(result)

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_ai_failure_uses_existing_fallback(self, mock_ai):
        mock_ai.side_effect = RuntimeError("Provider unavailable")

        result = get_ai_product_reply(
            "Tell me about it",
            self.organization,
            self.state,
            105,
        )

        self.assertIsNone(result)

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_active_product_selection_is_never_intercepted(self, mock_ai):
        self.state.current_step = "whatsapp_product_selection"

        result = get_ai_product_reply(
            "1",
            self.organization,
            self.state,
            106,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_active_quantity_step_is_never_intercepted(self, mock_ai):
        self.state.current_step = "whatsapp_product_quantity"

        result = get_ai_product_reply(
            "10",
            self.organization,
            self.state,
            107,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_active_next_action_is_never_intercepted(self, mock_ai):
        self.state.current_step = "whatsapp_product_next_action"

        result = get_ai_product_reply(
            "Delivery",
            self.organization,
            self.state,
            108,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_no_selected_product_does_not_call_ai(self, mock_ai):
        self.state.data = {}

        result = get_ai_product_reply(
            "Tell me about a product",
            self.organization,
            self.state,
            109,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()


    @patch("whatsapp.ai_service.interpret_product_message")
    def test_business_request_category_blocks_ai(self, mock_ai):
        self.state.data["category"] = "Property Services"

        result = get_ai_product_reply(
            "Tell me about it",
            self.organization,
            self.state,
            111,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_business_request_id_blocks_ai(self, mock_ai):
        self.state.data["business_request_id"] = 500

        result = get_ai_product_reply(
            "Tell me about it",
            self.organization,
            self.state,
            112,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_waiting_for_business_request_field_blocks_ai(self, mock_ai):
        self.state.waiting_for = "location"

        result = get_ai_product_reply(
            "Tell me about it",
            self.organization,
            self.state,
            113,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_linked_business_request_blocks_ai(self, mock_ai):
        self.state.conversation = SimpleNamespace(
            business_request_id=500,
            business_request=SimpleNamespace(pk=500),
        )

        result = get_ai_product_reply(
            "Tell me about it",
            self.organization,
            self.state,
            114,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_unknown_workflow_step_blocks_ai(self, mock_ai):
        self.state.current_step = "collecting_details"

        result = get_ai_product_reply(
            "Tell me about it",
            self.organization,
            self.state,
            115,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_completed_product_flow_allows_ai_follow_up(self, mock_ai):
        self.state.current_step = "whatsapp_product_completed"
        mock_ai.return_value = {
            "action": "answer_product",
            "product_id": 25,
            "answer": "Here are more details about the product.",
        }

        result = get_ai_product_reply(
            "Can you explain its features?",
            self.organization,
            self.state,
            116,
        )

        self.assertEqual(
            result,
            "Here are more details about the product.",
        )
        mock_ai.assert_called_once()

    @patch("whatsapp.ai_service.interpret_product_message")
    def test_empty_ai_answer_uses_existing_fallback(self, mock_ai):
        mock_ai.return_value = {
            "action": "answer_product",
            "product_id": 25,
            "answer": "   ",
        }

        result = get_ai_product_reply(
            "Tell me about it",
            self.organization,
            self.state,
            110,
        )

        self.assertIsNone(result)

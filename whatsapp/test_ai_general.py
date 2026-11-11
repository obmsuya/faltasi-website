import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from whatsapp.ai_service import (
    WhatsAppAIInvalidResponseError,
    WhatsAppAIConfigurationError,
    _parse_general_ai_response,
    interpret_general_message,
)
from whatsapp.views import get_ai_general_reply


class GeneralAIResponseTests(SimpleTestCase):

    def parse(self, payload, status="completed"):
        return _parse_general_ai_response(
            SimpleNamespace(
                status=status,
                output_text=json.dumps(payload),
            )
        )

    def test_accepts_swahili_greeting(self):
        result = self.parse({
            "action": "reply",
            "intent": "greeting",
            "answer": "Habari! Nikusaidie nini leo?",
        })
        self.assertEqual(result["intent"], "greeting")

    def test_accepts_english_greeting(self):
        result = self.parse({
            "action": "reply",
            "intent": "greeting",
            "answer": "Hello! How can I help?",
        })
        self.assertEqual(result["action"], "reply")

    def test_routes_product_enquiry(self):
        result = self.parse({
            "action": "route_existing",
            "intent": "product_enquiry",
            "answer": "",
        })
        self.assertEqual(result["intent"], "product_enquiry")

    def test_routes_service_enquiry(self):
        result = self.parse({
            "action": "route_existing",
            "intent": "service_enquiry",
            "answer": "",
        })
        self.assertEqual(result["action"], "route_existing")

    def test_routes_human_support(self):
        result = self.parse({
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
        })
        self.assertEqual(result["intent"], "human_support")

    def test_rejects_unexpected_fields(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "reply",
                "intent": "greeting",
                "answer": "Habari!",
                "secret": "value",
            })

    def test_rejects_unknown_intent(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "reply",
                "intent": "create_order",
                "answer": "Done",
            })

    def test_rejects_product_answer_from_general_ai(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "reply",
                "intent": "product_enquiry",
                "answer": "It costs TZS 50,000.",
            })

    def test_rejects_reply_for_business_request(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "reply",
                "intent": "business_request",
                "answer": "Request created.",
            })

    def test_rejects_empty_reply(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "reply",
                "intent": "greeting",
                "answer": "",
            })

    def test_rejects_incomplete_response(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "reply",
                "intent": "greeting",
                "answer": "Habari!",
            }, status="incomplete")


class GeneralAIServiceTests(SimpleTestCase):

    def setUp(self):
        self.organization = SimpleNamespace(pk=10)
        self.state = SimpleNamespace(
            pk=20,
            conversation=SimpleNamespace(organization_id=10),
        )

    def test_rejects_cross_organization_conversation(self):
        self.state.conversation.organization_id = 99

        with self.assertRaises(ValueError):
            interpret_general_message(
                "Habari", self.organization, self.state
            )

    def test_rejects_invalid_message_id(self):
        with self.assertRaises(ValueError):
            interpret_general_message(
                "Habari",
                self.organization,
                self.state,
                current_message_id=True,
            )

    @patch.dict("os.environ", {}, clear=True)
    def test_requires_provider_configuration(self):
        with self.assertRaises(WhatsAppAIConfigurationError):
            interpret_general_message(
                "Habari", self.organization, self.state
            )

    @patch("whatsapp.ai_service._get_recent_history")
    @patch.dict(
        "os.environ",
        {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"},
    )
    def test_uses_history_and_tanzanian_default(self, mock_history):
        mock_history.return_value = [
            {
                "direction": "inbound",
                "sender_type": "customer",
                "message": "Habari",
            }
        ]

        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            status="completed",
            output_text=json.dumps({
                "action": "reply",
                "intent": "greeting",
                "answer": "Habari! Nikusaidie nini?",
            }),
        )

        result = interpret_general_message(
            "Nataka kujua zaidi",
            self.organization,
            self.state,
            client=client,
            current_message_id=55,
        )

        self.assertEqual(result["action"], "reply")

        context = json.loads(
            client.responses.create.call_args.kwargs["input"]
        )

        self.assertEqual(
            context["default_language"], "Tanzanian Kiswahili"
        )
        self.assertEqual(len(context["conversation_history"]), 1)
        mock_history.assert_called_once()


class GeneralAIIntegrationTests(SimpleTestCase):

    def setUp(self):
        self.organization = SimpleNamespace(pk=10)
        self.state = SimpleNamespace(
            pk=20,
            data={},
            current_step=None,
            waiting_for=None,
            conversation=SimpleNamespace(
                organization_id=10,
                business_request_id=None,
                business_request=None,
            ),
        )

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_returns_greeting(self, mock_ai):
        mock_ai.return_value = {
            "action": "reply",
            "intent": "greeting",
            "answer": "Habari! Nikusaidie nini?",
        }

        self.assertEqual(
            get_ai_general_reply(
                "Habari", self.organization, self.state, 100
            ),
            "Habari! Nikusaidie nini?",
        )

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_product_enquiry_falls_through(self, mock_ai):
        mock_ai.return_value = {
            "action": "route_existing",
            "intent": "product_enquiry",
            "answer": "",
        }

        self.assertIsNone(
            get_ai_general_reply(
                "Natafuta laptop", self.organization, self.state, 101
            )
        )

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_active_request_blocks_ai(self, mock_ai):
        self.state.data["business_request_id"] = 500

        self.assertIsNone(
            get_ai_general_reply(
                "Habari", self.organization, self.state, 102
            )
        )
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_pending_field_blocks_ai(self, mock_ai):
        self.state.waiting_for = "location"

        self.assertIsNone(
            get_ai_general_reply(
                "Dar es Salaam", self.organization, self.state, 103
            )
        )
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_selected_product_blocks_ai(self, mock_ai):
        self.state.data["selected_whatsapp_product_id"] = 50

        self.assertIsNone(
            get_ai_general_reply(
                "Habari", self.organization, self.state, 104
            )
        )
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_unknown_step_blocks_ai(self, mock_ai):
        self.state.current_step = "future_workflow_step"

        self.assertIsNone(
            get_ai_general_reply(
                "Habari", self.organization, self.state, 105
            )
        )
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_linked_request_blocks_ai(self, mock_ai):
        self.state.conversation.business_request_id = 500

        self.assertIsNone(
            get_ai_general_reply(
                "Habari", self.organization, self.state, 106
            )
        )
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_provider_failure_falls_back(self, mock_ai):
        mock_ai.side_effect = RuntimeError("Provider unavailable")

        self.assertIsNone(
            get_ai_general_reply(
                "Habari", self.organization, self.state, 107
            )
        )

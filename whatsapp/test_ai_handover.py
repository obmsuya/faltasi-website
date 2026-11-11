import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from whatsapp.ai_service import (
    WhatsAppAIInvalidResponseError,
    _parse_general_ai_response,
)
from whatsapp.views import (
    _human_handover_acknowledgement,
    get_ai_human_support_intent,
    get_ai_human_support_language,
)


class Phase3DLanguageResponseTests(SimpleTestCase):

    def parse(self, payload):
        return _parse_general_ai_response(
            SimpleNamespace(
                status="completed",
                output_text=json.dumps(payload),
            )
        )

    def test_accepts_swahili_language(self):
        result = self.parse({
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
            "language": "sw",
        })
        self.assertEqual(result["language"], "sw")

    def test_accepts_english_language(self):
        result = self.parse({
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
            "language": "en",
        })
        self.assertEqual(result["language"], "en")

    def test_accepts_mixed_language(self):
        result = self.parse({
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
            "language": "mixed",
        })
        self.assertEqual(result["language"], "mixed")

    def test_rejects_unsupported_language(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "route_existing",
                "intent": "human_support",
                "answer": "",
                "language": "French",
            })

    def test_rejects_null_language(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "route_existing",
                "intent": "human_support",
                "answer": "",
                "language": None,
            })

    def test_legacy_three_field_response_remains_supported(self):
        result = self.parse({
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
        })
        self.assertEqual(
            result,
            {
                "action": "route_existing",
                "intent": "human_support",
                "answer": "",
            },
        )


class Phase3DHumanHandoverTests(SimpleTestCase):

    def setUp(self):
        self.organization = SimpleNamespace(pk=10)
        self.state = SimpleNamespace(
            pk=20,
            conversation=SimpleNamespace(organization_id=10),
        )

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_returns_detected_swahili_language(self, mock_interpret):
        mock_interpret.return_value = {
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
            "language": "sw",
        }

        result = get_ai_human_support_language(
            "Naomba kuongea na mtu",
            self.organization,
            self.state,
            55,
        )

        self.assertEqual(result, "sw")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_returns_detected_english_language(self, mock_interpret):
        mock_interpret.return_value = {
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
            "language": "en",
        }

        result = get_ai_human_support_language(
            "I want to speak to someone",
            self.organization,
            self.state,
            56,
        )

        self.assertEqual(result, "en")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_returns_detected_mixed_language(self, mock_interpret):
        mock_interpret.return_value = {
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
            "language": "mixed",
        }

        result = get_ai_human_support_language(
            "Naomba help from your team",
            self.organization,
            self.state,
            57,
        )

        self.assertEqual(result, "mixed")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_legacy_handover_defaults_to_swahili(self, mock_interpret):
        mock_interpret.return_value = {
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
        }

        result = get_ai_human_support_language(
            "Naomba msaada",
            self.organization,
            self.state,
            58,
        )

        self.assertEqual(result, "sw")

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_other_intent_does_not_trigger_handover(self, mock_interpret):
        mock_interpret.return_value = {
            "action": "reply",
            "intent": "general_enquiry",
            "answer": "Habari!",
        }

        result = get_ai_human_support_language(
            "Habari",
            self.organization,
            self.state,
            59,
        )

        self.assertIsNone(result)

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_cross_organization_conversation_is_rejected(self, mock_interpret):
        self.state.conversation.organization_id = 99

        result = get_ai_human_support_language(
            "Naomba msaada",
            self.organization,
            self.state,
            60,
        )

        self.assertIsNone(result)
        mock_interpret.assert_not_called()

    @patch("whatsapp.ai_service.interpret_general_message")
    def test_existing_boolean_helper_remains_compatible(self, mock_interpret):
        mock_interpret.return_value = {
            "action": "route_existing",
            "intent": "human_support",
            "answer": "",
            "language": "en",
        }

        result = get_ai_human_support_intent(
            "I need assistance",
            self.organization,
            self.state,
            61,
        )

        self.assertIs(result, True)

    def test_swahili_acknowledgement(self):
        self.assertEqual(
            _human_handover_acknowledgement("sw"),
            "Sawa, tumekuelewa. Tutaendelea kukusaidia hapa.",
        )

    def test_english_acknowledgement(self):
        self.assertEqual(
            _human_handover_acknowledgement("en"),
            "Thanks for letting us know. We’ll continue helping you here.",
        )

    def test_mixed_acknowledgement(self):
        self.assertEqual(
            _human_handover_acknowledgement("mixed"),
            "Sawa, tumekuelewa. We’ll continue helping you hapa.",
        )
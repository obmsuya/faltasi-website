import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from whatsapp.ai_service import (
    WhatsAppAIInvalidResponseError,
    _parse_product_discovery_response,
)
from whatsapp.views import get_ai_product_discovery_reply


class ProductDiscoveryResponseTests(SimpleTestCase):

    def parse(self, payload, status="completed"):
        response = SimpleNamespace(
            output_text=json.dumps(payload),
            status=status,
        )
        return _parse_product_discovery_response(response)

    def test_accepts_search_decision(self):
        result = self.parse({
            "action": "search",
            "search_query": "laptop suitable for accounting",
            "clarification": "",
        })

        self.assertEqual(result["action"], "search")
        self.assertEqual(
            result["search_query"],
            "laptop suitable for accounting",
        )

    def test_accepts_clarification_decision(self):
        result = self.parse({
            "action": "clarify",
            "search_query": "",
            "clarification": "Unahitaji laptop kwa matumizi gani?",
        })

        self.assertEqual(result["action"], "clarify")

    def test_rejects_product_id_or_extra_fields(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "search",
                "search_query": "laptop",
                "clarification": "",
                "product_id": 123,
            })

    def test_rejects_unknown_action(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "select_product",
                "search_query": "laptop",
                "clarification": "",
            })

    def test_rejects_empty_search(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "search",
                "search_query": "",
                "clarification": "",
            })

    def test_rejects_search_and_clarification_together(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "search",
                "search_query": "laptop",
                "clarification": "Which size?",
            })

    def test_rejects_incomplete_provider_response(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "search",
                "search_query": "laptop",
                "clarification": "",
            }, status="incomplete")

    def test_rejects_invalid_json(self):
        response = SimpleNamespace(
            output_text="not json",
            status="completed",
        )

        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_product_discovery_response(response)


class ProductDiscoveryIntegrationGuardTests(SimpleTestCase):

    def setUp(self):
        self.organization = SimpleNamespace(pk=10)

        self.conversation = SimpleNamespace(
            organization_id=10,
            business_request_id=None,
            business_request=None,
        )

        self.state = SimpleNamespace(
            pk=20,
            data={},
            waiting_for=None,
            current_step=None,
            conversation=self.conversation,
        )

    @patch("whatsapp.ai_service.interpret_product_discovery")
    def test_active_workflow_is_not_intercepted(self, mock_ai):
        self.state.waiting_for = "product_selection"

        result = get_ai_product_discovery_reply(
            "I need a laptop",
            self.organization,
            self.state,
            100,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_product_discovery")
    def test_business_request_is_not_intercepted(self, mock_ai):
        self.conversation.business_request_id = 55

        result = get_ai_product_discovery_reply(
            "I need a laptop",
            self.organization,
            self.state,
            100,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.ai_service.interpret_product_discovery")
    def test_unknown_workflow_step_is_not_intercepted(self, mock_ai):
        self.state.current_step = "unknown_future_workflow"

        result = get_ai_product_discovery_reply(
            "I need a laptop",
            self.organization,
            self.state,
            100,
        )

        self.assertIsNone(result)
        mock_ai.assert_not_called()

    @patch("whatsapp.views.search_whatsapp_products")
    @patch("whatsapp.ai_service.interpret_product_discovery")
    def test_search_decision_uses_django_catalogue_search(
        self,
        mock_ai,
        mock_search,
    ):
        mock_ai.return_value = {
            "action": "search",
            "search_query": "laptop for accounting",
            "clarification": "",
        }
        mock_search.return_value = "1. Actual catalogue laptop"

        result = get_ai_product_discovery_reply(
            "Natafuta laptop kwa accounting",
            self.organization,
            self.state,
            100,
        )

        mock_search.assert_called_once_with(
            "laptop for accounting",
            self.organization,
            self.state,
        )
        self.assertEqual(
            result["reply"],
            "1. Actual catalogue laptop",
        )
        self.assertEqual(
            result["product_reply"],
            "1. Actual catalogue laptop",
        )

    @patch("whatsapp.views.search_whatsapp_products")
    @patch("whatsapp.ai_service.interpret_product_discovery")
    def test_clarification_does_not_search_catalogue(
        self,
        mock_ai,
        mock_search,
    ):
        mock_ai.return_value = {
            "action": "clarify",
            "search_query": "",
            "clarification": "Unahitaji laptop kwa matumizi gani?",
        }

        result = get_ai_product_discovery_reply(
            "Nahitaji computer",
            self.organization,
            self.state,
            100,
        )

        mock_search.assert_not_called()
        self.assertEqual(
            result["reply"],
            "Unahitaji laptop kwa matumizi gani?",
        )
        self.assertIsNone(result["product_reply"])

    @patch("whatsapp.ai_service.interpret_product_discovery")
    def test_ai_failure_uses_existing_fallback(self, mock_ai):
        mock_ai.side_effect = RuntimeError("Provider unavailable")

        result = get_ai_product_discovery_reply(
            "I need a laptop",
            self.organization,
            self.state,
            100,
        )

        self.assertIsNone(result)
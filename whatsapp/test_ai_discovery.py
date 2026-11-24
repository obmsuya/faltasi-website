import json
from decimal import Decimal
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

    def base_payload(self, **overrides):
        payload = {
            "action": "search",
            "search_query": "laptop suitable for accounting",
            "clarification": "",
            "price_preference": "any",
            "min_price": None,
            "max_price": None,
            "specification_requirements": [],
        }
        payload.update(overrides)
        return payload

    def test_accepts_search_decision_with_any_price_and_any_specs(self):
        result = self.parse(self.base_payload())

        self.assertEqual(result["action"], "search")
        self.assertEqual(
            result["search_query"],
            "laptop suitable for accounting",
        )
        self.assertEqual(result["price_preference"], "any")
        self.assertIsNone(result["min_price"])
        self.assertIsNone(result["max_price"])
        self.assertEqual(result["specification_requirements"], [])

    def test_accepts_search_with_price_and_specification_requirements(self):
        result = self.parse(self.base_payload(
            price_preference="economical",
            min_price="100000",
            max_price="500000",
            specification_requirements=[
                "8GB RAM",
                "SSD storage",
            ],
        ))

        self.assertEqual(result["price_preference"], "economical")
        self.assertEqual(result["min_price"], Decimal("100000"))
        self.assertEqual(result["max_price"], Decimal("500000"))
        self.assertEqual(
            result["specification_requirements"],
            ["8GB RAM", "SSD storage"],
        )

    def test_accepts_clarification_decision(self):
        result = self.parse(self.base_payload(
            action="clarify",
            search_query="",
            clarification="Unahitaji laptop kwa matumizi gani?",
        ))

        self.assertEqual(result["action"], "clarify")
        self.assertEqual(
            result["clarification"],
            "Unahitaji laptop kwa matumizi gani?",
        )

    def test_rejects_product_id_or_extra_fields(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse(self.base_payload(product_id=123))

    def test_rejects_unknown_action(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse(self.base_payload(action="select_product"))

    def test_rejects_unknown_price_preference(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse(self.base_payload(price_preference="cheapish"))

    def test_rejects_empty_search(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse(self.base_payload(search_query=""))

    def test_rejects_search_and_clarification_together(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse(self.base_payload(
                clarification="Which size?",
            ))

    def test_rejects_incomplete_provider_response(self):
        response = SimpleNamespace(
            output_text=json.dumps(self.base_payload()),
            status="incomplete",
        )
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_product_discovery_response(response)

    def test_rejects_invalid_json(self):
        response = SimpleNamespace(
            output_text="not json",
            status="completed",
        )
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_product_discovery_response(response)

    def test_rejects_invalid_price_range(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse(self.base_payload(
                min_price="600000",
                max_price="500000",
            ))

    def test_rejects_invalid_specification_requirements(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse(self.base_payload(
                specification_requirements=["", 123],
            ))


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
            save=lambda **kwargs: None,
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
    def test_search_decision_passes_all_customer_requirements_to_catalogue(
        self,
        mock_ai,
        mock_search,
    ):
        mock_ai.return_value = {
            "action": "search",
            "search_query": "laptop for accounting",
            "clarification": "",
            "price_preference": "economical",
            "min_price": Decimal("100000"),
            "max_price": Decimal("500000"),
            "specification_requirements": ["8GB RAM", "SSD storage"],
        }
        mock_search.return_value = "1. Actual catalogue laptop"

        result = get_ai_product_discovery_reply(
            "Natafuta laptop kwa accounting, iwe economical na 8GB RAM",
            self.organization,
            self.state,
            100,
        )

        mock_search.assert_called_once_with(
            "laptop for accounting",
            self.organization,
            self.state,
            price_preference="economical",
            min_price=Decimal("100000"),
            max_price=Decimal("500000"),
            specification_requirements=["8GB RAM", "SSD storage"],
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
    def test_any_price_and_any_specifications_are_passed_to_catalogue(
        self,
        mock_ai,
        mock_search,
    ):
        mock_ai.return_value = {
            "action": "search",
            "search_query": "printer",
            "clarification": "",
            "price_preference": "any",
            "min_price": None,
            "max_price": None,
            "specification_requirements": [],
        }
        mock_search.return_value = "1. Actual catalogue printer"

        result = get_ai_product_discovery_reply(
            "Any price and any specifications",
            self.organization,
            self.state,
            101,
        )

        mock_search.assert_called_once_with(
            "printer",
            self.organization,
            self.state,
            price_preference="any",
            min_price=None,
            max_price=None,
            specification_requirements=[],
        )
        self.assertEqual(result["product_reply"], "1. Actual catalogue printer")

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
            "price_preference": "any",
            "min_price": None,
            "max_price": None,
            "specification_requirements": [],
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
        self.assertEqual(
            self.state.data["whatsapp_product_discovery"]["status"],
            "awaiting_clarification",
        )

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

import json
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from whatsapp.ai_service import (
    WhatsAppAIInvalidResponseError,
    _parse_request_category_response,
    interpret_request_category,
)


class RequestCategoryResponseParserTests(TestCase):

    def setUp(self):
        self.allowed_ids = {10, 20}

    def response(self, payload):
        return SimpleNamespace(
            status="completed",
            output_text=json.dumps(payload),
        )

    def test_accepts_valid_category_match(self):
        result = _parse_request_category_response(
            self.response({
                "action": "match",
                "category_id": 10,
                "clarification": "",
            }),
            self.allowed_ids,
        )
        self.assertEqual(result["category_id"], 10)

    def test_accepts_clarification(self):
        result = _parse_request_category_response(
            self.response({
                "action": "clarify",
                "category_id": None,
                "clarification": "Unahitaji huduma gani hasa?",
            }),
            self.allowed_ids,
        )
        self.assertEqual(result["action"], "clarify")

    def test_accepts_no_match(self):
        result = _parse_request_category_response(
            self.response({
                "action": "none",
                "category_id": None,
                "clarification": "",
            }),
            self.allowed_ids,
        )
        self.assertEqual(result["action"], "none")

    def test_rejects_category_outside_candidates(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_request_category_response(
                self.response({
                    "action": "match",
                    "category_id": 999,
                    "clarification": "",
                }),
                self.allowed_ids,
            )

    def test_rejects_boolean_category_id(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_request_category_response(
                self.response({
                    "action": "match",
                    "category_id": True,
                    "clarification": "",
                }),
                self.allowed_ids,
            )

    def test_rejects_extra_fields(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_request_category_response(
                self.response({
                    "action": "match",
                    "category_id": 10,
                    "clarification": "",
                    "business_request_id": 500,
                }),
                self.allowed_ids,
            )

    def test_rejects_match_with_clarification(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_request_category_response(
                self.response({
                    "action": "match",
                    "category_id": 10,
                    "clarification": "Are you sure?",
                }),
                self.allowed_ids,
            )

    def test_rejects_empty_clarification(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_request_category_response(
                self.response({
                    "action": "clarify",
                    "category_id": None,
                    "clarification": "",
                }),
                self.allowed_ids,
            )

    def test_rejects_invalid_action(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_request_category_response(
                self.response({
                    "action": "create_request",
                    "category_id": 10,
                    "clarification": "",
                }),
                self.allowed_ids,
            )

    def test_rejects_invalid_json(self):
        response = SimpleNamespace(
            status="completed",
            output_text="{invalid",
        )
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_request_category_response(
                response,
                self.allowed_ids,
            )


class RequestCategoryInterpreterTests(TestCase):

    def setUp(self):
        self.organization = SimpleNamespace(pk=10)
        self.state = SimpleNamespace(
            pk=100,
            conversation=SimpleNamespace(organization_id=10),
        )
        self.categories = [
            {"id": 1, "name": "Property Management"},
            {"id": 2, "name": "ICT Support"},
        ]

    @patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-key",
        "OPENAI_MODEL": "test-model",
    })
    @patch("whatsapp.ai_service._get_recent_history", return_value=[])
    def test_sends_restricted_categories_to_ai(self, history):
        client = MagicMock()
        client.responses.create.return_value = SimpleNamespace(
            status="completed",
            output_text=json.dumps({
                "action": "match",
                "category_id": 2,
                "clarification": "",
            }),
        )

        result = interpret_request_category(
            "Nahitaji msaada wa computer",
            self.organization,
            self.state,
            self.categories,
            client=client,
        )

        self.assertEqual(result["category_id"], 2)

        call = client.responses.create.call_args
        context = json.loads(call.kwargs["input"])
        self.assertIn("json", context["response_format_instruction"].lower())
        self.assertEqual(context["available_categories"], self.categories)

    def test_rejects_cross_organization_conversation(self):
        self.state.conversation.organization_id = 99

        with self.assertRaises(ValueError):
            interpret_request_category(
                "Nahitaji msaada",
                self.organization,
                self.state,
                self.categories,
            )

    def test_empty_category_list_returns_none(self):
        result = interpret_request_category(
            "Hello",
            self.organization,
            self.state,
            [],
        )
        self.assertEqual(result["action"], "none")

    def test_rejects_more_than_thirty_categories(self):
        categories = [
            {"id": i, "name": f"Category {i}"}
            for i in range(1, 32)
        ]

        with self.assertRaises(ValueError):
            interpret_request_category(
                "Hello",
                self.organization,
                self.state,
                categories,
            )
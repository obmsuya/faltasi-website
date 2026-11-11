import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from organizations.models import Organization
from customers.models import Customer
from products.models import Product
from whatsapp.models import Conversation, ConversationState, Message

from whatsapp.ai_service import (
    WhatsAppAIConfigurationError,
    WhatsAppAIInvalidResponseError,
    _clean_customer_data,
    _get_recent_history,
    _parse_ai_response,
    _product_context,
    interpret_product_message,
)


class WhatsAppAIResponseValidationTests(TestCase):

    def setUp(self):
        self.product = SimpleNamespace(pk=101)
        self.other_product = SimpleNamespace(pk=202)

    def parse(self, payload, products=None, selected=None, status=None):
        response = SimpleNamespace(
            output_text=json.dumps(payload),
            status=status,
        )
        return _parse_ai_response(
            response,
            products if products is not None else [self.product],
            selected,
        )

    def test_accepts_valid_product_answer(self):
        result = self.parse({
            "action": "answer_product",
            "product_id": 101,
            "answer": "The product costs TZS 50,000.",
        })

        self.assertEqual(result["action"], "answer_product")
        self.assertEqual(result["product_id"], 101)

    def test_accepts_numeric_string_product_id(self):
        result = self.parse({
            "action": "answer_product",
            "product_id": "101",
            "answer": "This product is available.",
        })

        self.assertEqual(result["product_id"], 101)

    def test_rejects_product_from_another_organization_context(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "answer_product",
                "product_id": 202,
                "answer": "Another product.",
            })

    def test_rejects_boolean_product_id(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "answer_product",
                "product_id": True,
                "answer": "Product answer.",
            })

    def test_rejects_fractional_product_id(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "answer_product",
                "product_id": 101.5,
                "answer": "Product answer.",
            })

    def test_rejects_unexpected_response_fields(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "answer_product",
                "product_id": 101,
                "answer": "Product answer.",
                "internal_cost": 100,
            })

    def test_rejects_empty_product_answer(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "answer_product",
                "product_id": 101,
                "answer": "",
            })

    def test_rejects_wrong_selected_product(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse(
                {
                    "action": "answer_product",
                    "product_id": 202,
                    "answer": "Product answer.",
                },
                products=[self.product],
                selected=self.product,
            )

    def test_selected_product_is_used_when_id_is_omitted(self):
        result = self.parse(
            {
                "action": "answer_product",
                "product_id": None,
                "answer": "This is the selected product.",
            },
            selected=self.product,
        )

        self.assertEqual(result["product_id"], 101)

    def test_accepts_clarification(self):
        result = self.parse({
            "action": "clarify_product",
            "product_id": None,
            "answer": "Which model are you interested in?",
        })

        self.assertEqual(result["action"], "clarify_product")

    def test_rejects_empty_clarification(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "clarify_product",
                "product_id": None,
                "answer": "",
            })

    def test_workflow_decision_must_not_include_answer(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse({
                "action": "workflow_input",
                "product_id": None,
                "answer": "I will process your order.",
            })

    def test_rejects_incomplete_provider_response(self):
        response = SimpleNamespace(
            output_text=json.dumps({
                "action": "other",
                "product_id": None,
                "answer": "",
            }),
            status="incomplete",
        )

        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_ai_response(response, [], None)

    def test_rejects_invalid_json(self):
        response = SimpleNamespace(
            output_text="not json",
            status="completed",
        )

        with self.assertRaises(WhatsAppAIInvalidResponseError):
            _parse_ai_response(response, [], None)


class WhatsAppAIProductDataTests(TestCase):

    def test_sensitive_nested_fields_are_removed(self):
        data = {
            "color": "black",
            "cost_price": 1000,
            "wholesale": {
                "price": 2000,
            },
            "details": [
                {
                    "supplier_name": "Private Supplier",
                    "description": "Customer-safe detail",
                }
            ],
        }

        cleaned = _clean_customer_data(data)

        self.assertEqual(cleaned["color"], "black")
        self.assertNotIn("cost_price", cleaned)
        self.assertNotIn("wholesale", cleaned)
        self.assertNotIn("supplier_name", cleaned["details"][0])

    def test_product_context_excludes_internal_inventory_and_prices(self):
        product = SimpleNamespace(
            pk=1,
            name="Laptop",
            short_description="Business laptop",
            description="Laptop description",
            brand="Lenovo",
            model="ThinkPad",
            manufacturer="Lenovo",
            price=1500000,
            currency="TZS",
            unit="piece",
            availability="in_stock",
            specifications={"RAM": "8GB"},
            additional_information={"warranty": "12 months"},
            cost_price=1000000,
            wholesale_price=1200000,
            quantity=50,
        )

        context = _product_context(product)

        self.assertEqual(context["selling_price"], "1500000")
        self.assertNotIn("cost_price", context)
        self.assertNotIn("wholesale_price", context)
        self.assertNotIn("quantity", context)


class WhatsAppAIConversationHistoryTests(TestCase):

    def setUp(self):
        self.organization = Organization.objects.create(
            name="AI Test Business",
            organization_type="business",
            status="active",
        )

        self.customer = Customer.objects.create(
            organization=self.organization,
            name="AI Test Customer",
            phone="+255700000091",
        )

        self.conversation = Conversation.objects.create(
            organization=self.organization,
            customer=self.customer,
            phone_number="+255700000091",
        )

        self.state = ConversationState.objects.create(
            conversation=self.conversation,
        )

    def create_message(self, content, direction="incoming"):
        return Message.objects.create(
            organization=self.organization,
            conversation=self.conversation,
            direction=direction,
            sender_type=(
                "customer" if direction == "incoming" else "faltasi"
            ),
            message_type="text",
            content=content,
        )

    def test_excludes_current_message_by_exact_database_id(self):
        earlier = self.create_message("Habari")
        current = self.create_message("Habari")

        history = _get_recent_history(
            self.state,
            current_text="Habari",
            current_message_id=current.pk,
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["message"], "Habari")
        self.assertEqual(earlier.content, history[0]["message"])

    def test_preserves_repeated_messages_when_no_id_is_supplied(self):
        self.create_message("Bei yake ni ngapi?")
        self.create_message("Bei yake ni ngapi?")

        history = _get_recent_history(
            self.state,
            current_text="Bei yake ni ngapi?",
        )

        self.assertEqual(len(history), 2)

    def test_history_is_limited_to_current_conversation(self):
        self.create_message("Message from this customer")

        other_customer = Customer.objects.create(
            organization=self.organization,
            name="Other Customer",
            phone="+255700000092",
        )

        other_conversation = Conversation.objects.create(
            organization=self.organization,
            customer=other_customer,
            phone_number="+255700000092",
        )

        Message.objects.create(
            organization=self.organization,
            conversation=other_conversation,
            direction="incoming",
            sender_type="customer",
            message_type="text",
            content="Private other conversation",
        )

        history = _get_recent_history(self.state)

        self.assertEqual(len(history), 1)
        self.assertEqual(
            history[0]["message"],
            "Message from this customer",
        )

    def test_invalid_current_message_id_is_rejected(self):
        with self.assertRaises(ValueError):
            _get_recent_history(
                self.state,
                current_message_id=True,
            )

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_openai_configuration_fails_safely(self):
        with self.assertRaises(WhatsAppAIConfigurationError):
            interpret_product_message(
                "Tell me about your products",
                self.organization,
                self.state,
                client=Mock(),
            )

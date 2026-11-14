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
    _get_published_product_conversation,
    _get_recent_history,
    _parse_ai_response,
    _parse_product_builder_answers,
    _product_context,
    interpret_product_message,
    
)

from conversation_builder.models import (
    ProductConversationConfiguration,
    ProductConversationVersion,
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


class WhatsAppAIProductBuilderAnswerParserTests(TestCase):

    def parse_answers(
        self,
        payload,
        allowed=("customer_name", "location"),
        allowed_corrections=(),
        status="completed",
    ):
        response = SimpleNamespace(
            output_text=json.dumps(payload, ensure_ascii=False),
            status=status,
        )
        return _parse_product_builder_answers(
            response, allowed, allowed_corrections
        )

    def test_accepts_multiple_known_answers(self):
        result = self.parse_answers({
            "answers": {
                "customer_name": "Amina",
                "location": "Dar es Salaam",
            }
        })
        self.assertEqual(result["answers"]["customer_name"], "Amina")
        self.assertEqual(result["answers"]["location"], "Dar es Salaam")

    def test_accepts_empty_extraction(self):
        self.assertEqual(
            self.parse_answers({"answers": {}}),
            {"answers": {}, "corrections": {}},
        )

    def test_rejects_unknown_question_key(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse_answers({"answers": {"internal_cost": "100"}})

    def test_rejects_non_text_answer(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse_answers({"answers": {"customer_name": {"value": "Amina"}}})

    def test_rejects_unexpected_outer_fields(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse_answers({"answers": {}, "action": "submit_order"})

    def test_rejects_empty_answer(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse_answers({"answers": {"customer_name": "   "}})

    def test_rejects_overlong_answer(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse_answers({"answers": {"customer_name": "x" * 1001}})



    def test_accepts_explicit_correction_for_saved_question(self):
        result = self.parse_answers(
            {
                "answers": {"location": "Arusha"},
                "corrections": {"customer_name": "Amira"},
            },
            allowed=("location",),
            allowed_corrections=("customer_name",),
        )
        self.assertEqual(result["answers"], {"location": "Arusha"})
        self.assertEqual(result["corrections"], {"customer_name": "Amira"})

    def test_rejects_correction_for_question_not_in_saved_allowlist(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse_answers(
                {
                    "answers": {},
                    "corrections": {"internal_cost": "100"},
                },
                allowed_corrections=("customer_name",),
            )

    def test_rejects_same_question_as_answer_and_correction(self):
        with self.assertRaises(WhatsAppAIInvalidResponseError):
            self.parse_answers(
                {
                    "answers": {"customer_name": "Amina"},
                    "corrections": {"customer_name": "Amira"},
                },
                allowed=("customer_name",),
                allowed_corrections=("customer_name",),
            )


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



class WhatsAppAIProductConversationConfigurationTests(TestCase):

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Product AI Configuration Business",
            organization_type="business",
            status="active",
        )

        self.other_organization = Organization.objects.create(
            name="Other Product AI Business",
            organization_type="business",
            status="active",
        )

        self.product = Product.objects.create(
            organization=self.organization,
            name="Test Product",
            show_on_whatsapp=True,
            is_active=True,
        )

        self.configuration = ProductConversationConfiguration.objects.create(
            organization=self.organization,
            product=self.product,
            is_enabled=True,
        )

    def create_version(self, status="published", number=1):
        return ProductConversationVersion.objects.create(
            configuration=self.configuration,
            version_number=number,
            status=status,
            default_language="sw",
            ai_instructions="Use friendly Tanzanian Kiswahili.",
            snapshot={
                "version_number": number,
                "default_language": "sw",
                "ai_instructions": "Use friendly Tanzanian Kiswahili.",
            },
        )

    def test_loads_published_product_configuration(self):
        version = self.create_version()

        self.configuration.published_version = version
        self.configuration.save(update_fields=["published_version"])

        result = _get_published_product_conversation(
            self.organization,
            self.product,
        )

        self.assertEqual(
            result["version_number"],
            1,
        )
        self.assertEqual(result["default_language"], "sw")
        self.assertEqual(
            result["ai_instructions"],
            "Use friendly Tanzanian Kiswahili.",
        )

    def test_ignores_draft_configuration(self):
        version = self.create_version(status="draft")

        self.configuration.draft_version = version
        self.configuration.save(update_fields=["draft_version"])

        result = _get_published_product_conversation(
            self.organization,
            self.product,
        )

        self.assertIsNone(result)

    def test_ignores_disabled_configuration(self):
        version = self.create_version()

        self.configuration.published_version = version
        self.configuration.is_enabled = False
        self.configuration.save(
            update_fields=["published_version", "is_enabled"]
        )

        result = _get_published_product_conversation(
            self.organization,
            self.product,
        )

        self.assertIsNone(result)

    def test_does_not_load_another_organizations_configuration(self):
        version = self.create_version()

        self.configuration.published_version = version
        self.configuration.save(update_fields=["published_version"])

        result = _get_published_product_conversation(
            self.other_organization,
            self.product,
        )

        self.assertIsNone(result)

    
    def test_returns_none_when_no_product_is_selected(self):
        result = _get_published_product_conversation(
            self.organization,
            None,
        )

        self.assertIsNone(result)

    @patch.dict(
        "os.environ",
        {
            "OPENAI_API_KEY": "test-api-key",
            "OPENAI_MODEL": "test-model",
        },
    )
    def test_published_configuration_is_sent_to_ai_provider(self):
        customer = Customer.objects.create(
            organization=self.organization,
            name="Integration Test Customer",
            phone="+255700000099",
        )

        conversation = Conversation.objects.create(
            organization=self.organization,
            customer=customer,
            phone_number="+255700000099",
        )

        state = ConversationState.objects.create(
            conversation=conversation,
            data={
                "selected_whatsapp_product_id": self.product.pk,
            },
        )

        version = self.create_version()

        self.configuration.published_version = version
        self.configuration.save(update_fields=["published_version"])

        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=json.dumps({
                "action": "answer_product",
                "product_id": self.product.pk,
                "answer": "Bidhaa hii inapatikana.",
            }),
            status="completed",
        )

        result = interpret_product_message(
            "Bidhaa hii ina maelezo gani?",
            self.organization,
            state,
            client=client,
        )

        self.assertEqual(result["action"], "answer_product")
        self.assertEqual(result["product_id"], self.product.pk)

        request = client.responses.create.call_args.kwargs
        sent_context = json.loads(request["input"])

        self.assertEqual(
            sent_context["product_conversation_configuration"],
            {
                "version_number": 1,
                "default_language": "sw",
                "ai_instructions": "Use friendly Tanzanian Kiswahili.",
            },
        )

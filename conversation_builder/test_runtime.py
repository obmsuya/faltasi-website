from types import SimpleNamespace

from django.test import TestCase

from organizations.models import Organization
from products.models import Product

from conversation_builder.models import (
    ProductConversationConfiguration,
    ProductConversationQuestion,
)
from conversation_builder.services import (
    publish_product_draft,
    create_product_configuration,
    create_product_draft_version,
)
from conversation_builder.runtime import (
    BUILDER_STEP,
    BUILDER_WAITING_FOR,
    get_next_question,
    get_runtime_status,
    skip_product_question,
    start_product_conversation,
    submit_product_question_answers,
    validate_product_question_answer,
)


class RuntimeState:
    """Minimal state object matching the runtime's required interface."""

    def __init__(self, data=None):
        self.data = data or {}
        self.current_step = None
        self.waiting_for = None
        self.save_count = 0

    def save(self):
        self.save_count += 1


class ProductConversationRuntimeTests(TestCase):

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Runtime Test Organization",
            slug="runtime-test-organization",
            status="active",
        )

        self.other_organization = Organization.objects.create(
            name="Other Runtime Organization",
            slug="other-runtime-organization",
            status="active",
        )

        self.product = Product.objects.create(
            organization=self.organization,
            name="Runtime Test Product",
            show_on_whatsapp=True,
            is_active=True,
        )

        self.configuration, self.draft = create_product_configuration(
            self.product.pk,
            self.organization.pk,
        )

        self.state = RuntimeState()

    def publish_questions(self, questions):
        for item in questions:
            question = ProductConversationQuestion.objects.create(
                version=self.draft,
                **item,
            )

            if item.get("field_type") == "choice":
                from conversation_builder.models import ProductConversationOption

                ProductConversationOption.objects.create(
                    question=question,
                    value="new",
                    label="Brand New",
                    order=1,
                )

        return publish_product_draft(
            self.configuration.pk,
            self.organization.pk,
        )

    def test_start_pins_published_version_and_sets_builder_state(self):
        self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
        ])

        result = start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(result["question"]["key"], "customer_name")
        self.assertEqual(self.state.current_step, BUILDER_STEP)
        self.assertEqual(
            self.state.waiting_for,
            BUILDER_WAITING_FOR,
        )
        self.assertEqual(
            self.state.data["product_conversation"]["version_id"],
            result["version"].pk,
        )

    def test_no_enabled_published_configuration_returns_none(self):
        result = start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        self.assertIsNone(result)
        self.assertNotIn("product_conversation", self.state.data)

    def test_multiple_answers_are_validated_and_saved(self):
        self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
            {
                "key": "quantity",
                "question": "How many do you need?",
                "field_type": "number",
                "order": 2,
                "validation_rules": {
                    "min_value": 1,
                    "max_value": 100,
                },
            },
        ])

        start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        result = submit_product_question_answers(
            self.state,
            self.organization,
            self.product,
            {
                "customer_name": "Amina",
                "quantity": "5",
                "unknown_key": "must not be stored",
            },
        )

        answers = self.state.data["product_conversation"]["answers"]

        self.assertEqual(result["accepted"], ["customer_name", "quantity"])
        self.assertEqual(answers["customer_name"], "Amina")
        self.assertEqual(answers["quantity"], 5)
        self.assertNotIn("unknown_key", answers)
        self.assertEqual(result["status"], "completed")

    def test_invalid_answer_increments_attempt_counter(self):
        self.publish_questions([
            {
                "key": "quantity",
                "question": "How many do you need?",
                "field_type": "number",
                "order": 1,
                "validation_rules": {
                    "min_value": 1,
                    "max_value": 10,
                },
                "max_attempts": 2,
            },
        ])

        start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        result = submit_product_question_answers(
            self.state,
            self.organization,
            self.product,
            {"quantity": "0"},
        )

        self.assertEqual(result["accepted"], [])
        self.assertEqual(len(result["rejected"]), 1)
        self.assertEqual(result["rejected"][0]["attempts"], 1)
        self.assertFalse(
            result["rejected"][0]["attempts_exhausted"]
        )

    def test_attempt_limit_is_reported_without_silently_skipping(self):
        self.publish_questions([
            {
                "key": "quantity",
                "question": "How many do you need?",
                "field_type": "number",
                "order": 1,
                "max_attempts": 1,
            },
        ])

        start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        result = submit_product_question_answers(
            self.state,
            self.organization,
            self.product,
            {"quantity": "not a number"},
        )

        self.assertTrue(
            result["rejected"][0]["attempts_exhausted"]
        )
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(
            result["next_question"]["key"],
            "quantity",
        )
        self.assertNotIn(
            "quantity",
            self.state.data["product_conversation"]["answers"],
        )

    def test_optional_question_can_be_skipped(self):
        self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
                "is_required": False,
                "allow_skip": True,
            },
            {
                "key": "quantity",
                "question": "How many do you need?",
                "field_type": "number",
                "order": 2,
            },
        ])

        start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        result = skip_product_question(
            self.state,
            self.organization,
            self.product,
            "customer_name",
        )

        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(
            result["next_question"]["key"],
            "quantity",
        )
        self.assertIn(
            "customer_name",
            self.state.data["product_conversation"]["skipped"],
        )

    def test_required_question_cannot_be_skipped(self):
        self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
                "is_required": True,
                "allow_skip": False,
            },
        ])

        start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        result = skip_product_question(
            self.state,
            self.organization,
            self.product,
            "customer_name",
        )

        self.assertEqual(result["status"], "skip_not_allowed")
        self.assertNotIn(
            "customer_name",
            self.state.data["product_conversation"]["skipped"],
        )

    def test_dependency_waits_until_parent_is_completed(self):
        self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
            {
                "key": "delivery_location",
                "question": "Where should we deliver?",
                "field_type": "text",
                "order": 2,
                "display_conditions": {
                    "depends_on": ["customer_name"],
                },
            },
        ])

        start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        namespace = self.state.data["product_conversation"]
        
        self.configuration.refresh_from_db()
        question = get_next_question(
            self.configuration.published_version.snapshot,
            namespace,
        )

        self.assertEqual(question["key"], "customer_name")

        submit_product_question_answers(
            self.state,
            self.organization,
            self.product,
            {"customer_name": "Amina"},
        )

        result = get_runtime_status(
            self.state,
            self.organization,
            self.product,
        )

        self.assertEqual(
            result["question"]["key"],
            "delivery_location",
        )

    def test_dependent_answers_are_processed_when_child_arrives_first(self):
        self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
            {
                "key": "delivery_location",
                "question": "Where should we deliver?",
                "field_type": "text",
                "order": 2,
                "display_conditions": {
                    "depends_on": ["customer_name"],
                },
            },
        ])

        start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        result = submit_product_question_answers(
            self.state,
            self.organization,
            self.product,
            {
                "delivery_location": "Arusha",
                "customer_name": "Amina",
            },
        )

        self.assertEqual(
            set(result["accepted"]),
            {"customer_name", "delivery_location"},
        )

        answers = self.state.data["product_conversation"]["answers"]

        self.assertEqual(answers["customer_name"], "Amina")
        self.assertEqual(answers["delivery_location"], "Arusha")
        self.assertEqual(result["status"], "completed")

    def test_future_dependent_question_cannot_be_skipped(self):
        self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
            {
                "key": "delivery_location",
                "question": "Where should we deliver?",
                "field_type": "text",
                "order": 2,
                "is_required": False,
                "allow_skip": True,
                "display_conditions": {
                    "depends_on": ["customer_name"],
                },
            },
        ])

        start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        result = skip_product_question(
            self.state,
            self.organization,
            self.product,
            "delivery_location",
        )

        self.assertEqual(result["status"], "question_not_available")

        skipped = self.state.data["product_conversation"]["skipped"]

        self.assertNotIn("delivery_location", skipped)

        runtime = get_runtime_status(
            self.state,
            self.organization,
            self.product,
        )

        self.assertEqual(
            runtime["question"]["key"],
            "customer_name",
        )

    def test_archived_pinned_version_continues_after_new_publication(self):
        first_published = self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
        ])

        start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        second_draft = create_product_draft_version(
            self.configuration.pk,
            self.organization.pk,
        )

        ProductConversationQuestion.objects.create(
            version=second_draft,
            key="phone_number",
            question="What is your phone number?",
            field_type="text",
            order=2,
        )

        publish_product_draft(
            self.configuration.pk,
            self.organization.pk,
        )

        first_published.refresh_from_db()

        self.assertEqual(first_published.status, "archived")

        result = get_runtime_status(
            self.state,
            self.organization,
            self.product,
        )

        self.assertEqual(result["version"].pk, first_published.pk)
        self.assertEqual(
            result["question"]["key"],
            "customer_name",
        )

    def test_other_organization_cannot_use_pinned_version(self):
        self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
        ])

        start_product_conversation(
            self.state,
            self.organization,
            self.product,
        )

        result = get_runtime_status(
            self.state,
            self.other_organization,
            self.product,
        )

        self.assertIsNone(result)

    def test_yes_no_validation_uses_configured_values(self):
        question = {
            "field_type": "yes_no",
            "validation_rules": {
                "yes_values": ["yes", "ndiyo"],
                "no_values": ["no", "hapana"],
            },
        }

        self.assertEqual(
            validate_product_question_answer(question, "NDIYO"),
            (True, "yes"),
        )
        self.assertEqual(
            validate_product_question_answer(question, "hapana"),
            (True, "no"),
        )
        self.assertEqual(
            validate_product_question_answer(question, "maybe"),
            (False, None),
        )

    def test_choice_validation_accepts_only_active_options(self):
        question = {
            "field_type": "choice",
            "options": [
                {
                    "value": "new",
                    "label": "Brand New",
                    "is_active": True,
                },
                {
                    "value": "used",
                    "label": "Used",
                    "is_active": False,
                },
            ],
        }

        self.assertEqual(
            validate_product_question_answer(question, "Brand New"),
            (True, "new"),
        )
        self.assertEqual(
            validate_product_question_answer(question, "used"),
            (False, None),
        )


    def test_explicit_correction_updates_existing_answer(self):
        self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
            {
                "key": "quantity",
                "question": "How many do you need?",
                "field_type": "number",
                "order": 2,
            },
        ])
        start_product_conversation(self.state, self.organization, self.product)
        submit_product_question_answers(
            self.state, self.organization, self.product,
            {"customer_name": "Amina"},
        )

        result = submit_product_question_answers(
            self.state, self.organization, self.product,
            {"quantity": "5"},
            corrections={"customer_name": "Amira"},
        )

        answers = self.state.data["product_conversation"]["answers"]
        self.assertEqual(answers["customer_name"], "Amira")
        self.assertEqual(answers["quantity"], 5)
        self.assertEqual(result["corrected"], ["customer_name"])
        self.assertEqual(result["accepted"], ["quantity"])

    def test_invalid_correction_preserves_previous_answer(self):
        self.publish_questions([
            {
                "key": "quantity",
                "question": "How many do you need?",
                "field_type": "number",
                "order": 1,
                "validation_rules": {"min_value": 1, "max_value": 10},
            },
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 2,
            },
        ])
        start_product_conversation(self.state, self.organization, self.product)
        submit_product_question_answers(
            self.state, self.organization, self.product,
            {"quantity": "5"},
        )

        result = submit_product_question_answers(
            self.state, self.organization, self.product,
            {},
            corrections={"quantity": "50"},
        )

        self.assertEqual(
            self.state.data["product_conversation"]["answers"]["quantity"], 5
        )
        self.assertEqual(result["corrected"], [])
        self.assertEqual(len(result["rejected"]), 1)
        self.assertTrue(result["rejected"][0]["correction"])

    def test_correction_cannot_overwrite_unknown_or_unanswered_key(self):
        self.publish_questions([
            {
                "key": "customer_name",
                "question": "What is your name?",
                "field_type": "text",
                "order": 1,
            },
            {
                "key": "location",
                "question": "Where are you?",
                "field_type": "text",
                "order": 2,
            },
        ])
        start_product_conversation(self.state, self.organization, self.product)
        submit_product_question_answers(
            self.state, self.organization, self.product,
            {"customer_name": "Amina"},
        )

        result = submit_product_question_answers(
            self.state, self.organization, self.product,
            {},
            corrections={
                "location": "Arusha",
                "internal_cost": "100",
            },
        )

        answers = self.state.data["product_conversation"]["answers"]
        self.assertEqual(answers, {"customer_name": "Amina"})
        self.assertEqual(result["corrected"], [])


from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from organizations.models import Organization

from .models import (
    ConversationConfiguration,
    ConversationConfigurationVersion,
    ConversationQuestion,
    ConversationConfigurationAudit,
)
from .services import (
    create_configuration,
    create_draft_version,
    publish_draft,
)

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from products.models import Product

from .models import (
    ProductConversationConfiguration,
    ProductConversationVersion,
    ProductConversationQuestion,
    ProductConversationOption,
    ProductConversationConfigurationAudit,
)

from .services import (
    create_product_configuration,
    create_product_draft_version,
    publish_product_draft,
)


User = get_user_model()


class ConversationConfigurationServiceTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="conversation_test_owner",
            password="TestPassword123!",
        )

        self.organization = Organization.objects.create(
            name="Conversation Test Organization",
            slug="conversation-test-organization",
            status="active",
        )

        self.other_organization = Organization.objects.create(
            name="Other Test Organization",
            slug="other-test-organization",
            status="active",
        )

    def test_create_configuration_and_first_draft(self):
        configuration, draft = create_configuration(
            self.organization,
            self.user,
        )

        self.assertEqual(
            configuration.organization,
            self.organization,
        )
        self.assertEqual(draft.version_number, 1)
        self.assertEqual(draft.status, "draft")
        self.assertEqual(configuration.draft_version_id, draft.pk)

        self.assertTrue(
            ConversationConfigurationAudit.objects.filter(
                configuration=configuration,
                action="created",
            ).exists()
        )

    def test_publish_first_version(self):
        configuration, draft = create_configuration(
            self.organization,
            self.user,
        )

        draft.welcome_message = "Welcome to our business."
        draft.save()

        published = publish_draft(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        configuration.refresh_from_db()

        self.assertEqual(published.status, "published")
        self.assertEqual(published.version_number, 1)
        self.assertIsNotNone(published.published_at)
        self.assertEqual(
            published.snapshot["welcome_message"],
            "Welcome to our business.",
        )

        self.assertEqual(configuration.published_version_id, published.pk)
        self.assertIsNone(configuration.draft_version_id)

        self.assertTrue(
            ConversationConfigurationAudit.objects.filter(
                configuration=configuration,
                action="published",
                version=published,
            ).exists()
        )

    def test_create_draft_from_published_version(self):
        configuration, draft = create_configuration(
            self.organization,
            self.user,
        )

        draft.welcome_message = "Original welcome."
        draft.save()

        publish_draft(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        new_draft = create_draft_version(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        self.assertEqual(new_draft.version_number, 2)
        self.assertEqual(new_draft.status, "draft")
        self.assertEqual(new_draft.welcome_message, "Original welcome.")

        configuration.refresh_from_db()
        self.assertEqual(configuration.draft_version_id, new_draft.pk)

    def test_publish_replacement_archives_previous_version(self):
        configuration, first_draft = create_configuration(
            self.organization,
            self.user,
        )

        first_draft.welcome_message = "Version one."
        first_draft.save()

        first_published = publish_draft(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        second_draft = create_draft_version(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        second_draft.welcome_message = "Version two."
        second_draft.save()

        second_published = publish_draft(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        first_published.refresh_from_db()

        self.assertEqual(first_published.status, "archived")
        self.assertEqual(second_published.status, "published")

        # The old published snapshot must remain unchanged.
        self.assertEqual(
            first_published.snapshot["welcome_message"],
            "Version one.",
        )

        configuration.refresh_from_db()
        self.assertEqual(
            configuration.published_version_id,
            second_published.pk,
        )

    def test_invalid_choice_question_prevents_publishing(self):
        configuration, draft = create_configuration(
            self.organization,
            self.user,
        )

        question = ConversationQuestion(
            version=draft,
            key="property_type",
            scope="general",
            question="What type of property do you have?",
            field_type="choice",
            is_required=False,
            allow_skip=True,
        )
        question.full_clean()
        question.save()

        with self.assertRaises(ValidationError):
            publish_draft(
                configuration.pk,
                self.organization.pk,
                self.user,
            )

        configuration.refresh_from_db()

        self.assertEqual(configuration.draft_version_id, draft.pk)
        self.assertIsNone(configuration.published_version_id)

    def test_cannot_create_second_draft_while_one_exists(self):
        configuration, first_draft = create_configuration(
            self.organization,
            self.user,
        )

        with self.assertRaises(ValidationError):
            create_draft_version(
                configuration.pk,
                self.organization.pk,
                self.user,
            )

    def test_organization_cannot_access_another_organizations_configuration(self):
        configuration, draft = create_configuration(
            self.organization,
            self.user,
        )

        with self.assertRaises(
            ConversationConfiguration.DoesNotExist
        ):
            create_draft_version(
                configuration.pk,
                self.other_organization.pk,
                self.user,
            )

    def test_published_version_cannot_be_edited_normally(self):
        configuration, draft = create_configuration(
            self.organization,
            self.user,
        )

        published = publish_draft(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        published.welcome_message = "Attempted modification."

        with self.assertRaises(ValidationError):
            published.save()

        published.refresh_from_db()
        self.assertEqual(published.welcome_message, "")


class ProductConversationModelTests(TestCase):

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Product Conversation Business",
            slug="product-conversation-business",
            status="active",
        )

        self.other_organization = Organization.objects.create(
            name="Other Product Business",
            slug="other-product-business",
            status="active",
        )

        self.product = Product.objects.create(
            organization=self.organization,
            name="Test WhatsApp Product",
            show_on_whatsapp=True,
            is_active=True,
        )

        self.configuration = ProductConversationConfiguration.objects.create(
            organization=self.organization,
            product=self.product,
        )

    def create_version(self, number=1):
        return ProductConversationVersion.objects.create(
            configuration=self.configuration,
            version_number=number,
            status="draft",
        )

    def test_product_has_one_conversation_configuration(self):
        self.assertEqual(
            ProductConversationConfiguration.objects.filter(
                product=self.product
            ).count(),
            1,
        )

    def test_configuration_rejects_wrong_organization(self):
        configuration = ProductConversationConfiguration(
            organization=self.other_organization,
            product=self.product,
        )

        with self.assertRaises(ValidationError):
            configuration.full_clean()

    def test_configuration_rejects_product_without_organization(self):
        product = Product.objects.create(
            organization=None,
            name="Unassigned Product",
        )

        configuration = ProductConversationConfiguration(
            organization=self.organization,
            product=product,
        )

        with self.assertRaises(ValidationError):
            configuration.full_clean()

    def test_product_cannot_have_two_configurations(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProductConversationConfiguration.objects.create(
                    organization=self.organization,
                    product=self.product,
                )

    def test_configuration_can_have_one_draft(self):
        self.create_version(1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_version(2)

    def test_configuration_can_have_one_published_version(self):
        version = self.create_version()

        ProductConversationVersion.objects.filter(
            pk=version.pk
        ).update(status="published")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProductConversationVersion.objects.create(
                    configuration=self.configuration,
                    version_number=2,
                    status="published",
                )

    def test_published_version_cannot_be_edited(self):
        version = self.create_version()

        ProductConversationVersion.objects.filter(
            pk=version.pk
        ).update(status="published")

        version.refresh_from_db()
        version.welcome_message = "Changed message"

        with self.assertRaises(ValidationError):
            version.save()

    def test_published_version_cannot_be_deleted(self):
        version = self.create_version()

        ProductConversationVersion.objects.filter(
            pk=version.pk
        ).update(status="published")

        version.refresh_from_db()

        with self.assertRaises(ValidationError):
            version.delete()

    def test_published_question_cannot_be_edited(self):
        version = self.create_version()

        question = ProductConversationQuestion.objects.create(
            version=version,
            key="customer_name",
            question="What is your name?",
            field_type="text",
            order=1,
        )

        ProductConversationVersion.objects.filter(
            pk=version.pk
        ).update(status="published")

        version.refresh_from_db()
        question.question = "What is your full name?"

        with self.assertRaises(ValidationError):
            question.save()

    def test_published_question_cannot_be_deleted(self):
        version = self.create_version()

        question = ProductConversationQuestion.objects.create(
            version=version,
            key="customer_name",
            question="What is your name?",
            field_type="text",
            order=1,
        )

        ProductConversationVersion.objects.filter(
            pk=version.pk
        ).update(status="published")

        version.refresh_from_db()

        with self.assertRaises(ValidationError):
            question.delete()

    def test_published_option_cannot_be_edited(self):
        version = self.create_version()

        question = ProductConversationQuestion.objects.create(
            version=version,
            key="product_condition",
            question="Which condition do you prefer?",
            field_type="choice",
            order=1,
        )

        option = ProductConversationOption.objects.create(
            question=question,
            value="new",
            label="Brand New",
            order=1,
        )

        ProductConversationVersion.objects.filter(
            pk=version.pk
        ).update(status="published")

        version.refresh_from_db()
        option.label = "New Product"

        with self.assertRaises(ValidationError):
            option.save()

    def test_draft_question_remains_editable(self):
        version = self.create_version()

        question = ProductConversationQuestion.objects.create(
            version=version,
            key="customer_name",
            question="What is your name?",
            field_type="text",
            order=1,
        )

        question.question = "What is your full name?"
        question.save()

        question.refresh_from_db()

        self.assertEqual(
            question.question,
            "What is your full name?",
        )


class ProductConversationServiceTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="product_service_test",
            password="TestPassword123!",
        )

        self.organization = Organization.objects.create(
            name="Product Service Business",
            slug="product-service-business",
            status="active",
        )

        self.other_organization = Organization.objects.create(
            name="Other Product Service Business",
            slug="other-product-service-business",
            status="active",
        )

        self.product = Product.objects.create(
            organization=self.organization,
            name="Service Test Product",
            show_on_whatsapp=True,
            is_active=True,
        )

    def test_create_product_configuration_and_first_draft(self):
        configuration, draft = create_product_configuration(
            self.product.pk,
            self.organization.pk,
            self.user,
        )

        self.assertEqual(configuration.organization, self.organization)
        self.assertEqual(configuration.product, self.product)
        self.assertEqual(configuration.draft_version_id, draft.pk)
        self.assertEqual(draft.version_number, 1)
        self.assertEqual(draft.status, "draft")
        self.assertEqual(
            draft.product_snapshot["name"],
            self.product.name,
        )

        self.assertTrue(
            ProductConversationConfigurationAudit.objects.filter(
                configuration=configuration,
                action="created",
                version=draft,
            ).exists()
        )

    def test_reject_product_from_another_organization(self):
        with self.assertRaises(ValidationError):
            create_product_configuration(
                self.product.pk,
                self.other_organization.pk,
                self.user,
            )

    def test_reject_product_disabled_for_whatsapp(self):
        self.product.show_on_whatsapp = False
        self.product.save()

        with self.assertRaises(ValidationError):
            create_product_configuration(
                self.product.pk,
                self.organization.pk,
                self.user,
            )

    def test_reject_inactive_product(self):
        self.product.is_active = False
        self.product.save()

        with self.assertRaises(ValidationError):
            create_product_configuration(
                self.product.pk,
                self.organization.pk,
                self.user,
            )

    def test_create_draft_from_published_version(self):
        configuration, first_draft = create_product_configuration(
            self.product.pk,
            self.organization.pk,
            self.user,
        )

        first_draft.welcome_message = "Welcome to our product."
        first_draft.save()

        ProductConversationQuestion.objects.create(
            version=first_draft,
            key="customer_name",
            question="What is your name?",
            field_type="text",
            order=1,
        )

        publish_product_draft(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        new_draft = create_product_draft_version(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        self.assertEqual(new_draft.version_number, 2)
        self.assertEqual(new_draft.status, "draft")
        self.assertEqual(
            new_draft.welcome_message,
            "Welcome to our product.",
        )

        self.assertTrue(
            new_draft.questions.filter(
                key="customer_name",
            ).exists()
        )

        configuration.refresh_from_db()
        self.assertEqual(configuration.draft_version_id, new_draft.pk)

    def test_published_product_draft_creates_snapshot(self):
        configuration, draft = create_product_configuration(
            self.product.pk,
            self.organization.pk,
            self.user,
        )

        draft.welcome_message = "Welcome to our business."
        draft.save()

        ProductConversationQuestion.objects.create(
            version=draft,
            key="customer_name",
            question="What is your name?",
            field_type="text",
            order=1,
        )

        published = publish_product_draft(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        configuration.refresh_from_db()

        self.assertEqual(published.status, "published")
        self.assertEqual(
            published.snapshot["welcome_message"],
            "Welcome to our business.",
        )
        self.assertEqual(
            published.snapshot["product"]["name"],
            self.product.name,
        )

        self.assertEqual(
            configuration.published_version_id,
            published.pk,
        )
        self.assertIsNone(configuration.draft_version_id)

        self.assertTrue(
            ProductConversationConfigurationAudit.objects.filter(
                configuration=configuration,
                action="published",
                version=published,
            ).exists()
        )

    def test_publishing_replacement_archives_previous_version(self):
        configuration, first_draft = create_product_configuration(
            self.product.pk,
            self.organization.pk,
            self.user,
        )

        first_draft.welcome_message = "Version one."
        first_draft.save()

        first_published = publish_product_draft(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        second_draft = create_product_draft_version(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        second_draft.welcome_message = "Version two."
        second_draft.save()

        second_published = publish_product_draft(
            configuration.pk,
            self.organization.pk,
            self.user,
        )

        first_published.refresh_from_db()

        self.assertEqual(first_published.status, "archived")
        self.assertEqual(second_published.status, "published")

        self.assertEqual(
            first_published.snapshot["welcome_message"],
            "Version one.",
        )

        self.assertTrue(
            ProductConversationConfigurationAudit.objects.filter(
                configuration=configuration,
                action="archived",
                version=first_published,
            ).exists()
        )

    def test_invalid_choice_question_prevents_publication(self):
        configuration, draft = create_product_configuration(
            self.product.pk,
            self.organization.pk,
            self.user,
        )

        ProductConversationQuestion.objects.create(
            version=draft,
            key="product_condition",
            question="Which condition do you prefer?",
            field_type="choice",
            order=1,
        )

        with self.assertRaises(ValidationError):
            publish_product_draft(
                configuration.pk,
                self.organization.pk,
                self.user,
            )

        draft.refresh_from_db()
        self.assertEqual(draft.status, "draft")

    def test_existing_draft_cannot_be_replaced_silently(self):
        configuration, first_draft = create_product_configuration(
            self.product.pk,
            self.organization.pk,
            self.user,
        )

        with self.assertRaises(ValidationError):
            create_product_draft_version(
                configuration.pk,
                self.organization.pk,
                self.user,
            )

        configuration.refresh_from_db()
        self.assertEqual(
            configuration.draft_version_id,
            first_draft.pk,
        )

    def test_other_organization_cannot_create_product_draft(self):
        configuration, draft = create_product_configuration(
            self.product.pk,
            self.organization.pk,
            self.user,
        )

        with self.assertRaises(
            ProductConversationConfiguration.DoesNotExist
        ):
            create_product_draft_version(
                configuration.pk,
                self.other_organization.pk,
                self.user,
            )


from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from unittest.mock import Mock, patch

from organizations.models import Organization, OrganizationMember
from products.forms import ProductForm
from products.models import (
    OrganizationCategoryAssignment,
    Product,
    ProductCategory,
)
from customers.models import Customer
from whatsapp.models import (
    Conversation,
    Message,
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
)
from whatsapp.views import search_whatsapp_products


class ProductFormCategoryAssignmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(
            name="Business A",
            organization_type="business",
            status="active",
        )
        cls.other_organization = Organization.objects.create(
            name="Business B",
            organization_type="business",
            status="active",
        )

        cls.assigned_category = ProductCategory.objects.create(
            organization=None,
            name="Assigned Category",
            is_active=True,
        )
        cls.unassigned_category = ProductCategory.objects.create(
            organization=None,
            name="Unassigned Category",
            is_active=True,
        )
        cls.inactive_category = ProductCategory.objects.create(
            organization=None,
            name="Inactive Category",
            is_active=False,
        )
        cls.other_owned_category = ProductCategory.objects.create(
            organization=cls.other_organization,
            name="Other Organization Category",
            is_active=True,
        )

        OrganizationCategoryAssignment.objects.create(
            organization=cls.organization,
            category=cls.assigned_category,
        )

    def test_form_only_shows_assigned_active_master_categories(self):
        form = ProductForm(organization=self.organization)

        category_ids = set(
            form.fields["category"].queryset.values_list(
                "id",
                flat=True,
            )
        )

        self.assertEqual(
            category_ids,
            {self.assigned_category.id},
        )

    def test_unassigned_category_is_rejected(self):
        form = ProductForm(
            data={
                "product_type": "product",
                "category": self.unassigned_category.id,
                "name": "Test Product",
                "price": "1000.00",
                "currency": "TZS",
                "unit": "piece",
                "quantity": "1",
                "minimum_stock": "0",
                "track_inventory": "True",
                "allow_backorder": "False",
                "availability": "in_stock",
                "show_on_website": "True",
                "show_on_whatsapp": "True",
                "allow_quote_request": "True",
                "is_active": "True",
            },
            organization=self.organization,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("category", form.errors)

    def test_other_organizations_category_is_not_available(self):
        form = ProductForm(organization=self.organization)

        self.assertFalse(
            form.fields["category"].queryset.filter(
                pk=self.other_owned_category.pk
            ).exists()
        )

    def test_inactive_category_is_not_available(self):
        form = ProductForm(organization=self.organization)

        self.assertFalse(
            form.fields["category"].queryset.filter(
                pk=self.inactive_category.pk
            ).exists()
        )

    def test_saved_product_belongs_to_selected_organization(self):
        form = ProductForm(
            data={
                "product_type": "product",
                "category": self.assigned_category.id,
                "name": "Assigned Product",
                "price": "1000.00",
                "currency": "TZS",
                "unit": "piece",
                "quantity": "1",
                "minimum_stock": "0",
                "track_inventory": "True",
                "allow_backorder": "False",
                "availability": "in_stock",
                "show_on_website": "True",
                "show_on_whatsapp": "True",
                "allow_quote_request": "True",
                "is_active": "True",
            },
            organization=self.organization,
        )

        self.assertTrue(form.is_valid(), form.errors)

        product = form.save()

        self.assertEqual(product.organization, self.organization)
        self.assertEqual(product.category, self.assigned_category)


class ProductPublicVisibilityTests(TestCase):
    def test_business_product_form_does_not_expose_public_visibility(self):
        organization = Organization.objects.create(
            name="Tenant Business",
            organization_type="business",
            status="active",
        )
        form = ProductForm(organization=organization)
        self.assertNotIn("is_publicly_visible", form.fields)

    def test_platform_owner_product_form_exposes_public_visibility(self):
        organization = Organization.objects.create(
            name="Faltasi Innovations Limited",
            organization_type="platform_owner",
            status="active",
        )
        form = ProductForm(organization=organization)
        self.assertIn("is_publicly_visible", form.fields)

class WhatsAppProductCatalogueIsolationTests(TestCase):

    def setUp(self):
        self.faltasi = Organization.objects.create(
            name="Faltasi Innovations Limited",
            organization_type="platform_owner",
            status="active",
        )

        self.business = Organization.objects.create(
            name="Independent Business",
            organization_type="business",
            status="active",
        )

        self.faltasi_product = Product.objects.create(
            organization=self.faltasi,
            name="Test Router",
            price="50000.00",
            show_on_whatsapp=True,
            is_active=True,
        )

        self.business_product = Product.objects.create(
            organization=self.business,
            name="Test Router",
            price="45000.00",
            show_on_whatsapp=True,
            is_active=True,
        )

    class TestConversationState:
        def __init__(self):
            self.data = {}
            self.current_step = None
            self.waiting_for = None
            self.saved = False

        def save(self):
            self.saved = True

    def test_faltasi_receives_its_own_catalogue_url(self):
        state = self.TestConversationState()

        reply = search_whatsapp_products(
            "router",
            self.faltasi,
            state,
        )

        self.assertIn(
            "https://www.faltasi.com/products/",
            reply,
        )

        self.assertIn("Test Router", reply)
        self.assertEqual(
            state.current_step,
            "whatsapp_product_selection",
        )
        self.assertEqual(
            state.waiting_for,
            "product_selection",
        )
        self.assertEqual(
            state.data["whatsapp_product_ids"],
            [self.faltasi_product.id],
        )
        self.assertTrue(state.saved)

    def test_business_receives_its_own_configured_catalogue(self):
        self.business.settings = {
            "public_catalogue_enabled": True,
            "public_catalogue_url": "https://business.example.com/products/",
        }
        self.business.save(update_fields=["settings"])

        reply = search_whatsapp_products(
            "router",
            self.business,
        )

        self.assertIn(
            "https://business.example.com/products/",
            reply,
        )

        self.assertNotIn(
            "https://www.faltasi.com/products/",
            reply,
        )

    def test_business_with_disabled_catalogue_receives_no_catalogue_link(self):
        self.business.settings = {
            "public_catalogue_enabled": False,
            "public_catalogue_url": "https://business.example.com/products/",
        }
        self.business.save(update_fields=["settings"])

        reply = search_whatsapp_products(
            "router",
            self.business,
        )

        self.assertNotIn("View our catalogue:", reply)
        self.assertNotIn(
            "https://www.faltasi.com/products/",
            reply,
        )

    def test_business_without_catalogue_url_receives_no_catalogue_link(self):
        self.business.settings = {
            "public_catalogue_enabled": True,
        }
        self.business.save(update_fields=["settings"])

        reply = search_whatsapp_products(
            "router",
            self.business,
        )

        self.assertNotIn("View our catalogue:", reply)
        self.assertNotIn(
            "https://www.faltasi.com/products/",
            reply,
        )

    def test_business_with_non_https_catalogue_url_receives_no_link(self):
        self.business.settings = {
            "public_catalogue_enabled": True,
            "public_catalogue_url": "http://business.example.com/products/",
        }
        self.business.save(update_fields=["settings"])

        reply = search_whatsapp_products(
            "router",
            self.business,
        )

        self.assertNotIn("View our catalogue:", reply)

    def test_business_product_search_does_not_expose_other_organization_products(self):
        reply = search_whatsapp_products(
            "router",
            self.business,
        )

        self.assertIn("Test Router", reply)

        state = self.TestConversationState()

        search_whatsapp_products(
            "router",
            self.business,
            state,
        )

        self.assertEqual(
            state.data["whatsapp_product_ids"],
            [self.business_product.id],
        )

        self.assertNotIn(
            self.faltasi_product.id,
            state.data["whatsapp_product_ids"],
        )

class ProductWhatsAppSharingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(
            name="Sharing Business A",
            organization_type="business",
            status="active",
            slug="sharing-business-a",
        )
        cls.org_b = Organization.objects.create(
            name="Sharing Business B",
            organization_type="business",
            status="active",
            slug="sharing-business-b",
        )

        User = get_user_model()
        cls.owner = User.objects.create_user(
            username="product_share_test_owner",
            password="test-password-123",
        )

        OrganizationMember.objects.create(
            organization=cls.org_a,
            user=cls.owner,
            role="owner",
            is_active=True,
        )

        cls.product = Product.objects.create(
            organization=cls.org_a,
            name="Test Sharing Product",
            price="10000.00",
            show_on_whatsapp=True,
            is_active=True,
        )

        cls.unsubscribed_customer = Customer.objects.create(
            organization=cls.org_a,
            name="Unsubscribed Customer",
            phone="255712345678",
            whatsapp_marketing_opt_in=False,
        )

        cls.subscribed_customer = Customer.objects.create(
            organization=cls.org_a,
            name="Subscribed Customer",
            phone="255713345678",
            whatsapp_marketing_opt_in=True,
        )

        cls.other_customer = Customer.objects.create(
            organization=cls.org_b,
            name="Other Organization Customer",
            phone="255714345678",
            whatsapp_marketing_opt_in=True,
        )

        waba = WhatsAppBusinessAccount.objects.create(
            organization=cls.org_a,
            business_name="Sharing Business A WhatsApp",
            status="connected",
            is_active=True,
        )

        cls.sender = WhatsAppPhoneNumber.objects.create(
            organization=cls.org_a,
            whatsapp_business_account=waba,
            phone_number_id="test-product-share-phone-id",
            phone_number="+255700000001",
            status="connected",
            is_active=True,
            is_default=True,
        )

    def setUp(self):
        self.client.force_login(self.owner)

        session = self.client.session
        session["active_organization_id"] = self.org_a.id
        session.save()

        self.url = reverse(
            "products:product_share_whatsapp",
            kwargs={"product_id": self.product.id},
        )

        # Create an active conversation with the subscribed customer.
        self.conversation = Conversation.objects.create(
            organization=self.org_a,
            whatsapp_phone_number=self.sender,
            customer=self.subscribed_customer,
            phone_number=self.subscribed_customer.phone,
            whatsapp_user_id=self.subscribed_customer.phone,
            status="active",
        )

        # Simulate a recent incoming customer message.
        Message.objects.create(
            organization=self.org_a,
            conversation=self.conversation,
            direction="incoming",
            sender_type="customer",
            message_type="text",
            content="Hello",
            delivery_status="delivered",
        )

    def test_unsubscribed_customer_gets_subscription_link(self):
        response = self.client.post(
            self.url,
            {"customer_id": str(self.unsubscribed_customer.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["subscription_link"],
            "https://wa.me/255700000001?text=YES",
        )
        self.assertContains(response, "https://wa.me/255700000001")

        self.unsubscribed_customer.refresh_from_db()
        self.assertFalse(
            self.unsubscribed_customer.whatsapp_marketing_opt_in
        )

    @override_settings(
        WHATSAPP_PRODUCT_SHARE_TEMPLATE_ENABLED=True
    )
    @patch(
        "whatsapp.views.get_public_product_image_url",
        return_value="https://example.com/product.jpg",
    )
    @patch("whatsapp.views.send_whatsapp_image")
    @patch("whatsapp.views.send_whatsapp_message")
    def test_subscribed_customer_receives_three_product_messages(
        self,
        mock_text,
        mock_image,
        mock_image_url,
    ):
        mock_text.side_effect = [
            Mock(
                status_code=200,
                json=lambda: {
                    "messages": [{"id": "wamid.greeting"}]
                },
            ),
            Mock(
                status_code=200,
                json=lambda: {
                    "messages": [{"id": "wamid.details"}]
                },
            ),
        ]

        mock_image.return_value = Mock(
            status_code=200,
            json=lambda: {
                "messages": [{"id": "wamid.image"}]
            },
        )

        self.product.short_description = "A sample product"
        self.product.save(update_fields=["short_description"])

        response = self.client.post(
            self.url,
            {"customer_id": str(self.subscribed_customer.id)},
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(mock_text.call_count, 2)
        self.assertEqual(mock_image.call_count, 1)

        self.assertEqual(
            mock_text.call_args_list[0].args[2],
            "Habari yako Subscribed, mzigo mpya!",
        )

        self.assertEqual(
            mock_text.call_args_list[1].args[2],
            "Bidhaa: Test Sharing Product\n"
            "Bei: TZS 10,000.00\n"
            "Maelezo: A sample product",
        )

        mock_image.assert_called_once_with(
            self.sender,
            "255713345678",
            "https://example.com/product.jpg",
            caption="",
        )

        outgoing = list(
            Message.objects.filter(
                organization=self.org_a,
                conversation=self.conversation,
                direction="outgoing",
            ).order_by("created_at", "id")
        )

        self.assertEqual(len(outgoing), 3)

        self.assertEqual(
            [
                message.metadata["product_share_stage"]
                for message in outgoing
            ],
            ["greeting", "product_image", "product_details"],
        )

        self.assertEqual(
            [message.delivery_status for message in outgoing],
            ["sent", "sent", "sent"],
        )

        for message in outgoing:
            self.assertNotIn("Availability", message.content)

        mock_image_url.assert_called_once()

    def test_cross_organization_customer_is_rejected(self):
        response = self.client.post(
            self.url,
            {"customer_id": str(self.other_customer.id)},
        )

        self.assertEqual(response.status_code, 404)

        self.assertFalse(
            Message.objects.filter(
                organization=self.org_a,
                conversation__customer=self.other_customer,
            ).exists()
        )

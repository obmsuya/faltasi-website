
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
    Message,
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
)


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

    @patch("whatsapp.views.send_whatsapp_template")
    def test_unsubscribed_customer_gets_subscription_link(self, mock_send):
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
        mock_send.assert_not_called()

        self.unsubscribed_customer.refresh_from_db()
        self.assertFalse(
            self.unsubscribed_customer.whatsapp_marketing_opt_in
        )

    @override_settings(
        WHATSAPP_PRODUCT_SHARE_TEMPLATE_ENABLED=True
    )
    @patch("whatsapp.views.send_whatsapp_template")
    def test_subscribed_customer_uses_approved_template(self, mock_send):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messages": [{"id": "wamid.test.product.share"}]
        }
        mock_send.return_value = mock_response

        response = self.client.post(
            self.url,
            {"customer_id": str(self.subscribed_customer.id)},
        )

        self.assertEqual(response.status_code, 302)
        mock_send.assert_called_once()

        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["whatsapp_phone"], self.sender)
        self.assertEqual(kwargs["phone_number"], "255713345678")
        self.assertEqual(
            kwargs["template_name"],
            "product_share_notification",
        )

        self.assertTrue(
            Message.objects.filter(
                organization=self.org_a,
                conversation__customer=self.subscribed_customer,
                direction="outgoing",
                message_type="template",
            ).exists()
        )

    @patch("whatsapp.views.send_whatsapp_template")
    def test_cross_organization_customer_is_rejected(self, mock_send):
        response = self.client.post(
            self.url,
            {"customer_id": str(self.other_customer.id)},
        )

        self.assertEqual(response.status_code, 404)
        mock_send.assert_not_called()

        self.assertFalse(
            Message.objects.filter(
                organization=self.org_a,
                conversation__customer=self.other_customer,
            ).exists()
        )

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from organizations.models import Organization, OrganizationMember
from products.models import Product
from .models import ProductChannelPublication


class ChannelManagementTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(
            name="Business A", organization_type="business", status="active"
        )
        self.org_b = Organization.objects.create(
            name="Business B", organization_type="business", status="active"
        )
        self.manager = User.objects.create_user(username="manager", password="test-pass-123")
        OrganizationMember.objects.create(
            organization=self.org_a, user=self.manager, role="manager", is_active=True
        )
        self.product_a = Product.objects.create(
            organization=self.org_a, name="Product A", show_on_website=True,
            show_on_whatsapp=True,
        )
        self.product_b = Product.objects.create(organization=self.org_b, name="Product B")
        self.client.login(username="manager", password="test-pass-123")

    def test_dashboard_lists_only_active_organizations_products(self):
        response = self.client.get(reverse("channels:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Product A")
        self.assertNotContains(response, "Product B")

    def test_website_toggle_does_not_grant_public_visibility(self):
        response = self.client.post(
            reverse("channels:toggle_product_channel", args=[self.product_a.pk, "website"]),
            {"enabled": "0"},
        )
        self.assertRedirects(response, reverse("channels:dashboard"))
        self.product_a.refresh_from_db()
        self.assertFalse(self.product_a.show_on_website)
        self.assertFalse(self.product_a.is_publicly_visible)

    def test_social_channel_toggle_is_scoped_to_current_organization(self):
        response = self.client.post(
            reverse("channels:toggle_product_channel", args=[self.product_a.pk, "instagram"]),
            {"enabled": "1"},
        )
        self.assertEqual(response.status_code, 302)
        publication = ProductChannelPublication.objects.get(
            product=self.product_a, channel="instagram"
        )
        self.assertTrue(publication.is_enabled)
        self.assertEqual(publication.status, "draft")

    def test_cannot_change_another_organizations_product(self):
        response = self.client.post(
            reverse("channels:toggle_product_channel", args=[self.product_b.pk, "instagram"]),
            {"enabled": "1"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ProductChannelPublication.objects.filter(product=self.product_b).exists())

    def test_staff_cannot_change_channel_settings(self):
        staff = User.objects.create_user(username="staff", password="test-pass-123")
        OrganizationMember.objects.create(
            organization=self.org_a, user=staff, role="staff", is_active=True
        )
        self.client.logout()
        self.client.login(username="staff", password="test-pass-123")
        response = self.client.post(
            reverse("channels:toggle_product_channel", args=[self.product_a.pk, "instagram"]),
            {"enabled": "1"},
        )
        self.assertEqual(response.status_code, 403)

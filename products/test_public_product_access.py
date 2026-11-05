from django.core import signing
from django.test import TestCase
from django.urls import reverse

from organizations.models import Organization
from products.models import Product


class PublicProductAccessTests(TestCase):
    def setUp(self):
        self.faltasi = Organization.objects.create(
            name="Faltasi Innovations Limited",
            organization_type="platform_owner",
            status="active",
            slug="faltasi",
        )
        self.merrylight = Organization.objects.create(
            name="Merrylight",
            organization_type="business",
            status="active",
            slug="merrylight",
        )

    def _share_token(self, organization, product):
        return signing.dumps(
            {
                "organization_id": organization.id,
                "product_id": product.id,
            },
            salt="products.whatsapp_product_share",
            compress=True,
        )

    def test_public_faltasi_product_can_open_without_share_token(self):
        product = Product.objects.create(
            organization=self.faltasi,
            name="Public Faltasi Product",
            is_active=True,
            show_on_website=True,
            show_on_whatsapp=True,
            is_publicly_visible=True,
        )
        response = self.client.get(
            reverse(
                "products:public_product_detail",
                kwargs={
                    "organization_slug": self.faltasi.slug,
                    "product_id": product.id,
                },
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_merrylight_product_is_not_public_without_signed_share(self):
        product = Product.objects.create(
            organization=self.merrylight,
            name="Merrylight Product",
            is_active=True,
            show_on_website=True,
            show_on_whatsapp=True,
            is_publicly_visible=True,
        )
        response = self.client.get(
            reverse(
                "products:public_product_detail",
                kwargs={
                    "organization_slug": self.merrylight.slug,
                    "product_id": product.id,
                },
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_merrylight_product_opens_with_valid_whatsapp_share_token(self):
        product = Product.objects.create(
            organization=self.merrylight,
            name="Merrylight Shared Product",
            is_active=True,
            show_on_website=True,
            show_on_whatsapp=True,
            is_publicly_visible=False,
        )
        response = self.client.get(
            reverse(
                "products:public_product_detail",
                kwargs={
                    "organization_slug": self.merrylight.slug,
                    "product_id": product.id,
                },
            ),
            {"share": self._share_token(self.merrylight, product)},
        )
        self.assertEqual(response.status_code, 200)

    def test_share_token_cannot_be_reused_for_another_product(self):
        product = Product.objects.create(
            organization=self.merrylight,
            name="Merrylight Product One",
            is_active=True,
            show_on_whatsapp=True,
        )
        other_product = Product.objects.create(
            organization=self.merrylight,
            name="Merrylight Product Two",
            is_active=True,
            show_on_whatsapp=True,
        )
        response = self.client.get(
            reverse(
                "products:public_product_detail",
                kwargs={
                    "organization_slug": self.merrylight.slug,
                    "product_id": other_product.id,
                },
            ),
            {"share": self._share_token(self.merrylight, product)},
        )
        self.assertEqual(response.status_code, 404)

    def test_invalid_share_token_does_not_grant_access(self):
        product = Product.objects.create(
            organization=self.merrylight,
            name="Private Merrylight Product",
            is_active=True,
            show_on_whatsapp=True,
        )
        response = self.client.get(
            reverse(
                "products:public_product_detail",
                kwargs={
                    "organization_slug": self.merrylight.slug,
                    "product_id": product.id,
                },
            ),
            {"share": "invalid-token"},
        )
        self.assertEqual(response.status_code, 404)

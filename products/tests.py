
from django.test import TestCase

from organizations.models import Organization
from products.forms import ProductForm
from products.models import (
    OrganizationCategoryAssignment,
    Product,
    ProductCategory,
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

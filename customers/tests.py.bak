
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from organizations.models import Organization, OrganizationMember
from .models import Customer


class CustomerOrganizationIsolationTests(TestCase):
    def setUp(self):
        # Create two separate active organizations.
        self.org_a = Organization.objects.create(
            name="Test Organization A",
            organization_type="business",
            status="active",
        )
        self.org_b = Organization.objects.create(
            name="Test Organization B",
            organization_type="business",
            status="active",
        )

        # Create a different user for each organization.
        self.user_a = User.objects.create_user(
            username="tenant_user_a",
            password="Test-Only-Password-123!",
        )
        self.user_b = User.objects.create_user(
            username="tenant_user_b",
            password="Test-Only-Password-456!",
        )

        OrganizationMember.objects.create(
            organization=self.org_a,
            user=self.user_a,
            role="owner",
            is_active=True,
        )
        OrganizationMember.objects.create(
            organization=self.org_b,
            user=self.user_b,
            role="owner",
            is_active=True,
        )

        # Each organization owns a different customer.
        self.customer_a = Customer.objects.create(
            organization=self.org_a,
            name="Customer A",
            phone="0764000001",
        )
        self.customer_b = Customer.objects.create(
            organization=self.org_b,
            name="Customer B",
            phone="0764000002",
        )

    def test_customer_list_shows_only_own_organization(self):
        self.client.force_login(self.user_a)

        response = self.client.get(reverse("customers:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Customer A")
        self.assertNotContains(response, "Customer B")

    def test_cannot_view_another_organizations_customer(self):
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse(
                "customers:detail",
                kwargs={"customer_id": self.customer_b.id},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_edit_another_organizations_customer(self):
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse(
                "customers:edit",
                kwargs={"customer_id": self.customer_b.id},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_delete_another_organizations_customer(self):
        self.client.force_login(self.user_a)

        response = self.client.post(
            reverse(
                "customers:delete",
                kwargs={"customer_id": self.customer_b.id},
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            Customer.objects.filter(pk=self.customer_b.pk).exists()
        )

    def test_customers_without_organization_are_not_in_tenant_list(self):
        Customer.objects.create(
            organization=None,
            name="Unassigned Customer",
            phone="0764000003",
        )

        self.client.force_login(self.user_a)

        response = self.client.get(reverse("customers:list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Unassigned Customer")

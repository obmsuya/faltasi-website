
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from organizations.models import Organization, OrganizationMember
from business_requests.models import Department


class OrganizationSwitchingTests(TestCase):

    def setUp(self):
        self.switch_url = reverse(
            "business_requests:switch_organization"
        )

        # Create organizations
        self.faltasi = Organization.objects.create(
            name="Faltasi Innovations Limited",
            organization_type="platform_owner",
            status="active",
            slug="faltasi",
        )

        self.company_a = Organization.objects.create(
            name="Company A",
            organization_type="business",
            status="active",
            slug="company-a",
        )

        self.company_b = Organization.objects.create(
            name="Company B",
            organization_type="business",
            status="active",
            slug="company-b",
        )

        self.company_c = Organization.objects.create(
            name="Company C",
            organization_type="business",
            status="active",
            slug="company-c",
        )

        # Ordinary user belonging to two organizations
        self.member = User.objects.create_user(
            username="multi_member",
            password="test-password",
        )

        OrganizationMember.objects.create(
            organization=self.company_a,
            user=self.member,
            role="staff",
            is_active=True,
        )

        OrganizationMember.objects.create(
            organization=self.company_b,
            user=self.member,
            role="manager",
            is_active=True,
        )

        # Organization C belongs to another user
        self.other_user = User.objects.create_user(
            username="other_user",
            password="test-password",
        )

        OrganizationMember.objects.create(
            organization=self.company_c,
            user=self.other_user,
            role="staff",
            is_active=True,
        )

        # Platform administrator
        self.admin = User.objects.create_user(
            username="platform_admin",
            password="test-password",
        )

        OrganizationMember.objects.create(
            organization=self.faltasi,
            user=self.admin,
            role="admin",
            is_active=True,
        )

    def test_member_can_switch_between_organizations(self):
        self.client.force_login(self.member)

        response = self.client.post(
            self.switch_url,
            {"organization_id": self.company_b.id},
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            self.client.session["active_organization_id"],
            self.company_b.id,
        )

    def test_member_cannot_switch_to_unauthorized_organization(self):
        self.client.force_login(self.member)

        response = self.client.post(
            self.switch_url,
            {"organization_id": self.company_c.id},
        )

        self.assertEqual(response.status_code, 404)

        self.assertNotIn(
            "active_organization_id",
            self.client.session,
        )

    def test_member_cannot_switch_to_inactive_membership(self):
        OrganizationMember.objects.filter(
            user=self.member,
            organization=self.company_b,
        ).update(is_active=False)

        self.client.force_login(self.member)

        response = self.client.post(
            self.switch_url,
            {"organization_id": self.company_b.id},
        )

        self.assertEqual(response.status_code, 404)

    def test_platform_admin_can_switch_organizations(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.switch_url,
            {"organization_id": self.company_a.id},
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            self.client.session["active_organization_id"],
            self.company_a.id,
        )

    def test_member_can_view_only_their_organizations(self):
        self.client.force_login(self.member)

        response = self.client.get(self.switch_url)

        self.assertEqual(response.status_code, 200)

        organizations = list(
            response.context["organizations"]
        )

        organization_ids = [
            organization.id for organization in organizations
        ]

        self.assertIn(self.company_a.id, organization_ids)
        self.assertIn(self.company_b.id, organization_ids)
        self.assertNotIn(self.company_c.id, organization_ids)
        self.assertNotIn(self.faltasi.id, organization_ids)

class BusinessSecurityProtectionTests(TestCase):

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Security Test Company",
            organization_type="business",
            status="active",
            slug="security-test-company",
        )

        self.owner = User.objects.create_user(
            username="security_owner",
            password="test-password",
        )

        OrganizationMember.objects.create(
            organization=self.organization,
            user=self.owner,
            role="owner",
            is_active=True,
        )

        self.employee = User.objects.create_user(
            username="security_employee",
            password="test-password",
        )

        OrganizationMember.objects.create(
            organization=self.organization,
            user=self.employee,
            role="staff",
            is_active=True,
        )

        self.target_user = User.objects.create_user(
            username="target_employee",
            password="test-password",
        )

        self.target_membership = OrganizationMember.objects.create(
            organization=self.organization,
            user=self.target_user,
            role="staff",
            is_active=True,
        )

        self.department = Department.objects.create(
            organization=self.organization,
            name="Security Test Department",
            is_active=True,
        )

        self.profile_url = reverse(
            "business_requests:business_profile"
        )

        self.user_status_url = reverse(
            "business_requests:toggle_user_status",
            args=[self.target_user.id],
        )

        self.department_toggle_url = reverse(
            "business_requests:department_toggle",
            args=[self.department.id],
        )

    def test_employee_cannot_update_business_profile(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            self.profile_url,
            {
                "name": "Unauthorized Company Name",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.organization.refresh_from_db()

        self.assertEqual(
            self.organization.name,
            "Security Test Company",
        )

    def test_get_request_cannot_toggle_user_status(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.user_status_url)

        self.assertEqual(response.status_code, 405)

        self.target_membership.refresh_from_db()

        self.assertTrue(self.target_membership.is_active)

    def test_get_request_cannot_toggle_department_status(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.department_toggle_url)

        self.assertEqual(response.status_code, 405)

        self.department.refresh_from_db()

        self.assertTrue(self.department.is_active)

    def test_owner_can_toggle_user_status_with_post(self):
        self.client.force_login(self.owner)

        response = self.client.post(self.user_status_url)

        self.assertEqual(response.status_code, 302)

        self.target_membership.refresh_from_db()

        self.assertFalse(self.target_membership.is_active)

    def test_owner_can_toggle_department_status_with_post(self):
        self.client.force_login(self.owner)

        response = self.client.post(self.department_toggle_url)

        self.assertEqual(response.status_code, 302)

        self.department.refresh_from_db()

        self.assertFalse(self.department.is_active)
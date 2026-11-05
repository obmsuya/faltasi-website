from django.test import TestCase
from .forms import OrganizationForm
from django.contrib.auth.models import User
from django.test import RequestFactory

from .models import Organization, OrganizationMember
from .utils import get_user_organization, is_platform_administrator


class OrganizationOwnerFormTests(TestCase):
    def base_data(self):
        return {
            "name": "Example Business",
            "organization_type": "business",
            "status": "pending",
            "owner_full_name": "Asha Mushi",
            "owner_phone": "0764 819 996",
            "owner_email": "asha@example.com",
        }

    def test_owner_phone_is_normalized_to_tanzanian_international_format(self):
        form = OrganizationForm(data=self.base_data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["owner_phone"], "+255764819996")

    def test_owner_phone_is_required(self):
        data = self.base_data()
        data["owner_phone"] = ""
        form = OrganizationForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("owner_phone", form.errors)

    def test_platform_owner_type_is_not_available_for_new_organizations(self):
        data = self.base_data()
        data["organization_type"] = "platform_owner"
        form = OrganizationForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("organization_type", form.errors)

class OrganizationResolverTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

        self.faltasi = Organization.objects.create(
            name="Faltasi Innovations Limited",
            organization_type="platform_owner",
            status="active",
            slug="faltasi",
        )

        self.merrylight = Organization.objects.create(
            name="Merrylight Tophair",
            organization_type="business",
            status="active",
            slug="merrylight",
        )

        self.admin = User.objects.create_user(
            username="platformadmin",
            password="test-password",
        )

        OrganizationMember.objects.create(
            organization=self.faltasi,
            user=self.admin,
            role="admin",
            is_active=True,
        )

        self.staff = User.objects.create_user(
            username="merrylightstaff",
            password="test-password",
        )

        OrganizationMember.objects.create(
            organization=self.merrylight,
            user=self.staff,
            role="staff",
            is_active=True,
        )

    def test_platform_admin_can_select_merrylight(self):
        request = self.factory.get("/")
        request.session = {
            "active_organization_id": self.merrylight.id
        }

        organization = get_user_organization(
            self.admin,
            request=request,
        )

        self.assertEqual(organization, self.merrylight)

    def test_platform_admin_defaults_to_faltasi(self):
        request = self.factory.get("/")
        request.session = {}

        organization = get_user_organization(
            self.admin,
            request=request,
        )

        self.assertEqual(organization, self.faltasi)

    def test_inactive_selected_organization_is_rejected(self):
        self.merrylight.status = "inactive"
        self.merrylight.save()

        request = self.factory.get("/")
        request.session = {
            "active_organization_id": self.merrylight.id
        }

        organization = get_user_organization(
            self.admin,
            request=request,
        )

        self.assertEqual(organization, self.faltasi)
        self.assertNotIn(
            "active_organization_id",
            request.session,
        )

    def test_normal_user_gets_active_membership_organization(self):
        organization = get_user_organization(self.staff)

        self.assertEqual(organization, self.merrylight)

    def test_normal_user_without_active_membership_gets_none(self):
        self.staff.organization_memberships.update(
            is_active=False
        )

        organization = get_user_organization(self.staff)

        self.assertIsNone(organization)

    def test_platform_admin_authorization(self):
        self.assertTrue(
            is_platform_administrator(self.admin)
        )

    def test_ordinary_user_is_not_platform_admin(self):
        self.assertFalse(
            is_platform_administrator(self.staff)
        )



    def test_normal_user_can_select_second_authorized_organization(self):
        second_org = Organization.objects.create(
            name="Second Business",
            organization_type="business",
            status="active",
            slug="second-business",
        )

        OrganizationMember.objects.create(
            organization=second_org,
            user=self.staff,
            role="staff",
            is_active=True,
        )

        request = self.factory.get("/")
        request.session = {
            "active_organization_id": second_org.id
        }

        organization = get_user_organization(
            self.staff,
            request=request,
        )

        self.assertEqual(organization, second_org)

    def test_normal_user_cannot_select_unauthorized_organization(self):
        unauthorized_org = Organization.objects.create(
            name="Unauthorized Business",
            organization_type="business",
            status="active",
            slug="unauthorized-business",
        )

        request = self.factory.get("/")
        request.session = {
            "active_organization_id": unauthorized_org.id
        }

        organization = get_user_organization(
            self.staff,
            request=request,
        )

        self.assertEqual(organization, self.merrylight)
from django.test import TestCase
from .forms import OrganizationForm


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

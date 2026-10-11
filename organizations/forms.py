import re
from django import forms
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from .models import Organization
from billing.models import SubscriptionPlan

User = get_user_model()


class OrganizationForm(forms.ModelForm):
    # On creation, the owner is always a new account so that we can collect
    # their name/phone and enforce the first-login password change.
    owner_full_name = forms.CharField(
        required=True,
        max_length=150,
        label="Owner's full name",
        help_text="Enter the owner's name as it should appear on the account.",
    )
    owner_phone = forms.CharField(
        required=True,
        max_length=30,
        label="Owner's WhatsApp / phone number",
        help_text="Use a Tanzanian number such as 07XXXXXXXX or an international +country-code number.",
    )
    owner_email = forms.EmailField(
        required=False,
        label="Owner's email address",
    )
    # Used only when editing to assign an existing user as owner.
    owner = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True, is_superuser=False).order_by("username"),
        required=False,
        label="Assign existing user as owner",
        help_text="For editing only: select a user to transfer ownership.",
    )
    plan = forms.ModelChoiceField(
        queryset=SubscriptionPlan.objects.filter(is_active=True),
        required=False,
        label="Initial subscription plan",
    )
    trial_end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Trial end date",
    )

    class Meta:
        model = Organization
        fields = [
            "name", "legal_name", "organization_type", "status", "is_verified",
            "phone", "secondary_phone", "email", "secondary_email", "website",
            "country", "region", "city", "address", "postal_code", "industry",
            "description", "logo", "timezone", "language", "notes",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "address": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.is_new = not getattr(kwargs.get("instance"), "pk", None)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                field.widget.attrs.get("class", "") + " org-input"
            ).strip()
        type_field = self.fields.get("organization_type")
        if type_field:
            if self.is_new or self.instance.organization_type != "platform_owner":
                type_field.choices = [
                    choice for choice in type_field.choices
                    if choice[0] != "platform_owner"
                ]
            else:
                type_field.disabled = True
                if "status" in self.fields:
                    self.fields["status"].disabled = True
        if self.is_new:
            self.fields.pop("owner", None)
        else:
            for name in ("owner_full_name", "owner_phone", "owner_email", "plan", "trial_end_date"):
                self.fields.pop(name, None)
            current_owner = self.instance.members.filter(role="owner").select_related("user").first()
            if current_owner:
                self.fields["owner"].initial = current_owner.user

    def clean_owner_phone(self):
        raw = self.cleaned_data["owner_phone"].strip()
        compact = re.sub(r"[\s().-]", "", raw)
        if compact.startswith("0"):
            compact = "+255" + compact[1:]
        elif compact.startswith("255"):
            compact = "+" + compact
        elif not compact.startswith("+"):
            raise forms.ValidationError(
                "Enter a number starting with 0, 255, or +country code."
            )
        digits = re.sub(r"\D", "", compact)
        if not 8 <= len(digits) <= 15:
            raise forms.ValidationError("Enter a valid phone number with 8–15 digits.")
        return "+" + digits

    def clean(self):
        data = super().clean()
        if self.is_new:
            if not (data.get("owner_full_name") or "").strip():
                self.add_error("owner_full_name", "The owner's full name is required.")
            if not data.get("owner_phone"):
                self.add_error("owner_phone", "The owner's phone number is required.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.slug:
            base = slugify(obj.name)[:90] or "organization"
            slug, n = base, 2
            while Organization.objects.filter(slug=slug).exclude(pk=obj.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            obj.slug = slug
        if commit:
            obj.save()
            self.save_m2m()
        return obj

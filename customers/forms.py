from django import forms

from .models import Customer


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer

        fields = [
            "name",
            "customer_type",
            "company",
            "phone",
            "email",
            "preferred_contact_method",
            "country",
            "city",
            "address",
            "status",
            "notes",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Customer name",
                }
            ),

            "customer_type": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "company": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Company / Organization",
                }
            ),

            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "+255...",
                }
            ),

            "email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "customer@example.com",
                }
            ),

            "preferred_contact_method": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "country": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "city": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "City",
                }
            ),

            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Address",
                }
            ),

            "status": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Internal notes",
                }
            ),
        }

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()

        if not phone:
            raise forms.ValidationError(
                "Customer phone number is required."
            )

        return phone
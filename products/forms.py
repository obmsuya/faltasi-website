
from django import forms

from products.models import Product, ProductCategory


class ProductForm(forms.ModelForm):
    """Create and edit products belonging to an individual organization."""

    class Meta:
        model = Product
        fields = [
            "product_type",
            "category",
            "name",
            "short_description",
            "description",
            "sku",
            "brand",
            "model",
            "manufacturer",
            "price",
            "currency",
            "unit",
            "quantity",
            "minimum_stock",
            "track_inventory",
            "allow_backorder",
            "availability",
            "image",
            "show_on_website",
            "show_on_whatsapp",
            "allow_quote_request",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "short_description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

        # Categories are managed at platform level.
        self.fields["category"].queryset = ProductCategory.objects.filter(
            organization__isnull=True,
            is_active=True,
        ).order_by("name")

    def save(self, commit=True):
        product = super().save(commit=False)
        product.organization = self.organization

        if commit:
            product.save()
            self.save_m2m()

        return product

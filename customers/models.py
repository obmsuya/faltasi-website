from django.db import models
from organizations.models import Organization


class Customer(models.Model):

    CUSTOMER_TYPE_CHOICES = [
        ("individual", "Individual"),
        ("company", "Company / Organization"),
    ]

    CUSTOMER_STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    CONTACT_METHOD_CHOICES = [
        ("whatsapp", "WhatsApp"),
        ("phone", "Phone"),
        ("email", "Email"),
    ]

    # SaaS organization / tenant
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="customers",
        blank=True,
        null=True,
    )

    name = models.CharField(
        max_length=200
    )

    customer_type = models.CharField(
        max_length=20,
        choices=CUSTOMER_TYPE_CHOICES,
        default="individual",
    )

    company = models.CharField(
        max_length=200,
        blank=True,
        null=True,
    )

    phone = models.CharField(
        max_length=30
    )

    email = models.EmailField(
        max_length=254,
        blank=True,
        null=True,
    )

    preferred_contact_method = models.CharField(
        max_length=20,
        choices=CONTACT_METHOD_CHOICES,
        default="whatsapp",
    )

    country = models.CharField(
        max_length=100,
        default="Tanzania",
        blank=True,
    )

    city = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    address = models.TextField(
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=CUSTOMER_STATUS_CHOICES,
        default="active",
    )

    notes = models.TextField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        if self.company:
            return self.company

        if self.name:
            return self.name

        return self.phone
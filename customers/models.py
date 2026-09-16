from django.db import models


class Customer(models.Model):

    # ---------------------------------------------------------
    # CUSTOMER TYPE
    # ---------------------------------------------------------
    CUSTOMER_TYPE_CHOICES = [
        ("individual", "Individual"),
        ("company", "Company / Organization"),
    ]

    # ---------------------------------------------------------
    # CUSTOMER STATUS
    # ---------------------------------------------------------
    CUSTOMER_STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    # ---------------------------------------------------------
    # PREFERRED CONTACT METHOD
    # ---------------------------------------------------------
    CONTACT_METHOD_CHOICES = [
        ("whatsapp", "WhatsApp"),
        ("phone", "Phone"),
        ("email", "Email"),
    ]

    # ---------------------------------------------------------
    # BASIC CUSTOMER INFORMATION
    # ---------------------------------------------------------
    name = models.CharField(
        max_length=200
    )

    customer_type = models.CharField(
        max_length=20,
        choices=CUSTOMER_TYPE_CHOICES,
        default="individual"
    )

    company = models.CharField(
        max_length=200,
        blank=True,
        null=True
    )

    # ---------------------------------------------------------
    # CONTACT INFORMATION
    # ---------------------------------------------------------
    phone = models.CharField(
        max_length=30
    )

    email = models.EmailField(
        max_length=254,
        blank=True,
        null=True
    )

    preferred_contact_method = models.CharField(
        max_length=20,
        choices=CONTACT_METHOD_CHOICES,
        default="whatsapp"
    )

    # ---------------------------------------------------------
    # LOCATION
    # ---------------------------------------------------------
    country = models.CharField(
        max_length=100,
        default="Tanzania"
    )

    city = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    address = models.TextField(
        blank=True,
        null=True
    )

    # ---------------------------------------------------------
    # CUSTOMER STATUS
    # ---------------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=CUSTOMER_STATUS_CHOICES,
        default="active"
    )

    # ---------------------------------------------------------
    # INTERNAL NOTES
    # ---------------------------------------------------------
    notes = models.TextField(
        blank=True,
        null=True
    )

    # ---------------------------------------------------------
    # SYSTEM DATES
    # ---------------------------------------------------------
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    # ---------------------------------------------------------
    # DISPLAY NAME
    # ---------------------------------------------------------
    def __str__(self):
        if self.company:
            return self.company

        if self.name:
            return self.name

        return self.phone
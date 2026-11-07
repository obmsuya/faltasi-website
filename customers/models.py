
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

    RELATIONSHIP_STAGE_CHOICES = [
        ("visitor", "Visitor"),
        ("potential", "Potential Customer"),
        ("customer", "Customer"),
    ]

    PHONE_STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("blocked", "Blocked"),
        ("removed", "Removed"),
    ]

    CONTACT_SOURCE_CHOICES = [
        ("manual", "Manually Added"),
        ("whatsapp", "WhatsApp"),
        ("website", "Website"),
        ("import", "Import"),
        ("other", "Other"),
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
        max_length=30,
        blank=True,
        default="",
    )

    # CRM relationship and contact-channel lifecycle are independent.
    relationship_stage = models.CharField(
        max_length=20,
        choices=RELATIONSHIP_STAGE_CHOICES,
        default="visitor",
        db_index=True,
    )

    phone_status = models.CharField(
        max_length=20,
        choices=PHONE_STATUS_CHOICES,
        default="active",
        db_index=True,
    )

    contact_source = models.CharField(
        max_length=20,
        choices=CONTACT_SOURCE_CHOICES,
        default="manual",
    )

    first_contact_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    last_interaction_at = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
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

    # ==========================================
    # WHATSAPP MARKETING CONSENT
    # ==========================================

    whatsapp_marketing_opt_in = models.BooleanField(
        default=False,
        help_text=(
            "Whether this customer has explicitly "
            "agreed to receive WhatsApp marketing messages."
        ),
    )

    whatsapp_marketing_opt_in_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    whatsapp_marketing_opt_in_source = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text=(
            "How consent was obtained, e.g. whatsapp_reply."
        ),
    )

    whatsapp_marketing_opt_out_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    # Records when the marketing subscription invitation was sent.
    whatsapp_marketing_invitation_sent_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text=(
            "When the WhatsApp marketing subscription invitation "
            "was successfully sent to this customer."
        ),
    )

    # Records when the customer explicitly declined marketing.
    whatsapp_marketing_declined_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text=(
            "When the customer declined WhatsApp marketing "
            "by replying NO."
        ),
    )

    @property
    def marketing_consent_status(self):
        """
        Derive the current WhatsApp marketing consent status.

        This property does not create an additional database field.
        """

        if self.whatsapp_marketing_opt_in:
            return "subscribed"

        if self.whatsapp_marketing_opt_out_at:
            return "unsubscribed"

        if self.whatsapp_marketing_declined_at:
            return "declined"

        if self.whatsapp_marketing_invitation_sent_at:
            return "pending"

        return "not_asked"

    # ==========================================
    # CUSTOMER LOCATION AND DETAILS
    # ==========================================

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

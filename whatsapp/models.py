from django.db import models

from organizations.models import Organization
from customers.models import Customer
from business_requests.models import BusinessRequest


class WhatsAppBusinessAccount(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("connected", "Connected"),
        ("disconnected", "Disconnected"),
        ("suspended", "Suspended"),
        ("error", "Error"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="whatsapp_business_accounts",
    )

    # Meta WhatsApp Business Account ID
    waba_id = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
    )

    # Business name as registered/displayed in Meta
    business_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    # Meta Business Manager ID
    business_manager_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="pending",
    )

    is_active = models.BooleanField(
        default=True,
    )

    # Additional Meta/API information.
    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    notes = models.TextField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["organization__name", "business_name"]

    def __str__(self):
        return (
            f"{self.organization.name} - "
            f"{self.business_name or self.waba_id or 'WhatsApp Account'}"
        )


class WhatsAppPhoneNumber(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("connected", "Connected"),
        ("disconnected", "Disconnected"),
        ("suspended", "Suspended"),
        ("error", "Error"),
    ]

    whatsapp_business_account = models.ForeignKey(
        WhatsAppBusinessAccount,
        on_delete=models.CASCADE,
        related_name="phone_numbers",
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="whatsapp_phone_numbers",
    )

    # Meta Phone Number ID
    phone_number_id = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
    )

    # Actual WhatsApp number
    phone_number = models.CharField(
        max_length=30,
    )

    # Display name shown in WhatsApp
    display_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    # Meta verified name
    verified_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    country_code = models.CharField(
        max_length=10,
        blank=True,
        null=True,
    )

    quality_rating = models.CharField(
        max_length=50,
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="pending",
    )

    is_active = models.BooleanField(
        default=True,
    )

    # Whether this is the primary WhatsApp number
    # for the organization.
    is_default = models.BooleanField(
        default=False,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    notes = models.TextField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "organization__name",
            "phone_number",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "phone_number",
                ],
                name="unique_org_whatsapp_phone",
            ),
        ]

    def __str__(self):
        return (
            f"{self.organization.name} - "
            f"{self.phone_number}"
        )


class WhatsAppConnection(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("connected", "Connected"),
        ("disconnected", "Disconnected"),
        ("error", "Error"),
    ]

    whatsapp_business_account = models.OneToOneField(
        WhatsAppBusinessAccount,
        on_delete=models.CASCADE,
        related_name="connection",
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="whatsapp_connections",
    )

    access_token = models.TextField(
        blank=True,
        null=True,
    )

    token_expires_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="pending",
    )

    last_connected_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    last_error = models.TextField(
        blank=True,
        null=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["organization__name"]

    def __str__(self):
        return (
            f"{self.organization.name} - "
            f"{self.whatsapp_business_account.business_name or 'WhatsApp Connection'}"
        )
class Conversation(models.Model):

    STATUS_CHOICES = [
        ("active", "Active"),
        ("closed", "Closed"),
    ]

    # SaaS organization / tenant
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="whatsapp_conversations",
        blank=True,
        null=True,
    )

    # WhatsApp phone number that received/sent
    # this conversation.
    whatsapp_phone_number = models.ForeignKey(
        WhatsAppPhoneNumber,
        on_delete=models.SET_NULL,
        related_name="conversations",
        blank=True,
        null=True,
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="whatsapp_conversations",
    )

    phone_number = models.CharField(
        max_length=30,
    )

    whatsapp_user_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    business_request = models.ForeignKey(
        BusinessRequest,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="whatsapp_conversations",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
    )

    started_at = models.DateTimeField(
        auto_now_add=True,
    )

    last_message_at = models.DateTimeField(
        auto_now=True,
    )

    closed_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["-last_message_at"]

    def __str__(self):
        return (
            f"Conversation - "
            f"{self.phone_number}"
        )


class ConversationState(models.Model):

    conversation = models.OneToOneField(
        Conversation,
        on_delete=models.CASCADE,
        related_name="state",
    )

    current_step = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    waiting_for = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    data = models.JSONField(
        default=dict,
        blank=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return (
            f"State - "
            f"{self.conversation.phone_number}"
        )


class Message(models.Model):

    DIRECTION_CHOICES = [
        ("incoming", "Incoming"),
        ("outgoing", "Outgoing"),
    ]

    SENDER_TYPE_CHOICES = [
        ("customer", "Customer"),
        ("faltasi", "Faltasi"),
        ("agent", "Agent"),
        ("system", "System"),
    ]

    MESSAGE_TYPE_CHOICES = [
        ("text", "Text"),
        ("image", "Image"),
        ("audio", "Audio"),
        ("video", "Video"),
        ("document", "Document"),
        ("location", "Location"),
        ("interactive", "Interactive"),
        ("unknown", "Unknown"),
    ]

    DELIVERY_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("sent", "Sent"),
        ("delivered", "Delivered"),
        ("read", "Read"),
        ("failed", "Failed"),
    ]

    # SaaS organization / tenant
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="whatsapp_messages",
        blank=True,
        null=True,
    )

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    direction = models.CharField(
        max_length=20,
        choices=DIRECTION_CHOICES,
    )

    sender_type = models.CharField(
        max_length=20,
        choices=SENDER_TYPE_CHOICES,
    )

    message_type = models.CharField(
        max_length=20,
        choices=MESSAGE_TYPE_CHOICES,
        default="unknown",
    )

    content = models.TextField(
        blank=True,
        null=True,
    )

    whatsapp_message_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
    )

    delivery_status = models.CharField(
        max_length=20,
        choices=DELIVERY_STATUS_CHOICES,
        default="pending",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return (
            f"{self.direction.title()} "
            f"Message - "
            f"{self.conversation.phone_number}"
        )
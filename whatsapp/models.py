from django.db import models
from customers.models import Customer
from business_requests.models import BusinessRequest


class Conversation(models.Model):

    STATUS_CHOICES = [
        ("active", "Active"),
        ("closed", "Closed"),
    ]

    # ---------------------------------------------------------
    # CUSTOMER
    # ---------------------------------------------------------
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="whatsapp_conversations"
    )

    # ---------------------------------------------------------
    # WHATSAPP INFORMATION
    # ---------------------------------------------------------
    phone_number = models.CharField(
        max_length=30
    )

    whatsapp_user_id = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    # ---------------------------------------------------------
    # BUSINESS REQUEST
    # ---------------------------------------------------------
    business_request = models.ForeignKey(
        BusinessRequest,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="whatsapp_conversations"
    )

    # ---------------------------------------------------------
    # CONVERSATION STATUS
    # ---------------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active"
    )

    # ---------------------------------------------------------
    # DATES
    # ---------------------------------------------------------
    started_at = models.DateTimeField(
        auto_now_add=True
    )

    last_message_at = models.DateTimeField(
        auto_now=True
    )

    closed_at = models.DateTimeField(
        blank=True,
        null=True
    )

    def __str__(self):
        return f"WhatsApp - {self.phone_number}"


class ConversationState(models.Model):

    conversation = models.OneToOneField(
        Conversation,
        on_delete=models.CASCADE,
        related_name="state"
    )

    # ---------------------------------------------------------
    # CURRENT CHATBOT STATE
    # ---------------------------------------------------------
    current_step = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    waiting_for = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    # ---------------------------------------------------------
    # TEMPORARY CONVERSATION DATA
    # ---------------------------------------------------------
    data = models.JSONField(
        default=dict,
        blank=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"State - {self.conversation.phone_number}"


class Message(models.Model):

    DIRECTION_CHOICES = [
        ("incoming", "Incoming"),
        ("outgoing", "Outgoing"),
    ]

    SENDER_CHOICES = [
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

    # ---------------------------------------------------------
    # CONVERSATION
    # ---------------------------------------------------------
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages"
    )

    # ---------------------------------------------------------
    # MESSAGE INFORMATION
    # ---------------------------------------------------------
    direction = models.CharField(
        max_length=20,
        choices=DIRECTION_CHOICES
    )

    sender_type = models.CharField(
        max_length=20,
        choices=SENDER_CHOICES
    )

    message_type = models.CharField(
        max_length=30,
        choices=MESSAGE_TYPE_CHOICES,
        default="text"
    )

    content = models.TextField(
        blank=True,
        null=True
    )

    # ---------------------------------------------------------
    # META / WHATSAPP INFORMATION
    # ---------------------------------------------------------
    whatsapp_message_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True
    )

    # ---------------------------------------------------------
    # DELIVERY
    # ---------------------------------------------------------
    delivery_status = models.CharField(
        max_length=20,
        choices=DELIVERY_STATUS_CHOICES,
        default="pending"
    )

    # ---------------------------------------------------------
    # MESSAGE DATA
    # ---------------------------------------------------------
    metadata = models.JSONField(
        default=dict,
        blank=True
    )

    # ---------------------------------------------------------
    # TIMESTAMP
    # ---------------------------------------------------------
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.direction} - {self.message_type}"
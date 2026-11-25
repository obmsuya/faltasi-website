from django.core.exceptions import ValidationError
from django.db import models

from organizations.models import Organization
from customers.models import Customer
from business_requests.models import BusinessRequest
import uuid
from django.contrib.gis.db.models import PointField
from django.contrib.gis.geos import Point

from django.core.validators import MinValueValidator, MaxValueValidator
from django.conf import settings


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

    def clean(self):
        super().clean()

        if (
            self.organization_id
            and self.whatsapp_business_account_id
        ):
            waba_organization_id = (
                self.whatsapp_business_account.organization_id
            )

            if waba_organization_id != self.organization_id:
                raise ValidationError({
                    "whatsapp_business_account": (
                        "The WhatsApp Business Account must belong "
                        "to the same organization as this phone number."
                    )
                })

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

    def clean(self):
        super().clean()

        if (
            self.organization_id
            and self.whatsapp_business_account_id
        ):
            waba_organization_id = (
                self.whatsapp_business_account.organization_id
            )

            if waba_organization_id != self.organization_id:
                raise ValidationError({
                    "whatsapp_business_account": (
                        "The WhatsApp Business Account must belong "
                        "to the same organization as this connection."
                    )
                })

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

    HANDLING_MODE_CHOICES = [
        ("ai", "AI handled"),
        ("human", "Human handled"),
    ]

    handling_mode = models.CharField(
        max_length=10,
        choices=HANDLING_MODE_CHOICES,
        default="ai",
    )
    # Timestamp identifying the current human handover.
    # Used to invalidate outdated Celery timeout tasks.
    handover_at = models.DateTimeField(
        blank=True,
        null=True,
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

    def clean(self):
        super().clean()

        if not self.organization_id:
            return

        # Customer must belong to the conversation organization.
        if self.customer_id:
            customer_organization_id = self.customer.organization_id

            if (
                customer_organization_id
                and customer_organization_id != self.organization_id
            ):
                raise ValidationError({
                    "customer": (
                        "The customer must belong to the same "
                        "organization as the conversation."
                    )
                })

        # WhatsApp phone must belong to the conversation organization.
        if self.whatsapp_phone_number_id:
            phone_organization_id = (
                self.whatsapp_phone_number.organization_id
            )

            if phone_organization_id != self.organization_id:
                raise ValidationError({
                    "whatsapp_phone_number": (
                        "The WhatsApp phone number must belong "
                        "to the same organization as the conversation."
                    )
                })

        # Linked business request must belong to the same organization.
        if self.business_request_id:
            business_request = self.business_request

            request_customer_organization_id = (
                business_request.customer.organization_id
            )

            if (
                request_customer_organization_id
                and request_customer_organization_id != self.organization_id
            ):
                raise ValidationError({
                    "business_request": (
                        "The business request customer must belong "
                        "to the conversation organization."
                    )
                })

            if business_request.category_id:
                category_organization_id = (
                    business_request.category.organization_id
                )

                if category_organization_id != self.organization_id:
                    raise ValidationError({
                        "business_request": (
                            "The business request category must belong "
                            "to the conversation organization."
                        )
                    })

            if business_request.department_id:
                department_organization_id = (
                    business_request.department.organization_id
                )

                if department_organization_id != self.organization_id:
                    raise ValidationError({
                        "business_request": (
                            "The business request department must belong "
                            "to the conversation organization."
                        )
                    })

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

    def clean(self):
        super().clean()

        if (
            self.organization_id
            and self.conversation_id
        ):
            conversation_organization_id = (
                self.conversation.organization_id
            )

            if (
                conversation_organization_id
                and conversation_organization_id != self.organization_id
            ):
                raise ValidationError({
                    "organization": (
                        "The message must belong to the same "
                        "organization as its conversation."
                    )
                })

    def __str__(self):
        return (
            f"{self.direction.title()} "
            f"Message - "
            f"{self.conversation.phone_number}"
        )





class WhatsAppLocationRecord(models.Model):
    """
    Stores geographical locations collected through WhatsApp
    or entered manually by an organization member.

    Collector: person submitting the location.
    Subject: person, property, business, or place being recorded.
    """

    SOURCE_CHOICES = [
        ("whatsapp_pin", "WhatsApp location pin"),
        ("google_maps_link", "Google Maps link"),
        ("manual", "Manually entered"),
    ]

    STATUS_CHOICES = [
        ("pending_review", "Pending review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    reference = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="whatsapp_location_records",
    )

    # WhatsApp conversation is optional for manually entered records.
    conversation = models.ForeignKey(
        "Conversation",
        on_delete=models.PROTECT,
        related_name="location_records",
        blank=True,
        null=True,
    )

    source_message = models.OneToOneField(
        "Message",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="collected_location_record",
    )

    # COLLECTOR DETAILS

    collector_name = models.CharField(
        max_length=255,
        help_text="Name of the person collecting and submitting the data.",
    )

    collector_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text="WhatsApp number used by the collector, if available.",
    )

    # SUBJECT DETAILS

    subject_name = models.CharField(
        max_length=255,
        help_text="Name of the person, property owner, business, or subject.",
    )

    subject_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text="Contact number of the subject, if available.",
    )

    # GEOGRAPHICAL INFORMATION

    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        validators=[
            MinValueValidator(-90),
            MaxValueValidator(90),
        ],
        help_text="Latitude in decimal degrees, WGS84.",
    )

    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        validators=[
            MinValueValidator(-180),
            MaxValueValidator(180),
        ],
        help_text="Longitude in decimal degrees, WGS84.",
    )

    location = PointField(
        srid=4326,
        geography=True,
        null=True,
        blank=True,
        spatial_index=True,
        help_text="Spatial location stored in WGS84.",
    )

    location_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of the location, property, or place.",
    )

    location_address = models.CharField(
        max_length=500,
        blank=True,
        help_text="Address supplied with the location, if available.",
    )

    location_description = models.TextField(
        blank=True,
        help_text="Additional field observations about the location.",
    )

    accuracy_meters = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
        help_text="Reported horizontal location accuracy in metres.",
    )

    altitude_meters = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Altitude in metres, if supplied by the source.",
    )

    # LOCATION SOURCE AND EVIDENCE

    source = models.CharField(
        max_length=30,
        choices=SOURCE_CHOICES,
    )

    source_url = models.URLField(
        max_length=2048,
        blank=True,
        help_text="Original Google Maps URL, when a map link was submitted.",
    )

    source_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional source information, such as provider metadata.",
    )

    # REVIEW INFORMATION

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="pending_review",
    )

    review_reason = models.TextField(
        blank=True,
        help_text="Reason or notes provided during review.",
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_gis_locations",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # SOFT DELETION

    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
    )

    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_gis_locations",
    )

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # TIMESTAMPS

    collected_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Time the location was captured, if supplied by the source.",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-created_at"]

        verbose_name = "WhatsApp Location Record"
        verbose_name_plural = "WhatsApp Location Records"

        indexes = [
            models.Index(
                fields=["organization", "created_at"],
                name="wa_loc_org_created_idx",
            ),
            models.Index(
                fields=["organization", "status"],
                name="wa_loc_org_status_idx",
            ),
            models.Index(
                fields=["organization", "subject_phone"],
                name="wa_loc_org_subject_idx",
            ),
            models.Index(
                fields=["organization", "collector_phone"],
                name="wa_loc_org_collect_idx",
            ),
            models.Index(
                fields=["organization", "is_deleted"],
                name="wa_loc_org_deleted_idx",
            ),
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    latitude__gte=-90,
                    latitude__lte=90,
                ),
                name="wa_loc_valid_latitude",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    longitude__gte=-180,
                    longitude__lte=180,
                ),
                name="wa_loc_valid_longitude",
            ),
        ]

    def _sync_location(self):
        """
        Synchronize the PostGIS point from latitude and longitude.

        PostGIS coordinate order:
        X = longitude
        Y = latitude
        """
        if self.latitude is None or self.longitude is None:
            self.location = None
            return

        self.location = Point(
            float(self.longitude),
            float(self.latitude),
            srid=4326,
        )

    def clean(self):
        super().clean()

        errors = {}

        # WhatsApp records must have a conversation.
        # Manual records do not require one.
        if (
            self.source in ["whatsapp_pin", "google_maps_link"]
            and not self.conversation_id
        ):
            errors["conversation"] = (
                "A WhatsApp conversation is required for this source."
            )

        # Validate organization and conversation ownership.
        if self.organization_id and self.conversation_id:
            if (
                self.conversation.organization_id
                != self.organization_id
            ):
                errors["conversation"] = (
                    "The conversation must belong to the same "
                    "organization as this location record."
                )

        # Validate source message ownership.
        if self.source_message_id:
            if self.conversation_id:
                if (
                    self.source_message.conversation_id
                    != self.conversation_id
                ):
                    errors["source_message"] = (
                        "The source message must belong to the selected "
                        "conversation."
                    )

            if (
                self.organization_id
                and self.source_message.organization_id
                != self.organization_id
            ):
                errors["source_message"] = (
                    "The source message must belong to the same "
                    "organization as this location record."
                )

        # Google Maps links must have a source URL.
        if (
            self.source == "google_maps_link"
            and not self.source_url
        ):
            errors["source_url"] = (
                "A Google Maps URL is required for this source."
            )

        # Manual records must not require WhatsApp source evidence.
        if self.source == "manual":
            self.source_message = None

        # Validate accuracy.
        if (
            self.accuracy_meters is not None
            and self.accuracy_meters < 0
        ):
            errors["accuracy_meters"] = (
                "Accuracy cannot be negative."
            )

        if errors:
            raise ValidationError(errors)

        self._sync_location()

    def save(self, *args, **kwargs):
        """
        Always synchronize the PostGIS point before saving.

        Also ensures the spatial point is included when update_fields
        is explicitly supplied.
        """
        self._sync_location()

        update_fields = kwargs.get("update_fields")

        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"location"}

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.subject_name} | "
            f"{self.latitude}, {self.longitude}"
        )


 
class WhatsAppLocationRecordHistory(models.Model):
    ACTION_CHOICES = [
        ("created", "Created"),
        ("updated", "Updated"),
        ("moved", "Coordinates changed"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("deleted", "Soft deleted"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="gis_location_history",
    )

    location_record = models.ForeignKey(
        WhatsAppLocationRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history",
    )

    reference = models.UUIDField(
        db_index=True,
    )

    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gis_location_actions",
    )

    reason = models.TextField(blank=True)

    old_values = models.JSONField(default=dict, blank=True)

    new_values = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["organization", "reference", "created_at"],
                name="gis_hist_org_ref_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.action} - {self.reference}"

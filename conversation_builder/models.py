
from django.conf import settings as django_settings
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

def ensure_version_is_editable(version):
    """Prevent changes to records belonging to a published version."""
    if version and version.status == "published":
        raise ValidationError(
            "Published conversation versions are immutable. "
            "Create a new draft to make changes."
        )


class ConversationConfiguration(models.Model):
    """One WhatsApp conversation configuration per organization."""

    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="whatsapp_conversation_configuration",
    )

    draft_version = models.ForeignKey(
        "ConversationConfigurationVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="draft_for_configurations",
    )

    published_version = models.ForeignKey(
        "ConversationConfigurationVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_for_configurations",
    )

    is_enabled = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        errors = {}

        if self.draft_version_id:
            if self.draft_version.configuration_id != self.pk:
                errors["draft_version"] = (
                    "Draft version must belong to this configuration."
                )
            elif self.draft_version.status != "draft":
                errors["draft_version"] = (
                    "The selected version must have draft status."
                )

        if self.published_version_id:
            if self.published_version.configuration_id != self.pk:
                errors["published_version"] = (
                    "Published version must belong to this configuration."
                )
            elif self.published_version.status != "published":
                errors["published_version"] = (
                    "The selected version must be published."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Conversation Configuration - {self.organization}"


class ConversationConfigurationVersion(models.Model):
    """A versioned configuration with immutable published versions."""

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("published", "Published"),
        ("archived", "Archived"),
    ]

    LANGUAGE_CHOICES = [
        ("auto", "Automatic"),
        ("en", "English"),
        ("sw", "Kiswahili"),
    ]

    configuration = models.ForeignKey(
        ConversationConfiguration,
        on_delete=models.CASCADE,
        related_name="versions",
    )

    version_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
    )

    # General conversation settings.
    default_language = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default="auto",
    )

    welcome_message = models.TextField(blank=True, default="")
    fallback_message = models.TextField(blank=True, default="")
    closing_message = models.TextField(blank=True, default="")
    handover_message = models.TextField(blank=True, default="")

    # Additional AI guidance. Django remains authoritative
    # for workflows, validation, permissions and transactions.
    ai_instructions = models.TextField(blank=True, default="")

    # Extensible, schema-validated settings.
    settings = models.JSONField(default=dict, blank=True)

    # Immutable snapshot created during publishing.
    snapshot = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_conversation_config_versions",
    )

    published_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_conversation_config_versions",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["configuration", "version_number"],
                name="unique_conversation_config_version",
            ),
            models.UniqueConstraint(
                fields=["configuration"],
                condition=Q(status="draft"),
                name="one_draft_conversation_version",
            ),
            models.UniqueConstraint(
                fields=["configuration"],
                condition=Q(status="published"),
                name="one_published_conversation_version",
            ),
            models.CheckConstraint(
                condition=Q(version_number__gte=1),
                name="conversation_version_number_positive",
            ),
        ]

    def clean(self):
        super().clean()

        if self.version_number < 1:
            raise ValidationError({
                "version_number": "Version number must be at least 1."
            })

        if self.status not in dict(self.STATUS_CHOICES):
            raise ValidationError({
                "status": "Invalid configuration version status."
            })

        if not isinstance(self.settings, dict):
            raise ValidationError({
                "settings": "Settings must be a JSON object."
            })

        if not isinstance(self.snapshot, dict):
            raise ValidationError({
                "snapshot": "Snapshot must be a JSON object."
            })

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()

            if old and old.status == "published":
                raise ValidationError(
                    "Published versions cannot be modified. "
                    "Create a new draft instead."
                )

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == "published":
            raise ValidationError(
                "Published versions cannot be deleted."
            )

        return super().delete(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.configuration.organization} - "
            f"Version {self.version_number} ({self.status})"
        )


class ConversationQuestion(models.Model):
    """Configurable general and product conversation questions."""

    SCOPE_CHOICES = [
        ("general", "General Conversation"),
        ("product", "Product Enquiry"),
    ]

    FIELD_TYPE_CHOICES = [
        ("text", "Text"),
        ("number", "Number"),
        ("yes_no", "Yes / No"),
        ("choice", "Choice"),
    ]

    version = models.ForeignKey(
        ConversationConfigurationVersion,
        on_delete=models.CASCADE,
        related_name="questions",
    )

    key = models.SlugField(max_length=100)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    question = models.CharField(max_length=500)

    field_type = models.CharField(
        max_length=20,
        choices=FIELD_TYPE_CHOICES,
        default="text",
    )

    help_text = models.CharField(max_length=500, blank=True, default="")
    retry_message = models.CharField(max_length=500, blank=True, default="")
    skip_message = models.CharField(max_length=500, blank=True, default="")

    is_required = models.BooleanField(default=False)
    allow_skip = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    order = models.PositiveIntegerField(default=1)
    max_attempts = models.PositiveSmallIntegerField(default=3)

    validation_rules = models.JSONField(default=dict, blank=True)
    translations = models.JSONField(default=dict, blank=True)
    display_conditions = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scope", "order", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["version", "key"],
                name="unique_question_key_per_version",
            ),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1),
                name="conversation_question_attempts_positive",
            ),
            models.CheckConstraint(
                condition=Q(order__gte=1),
                name="conversation_question_order_positive",
            ),
            models.CheckConstraint(
                condition=~Q(is_required=True, allow_skip=True),
                name="required_question_cannot_skip",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.is_required and self.allow_skip:
            errors["allow_skip"] = (
                "A required question cannot allow skipping."
            )

        if self.max_attempts < 1:
            errors["max_attempts"] = (
                "At least one attempt must be allowed."
            )

        if self.order < 1:
            errors["order"] = "Question order must be at least 1."

        for field_name, value in (
            ("validation_rules", self.validation_rules),
            ("translations", self.translations),
            ("display_conditions", self.display_conditions),
        ):
            if not isinstance(value, dict):
                errors[field_name] = "This field must be a JSON object."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.version_id:
            ensure_version_is_editable(self.version)

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        ensure_version_is_editable(self.version)
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.version} - {self.key}"


class ConversationOption(models.Model):
    """Selectable answers belonging to a choice question."""

    question = models.ForeignKey(
        ConversationQuestion,
        on_delete=models.CASCADE,
        related_name="options",
    )

    value = models.CharField(max_length=150)
    label = models.CharField(max_length=150)
    translations = models.JSONField(default=dict, blank=True)

    order = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["question", "value"],
                name="unique_option_value_per_question",
            ),
            models.CheckConstraint(
                condition=Q(order__gte=1),
                name="conversation_option_order_positive",
            ),
        ]

    def clean(self):
        super().clean()

        if self.order < 1:
            raise ValidationError({
                "order": "Option order must be at least 1."
            })

        if not isinstance(self.translations, dict):
            raise ValidationError({
                "translations": "Translations must be a JSON object."
            })

    def save(self, *args, **kwargs):
        if self.question_id:
            ensure_version_is_editable(self.question.version)

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        ensure_version_is_editable(self.question.version)
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.question.key} - {self.label}"


class ConversationCategoryRule(models.Model):
    """Connect a configuration version to existing request categories."""

    version = models.ForeignKey(
        ConversationConfigurationVersion,
        on_delete=models.CASCADE,
        related_name="category_rules",
    )

    category = models.ForeignKey(
        "business_requests.RequestCategory",
        on_delete=models.PROTECT,
        related_name="conversation_rules",
    )

    is_enabled = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=1)

    instructions = models.TextField(blank=True, default="")
    welcome_message = models.TextField(blank=True, default="")
    closing_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["version", "category"],
                name="unique_category_rule_per_version",
            ),
            models.CheckConstraint(
                condition=Q(priority__gte=1),
                name="conversation_category_priority_positive",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.priority < 1:
            errors["priority"] = "Priority must be at least 1."

        if self.version_id and self.category_id:
            if (
                self.version.configuration.organization_id
                != self.category.organization_id
            ):
                errors["category"] = (
                    "The category must belong to the same organization "
                    "as the conversation configuration."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.version_id:
            ensure_version_is_editable(self.version)

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        ensure_version_is_editable(self.version)
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.version} - {self.category.name}"


class ConversationConfigurationAudit(models.Model):
    """Audit trail for configuration changes and publishing actions."""

    ACTION_CHOICES = [
        ("created", "Created"),
        ("edited", "Edited"),
        ("draft_created", "Draft Created"),
        ("published", "Published"),
        ("archived", "Archived"),
        ("rolled_back", "Rolled Back"),
        ("enabled", "Enabled"),
        ("disabled", "Disabled"),
    ]

    configuration = models.ForeignKey(
        ConversationConfiguration,
        on_delete=models.CASCADE,
        related_name="audit_entries",
    )

    version = models.ForeignKey(
        ConversationConfigurationVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )

    actor = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversation_configuration_audit_entries",
    )

    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def clean(self):
        super().clean()

        if self.version_id and self.configuration_id:
            if self.version.configuration_id != self.configuration_id:
                raise ValidationError({
                    "version": (
                        "Audit version must belong to this configuration."
                    )
                })

        if not isinstance(self.details, dict):
            raise ValidationError({
                "details": "Audit details must be a JSON object."
            })

    def __str__(self):
        return f"{self.configuration} - {self.action}"

class ProductConversationConfiguration(models.Model):
    """
    Holds the conversation configuration for one WhatsApp-enabled product.
    """

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="product_conversation_configurations",
    )

    product = models.OneToOneField(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="conversation_configuration",
    )

    draft_version = models.ForeignKey(
        "ProductConversationVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="draft_for_configurations",
    )

    published_version = models.ForeignKey(
        "ProductConversationVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_for_configurations",
    )

    is_enabled = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__name"]

    def clean(self):
        super().clean()

        if self.product_id and self.organization_id:
            from products.models import Product

            product = Product.objects.filter(
                pk=self.product_id
            ).only("organization_id").first()

            if product and product.organization_id != self.organization_id:
                raise ValidationError({
                    "organization": (
                        "The organization must own the selected product."
                    )
                })

        for field in ["draft_version", "published_version"]:
            version = getattr(self, field, None)

            if version and version.configuration_id != self.pk:
                raise ValidationError({
                    field: "The selected version belongs to another configuration."
                })

    def __str__(self):
        return f"Conversation - {self.product.name}"

class ProductConversationVersion(models.Model):

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("published", "Published"),
        ("archived", "Archived"),
    ]

    LANGUAGE_CHOICES = [
        ("auto", "Automatic"),
        ("en", "English"),
        ("sw", "Swahili"),
    ]

    configuration = models.ForeignKey(
        ProductConversationConfiguration,
        on_delete=models.CASCADE,
        related_name="versions",
    )

    version_number = models.PositiveIntegerField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
    )

    default_language = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default="auto",
    )

    welcome_message = models.TextField(blank=True)
    fallback_message = models.TextField(blank=True)
    closing_message = models.TextField(blank=True)
    handover_message = models.TextField(blank=True)

    ai_instructions = models.TextField(blank=True)

    # Sanitized customer-facing product information.
    product_snapshot = models.JSONField(default=dict, blank=True)

    # Final immutable published configuration snapshot.
    snapshot = models.JSONField(default=dict, blank=True)

    # Records AI generation information.
    generation_metadata = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_product_conversation_versions",
    )

    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_product_conversation_versions",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["configuration", "version_number"],
                name="unique_product_conversation_version",
            ),
            models.UniqueConstraint(
                fields=["configuration"],
                condition=models.Q(status="draft"),
                name="one_product_conversation_draft",
            ),
            models.UniqueConstraint(
                fields=["configuration"],
                condition=models.Q(status="published"),
                name="one_product_conversation_published",
            ),
            models.CheckConstraint(
                condition=models.Q(version_number__gte=1),
                name="product_conversation_version_positive",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(
                pk=self.pk
            ).only("status").first()

            if previous and previous.status == "published":
                raise ValidationError(
                    "Published product conversation versions are immutable."
                )

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == "published":
            raise ValidationError(
                "Published product conversation versions cannot be deleted."
            )

        return super().delete(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.configuration.product.name} "
            f"- Version {self.version_number} ({self.status})"
        )

class ProductConversationQuestion(models.Model):

    FIELD_TYPE_CHOICES = [
        ("text", "Text"),
        ("number", "Number"),
        ("yes_no", "Yes / No"),
        ("choice", "Multiple Choice"),
    ]

    version = models.ForeignKey(
        ProductConversationVersion,
        on_delete=models.CASCADE,
        related_name="questions",
    )

    key = models.SlugField(max_length=100)

    question = models.CharField(max_length=500)

    help_text = models.CharField(max_length=500, blank=True)

    field_type = models.CharField(
        max_length=20,
        choices=FIELD_TYPE_CHOICES,
        default="text",
    )

    is_required = models.BooleanField(default=True)
    allow_skip = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    order = models.PositiveIntegerField(default=1)

    max_attempts = models.PositiveIntegerField(default=3)

    retry_message = models.TextField(blank=True)
    skip_message = models.TextField(blank=True)

    validation_rules = models.JSONField(default=dict, blank=True)
    translations = models.JSONField(default=dict, blank=True)
    display_conditions = models.JSONField(default=dict, blank=True)

    # Explains why the AI suggested this question.
    generation_rationale = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]

        constraints = [
            models.UniqueConstraint(
                fields=["version", "key"],
                name="unique_product_question_key",
            ),
            models.CheckConstraint(
                condition=models.Q(order__gte=1),
                name="product_question_order_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1),
                name="product_question_attempts_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_required=False)
                    | models.Q(allow_skip=False)
                ),
                name="required_product_question_cannot_skip",
            ),
        ]

    def save(self, *args, **kwargs):
        ensure_product_version_is_editable(self.version)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        ensure_product_version_is_editable(self.version)
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.version} - {self.question}"

class ProductConversationOption(models.Model):

    question = models.ForeignKey(
        ProductConversationQuestion,
        on_delete=models.CASCADE,
        related_name="options",
    )

    value = models.CharField(max_length=100)
    label = models.CharField(max_length=200)

    translations = models.JSONField(default=dict, blank=True)

    order = models.PositiveIntegerField(default=1)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]

        constraints = [
            models.UniqueConstraint(
                fields=["question", "value"],
                name="unique_product_question_option",
            ),
            models.CheckConstraint(
                condition=models.Q(order__gte=1),
                name="product_option_order_positive",
            ),
        ]

    def save(self, *args, **kwargs):
        ensure_product_version_is_editable(
            self.question.version
        )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        ensure_product_version_is_editable(
            self.question.version
        )
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.label

def ensure_product_version_is_editable(version):
    if version and version.status == "published":
        raise ValidationError(
            "Published product conversation versions are immutable."
        )

class ProductConversationConfigurationAudit(models.Model):
    ACTION_CHOICES = [
        ("created", "Created"),
        ("draft_created", "Draft Created"),
        ("published", "Published"),
        ("archived", "Archived"),
        ("enabled", "Enabled"),
        ("disabled", "Disabled"),
    ]

    configuration = models.ForeignKey(
        ProductConversationConfiguration,
        on_delete=models.CASCADE,
        related_name="audit_entries",
    )

    version = models.ForeignKey(
        ProductConversationVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_conversation_audit_entries",
    )

    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def clean(self):
        super().clean()

        if self.version_id and self.configuration_id:
            if self.version.configuration_id != self.configuration_id:
                raise ValidationError({
                    "version": (
                        "Audit version must belong to this configuration."
                    )
                })

        if not isinstance(self.details, dict):
            raise ValidationError({
                "details": "Audit details must be a JSON object."
            })

    def __str__(self):
        return f"{self.configuration} - {self.action}"
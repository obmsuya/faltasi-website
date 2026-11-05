from django.core.exceptions import ValidationError
from django.db import models


class ChannelConnection(models.Model):
    """Organization-owned external channel account metadata.

    OAuth credentials are deliberately not stored in this initial model.
    Provider authorization and encrypted credential storage will be added
    with the corresponding OAuth integration.
    """

    PROVIDER_CHOICES = [
        ("instagram", "Instagram"),
        ("facebook", "Facebook"),
        ("tiktok", "TikTok"),
        ("google_business_profile", "Google Business Profile"),
        ("google_merchant_center", "Google Merchant Center"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending authorization"),
        ("connected", "Connected"),
        ("expired", "Authorization expired"),
        ("disconnected", "Disconnected"),
        ("error", "Connection error"),
    ]

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="channel_connections",
    )
    provider = models.CharField(max_length=40, choices=PROVIDER_CHOICES)
    external_account_id = models.CharField(max_length=255, blank=True, default="")
    account_name = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    metadata = models.JSONField(default=dict, blank=True)
    connected_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider", "account_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider", "external_account_id"],
                name="unique_org_channel_external_account",
            )
        ]

    def __str__(self):
        return f"{self.organization} - {self.get_provider_display()}"


class ProductChannelPublication(models.Model):
    """Per-product channel publication preference and synchronization state."""

    CHANNEL_CHOICES = [
        ("instagram", "Instagram"),
        ("facebook", "Facebook"),
        ("tiktok", "TikTok"),
        ("google_business_profile", "Google Business Profile"),
        ("google_merchant_center", "Google Merchant Center"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending", "Pending publication"),
        ("published", "Published"),
        ("failed", "Failed"),
        ("unpublished", "Unpublished"),
    ]

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="channel_publications",
    )
    channel = models.CharField(max_length=40, choices=CHANNEL_CHOICES)
    is_enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    external_product_id = models.CharField(max_length=255, blank=True, default="")
    last_synced_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["channel", "product__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "channel"],
                name="unique_product_channel_publication",
            )
        ]

    def clean(self):
        if self.product_id and self.product.organization_id is None:
            raise ValidationError("A channel publication requires an organization-owned product.")

    def __str__(self):
        return f"{self.product} - {self.get_channel_display()}"

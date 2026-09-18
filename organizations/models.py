from django.db import models


class Country(models.Model):
    """
    Countries supported by the Faltasi platform.
    """

    code = models.CharField(
        max_length=3,
        unique=True,
        help_text="Country code, e.g. TZ, KE, US.",
    )

    name = models.CharField(
        max_length=100,
        unique=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Organization(models.Model):
    """
    A business or organization using the Faltasi platform.

    Faltasi Innovations Limited itself will also be represented
    as an Organization with organization_type='platform_owner'.
    """

    ORGANIZATION_TYPE_CHOICES = [
        ("platform_owner", "Platform Owner"),
        ("business", "Business"),
        ("partner", "Partner"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("suspended", "Suspended"),
    ]

    # =========================================================
    # BASIC INFORMATION
    # =========================================================

    name = models.CharField(
        max_length=200,
    )

    legal_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    organization_type = models.CharField(
        max_length=30,
        choices=ORGANIZATION_TYPE_CHOICES,
        default="business",
    )

    slug = models.SlugField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
    )

    # =========================================================
    # CONTACT INFORMATION
    # =========================================================

    phone = models.CharField(
        max_length=30,
        blank=True,
        null=True,
    )

    secondary_phone = models.CharField(
        max_length=30,
        blank=True,
        null=True,
    )

    email = models.EmailField(
        max_length=254,
        blank=True,
        null=True,
    )

    secondary_email = models.EmailField(
        max_length=254,
        blank=True,
        null=True,
    )

    website = models.URLField(
        blank=True,
        null=True,
    )

    # =========================================================
    # LOCATION
    # =========================================================

    country = models.ForeignKey(
        Country,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="organizations",
    )

    region = models.CharField(
        max_length=100,
        blank=True,
        null=True,
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

    postal_code = models.CharField(
        max_length=30,
        blank=True,
        null=True,
    )

    # =========================================================
    # BUSINESS PROFILE
    # =========================================================

    industry = models.CharField(
        max_length=150,
        blank=True,
        null=True,
    )

    description = models.TextField(
        blank=True,
        null=True,
    )

    logo = models.ImageField(
        upload_to="organizations/logos/",
        blank=True,
        null=True,
    )

    # =========================================================
    # PLATFORM STATUS
    # =========================================================

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    is_verified = models.BooleanField(
        default=False,
    )

    suspended_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    suspension_reason = models.TextField(
        blank=True,
        null=True,
    )

    # =========================================================
    # ORGANIZATION SETTINGS
    # =========================================================

    timezone = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default=None,
    )

    language = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        default=None,
    )

    settings = models.JSONField(
        default=dict,
        blank=True,
    )

    # =========================================================
    # INTERNAL INFORMATION
    # =========================================================

    notes = models.TextField(
        blank=True,
        null=True,
    )

    # =========================================================
    # TIMESTAMPS
    # =========================================================

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrganizationMember(models.Model):
    """
    Connects Django users to organizations.

    A user can belong to more than one organization.
    """

    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("admin", "Administrator"),
        ("manager", "Manager"),
        ("agent", "Agent"),
        ("staff", "Staff"),
        ("viewer", "Viewer"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="members",
    )

    user = models.ForeignKey(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="organization_memberships",
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="staff",
    )

    is_active = models.BooleanField(
        default=True,
    )

    joined_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="unique_organization_member",
            )
        ]

    def __str__(self):
        return f"{self.organization.name} - {self.user.username}"
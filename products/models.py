from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone

from organizations.models import Organization


class ProductCategory(models.Model):

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="product_categories",
        null=True,
        blank=True,
    )

    name = models.CharField(
        max_length=150,
    )

    description = models.TextField(
        blank=True,
        null=True,
    )

    image = models.ImageField(
        upload_to="product_categories/",
        blank=True,
        null=True,
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


class Product(models.Model):

    PRODUCT_TYPE_CHOICES = [
        ("product", "Product"),
        ("service", "Service"),
    ]

    AVAILABILITY_CHOICES = [
        ("in_stock", "In Stock"),
        ("out_of_stock", "Out of Stock"),
        ("on_order", "On Order"),
        ("available_on_request", "Available on Request"),
        ("discontinued", "Discontinued"),
    ]

    UNIT_CHOICES = [
        ("piece", "Piece"),
        ("box", "Box"),
        ("pack", "Pack"),
        ("set", "Set"),
        ("pair", "Pair"),
        ("kg", "Kilogram"),
        ("g", "Gram"),
        ("ton", "Ton"),
        ("liter", "Liter"),
        ("ml", "Milliliter"),
        ("meter", "Meter"),
        ("cm", "Centimeter"),
        ("foot", "Foot"),
        ("roll", "Roll"),
        ("carton", "Carton"),
        ("hour", "Hour"),
        ("day", "Day"),
        ("month", "Month"),
        ("year", "Year"),
        ("service", "Service"),
        ("other", "Other"),
    ]

    # ==========================================================
    # ORGANIZATION
    # ==========================================================

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="products",
        null=True,
        blank=True,
    )

    # ==========================================================
    # BASIC INFORMATION
    # ==========================================================

    product_type = models.CharField(
        max_length=20,
        choices=PRODUCT_TYPE_CHOICES,
        default="product",
    )

    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )

    request_category = models.ForeignKey(
        "business_requests.RequestCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )

    name = models.CharField(
        max_length=255,
    )

    short_description = models.CharField(
        max_length=500,
        blank=True,
        null=True,
    )

    description = models.TextField(
        blank=True,
        null=True,
    )

    # ==========================================================
    # IDENTIFICATION
    # ==========================================================

    sku = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    barcode = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    brand = models.CharField(
        max_length=150,
        blank=True,
        null=True,
    )

    model = models.CharField(
        max_length=150,
        blank=True,
        null=True,
    )

    manufacturer = models.CharField(
        max_length=150,
        blank=True,
        null=True,
    )

    # ==========================================================
    # PRICING
    # ==========================================================

    price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[
            MinValueValidator(0),
        ],
    )

    cost_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[
            MinValueValidator(0),
        ],
    )

    wholesale_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[
            MinValueValidator(0),
        ],
    )

    currency = models.CharField(
        max_length=10,
        default="TZS",
    )

    # ==========================================================
    # INVENTORY
    # ==========================================================

    unit = models.CharField(
        max_length=20,
        choices=UNIT_CHOICES,
        default="piece",
    )

    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    minimum_stock = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    maximum_stock = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[
            MinValueValidator(0),
        ],
    )

    track_inventory = models.BooleanField(
        default=True,
    )

    allow_backorder = models.BooleanField(
        default=False,
    )

    # ==========================================================
    # AVAILABILITY
    # ==========================================================

    availability = models.CharField(
        max_length=30,
        choices=AVAILABILITY_CHOICES,
        default="available_on_request",
    )

    # ==========================================================
    # IMAGE
    # ==========================================================

    image = models.ImageField(
        upload_to="products/",
        blank=True,
        null=True,
    )

    # ==========================================================
    # WEBSITE / WHATSAPP
    # ==========================================================

    is_featured = models.BooleanField(
        default=False,
    )

    show_on_website = models.BooleanField(
        default=True,
    )

    show_on_whatsapp = models.BooleanField(
        default=True,
    )

    allow_quote_request = models.BooleanField(
        default=True,
    )

    # ==========================================================
    # DISPLAY
    # ==========================================================

    display_order = models.PositiveIntegerField(
        default=0,
    )

    # ==========================================================
    # EXTRA INFORMATION
    # ==========================================================

    specifications = models.JSONField(
        default=dict,
        blank=True,
    )

    additional_information = models.JSONField(
        default=dict,
        blank=True,
    )

    # ==========================================================
    # STATUS
    # ==========================================================

    is_active = models.BooleanField(
        default=True,
    )

    deleted_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    # ==========================================================
    # TIMESTAMPS
    # ==========================================================

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "display_order",
            "name",
        ]

    def __str__(self):
        return self.name

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def is_low_stock(self):
        if not self.track_inventory:
            return False

        return self.quantity <= self.minimum_stock

    def soft_delete(self):
        self.is_active = False
        self.deleted_at = timezone.now()

        self.save(
            update_fields=[
                "is_active",
                "deleted_at",
                "updated_at",
            ]
        )

    def restore(self):
        self.is_active = True
        self.deleted_at = None

        self.save(
            update_fields=[
                "is_active",
                "deleted_at",
                "updated_at",
            ]
        )
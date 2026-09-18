from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

from organizations.models import Organization


class SubscriptionPlan(models.Model):

    BILLING_INTERVAL_CHOICES = [
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
        ("semi_annual", "Semi-Annual"),
        ("annual", "Annual"),
        ("one_time", "One Time"),
    ]

    name = models.CharField(
        max_length=100,
        unique=True
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    # Price for ONE billing interval.
    #
    # Example:
    # Monthly plan     = TZS 50,000 per month
    # Quarterly plan   = TZS 150,000 per quarter
    # Annual plan      = TZS 1,200,000 per year
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    currency = models.CharField(
        max_length=10,
        default="TZS"
    )

    billing_interval = models.CharField(
        max_length=20,
        choices=BILLING_INTERVAL_CHOICES,
        default="monthly"
    )

    # Mainly useful for one-time plans.
    duration_days = models.PositiveIntegerField(
        default=30
    )

    is_free = models.BooleanField(
        default=False
    )

    is_active = models.BooleanField(
        default=True
    )

    features = models.JSONField(
        default=dict,
        blank=True
    )

    notes = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["price", "name"]

    def __str__(self):
        return self.name


class Subscription(models.Model):

    STATUS_CHOICES = [
        ("trial", "Trial"),
        ("active", "Active"),
        ("past_due", "Past Due"),
        ("suspended", "Suspended"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="subscriptions"
    )

    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="trial"
    )

    # Admin enters the starting date.
    start_date = models.DateTimeField(
        default=timezone.now
    )

    # System calculates this automatically
    # when a payment is applied.
    end_date = models.DateTimeField(
        blank=True,
        null=True
    )

    trial_end_date = models.DateTimeField(
        blank=True,
        null=True
    )

    auto_renew = models.BooleanField(
        default=False
    )

    cancelled_at = models.DateTimeField(
        blank=True,
        null=True
    )

    cancellation_reason = models.TextField(
        blank=True,
        null=True
    )

    notes = models.TextField(
        blank=True,
        null=True
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
        return f"{self.organization.name} - {self.plan.name}"


class Payment(models.Model):

    PAYMENT_METHOD_CHOICES = [
        ("bank_transfer", "Bank Transfer"),
        ("mobile_money", "Mobile Money"),
        ("cash", "Cash"),
        ("card", "Card"),
        ("cheque", "Cheque"),
        ("online", "Online Payment"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
        ("cancelled", "Cancelled"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="payments"
    )

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="payments"
    )

    # Actual amount paid by the customer.
    #
    # Example:
    # Plan price = TZS 50,000/month
    # Payment    = TZS 300,000
    # System calculates 6 billing periods.
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    currency = models.CharField(
        max_length=10,
        default="TZS"
    )

    payment_method = models.CharField(
        max_length=30,
        choices=PAYMENT_METHOD_CHOICES,
        default="bank_transfer"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="confirmed"
    )

    transaction_reference = models.CharField(
        max_length=200,
        blank=True,
        null=True
    )

    payment_date = models.DateTimeField(
        default=timezone.now
    )

    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="recorded_payments"
    )

    # --------------------------------------------------
    # SYSTEM-CALCULATED BILLING INFORMATION
    # --------------------------------------------------

    # Number of billing periods covered by this payment.
    #
    # Example:
    #
    # Plan = 50,000/month
    # Payment = 300,000
    #
    # periods_covered = 6
    #
    # Admin does NOT enter this value.
    periods_covered = models.PositiveIntegerField(
        blank=True,
        null=True,
        editable=False
    )

    # Date/time when the payment was actually
    # applied to the subscription.
    applied_at = models.DateTimeField(
        blank=True,
        null=True,
        editable=False
    )

    notes = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["-payment_date"]

    def __str__(self):
        return (
            f"{self.organization.name} - "
            f"{self.amount} {self.currency}"
        )
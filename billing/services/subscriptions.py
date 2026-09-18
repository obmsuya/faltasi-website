import calendar
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from billing.models import Subscription, Payment


# Number of calendar months in each billing interval.
BILLING_INTERVAL_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "semi_annual": 6,
    "annual": 12,
}


def add_months(value, months):
    """
    Add calendar months to a datetime.

    Example:
        17 September + 6 months
        = 17 March

    It also handles dates such as January 31 correctly.
    """

    month_index = value.month - 1 + months

    year = value.year + (month_index // 12)

    month = (month_index % 12) + 1

    last_day = calendar.monthrange(year, month)[1]

    day = min(value.day, last_day)

    return value.replace(
        year=year,
        month=month,
        day=day,
    )


def get_billing_interval_months(plan):
    """
    Return the number of months represented by
    the plan's billing interval.
    """

    return BILLING_INTERVAL_MONTHS.get(
        plan.billing_interval
    )


def calculate_periods_from_payment(payment):
    """
    Calculate how many billing periods a payment covers.

    Example:

        Plan price = 50,000 TZS/month
        Payment    = 300,000 TZS

        Result = 6 months
    """

    subscription = payment.subscription

    if subscription is None:
        raise ValueError(
            "This payment is not linked to a subscription."
        )

    plan = subscription.plan

    if plan.price <= 0:
        raise ValueError(
            "The subscription plan does not have a valid paid price."
        )

    if payment.amount <= 0:
        raise ValueError(
            "Payment amount must be greater than zero."
        )

    if payment.currency != plan.currency:
        raise ValueError(
            f"Payment currency ({payment.currency}) does not "
            f"match plan currency ({plan.currency})."
        )

    # One-time plans require full payment.
    if plan.billing_interval == "one_time":

        if payment.amount != plan.price:
            raise ValueError(
                "A one-time plan must be paid in full."
            )

        return 1

    # Calculate the number of periods.
    periods_decimal = payment.amount / plan.price

    # Payment must represent a complete number of periods.
    if periods_decimal != periods_decimal.to_integral_value():
        raise ValueError(
            f"Payment amount {payment.amount} is not an exact "
            f"multiple of the plan price {plan.price}."
        )

    periods = int(periods_decimal)

    if periods <= 0:
        raise ValueError(
            "Payment does not cover any billing period."
        )

    return periods


def calculate_end_date(start_date, plan, periods):
    """
    Calculate the subscription end date.

    Example:

        Start date = 17 September 2026
        Plan       = Monthly
        Periods    = 6

        End date   = 17 March 2027
    """

    if periods <= 0:
        raise ValueError(
            "Number of billing periods must be greater than zero."
        )

    # One-time plan.
    if plan.billing_interval == "one_time":

        return start_date + timedelta(
            days=plan.duration_days
        )

    interval_months = get_billing_interval_months(plan)

    if interval_months is None:
        raise ValueError(
            f"Unsupported billing interval: "
            f"{plan.billing_interval}"
        )

    total_months = interval_months * periods

    return add_months(
        start_date,
        total_months
    )


def get_current_subscription(organization):
    """
    Return the organization's current active/trial subscription.

    A subscription is considered current when:
        - status is trial or active
        - end_date is empty, or
        - end_date is still in the future
    """

    now = timezone.now()

    subscriptions = (
        Subscription.objects
        .filter(
            organization=organization,
            status__in=["trial", "active"],
        )
        .order_by(
            "-end_date",
            "-created_at",
        )
    )

    for subscription in subscriptions:

        if subscription.end_date is None:
            return subscription

        if subscription.end_date >= now:
            return subscription

    return None


def has_active_subscription(organization):
    """
    Check whether an organization has an active subscription.
    """

    return get_current_subscription(organization) is not None


@transaction.atomic
def apply_payment_to_subscription(payment):
    """
    Apply a confirmed payment to a subscription.

    The system will:

    1. Validate the payment.
    2. Calculate how many billing periods were purchased.
    3. Determine the correct starting point.
    4. Calculate the new end date.
    5. Activate the subscription.
    6. Record periods covered.
    7. Record when the payment was applied.

    IMPORTANT:

    If the subscription is still active, the new payment
    is added AFTER the existing end date.

    Example:

        Existing end:
        17 December 2026

        Payment:
        150,000 TZS

        Plan:
        50,000/month

        Periods:
        3

        New end:
        17 March 2027
    """

    # Lock the payment so it cannot be applied twice
    # simultaneously.
    payment = (
        Payment.objects
        .select_for_update()
        .select_related(
            "subscription",
            "subscription__plan",
            "organization",
        )
        .get(pk=payment.pk)
    )

    # Payment must be confirmed.
    if payment.status != "confirmed":
        raise ValueError(
            "Only confirmed payments can be applied."
        )

    # Payment must have a subscription.
    if payment.subscription is None:
        raise ValueError(
            "Payment must be linked to a subscription."
        )

    # Prevent double application.
    if payment.periods_covered is not None:
        raise ValueError(
            "This payment has already been applied "
            "to a subscription."
        )

    subscription = payment.subscription

    plan = subscription.plan

    # Make sure organization matches.
    if payment.organization_id != subscription.organization_id:
        raise ValueError(
            "Payment organization does not match "
            "subscription organization."
        )

    now = timezone.now()

    # Calculate purchased billing periods.
    periods = calculate_periods_from_payment(
        payment
    )

    # --------------------------------------------------
    # DETERMINE STARTING DATE
    # --------------------------------------------------

    if (
        subscription.status == "active"
        and subscription.end_date is not None
        and subscription.end_date > now
    ):
        # ACTIVE SUBSCRIPTION:
        #
        # Extend from the existing end date.
        #
        # This preserves all remaining paid time.
        calculation_start = subscription.end_date

    else:
        # NEW OR EXPIRED SUBSCRIPTION:
        #
        # Start from the subscription start date,
        # unless that date is already in the past.
        calculation_start = subscription.start_date

        if calculation_start < now:
            calculation_start = now

    # --------------------------------------------------
    # CALCULATE NEW END DATE
    # --------------------------------------------------

    new_end_date = calculate_end_date(
        calculation_start,
        plan,
        periods,
    )

    # --------------------------------------------------
    # UPDATE SUBSCRIPTION
    # --------------------------------------------------

    subscription.status = "active"

    # For a new or expired subscription, use the
    # calculation start as the new start date.
    if (
        subscription.end_date is None
        or subscription.end_date <= now
        or subscription.status != "active"
    ):
        subscription.start_date = calculation_start

    subscription.end_date = new_end_date

    subscription.save(
        update_fields=[
            "status",
            "start_date",
            "end_date",
            "updated_at",
        ]
    )

    # --------------------------------------------------
    # UPDATE PAYMENT
    # --------------------------------------------------

    payment.periods_covered = periods

    payment.applied_at = now

    payment.save(
        update_fields=[
            "periods_covered",
            "applied_at",
            "updated_at",
        ]
    )

    return subscription


@transaction.atomic
def activate_free_subscription(subscription):
    """
    Activate a free subscription.

    Free plans do not require a payment.
    """

    now = timezone.now()

    plan = subscription.plan

    if not plan.is_free:
        raise ValueError(
            "This subscription is not a free plan."
        )

    subscription.status = "active"

    # If the start date is in the past,
    # start the free subscription today.
    if subscription.start_date < now:
        subscription.start_date = now

    # One-time free plan.
    if plan.billing_interval == "one_time":

        subscription.end_date = (
            subscription.start_date
            + timedelta(
                days=plan.duration_days
            )
        )

    else:

        interval_months = get_billing_interval_months(
            plan
        )

        if interval_months is not None:

            subscription.end_date = add_months(
                subscription.start_date,
                interval_months
            )

        else:

            subscription.end_date = (
                subscription.start_date
                + timedelta(
                    days=plan.duration_days
                )
            )

    subscription.save()

    return subscription
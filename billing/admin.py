from django.contrib import admin, messages

from .models import (
    SubscriptionPlan,
    Subscription,
    Payment,
)

from .services.subscriptions import (
    apply_payment_to_subscription,
    activate_free_subscription,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "price",
        "currency",
        "billing_interval",
        "duration_days",
        "is_free",
        "is_active",
    )

    list_filter = (
        "billing_interval",
        "is_free",
        "is_active",
        "currency",
    )

    search_fields = (
        "name",
        "description",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):

    list_display = (
        "organization",
        "plan",
        "status",
        "start_date",
        "end_date",
        "auto_renew",
    )

    list_filter = (
        "status",
        "auto_renew",
        "plan",
    )

    search_fields = (
        "organization__name",
        "plan__name",
    )

    # End date is calculated by the system.
    readonly_fields = (
        "end_date",
        "created_at",
        "updated_at",
    )

    actions = [
        "activate_free",
    ]

    @admin.action(
        description="Activate selected free subscriptions"
    )
    def activate_free(self, request, queryset):

        success_count = 0

        for subscription in queryset:

            if not subscription.plan.is_free:

                self.message_user(
                    request,
                    (
                        f"{subscription} is not a free plan."
                    ),
                    level=messages.ERROR,
                )

                continue

            try:

                activate_free_subscription(
                    subscription
                )

                success_count += 1

            except Exception as e:

                self.message_user(
                    request,
                    (
                        f"Could not activate "
                        f"{subscription}: {e}"
                    ),
                    level=messages.ERROR,
                )

        if success_count:

            self.message_user(
                request,
                (
                    f"{success_count} free subscription(s) "
                    f"activated."
                ),
                level=messages.SUCCESS,
            )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):

    list_display = (
        "organization",
        "subscription",
        "amount",
        "currency",
        "payment_method",
        "status",
        "periods_covered",
        "payment_date",
        "applied_at",
        "recorded_by",
    )

    list_filter = (
        "payment_method",
        "status",
        "currency",
        "payment_date",
    )

    search_fields = (
        "organization__name",
        "transaction_reference",
        "notes",
        "recorded_by__username",
    )

    # These are calculated/system-controlled fields.
    readonly_fields = (
        "periods_covered",
        "applied_at",
        "recorded_by",
        "created_at",
        "updated_at",
    )

    actions = [
        "apply_selected_payments",
    ]

    def save_model(self, request, obj, form, change):
        """
        Automatically record the administrator who
        creates the payment.
        """

        if not obj.recorded_by:
            obj.recorded_by = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )

    @admin.action(
        description="Apply confirmed payments to subscriptions"
    )
    def apply_selected_payments(
        self,
        request,
        queryset,
    ):

        success_count = 0
        error_count = 0

        for payment in queryset:

            try:

                subscription = (
                    apply_payment_to_subscription(
                        payment
                    )
                )

                # Refresh the payment so we get the
                # calculated periods_covered and applied_at.
                payment.refresh_from_db()

                success_count += 1

                self.message_user(
                    request,
                    (
                        f"Payment #{payment.id} applied "
                        f"successfully. "
                        f"{payment.amount} "
                        f"{payment.currency} = "
                        f"{payment.periods_covered} "
                        f"billing period(s). "
                        f"New subscription end date: "
                        f"{subscription.end_date}"
                    ),
                    level=messages.SUCCESS,
                )

            except Exception as e:

                error_count += 1

                self.message_user(
                    request,
                    (
                        f"Payment #{payment.id} "
                        f"could not be applied: {e}"
                    ),
                    level=messages.ERROR,
                )

        if success_count:

            self.message_user(
                request,
                (
                    f"{success_count} payment(s) "
                    f"applied successfully."
                ),
                level=messages.SUCCESS,
            )

        if error_count:

            self.message_user(
                request,
                (
                    f"{error_count} payment(s) "
                    f"could not be applied."
                ),
                level=messages.ERROR,
            )
from django.contrib import admin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "customer_type",
        "company",
        "phone",
        "email",
        "country",
        "city",
        "preferred_contact_method",
        "status",
        "created_at",
    )

    list_filter = (
        "customer_type",
        "status",
        "preferred_contact_method",
        "country",
        "created_at",
    )

    search_fields = (
        "name",
        "company",
        "phone",
        "email",
        "city",
        "country",
    )

    ordering = (
        "-created_at",
    )
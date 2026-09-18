from django.contrib import admin

from .models import (
    Country,
    Organization,
    OrganizationMember,
)


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "code",
        "name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization_type",
        "country",
        "city",
        "status",
        "is_verified",
        "created_at",
    )

    list_filter = (
        "organization_type",
        "status",
        "is_verified",
        "country",
    )

    search_fields = (
        "name",
        "legal_name",
        "phone",
        "email",
        "city",
        "region",
    )

    prepopulated_fields = {
        "slug": ("name",),
    }

    readonly_fields = (
        "created_at",
        "updated_at",
        "suspended_at",
    )

    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "name",
                    "legal_name",
                    "organization_type",
                    "slug",
                )
            },
        ),
        (
            "Contact Information",
            {
                "fields": (
                    "phone",
                    "secondary_phone",
                    "email",
                    "secondary_email",
                    "website",
                )
            },
        ),
        (
            "Location",
            {
                "fields": (
                    "country",
                    "region",
                    "city",
                    "address",
                    "postal_code",
                )
            },
        ),
        (
            "Business Profile",
            {
                "fields": (
                    "industry",
                    "description",
                    "logo",
                )
            },
        ),
        (
            "Platform Status",
            {
                "fields": (
                    "status",
                    "is_verified",
                    "suspended_at",
                    "suspension_reason",
                )
            },
        ),
        (
            "Organization Settings",
            {
                "fields": (
                    "timezone",
                    "language",
                    "settings",
                )
            },
        ),
        (
            "Internal Information",
            {
                "fields": (
                    "notes",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


@admin.register(OrganizationMember)
class OrganizationMemberAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "user",
        "role",
        "is_active",
        "joined_at",
    )

    list_filter = (
        "role",
        "is_active",
        "organization",
    )

    search_fields = (
        "organization__name",
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
    )

    readonly_fields = (
        "joined_at",
        "updated_at",
    )
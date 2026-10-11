from django.contrib import admin

from .models import (
    Country,
    Organization,
    OrganizationMember,
    OrganizationOnboardingMessage,
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
        "created_at", "updated_at", "suspended_at", "created_by", "updated_by",
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


    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.organization_type == "platform_owner":
            for protected in ("status", "organization_type"):
                if protected not in fields:
                    fields.append(protected)
        elif obj and "organization_type" not in fields:
            fields.append("organization_type")
        return tuple(fields)

    def delete_queryset(self, request, queryset):
        # Keep the platform owner protected even from the bulk-delete action.
        queryset.exclude(organization_type="platform_owner").delete()

    def has_delete_permission(self, request, obj=None):
        if obj and obj.organization_type == "platform_owner":
            return False
        return super().has_delete_permission(request, obj)


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

@admin.register(OrganizationOnboardingMessage)
class OrganizationOnboardingMessageAdmin(admin.ModelAdmin):
    list_display = ("organization", "recipient_phone", "status", "attempt_number", "attempted_at", "provider_message_id")
    list_filter = ("status", "created_at")
    search_fields = ("organization__name", "recipient_phone", "provider_message_id", "error_message")
    readonly_fields = ("organization", "membership", "recipient_phone", "status", "attempt_number", "provider_message_id", "error_message", "attempted_at", "created_at")
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

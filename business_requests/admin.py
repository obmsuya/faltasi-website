from django.contrib import admin

from .models import (
    BusinessRequest,
    Department,
    DepartmentMember,
    RequestApproval,
    RequestAssignment,
    RequestCategory,
    RequestField,
    RequestNotification,
    StaffContact,
    WhatsAppAutomationSettings,
    WorkflowStep,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "organization", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("name", "organization__name")


@admin.register(DepartmentMember)
class DepartmentMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "department", "role", "is_active")
    list_filter = ("department__organization", "department", "role", "is_active")
    search_fields = ("user__username", "user__first_name", "user__last_name", "department__name")
    ordering = ("department", "user")


@admin.register(RequestCategory)
class RequestCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "organization", "department", "is_active")
    list_filter = ("organization", "department", "is_active")
    search_fields = ("name", "keywords", "description", "organization__name")


@admin.register(RequestField)
class RequestFieldAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "category", "field_type", "is_required", "order", "is_active")
    list_filter = ("category__organization", "field_type", "is_required", "is_active")
    search_fields = ("name", "display_label", "question", "category__name")
    ordering = ("category", "order", "id")
    fields = (
        "category", "name", "display_label", "question", "field_type",
        "is_required", "order", "is_active", "validation_rules",
        "retry_message_sw", "retry_message_en",
    )


@admin.register(BusinessRequest)
class BusinessRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "subject", "category", "department", "status", "priority", "source", "created_at", "completed_at")
    list_filter = ("status", "priority", "source", "category", "department")
    search_fields = ("subject", "request_text", "internal_notes", "customer__name", "customer__phone", "customer__company")
    ordering = ("-created_at",)


@admin.register(RequestAssignment)
class RequestAssignmentAdmin(admin.ModelAdmin):
    list_display = ("request", "assigned_to", "department", "is_current", "assigned_at")
    list_filter = ("department", "is_current")
    search_fields = ("request__subject", "assigned_to__username")


@admin.register(RequestApproval)
class RequestApprovalAdmin(admin.ModelAdmin):
    list_display = ("request", "requested_from", "status", "requested_at", "decided_at")
    list_filter = ("status",)


@admin.register(WorkflowStep)
class WorkflowStepAdmin(admin.ModelAdmin):
    list_display = ("request", "name", "step_order", "status", "assigned_to")
    list_filter = ("status",)


@admin.register(RequestNotification)
class RequestNotificationAdmin(admin.ModelAdmin):
    list_display = ("request", "recipient", "notification_type", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")


@admin.register(StaffContact)
class StaffContactAdmin(admin.ModelAdmin):
    list_display = ("user", "whatsapp_number", "updated_at")
    search_fields = ("user__username", "user__first_name", "user__last_name", "whatsapp_number")


@admin.register(WhatsAppAutomationSettings)
class WhatsAppAutomationSettingsAdmin(admin.ModelAdmin):
    list_display = ("organization", "default_language", "is_active", "updated_at")
    list_filter = ("default_language", "is_active")
    search_fields = ("organization__name",)
    readonly_fields = ("created_at", "updated_at")

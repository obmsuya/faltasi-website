from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import (
    Department,
    RequestCategory,
    RequestField,
    BusinessRequest,
    RequestAssignment,
    RequestApproval,
    WorkflowStep,
    RequestNotification,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
        "created_at",
    )

    search_fields = (
        "name",
        "description",
    )

    ordering = (
        "name",
    )


@admin.register(RequestCategory)
class RequestCategoryAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "department",
        "is_active",
        "created_at",
    )

    list_filter = (
        "department",
        "is_active",
        "created_at",
    )

    search_fields = (
        "name",
        "description",
    )

    ordering = (
        "name",
    )


@admin.register(BusinessRequest)
class BusinessRequestAdmin(admin.ModelAdmin):

    list_display = (
        "subject",
        "customer",
        "category",
        "department",
        "status",
        "priority",
        "source",
        "created_at",
    )

    list_filter = (
        "status",
        "priority",
        "source",
        "department",
        "category",
        "created_at",
    )

    search_fields = (
        "subject",
        "request_text",
        "customer__name",
        "customer__company",
        "customer__phone",
        "customer__email",
    )

    ordering = (
        "-created_at",
    )


@admin.register(RequestAssignment)
class RequestAssignmentAdmin(admin.ModelAdmin):

    list_display = (
        "request",
        "assigned_to",
        "department",
        "is_current",
        "assigned_at",
    )

    list_filter = (
        "department",
        "is_current",
        "assigned_at",
    )

    search_fields = (
        "request__subject",
        "request__request_text",
        "assigned_to__username",
    )

    ordering = (
        "-assigned_at",
    )


@admin.register(RequestApproval)
class RequestApprovalAdmin(admin.ModelAdmin):

    list_display = (
        "request",
        "requested_from",
        "status",
        "requested_at",
        "decided_at",
    )

    list_filter = (
        "status",
        "requested_at",
        "decided_at",
    )

    search_fields = (
        "request__subject",
        "requested_from__username",
    )

    ordering = (
        "-requested_at",
    )


@admin.register(WorkflowStep)
class WorkflowStepAdmin(admin.ModelAdmin):

    list_display = (
        "request",
        "name",
        "step_order",
        "status",
        "assigned_to",
        "created_at",
    )

    list_filter = (
        "status",
        "assigned_to",
        "created_at",
    )

    search_fields = (
        "request__subject",
        "name",
        "description",
        "assigned_to__username",
    )

    ordering = (
        "request",
        "step_order",
    )


@admin.register(RequestNotification)
class RequestNotificationAdmin(admin.ModelAdmin):

    list_display = (
        "title",
        "recipient",
        "request",
        "notification_type",
        "is_read",
        "created_at",
    )

    list_filter = (
        "notification_type",
        "is_read",
        "created_at",
    )

    search_fields = (
        "title",
        "message",
        "recipient__username",
        "request__subject",
    )

    ordering = (
        "-created_at",
    )

@admin.register(RequestField)
class RequestFieldAdmin(admin.ModelAdmin):
    list_display = (
        "category",
        "name",
        "question",
        "field_type",
        "is_required",
        "order",
        "is_active",
    )
    list_filter = (
        "category",
        "field_type",
        "is_required",
        "is_active",
    )
    search_fields = (
        "name",
        "question",
        "category__name",
    )
    ordering = (
        "category",
        "order",
    )
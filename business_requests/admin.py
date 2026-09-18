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
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(RequestCategory)
class RequestCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "department")
    search_fields = ("name", "keywords", "description")
    list_filter = ("department",)


@admin.register(RequestField)
class RequestFieldAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "category",
        "field_type",
        "is_required",
        "order",
        "is_active",
    )
    list_filter = (
        "field_type",
        "is_required",
        "is_active",
    )
    search_fields = (
        "name",
        "question",
        "category__name",
    )
    ordering = ("category", "order", "id")


@admin.register(BusinessRequest)
class BusinessRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "subject",
        "category",
        "department",
        "status",
        "priority",
        "source",
        "created_at",
        "completed_at",
    )

    list_filter = (
        "status",
        "priority",
        "source",
        "category",
        "department",
    )

    search_fields = (
        "subject",
        "request_text",
        "internal_notes",
        "customer__name",
        "customer__phone",
        "customer__company",
    )

    ordering = ("-created_at",)


@admin.register(RequestAssignment)
class RequestAssignmentAdmin(admin.ModelAdmin):
    pass


@admin.register(RequestApproval)
class RequestApprovalAdmin(admin.ModelAdmin):
    pass


@admin.register(WorkflowStep)
class WorkflowStepAdmin(admin.ModelAdmin):
    pass


@admin.register(RequestNotification)
class RequestNotificationAdmin(admin.ModelAdmin):
    pass
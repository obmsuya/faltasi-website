from django.db import models
from django.contrib.auth.models import User
from customers.models import Customer


# =========================================================
# DEPARTMENT
# =========================================================

class Department(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="departments",
    )

    name = models.CharField(max_length=150)

    description = models.TextField(
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
        ordering = ["organization__name", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_department_per_organization",
            )
        ]

    def __str__(self):
        return f"{self.organization.name} - {self.name}"

class DepartmentMember(models.Model):
    ROLE_CHOICES = [
        ("manager", "Manager"),
        ("agent", "Agent"),
        ("staff", "Staff"),
        ("viewer", "Viewer"),
    ]

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="members",
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="department_memberships",
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="staff",
    )

    is_active = models.BooleanField(default=True)

    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["department__name", "user__username"]

        constraints = [
            models.UniqueConstraint(
                fields=["department", "user"],
                name="unique_department_member",
            )
        ]

    def __str__(self):
        return (
            f"{self.department.name} - "
            f"{self.user.get_full_name() or self.user.username}"
        )
# =========================================================
# REQUEST CATEGORY
# =========================================================

class RequestCategory(models.Model):

    name = models.CharField(
        max_length=150,
        unique=True
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    keywords = models.TextField(
        blank=True,
        null=True,
        help_text="Enter keywords separated by commas."
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_categories"
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.name


# =========================================================
# REQUEST FIELD
# =========================================================

class RequestField(models.Model):
    """
    Defines information that may need to be
    collected for a particular request category.
    """

    FIELD_TYPE_CHOICES = [
        ("text", "Text"),
        ("number", "Number"),
        ("yes_no", "Yes / No"),
        ("choice", "Choice"),
    ]

    category = models.ForeignKey(
        RequestCategory,
        on_delete=models.CASCADE,
        related_name="request_fields"
    )

    name = models.CharField(
        max_length=150,
        help_text="Internal name, e.g. location or number_of_cameras."
    )

    question = models.CharField(
        max_length=255,
        help_text="Question that WhatsApp should ask the customer."
    )

    field_type = models.CharField(
        max_length=20,
        choices=FIELD_TYPE_CHOICES,
        default="text"
    )

    is_required = models.BooleanField(
        default=True
    )

    order = models.PositiveIntegerField(
        default=1,
        help_text="Order in which this information should be collected."
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["category", "order", "id"]

    def __str__(self):
        return f"{self.category.name} - {self.name}"


# =========================================================
# BUSINESS REQUEST
# =========================================================

class BusinessRequest(models.Model):

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    STATUS_CHOICES = [
        ("new", "New"),
        ("in_progress", "In Progress"),
        ("waiting_customer", "Waiting for Customer"),
        ("waiting_approval", "Waiting for Approval"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    # ---------------------------------------------------------
    # PRIORITY
    # ---------------------------------------------------------

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("urgent", "Urgent"),
    ]

    # ---------------------------------------------------------
    # SOURCE
    # ---------------------------------------------------------

    SOURCE_CHOICES = [
        ("whatsapp", "WhatsApp"),
        ("website", "Website"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("walk_in", "Walk-in"),
        ("staff", "Staff Entry"),
        ("other", "Other"),
    ]

    # ---------------------------------------------------------
    # CUSTOMER
    # ---------------------------------------------------------

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="business_requests"
    )

    # ---------------------------------------------------------
    # CUSTOMER'S ORIGINAL REQUEST
    # ---------------------------------------------------------

    request_text = models.TextField(
        help_text="The customer's original request in their own words."
    )

    # ---------------------------------------------------------
    # INTERNAL REQUEST INFORMATION
    # ---------------------------------------------------------

    subject = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    category = models.ForeignKey(
        RequestCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_requests"
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_requests"
    )

    # ---------------------------------------------------------
    # MANAGEMENT
    # ---------------------------------------------------------

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="new"
    )

    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default="normal"
    )

    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default="website"
    )

    # ---------------------------------------------------------
    # INTERNAL NOTES
    # ---------------------------------------------------------

    internal_notes = models.TextField(
        blank=True,
        null=True
    )

    # ---------------------------------------------------------
    # DATES
    # ---------------------------------------------------------

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    completed_at = models.DateTimeField(
        blank=True,
        null=True
    )

    def __str__(self):
        return self.subject or self.request_text[:60]


# =========================================================
# REQUEST ASSIGNMENT
# =========================================================

class RequestAssignment(models.Model):

    request = models.ForeignKey(
        BusinessRequest,
        on_delete=models.CASCADE,
        related_name="assignments"
    )

    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_request_assignments"
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments"
    )

    is_current = models.BooleanField(
        default=True
    )

    notes = models.TextField(
        blank=True,
        null=True
    )

    assigned_at = models.DateTimeField(
        auto_now_add=True
    )

    completed_at = models.DateTimeField(
        blank=True,
        null=True
    )

    def __str__(self):
        return f"{self.request} - Assignment"


# =========================================================
# REQUEST APPROVAL
# =========================================================

class RequestApproval(models.Model):

    APPROVAL_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    request = models.ForeignKey(
        BusinessRequest,
        on_delete=models.CASCADE,
        related_name="approvals"
    )

    requested_from = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_approvals"
    )

    status = models.CharField(
        max_length=20,
        choices=APPROVAL_STATUS_CHOICES,
        default="pending"
    )

    reason = models.TextField(
        blank=True,
        null=True
    )

    decision_notes = models.TextField(
        blank=True,
        null=True
    )

    requested_at = models.DateTimeField(
        auto_now_add=True
    )

    decided_at = models.DateTimeField(
        blank=True,
        null=True
    )

    def __str__(self):
        return f"{self.request} - {self.status}"


# =========================================================
# WORKFLOW STEP
# =========================================================

class WorkflowStep(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("skipped", "Skipped"),
    ]

    request = models.ForeignKey(
        BusinessRequest,
        on_delete=models.CASCADE,
        related_name="workflow_steps"
    )

    name = models.CharField(
        max_length=150
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    step_order = models.PositiveIntegerField(
        default=1
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_steps"
    )

    started_at = models.DateTimeField(
        blank=True,
        null=True
    )

    completed_at = models.DateTimeField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.request} - {self.name}"


# =========================================================
# REQUEST NOTIFICATION
# =========================================================

class RequestNotification(models.Model):

    NOTIFICATION_TYPE_CHOICES = [
        ("assignment", "Assignment"),
        ("approval", "Approval"),
        ("workflow", "Workflow"),
        ("status", "Status"),
        ("general", "General"),
    ]

    request = models.ForeignKey(
        BusinessRequest,
        on_delete=models.CASCADE,
        related_name="notifications"
    )

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="request_notifications"
    )

    notification_type = models.CharField(
        max_length=30,
        choices=NOTIFICATION_TYPE_CHOICES,
        default="general"
    )

    title = models.CharField(
        max_length=255
    )

    message = models.TextField()

    is_read = models.BooleanField(
        default=False
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    read_at = models.DateTimeField(
        blank=True,
        null=True
    )

    def __str__(self):
        return self.title
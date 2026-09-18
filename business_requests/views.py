from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.db import transaction



from .models import (
    Department,
    DepartmentMember,
    BusinessRequest,
    RequestAssignment,
    WorkflowStep,
)

def get_user_organization(user):
    """
    Return the active organization for a normal user.

    Superusers are handled separately because they are
    platform administrators.
    """

    membership = (
        user.organization_memberships
        .filter(is_active=True)
        .select_related("organization")
        .first()
    )

    if membership:
        return membership.organization

    return None

@login_required
def request_dashboard(request):
    """
    Main internal dashboard for business requests.
    """

    requests = (
        BusinessRequest.objects
        .select_related(
            "customer",
            "customer__organization",
            "category",
            "department",
        )
        .prefetch_related(
            "assignments__assigned_to",
            "workflow_steps__assigned_to",
        )
        .order_by("-created_at")
    )

    # Platform administrators can see all requests.
    # Normal users can only see requests belonging
    # to their organization.

    if not request.user.is_superuser:

        membership = (
            request.user
            .organization_memberships
            .filter(is_active=True)
            .select_related("organization")
            .first()
        )

        if membership:
            requests = requests.filter(
                customer__organization=membership.organization
            )
        else:
            requests = requests.none()

    # Optional filters
    status = request.GET.get("status")
    department_id = request.GET.get("department")

    if status:
        requests = requests.filter(status=status)

    if department_id:
        requests = requests.filter(
            department_id=department_id
        )

    departments = (
        BusinessRequest.objects
        .exclude(department=None)
        .values(
            "department_id",
            "department__name",
        )
        .distinct()
        .order_by("department__name")
    )

    context = {
        "requests": requests,
        "departments": departments,
        "selected_status": status,
        "selected_department": department_id,
        "status_choices": BusinessRequest.STATUS_CHOICES,
    }

    return render(
        request,
        "business_requests/dashboard.html",
        context,
    )


@login_required
def request_detail(request, request_id):
    """
    Display one business request and its workflow.

    Superusers can view requests from all organizations.

    Normal users can only view requests belonging to
    their active organization.
    """

    # ---------------------------------------------------------
    # GET BUSINESS REQUEST
    # ---------------------------------------------------------

    if request.user.is_superuser:

        # Platform administrators can view all requests.
        business_request = get_object_or_404(
            BusinessRequest.objects
            .select_related(
                "customer",
                "customer__organization",
                "category",
                "department",
            )
            .prefetch_related(
                "assignments__assigned_to",
                "workflow_steps__assigned_to",
            ),
            id=request_id,
        )

    else:

        # Normal users must belong to an organization.
        organization = get_user_organization(request.user)

        if not organization:
            messages.error(
                request,
                "You are not assigned to an organization.",
            )

            return redirect(
                "business_requests:dashboard"
            )

        # Only allow access to requests belonging
        # to the user's organization.
        business_request = get_object_or_404(
            BusinessRequest.objects
            .select_related(
                "customer",
                "customer__organization",
                "category",
                "department",
            )
            .prefetch_related(
                "assignments__assigned_to",
                "workflow_steps__assigned_to",
            ),
            id=request_id,
            customer__organization=organization,
        )

    # ---------------------------------------------------------
    # STAFF AVAILABLE FOR THIS REQUEST
    # ---------------------------------------------------------

    if business_request.department:

        staff_users = (
            User.objects
            .filter(
                department_memberships__department=business_request.department,
                department_memberships__is_active=True,
                is_active=True,
            )
            .distinct()
            .order_by(
                "first_name",
                "last_name",
                "username",
            )
        )

    else:

        # No department means there are no department
        # staff members available for assignment.
        staff_users = User.objects.none()

    # ---------------------------------------------------------
    # CURRENT ASSIGNMENT
    # ---------------------------------------------------------

    current_assignment = (
        business_request.assignments
        .filter(
            is_current=True
        )
        .select_related(
            "assigned_to",
            "department",
        )
        .first()
    )

    # ---------------------------------------------------------
    # WORKFLOW
    # ---------------------------------------------------------

    workflow_steps = (
        business_request.workflow_steps
        .select_related("assigned_to")
        .order_by("step_order", "id")
    )

    # ---------------------------------------------------------
    # CONTEXT
    # ---------------------------------------------------------

    context = {
        "business_request": business_request,
        "staff_users": staff_users,
        "current_assignment": current_assignment,
        "workflow_steps": workflow_steps,
    }

    return render(
        request,
        "business_requests/request_detail.html",
        context,
    )
@login_required
@transaction.atomic
def assign_request(request, request_id):
    """
    Assign a business request to an active staff member
    belonging to the request's department.

    Superusers can manage requests across organizations.

    Normal users can only assign requests belonging to
    their own organization.
    """

    # ---------------------------------------------------------
    # ONLY POST IS ALLOWED
    # ---------------------------------------------------------

    if request.method != "POST":
        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    # ---------------------------------------------------------
    # GET REQUEST WITH ORGANIZATION SECURITY
    # ---------------------------------------------------------

    if request.user.is_superuser:

        # Platform administrator
        business_request = get_object_or_404(
            BusinessRequest,
            id=request_id,
        )

    else:

        # Normal user must belong to an organization.
        organization = get_user_organization(request.user)

        if not organization:
            messages.error(
                request,
                "You are not assigned to an organization.",
            )

            return redirect(
                "business_requests:dashboard"
            )

        # Make sure this request belongs to the
        # user's organization.
        business_request = get_object_or_404(
            BusinessRequest,
            id=request_id,
            customer__organization=organization,
        )

    # ---------------------------------------------------------
    # CHECK DEPARTMENT
    # ---------------------------------------------------------

    if not business_request.department:

        messages.error(
            request,
            "This request does not have a department assigned.",
        )

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    # ---------------------------------------------------------
    # GET STAFF ID
    # ---------------------------------------------------------

    staff_id = request.POST.get("staff_id")

    if not staff_id:

        messages.error(
            request,
            "Please select a staff member.",
        )

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    # ---------------------------------------------------------
    # VALIDATE STAFF MEMBER
    # ---------------------------------------------------------
    #
    # The selected user must:
    #
    # 1. Exist
    # 2. Be active
    # 3. Belong to the request's department
    # 4. Have an active DepartmentMember record
    #
    # ---------------------------------------------------------

    staff_user = get_object_or_404(
        User,
        id=staff_id,
        is_active=True,
        department_memberships__department=business_request.department,
        department_memberships__is_active=True,
    )

    # ---------------------------------------------------------
    # CLOSE PREVIOUS CURRENT ASSIGNMENTS
    # ---------------------------------------------------------

    RequestAssignment.objects.filter(
        request=business_request,
        is_current=True,
    ).update(
        is_current=False,
    )

    # ---------------------------------------------------------
    # CREATE NEW ASSIGNMENT
    # ---------------------------------------------------------

    assignment = RequestAssignment.objects.create(
        request=business_request,
        assigned_to=staff_user,
        department=business_request.department,
        is_current=True,
        notes=(
            f"Assigned to "
            f"{staff_user.get_full_name() or staff_user.username} "
            f"by "
            f"{request.user.get_full_name() or request.user.username}."
        ),
    )

    # ---------------------------------------------------------
    # FIND ACTIVE WORKFLOW STEP
    # ---------------------------------------------------------

    workflow_step = (
        WorkflowStep.objects
        .filter(
            request=business_request,
            status="active",
        )
        .order_by(
            "step_order",
            "id",
        )
        .first()
    )

    # ---------------------------------------------------------
    # UPDATE EXISTING WORKFLOW STEP
    # ---------------------------------------------------------

    if workflow_step:

        workflow_step.assigned_to = staff_user

        workflow_step.save(
            update_fields=[
                "assigned_to",
            ]
        )

    # ---------------------------------------------------------
    # CREATE WORKFLOW STEP IF MISSING
    # ---------------------------------------------------------

    else:

        workflow_step = WorkflowStep.objects.create(
            request=business_request,
            name="Department Review",
            description=(
                "Review the customer's request and "
                "process the request."
            ),
            step_order=1,
            status="active",
            assigned_to=staff_user,
        )

    # ---------------------------------------------------------
    # UPDATE REQUEST STATUS
    # ---------------------------------------------------------

    business_request.status = "in_progress"

    business_request.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    # ---------------------------------------------------------
    # SUCCESS MESSAGE
    # ---------------------------------------------------------

    staff_name = (
        staff_user.get_full_name()
        or staff_user.username
    )

    messages.success(
        request,
        (
            f"Request #{business_request.id} has been "
            f"assigned to {staff_name}."
        ),
    )

    # ---------------------------------------------------------
    # RETURN TO REQUEST
    # ---------------------------------------------------------

    return redirect(
        "business_requests:request_detail",
        request_id=request_id,
    )

@login_required
def staff_management(request):
    """
    Staff management page.

    Superusers can manage departments and staff
    across all organizations.

    Normal users can only manage departments and
    staff belonging to their own organization.
    """

    if request.user.is_superuser:

        memberships = (
            DepartmentMember.objects
            .select_related(
                "user",
                "department",
                "department__organization",
            )
            .order_by(
                "department__organization__name",
                "department__name",
                "user__username",
            )
        )

        departments = (
            Department.objects
            .filter(is_active=True)
            .select_related("organization")
            .order_by(
                "organization__name",
                "name",
            )
        )

    else:

        organization = get_user_organization(request.user)

        if not organization:
            messages.error(
                request,
                "You are not assigned to an organization.",
            )

            return redirect(
                "business_requests:dashboard"
            )

        memberships = (
            DepartmentMember.objects
            .select_related(
                "user",
                "department",
                "department__organization",
            )
            .filter(
                department__organization=organization,
                is_active=True,
            )
            .order_by(
                "department__name",
                "user__username",
            )
        )

        departments = (
            Department.objects
            .filter(
                organization=organization,
                is_active=True,
            )
            .select_related("organization")
            .order_by("name")
        )

    users = (
        User.objects
        .filter(is_active=True)
        .order_by(
            "first_name",
            "last_name",
            "username",
        )
    )

    context = {
        "memberships": memberships,
        "departments": departments,
        "users": users,
    }

    return render(
        request,
        "business_requests/staff_management.html",
        context,
    )
@login_required
@transaction.atomic
def add_department_member(request):
    """
    Add an existing Django user to a department.

    A normal user can only add staff to departments
    belonging to their own organization.

    Superusers can manage departments across
    all organizations.
    """

    if request.method != "POST":
        return redirect(
            "business_requests:staff_management"
        )

    user_id = request.POST.get("user_id")
    department_id = request.POST.get("department_id")
    role = request.POST.get("role")

    if not user_id or not department_id or not role:
        messages.error(
            request,
            "Please provide the user, department and role.",
        )

        return redirect(
            "business_requests:staff_management"
        )

    valid_roles = {
        "manager",
        "agent",
        "staff",
        "viewer",
    }

    if role not in valid_roles:
        messages.error(
            request,
            "Invalid staff role.",
        )

        return redirect(
            "business_requests:staff_management"
        )

    staff_user = get_object_or_404(
        User,
        id=user_id,
        is_active=True,
    )

    if request.user.is_superuser:

        department = get_object_or_404(
            Department,
            id=department_id,
            is_active=True,
        )

    else:

        organization = get_user_organization(
            request.user
        )

        if not organization:
            messages.error(
                request,
                "You are not assigned to an organization.",
            )

            return redirect(
                "business_requests:staff_management"
            )

        department = get_object_or_404(
            Department,
            id=department_id,
            organization=organization,
            is_active=True,
        )

        # The user performing the action must be
        # a member of this department with an active
        # department membership.
        allowed = DepartmentMember.objects.filter(
            department=department,
            user=request.user,
            is_active=True,
        ).exists()

        if not allowed:
            messages.error(
                request,
                "You are not authorized to manage this department.",
            )

            return redirect(
                "business_requests:staff_management"
            )

    membership, created = (
        DepartmentMember.objects.get_or_create(
            department=department,
            user=staff_user,
            defaults={
                "role": role,
                "is_active": True,
            },
        )
    )

    if not created:

        membership.role = role
        membership.is_active = True

        membership.save(
            update_fields=[
                "role",
                "is_active",
                "updated_at",
            ]
        )

        messages.success(
            request,
            (
                f"{staff_user.get_full_name() or staff_user.username} "
                f"is already a member of {department.name}. "
                f"The membership has been updated."
            ),
        )

    else:

        messages.success(
            request,
            (
                f"{staff_user.get_full_name() or staff_user.username} "
                f"has been added to {department.name} "
                f"as {membership.get_role_display()}."
            ),
        )

    return redirect(
        "business_requests:staff_management"
    )
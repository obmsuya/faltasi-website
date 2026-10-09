from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.db import transaction

from organizations.models import (Country, Organization, OrganizationMember,)
from customers.models import Customer

from .models import (
    Department,
    DepartmentMember,
    BusinessRequest,
    RequestAssignment,
    WorkflowStep,
    StaffContact,
)
from django.contrib.auth import login
from django.core.mail import send_mail
from django.utils import timezone
from whatsapp.models import Conversation, Message, WhatsAppPhoneNumber
from whatsapp.views import send_whatsapp_message
from django.conf import settings



from django.contrib.admin.views.decorators import staff_member_required


from .forms import CategoryQuestionsUploadForm
from .excel_importer import import_categories_from_excel
from organizations.models import Organization

def is_platform_administrator(user):
    """
    Return True when the logged-in user is authorized
    as a Platform Administrator.

    A Platform Administrator belongs to the platform_owner
    organization and has an owner or admin role.
    """

    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    membership = (
        OrganizationMember.objects
        .select_related("organization")
        .filter(
            user=user,
            is_active=True,
            organization__organization_type="platform_owner",
            role__in=["owner", "admin"],
        )
        .first()
    )

    return membership is not None

def get_user_organization(user, request=None):
    """
    Return the organization that should be used for the current user.

    Platform administrators:
        Use the organization selected in the session.
        If none is selected, use the first active platform-owner
        organization.

    Normal users:
        Use their active organization membership.
    """

    # ---------------------------------------------------------
    # PLATFORM ADMINISTRATORS
    # ---------------------------------------------------------

    if user.is_superuser:

        # Check whether the administrator selected an organization
        if request:

            active_organization_id = request.session.get(
                "active_organization_id"
            )

            if active_organization_id:

                organization = (
                    Organization.objects
                    .filter(
                        id=active_organization_id,
                        status="active",
                    )
                    .first()
                )

                if organization:
                    return organization

                # Selected organization no longer exists/is inactive
                request.session.pop(
                    "active_organization_id",
                    None,
                )

        # Default organization
        return (
            Organization.objects
            .filter(
                organization_type="platform_owner",
                status="active",
            )
            .order_by("id")
            .first()
        )

    # ---------------------------------------------------------
    # NORMAL ORGANIZATION USERS
    # ---------------------------------------------------------

    membership = (
        user.organization_memberships
        .filter(
            is_active=True,
            organization__status="active",
        )
        .select_related("organization")
        .first()
    )

    if membership:
        return membership.organization

    return None

@login_required
def switch_organization(request):
    """
    Allow Platform Administrators to select which organization
    they are currently administering.
    """

    if not is_platform_administrator(request.user):

        messages.error(
            request,
            "You are not authorized to switch organizations.",
        )

        return redirect(
            "business_requests:dashboard"
        )

    organizations = (
        Organization.objects
        .filter(status="active")
        .order_by("name")
    )

    if request.method == "POST":

        organization_id = request.POST.get(
            "organization_id"
        )

        organization = get_object_or_404(
            Organization,
            id=organization_id,
            status="active",
        )

        request.session[
            "active_organization_id"
        ] = organization.id

        messages.success(
            request,
            f"Active organization changed to {organization.name}.",
        )

        return redirect(
            "business_requests:dashboard"
        )

    current_organization = get_user_organization(
        request.user,
        request=request,
    )

    return render(
        request,
        "business_requests/switch_organization.html",
        {
            "organizations": organizations,
            "current_organization": current_organization,
        },
    )


@login_required
def business_dashboard(request):
    """
    Main dashboard for an organization.

    Platform administrators:
        Use the organization selected in the session.

    Normal organization users:
        Use their active organization membership.
    """

    organization = get_user_organization(
        request.user,
        request=request,
    )

    if not organization:
        messages.error(
            request,
            "You are not assigned to an organization.",
        )
        return redirect("accounts:login")

    current_membership = (
        OrganizationMember.objects
        .filter(
            user_id=request.user.id,
            organization_id=organization.id,
            is_active=True,
        )
        .select_related("user", "organization")
        .first()
    )

    department_membership = (
        DepartmentMember.objects
        .filter(
            user=request.user,
            department__organization=organization,
            is_active=True,
        )
        .select_related("department")
        .first()
    )

    customer_count = (
        Customer.objects
        .filter(
            organization=organization,
        )
        .count()
    )

    request_count = (
        BusinessRequest.objects
        .filter(
            customer__organization=organization,
        )
        .count()
    )

    staff_count = (
        OrganizationMember.objects
        .filter(
            organization=organization,
            is_active=True,
        )
        .values("user")
        .distinct()
        .count()
    )

    department_count = (
        Department.objects
        .filter(
            organization=organization,
            is_active=True,
        )
        .count()
    )

    context = {
        "organization": organization,
        "customer_count": customer_count,
        "request_count": request_count,
        "staff_count": staff_count,
        "department_count": department_count,
        "current_membership": current_membership,
        "department_membership": department_membership,
    }

    return render(
        request,
        "business_requests/business_dashboard.html",
        context,
    )

@login_required
def request_dashboard(request):
    """
    Main internal dashboard for business requests.
    Users see requests belonging to their organization.
    """

    organization = get_user_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to a business organization."
        )
        return redirect("business_requests:business_dashboard")

    # ---------------------------------------------------------
    # REQUESTS FOR THIS ORGANIZATION
    # ---------------------------------------------------------

    requests = (
        BusinessRequest.objects
        .select_related(
            "customer",
            "customer__organization",
            "category",
            "department",
            "product",
        )
        .prefetch_related(
            "assignments__assigned_to",
            "workflow_steps__assigned_to",
        )
        .filter(
            customer__organization_id=organization.id
        )
        .order_by("-created_at")
    )

    # ---------------------------------------------------------
    # FILTERS
    # ---------------------------------------------------------

    status = request.GET.get("status", "").strip()
    department_id = request.GET.get("department", "").strip()
    request_type = request.GET.get("type", "").strip()

    if status:
        requests = requests.filter(status=status)

    if department_id:
        requests = requests.filter(
            department_id=department_id,
            department__organization_id=organization.id,
        )

    # General website inquiries have no product or category.
    if request_type == "general_inquiry":
        requests = requests.filter(
            source="website",
            product__isnull=True,
            category__isnull=True,
        )

    # Product quote requests have a product attached.
    elif request_type == "product_quote":
        requests = requests.filter(
            source="website",
            product__isnull=False,
        )

    # ---------------------------------------------------------
    # ORGANIZATION DEPARTMENTS
    # ---------------------------------------------------------

    departments = (
        Department.objects
        .filter(
            organization_id=organization.id,
            is_active=True,
        )
        .order_by("name")
    )

    # ---------------------------------------------------------
    # DASHBOARD CONTEXT
    # ---------------------------------------------------------

    context = {
        "organization": organization,
        "requests": requests,
        "departments": departments,
        "selected_status": status,
        "selected_department": department_id,
        "selected_type": request_type,
        "status_choices": BusinessRequest.STATUS_CHOICES,
    }

    return render(
        request,
        "business_requests/dashboard.html",
        context,
    )

@login_required
def my_requests(request):
    """
    Display business requests assigned to the currently logged-in staff member.

    Staff can only see requests:
    - assigned to them
    - belonging to their organization
    - through a current assignment
    """

    organization = get_user_organization(request.user,request=request,)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to a business organization."
        )
        return redirect(
            "business_requests:business_dashboard"
        )

    # ---------------------------------------------------------
    # REQUESTS CURRENTLY ASSIGNED TO THIS USER
    # ---------------------------------------------------------

    requests = (
        BusinessRequest.objects
        .select_related(
            "customer",
            "customer__organization",
            "department",
            "category",
        )
        .filter(
            customer__organization=organization,
            assignments__assigned_to=request.user,
            assignments__is_current=True,
        )
        .distinct()
        .order_by("-created_at")
    )

    # ---------------------------------------------------------
    # OPTIONAL STATUS FILTER
    # ---------------------------------------------------------

    status = request.GET.get("status", "").strip()

    if status:
        requests = requests.filter(
            status=status
        )

    # ---------------------------------------------------------
    # COUNTS
    # ---------------------------------------------------------

    all_count = (
        BusinessRequest.objects
        .filter(
            customer__organization=organization,
            assignments__assigned_to=request.user,
            assignments__is_current=True,
        )
        .distinct()
        .count()
    )

    new_count = (
        BusinessRequest.objects
        .filter(
            customer__organization=organization,
            assignments__assigned_to=request.user,
            assignments__is_current=True,
            status="new",
        )
        .distinct()
        .count()
    )

    in_progress_count = (
        BusinessRequest.objects
        .filter(
            customer__organization=organization,
            assignments__assigned_to=request.user,
            assignments__is_current=True,
            status="in_progress",
        )
        .distinct()
        .count()
    )

    completed_count = (
        BusinessRequest.objects
        .filter(
            customer__organization=organization,
            assignments__assigned_to=request.user,
            assignments__is_current=True,
            status="completed",
        )
        .distinct()
        .count()
    )

    context = {
        "organization": organization,
        "requests": requests,
        "selected_status": status,

        "all_count": all_count,
        "new_count": new_count,
        "in_progress_count": in_progress_count,
        "completed_count": completed_count,

        "status_choices": BusinessRequest.STATUS_CHOICES,
    }

    return render(
        request,
        "business_requests/my_requests.html",
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
        organization = get_user_organization(
            request.user,
            request=request,
        )

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
    # ACTIVE DEPARTMENTS FOR THIS REQUEST'S ORGANIZATION
    # ---------------------------------------------------------

    departments = (
        Department.objects
        .filter(
            organization=business_request.customer.organization,
            is_active=True,
        )
        .order_by("name")
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
        "status_choices": BusinessRequest.STATUS_CHOICES,
        "departments": departments,
    }

    return render(
        request,
        "business_requests/request_detail.html",
        context,
    )


@login_required
@transaction.atomic
def set_request_department(request, request_id):
    """Assign an active department to a request that has none."""

    if request.method != "POST":
        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    # Find the request within the user's organization.
    if request.user.is_superuser:
        business_request = get_object_or_404(
            BusinessRequest.objects.select_related(
                "customer__organization"
            ),
            id=request_id,
        )
    else:
        organization = get_user_organization(
            request.user,
            request=request,
        )

        if not organization:
            messages.error(
                request,
                "Your account is not connected to an organization.",
            )
            return redirect("business_requests:dashboard")

        business_request = get_object_or_404(
            BusinessRequest.objects.select_related(
                "customer__organization"
            ),
            id=request_id,
            customer__organization=organization,
        )

    organization = business_request.customer.organization

    # Only organization owners and admins may choose a department.
    if not request.user.is_superuser:
        permitted = OrganizationMember.objects.filter(
            organization=organization,
            user=request.user,
            is_active=True,
            role__in=["owner", "admin"],
        ).exists()

        if not permitted:
            messages.error(
                request,
                "You do not have permission to assign departments.",
            )
            return redirect(
                "business_requests:request_detail",
                request_id=request_id,
            )

    # Do not overwrite an existing department or assignment.
    if business_request.department_id:
        messages.error(
            request,
            "This request already has a department.",
        )
        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    if business_request.assignments.filter(is_current=True).exists():
        messages.error(
            request,
            "This request already has a current staff assignment.",
        )
        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    department_id = request.POST.get("department_id", "").strip()

    if not department_id.isdigit():
        messages.error(request, "Please select a valid department.")
        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    department = get_object_or_404(
        Department,
        id=int(department_id),
        organization=organization,
        is_active=True,
    )

    business_request.department = department
    business_request.save(update_fields=["department", "updated_at"])

    messages.success(
        request,
        f"Department assigned: {department.name}. "
        "You can now assign this request to a staff member.",
    )

    return redirect(
        "business_requests:request_detail",
        request_id=request_id,
    )



@login_required
@transaction.atomic
def update_request(request, request_id):
    """
    Update the status and internal notes of a business request.

    Users can only update requests belonging to their organization.
    Superusers can update requests across organizations.
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
    # GET BUSINESS REQUEST WITH ORGANIZATION SECURITY
    # ---------------------------------------------------------

    if request.user.is_superuser:

        business_request = get_object_or_404(
            BusinessRequest,
            id=request_id,
        )

    else:

        organization = get_user_organization(request.user, request=request)

        if not organization:
            messages.error(
                request,
                "You are not assigned to an organization.",
            )

            return redirect(
                "business_requests:dashboard"
            )

        business_request = get_object_or_404(
            BusinessRequest,
            id=request_id,
            customer__organization=organization,
        )

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    status = request.POST.get("status", "").strip()

    valid_statuses = {
        value
        for value, label in BusinessRequest.STATUS_CHOICES
    }

    if status:

        if status not in valid_statuses:

            messages.error(
                request,
                "Invalid request status.",
            )

            return redirect(
                "business_requests:request_detail",
                request_id=request_id,
            )

        business_request.status = status

    # ---------------------------------------------------------
    # INTERNAL NOTES
    # ---------------------------------------------------------

    internal_notes = request.POST.get(
        "internal_notes"
    )

    if internal_notes is not None:
        business_request.internal_notes = internal_notes.strip()

    # ---------------------------------------------------------
    # COMPLETION DATE
    # ---------------------------------------------------------

    if status == "completed":

        if not business_request.completed_at:
            business_request.completed_at = timezone.now()

    else:

        business_request.completed_at = None

    # ---------------------------------------------------------
    # SAVE
    # ---------------------------------------------------------

    business_request.save(
        update_fields=[
            "status",
            "internal_notes",
            "completed_at",
            "updated_at",
        ]
    )

    # ---------------------------------------------------------
    # SUCCESS
    # ---------------------------------------------------------

    messages.success(
        request,
        f"Request #{business_request.id} has been updated successfully.",
    )

    return redirect(
        "business_requests:request_detail",
        request_id=request_id,
    )

@login_required
def send_request_whatsapp_message(request, request_id):
    """
    Send a WhatsApp message to the customer attached to a business request.

    The message is sent through the customer's existing WhatsApp conversation
    and the organization's configured WhatsApp connection.
    """

    print("====================================================")
    print("SEND REQUEST WHATSAPP VIEW STARTED")
    print("REQUEST ID:", request_id)
    print("HTTP METHOD:", request.method)
    print("USER:", request.user.username)
    print("====================================================")

    # =====================================================
    # CHECK REQUEST METHOD
    # =====================================================

    if request.method != "POST":

        print("INVALID METHOD:", request.method)

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    # =====================================================
    # GET BUSINESS REQUEST
    # =====================================================

    print("STEP 1: Getting business request...")

    if request.user.is_superuser:

        business_request = get_object_or_404(
            BusinessRequest.objects.select_related(
                "customer",
                "customer__organization",
            ),
            id=request_id,
        )

    else:

        organization = get_user_organization(request.user, request=request,)

        print(
            "USER ORGANIZATION:",
            organization,
        )

        if not organization:

            print(
                "ERROR: User is not connected to an organization."
            )

            messages.error(
                request,
                "Your account is not connected to an organization.",
            )

            return redirect(
                "business_requests:business_dashboard"
            )

        business_request = get_object_or_404(
            BusinessRequest.objects.select_related(
                "customer",
                "customer__organization",
            ),
            id=request_id,
            customer__organization=organization,
        )

    print(
        "BUSINESS REQUEST FOUND:",
        business_request.id,
    )

    print(
        "REQUEST SUBJECT:",
        business_request.subject,
    )

    # =====================================================
    # GET MESSAGE
    # =====================================================

    print("STEP 2: Reading WhatsApp message...")

    message_text = request.POST.get(
        "message",
        "",
    ).strip()

    print(
        "MESSAGE LENGTH:",
        len(message_text),
    )

    if not message_text:

        print(
            "ERROR: Empty WhatsApp message."
        )

        messages.error(
            request,
            "Please enter a message before sending.",
        )

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    # =====================================================
    # GET CUSTOMER
    # =====================================================

    print("STEP 3: Getting customer...")

    customer = business_request.customer

    print(
        "CUSTOMER:",
        customer,
    )

    if not customer:

        print(
            "ERROR: Business request has no customer."
        )

        messages.error(
            request,
            "This request does not have a customer.",
        )

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    print(
        "CUSTOMER NAME:",
        customer.name,
    )

    print(
        "CUSTOMER PHONE:",
        customer.phone,
    )

    print(
        "CUSTOMER ORGANIZATION:",
        customer.organization,
    )

    if not customer.phone:

        print(
            "ERROR: Customer has no phone number."
        )

        messages.error(
            request,
            "The customer does not have a WhatsApp phone number.",
        )

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    # =====================================================
    # FIND EXISTING WHATSAPP CONVERSATION
    # =====================================================

    print(
        "STEP 4: Searching for WhatsApp conversation..."
    )

    conversation = (
        Conversation.objects
        .select_related(
            "organization",
            "whatsapp_phone_number",
            "customer",
        )
        .filter(
            organization=customer.organization,
            customer=customer,
            phone_number=customer.phone,
            status="active",
        )
        .order_by(
            "-last_message_at",
            "-id",
        )
        .first()
    )

    print(
        "CONVERSATION RESULT:",
        conversation,
    )

    if not conversation:

        print("NO ACTIVE CONVERSATION FOUND.")
        print("STEP 5: Searching for WhatsApp phone number...")

        whatsapp_phone = (
            WhatsAppPhoneNumber.objects
            .select_related("whatsapp_business_account", "organization")
            .filter(
                organization=customer.organization,
                status="connected",
                is_active=True,
            )
            .order_by("-is_default", "id")
            .first()
        )

        print("WHATSAPP PHONE RESULT:", whatsapp_phone)

        # ---------------------------------------------------------
        # TEMPORARY DEVELOPMENT FALLBACK
        # ---------------------------------------------------------
        # If the business does not yet have its own WhatsApp
        # connection, temporarily use the platform owner's
        # connected WhatsApp phone during local development.
        #
        # This is enabled only when DEBUG=True.
        # It is NOT the production multi-tenant setup.
        # ---------------------------------------------------------
        if not whatsapp_phone and settings.DEBUG:

            fallback_phone_number_id = getattr(
                settings,
                "WHATSAPP_PHONE_NUMBER_ID",
                None,
            )

            if fallback_phone_number_id:
                whatsapp_phone = (
                    WhatsAppPhoneNumber.objects
                    .filter(
                        phone_number_id=fallback_phone_number_id,
                        organization__organization_type="platform_owner",
                        status="connected",
                        is_active=True,
                    )
                    .select_related(
                        "whatsapp_business_account",
                        "organization",
                    )
                    .first()
                )

                if whatsapp_phone:
                    print(
                        "TEMPORARY DEVELOPMENT FALLBACK ENABLED"
                    )
                    print(
                        "REQUEST ORGANIZATION:",
                        customer.organization.name,
                    )
                    print(
                        "WHATSAPP PHONE OWNER:",
                        whatsapp_phone.organization.name,
                    )

        print("FINAL WHATSAPP PHONE RESULT:", whatsapp_phone)

        if not whatsapp_phone:
            print("ERROR: No active WhatsApp phone number found.")
            messages.error(
                request,
                "No active WhatsApp phone number is connected to this business.",
            )
            return redirect(
                "business_requests:request_detail",
                request_id=request_id,
            )

        print("WHATSAPP PHONE:", whatsapp_phone.phone_number)
        print("PHONE NUMBER ID:", whatsapp_phone.phone_number_id)
        print("PHONE STATUS:", whatsapp_phone.status)

        conversation = Conversation.objects.create(
            organization=customer.organization,
            whatsapp_phone_number=whatsapp_phone,
            customer=customer,
            phone_number=customer.phone,
            business_request=business_request,
            status="active",
        )

        print("CONVERSATION CREATED:", conversation.id)

    else:
        print("EXISTING CONVERSATION FOUND:", conversation.id)

        if conversation.business_request_id != business_request.id:
            conversation.business_request = business_request
            conversation.save(
                update_fields=["business_request", "last_message_at"]
            )
            print("CONVERSATION LINKED TO REQUEST:", business_request.id)

    print("CONVERSATION ID:", conversation.id)

    print(
        "CONVERSATION PHONE:",
        conversation.phone_number,
    )

    print(
        "CONVERSATION STATUS:",
        conversation.status,
    )

    # =====================================================
    # GET WHATSAPP PHONE
    # =====================================================

    print(
        "STEP 5: Getting WhatsApp phone connection..."
    )

    whatsapp_phone = conversation.whatsapp_phone_number

    print(
        "WHATSAPP PHONE OBJECT:",
        whatsapp_phone,
    )

    if not whatsapp_phone:

        print(
            "ERROR: Conversation has no WhatsApp phone connection."
        )

        messages.error(
            request,
            "No WhatsApp phone number is connected to this conversation.",
        )

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    print(
        "WHATSAPP PHONE ID:",
        whatsapp_phone.id,
    )

    # =====================================================
    # SEND WHATSAPP MESSAGE
    # =====================================================

    print(
        "STEP 6: Calling send_whatsapp_message()..."
    )

    print(
        "RECIPIENT:",
        customer.phone,
    )

    print(
        "MESSAGE:",
        message_text,
    )

    try:

        response = send_whatsapp_message(
            whatsapp_phone,
            customer.phone,
            message_text,
        )

    except Exception as e:

        print(
            "===================================================="
        )
        print(
            "EXCEPTION INSIDE send_whatsapp_message()"
        )
        print(
            "ERROR TYPE:",
            type(e).__name__,
        )
        print(
            "ERROR:",
            str(e),
        )
        print(
            "===================================================="
        )

        messages.error(
            request,
            "An error occurred while sending the WhatsApp message.",
        )

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    print(
        "SEND WHATSAPP FUNCTION RETURNED:"
    )

    print(
        "RESPONSE:",
        response,
    )

    # =====================================================
    # CHECK WHATSAPP RESPONSE
    # =====================================================

    if response is None:

        print(
            "ERROR: send_whatsapp_message() returned None."
        )

        messages.error(
            request,
            "WhatsApp message could not be sent. Please check the WhatsApp connection.",
        )

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    print(
        "META RESPONSE STATUS:",
        response.status_code,
    )

    print(
        "META RESPONSE TEXT:",
        response.text,
    )

    # =====================================================
    # CHECK HTTP STATUS
    # =====================================================

    if response.status_code not in [200, 201]:

        try:

            response_data = response.json()

        except ValueError:

            response_data = {
                "raw_response": response.text,
            }

        print(
            "===================================================="
        )

        print(
            "REQUEST WHATSAPP SEND FAILED"
        )

        print(
            "STATUS:",
            response.status_code,
        )

        print(
            "RESPONSE:",
            response_data,
        )

        print(
            "===================================================="
        )

        messages.error(
            request,
            "WhatsApp rejected the message. Please check the WhatsApp connection and messaging window.",
        )

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    # =====================================================
    # READ META RESPONSE
    # =====================================================

    print(
        "STEP 7: Reading Meta response..."
    )

    try:

        response_data = response.json()

    except ValueError:

        response_data = {
            "raw_response": response.text,
        }

    print(
        "META RESPONSE DATA:",
        response_data,
    )

    # =====================================================
    # GET WHATSAPP MESSAGE ID
    # =====================================================

    whatsapp_message_id = None

    try:

        whatsapp_message_id = (
            response_data
            .get("messages", [{}])[0]
            .get("id")
        )

    except (
        IndexError,
        AttributeError,
        TypeError,
    ):

        whatsapp_message_id = None

    print(
        "WHATSAPP MESSAGE ID:",
        whatsapp_message_id,
    )

    # =====================================================
    # SAVE OUTGOING MESSAGE
    # =====================================================

    print(
        "STEP 8: Saving outgoing message to database..."
    )

    try:

        outgoing_message = Message.objects.create(
            organization=customer.organization,
            conversation=conversation,
            direction="outgoing",
            sender_type="agent",
            message_type="text",
            content=message_text,
            whatsapp_message_id=whatsapp_message_id,
            delivery_status="sent",
            metadata={
                "source": "business_request",
                "business_request_id": business_request.id,
                "sent_by_user_id": request.user.id,
                "sent_by_username": request.user.username,
                "whatsapp_response": response_data,
            },
        )

    except Exception as e:

        print(
            "===================================================="
        )

        print(
            "DATABASE ERROR WHILE SAVING MESSAGE"
        )

        print(
            "ERROR TYPE:",
            type(e).__name__,
        )

        print(
            "ERROR:",
            str(e),
        )

        print(
            "===================================================="
        )

        messages.error(
            request,
            "WhatsApp was sent, but the message could not be saved to the database.",
        )

        return redirect(
            "business_requests:request_detail",
            request_id=request_id,
        )

    print(
        "OUTGOING MESSAGE SAVED:",
        outgoing_message.id,
    )

    # =====================================================
    # UPDATE CONVERSATION ACTIVITY
    # =====================================================

    print(
        "STEP 9: Updating conversation activity..."
    )

    conversation.last_message_at = timezone.now()

    conversation.save(
        update_fields=[
            "last_message_at",
        ]
    )

    print(
        "CONVERSATION LAST MESSAGE UPDATED."
    )

    # =====================================================
    # SUCCESS
    # =====================================================

    print(
        "===================================================="
    )

    print(
        "REQUEST WHATSAPP MESSAGE SENT SUCCESSFULLY"
    )

    print(
        "REQUEST ID:",
        business_request.id,
    )

    print(
        "CUSTOMER:",
        customer.name,
    )

    print(
        "CUSTOMER PHONE:",
        customer.phone,
    )

    print(
        "WHATSAPP MESSAGE ID:",
        whatsapp_message_id,
    )

    print(
        "===================================================="
    )

    messages.success(
        request,
        "WhatsApp message sent successfully.",
    )

    return redirect(
        "business_requests:request_detail",
        request_id=request_id,
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
        organization = get_user_organization(request.user, request=request,)

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
    # WHATSAPP NOTIFICATION TO ASSIGNED STAFF
    # ---------------------------------------------------------

    staff_contact = StaffContact.objects.filter(
        user=staff_user
    ).first()

    if not staff_contact or not staff_contact.whatsapp_number.strip():
        messages.warning(
            request,
            (
                f"{staff_user.get_full_name() or staff_user.username} "
                "was assigned successfully, but no WhatsApp number is saved "
                "for this staff member. Add one in Staff Management to enable notifications."
            ),
        )
    else:
        organization = business_request.customer.organization
        whatsapp_phone = (
            WhatsAppPhoneNumber.objects
            .filter(
                organization=organization,
                status="connected",
                is_active=True,
            )
            .order_by("-is_default", "id")
            .first()
        )

        if not whatsapp_phone:
            messages.warning(
                request,
                (
                    "The request was assigned successfully, but this "
                    "organization has no active WhatsApp connection. "
                    "The staff member was not notified."
                ),
            )
        else:
            staff_name_for_message = (
                staff_user.get_full_name() or staff_user.username
            )
            request_subject = getattr(
                business_request,
                "subject",
                "",
            ) or f"Request #{business_request.id}"
            customer_name = (
                business_request.customer.name
                if business_request.customer_id
                else "Not provided"
            )
            customer_phone = (
                business_request.customer.phone
                if business_request.customer_id
                else "Not provided"
            )
            notification_text = (
                f"Hello {staff_name_for_message}, a business request "
                f"has been assigned to you.\n\n"
                f"Request: #{business_request.id}\n"
                f"Subject: {request_subject}\n"
                f"Department: {business_request.department.name}\n"
                f"Customer: {customer_name}\n"
                f"Customer phone: {customer_phone}\n\n"
                "Please open your business dashboard to review and process it."
            )

            try:
                whatsapp_response = send_whatsapp_message(
                    whatsapp_phone,
                    staff_contact.whatsapp_number.strip(),
                    notification_text,
                )

                if (
                    whatsapp_response is not None
                    and getattr(whatsapp_response, "status_code", None)
                    in (200, 201)
                ):
                    messages.success(
                        request,
                        f"WhatsApp notification sent to {staff_name_for_message}.",
                    )
                else:
                    response_status = getattr(
                        whatsapp_response,
                        "status_code",
                        "no response",
                    )
                    response_text = getattr(
                        whatsapp_response,
                        "text",
                        "",
                    )
                    print(
                        "STAFF WHATSAPP NOTIFICATION FAILED:",
                        response_status,
                        response_text,
                    )
                    messages.warning(
                        request,
                        (
                            "The request was assigned successfully, but "
                            "WhatsApp could not confirm delivery to the staff "
                            "member. Check the WhatsApp connection and Meta's "
                            "messaging-window/template requirements."
                        ),
                    )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "WhatsApp notification failed for request %s assigned to user %s",
                    business_request.id,
                    staff_user.id,
                )
                messages.warning(
                    request,
                    (
                        "The request was assigned successfully, but an error "
                        "occurred while notifying the staff member on WhatsApp."
                    ),
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
    User & Role Management for the current organization.
    Only Owners and Admins can manage organization users.
    """

    organization = get_user_organization(
        request.user,
        request=request,
    )

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an organization."
        )
        return redirect(
            "business_requests:business_dashboard"
        )

    # ---------------------------------------------------------
    # CHECK USER MANAGEMENT PERMISSION
    # ---------------------------------------------------------

    membership = (
        OrganizationMember.objects
        .filter(
            organization=organization,
            user=request.user,
            is_active=True,
        )
        .first()
    )

    # Superusers are allowed.
    # Organization Owners and Admins are allowed.
    # Everyone else is denied.
    if not request.user.is_superuser:

        if not membership or membership.role not in [
            "owner",
            "admin",
        ]:
            messages.error(
                request,
                "You do not have permission to manage users."
            )

            return redirect(
                "business_requests:business_dashboard"
            )

    # ---------------------------------------------------------
    # ORGANIZATION MEMBERS
    # ---------------------------------------------------------

    memberships = (
        OrganizationMember.objects
        .filter(
            organization=organization,
            
        )
        .select_related(
            "user",
            "organization",
        )
        .order_by("user__username")
    )

    # ---------------------------------------------------------
    # BUILD USER INFORMATION
    # ---------------------------------------------------------

    user_rows = []

    for member in memberships:

        department_membership = (
            DepartmentMember.objects
            .filter(
                user=member.user,
                department__organization=organization,
                is_active=True,
            )
            .select_related("department")
            .first()
        )

        user_rows.append({
            "membership": member,
            "user": member.user,
            "department_membership": department_membership,
            "staff_contact": StaffContact.objects.filter(
                user=member.user
            ).first(),
        })

    # ---------------------------------------------------------
    # DEPARTMENTS
    # ---------------------------------------------------------

    departments = (
        Department.objects
        .filter(
            organization=organization,
            is_active=True,
        )
        .order_by("name")
    )

    context = {
        "organization": organization,
        "user_rows": user_rows,
        "memberships": memberships,
        "departments": departments,
        "can_manage_users": True,
    }

    return render(
        request,
        "business_requests/staff.html",
        context,
    )
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render

from organizations.models import Organization, OrganizationMember
from business_requests.models import Department, DepartmentMember

User = get_user_model()


@login_required
def add_department_member(request):
    """
    Create a user for the current organization and assign
    an organization role and optional department role.
    """

    # ---------------------------------------------------------
    # DETERMINE ORGANIZATION
    # ---------------------------------------------------------

    organization = get_user_organization(
        request.user,
        request=request,
    )

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an organization."
        )

        return redirect(
            "business_requests:business_dashboard"
        )

    # ---------------------------------------------------------
    # CHECK PERMISSION
    # ---------------------------------------------------------

    membership = (
        OrganizationMember.objects
        .filter(
            organization=organization,
            user=request.user,
            is_active=True,
        )
        .first()
    )

    if not request.user.is_superuser:

        if not membership or membership.role not in [
            "owner",
            "admin",
        ]:
            messages.error(
                request,
                "You do not have permission to create users."
            )

            return redirect(
                "business_requests:staff_management"
            )

    # ---------------------------------------------------------
    # ORGANIZATION ROLES
    # ---------------------------------------------------------

    organization_roles = [
        (
            "admin",
            "Admin",
            "Full operational access, except ownership control.",
        ),
        (
            "manager",
            "Manager",
            "Manages day-to-day operations and assigned teams.",
        ),
        (
            "agent",
            "Agent",
            "Handles customers, requests and assigned work.",
        ),
        (
            "staff",
            "Staff",
            "Performs assigned operational duties.",
        ),
        (
            "viewer",
            "Viewer",
            "Read-only access to permitted information.",
        ),
    ]

    # ---------------------------------------------------------
    # DEPARTMENT ROLES
    # ---------------------------------------------------------

    department_roles = [
        ("manager", "Manager"),
        ("agent", "Agent"),
        ("staff", "Staff"),
        ("viewer", "Viewer"),
    ]

    # ---------------------------------------------------------
    # DEPARTMENTS
    # ---------------------------------------------------------

    departments = (
        Department.objects
        .filter(
            organization=organization,
            is_active=True,
        )
        .order_by("name")
    )

    # ---------------------------------------------------------
    # POST
    # ---------------------------------------------------------

    if request.method == "POST":

        username = request.POST.get(
            "username",
            "",
        ).strip()

        first_name = request.POST.get(
            "first_name",
            "",
        ).strip()

        last_name = request.POST.get(
            "last_name",
            "",
        ).strip()

        email = request.POST.get(
            "email",
            "",
        ).strip()

        whatsapp_number = request.POST.get(
            "whatsapp_number",
            "",
        ).strip()

        password = request.POST.get(
            "password",
            "",
        )

        password_confirm = request.POST.get(
            "password_confirm",
            "",
        )

        organization_role = request.POST.get(
            "organization_role",
            "staff",
        ).strip()

        department_id = request.POST.get(
            "department_id",
            "",
        ).strip()

        department_role = request.POST.get(
            "department_role",
            "",
        ).strip()

        errors = []

        # -----------------------------------------------------
        # VALIDATE ORGANIZATION ROLE
        # -----------------------------------------------------

        valid_organization_roles = {
            "admin",
            "manager",
            "agent",
            "staff",
            "viewer",
        }

        if organization_role not in valid_organization_roles:
            errors.append(
                "Please select a valid organization role."
            )

        # -----------------------------------------------------
        # VALIDATE BASIC INFORMATION
        # -----------------------------------------------------

        if not username:
            errors.append(
                "Username is required."
            )

        if not email:
            errors.append(
                "Email address is required."
            )

        if not password:
            errors.append(
                "Password is required."
            )
        elif len(password) < 8:
            errors.append(
                "Password must contain at least 8 characters."
            )

        if password != password_confirm:
            errors.append(
                "Passwords do not match."
            )

        # -----------------------------------------------------
        # USERNAME
        # -----------------------------------------------------

        if username and User.objects.filter(
            username__iexact=username
        ).exists():

            errors.append(
                "A user with this username already exists."
            )

        # -----------------------------------------------------
        # EMAIL
        # -----------------------------------------------------

        if email and User.objects.filter(
            email__iexact=email
        ).exists():

            errors.append(
                "A user with this email address already exists."
            )

        # -----------------------------------------------------
        # DEPARTMENT
        # -----------------------------------------------------

        department = None

        if department_id:

            try:

                department = Department.objects.get(
                    id=department_id,
                    organization=organization,
                    is_active=True,
                )

            except Department.DoesNotExist:

                errors.append(
                    "The selected department is invalid."
                )

        # -----------------------------------------------------
        # DEPARTMENT ROLE
        # -----------------------------------------------------

        valid_department_roles = {
            "manager",
            "agent",
            "staff",
            "viewer",
        }

        if department_id:

            if department_role not in valid_department_roles:

                errors.append(
                    "Please select a valid department role."
                )

        # -----------------------------------------------------
        # DEPARTMENT REQUIREMENT
        # -----------------------------------------------------

        # Operational roles should normally have a department.
        if organization_role in {
            "manager",
            "agent",
            "staff",
        } and not department:

            errors.append(
                "Please select a department for this organization role."
            )

        # -----------------------------------------------------
        # RETURN ERRORS
        # -----------------------------------------------------

        if errors:

            for error in errors:
                messages.error(request, error)

            context = {
                "organization": organization,
                "departments": departments,
                "organization_roles": organization_roles,
                "department_roles": department_roles,
                "form_data": request.POST,
            }

            return render(
                request,
                "business_requests/add_department_member.html",
                context,
            )

        # -----------------------------------------------------
        # CREATE USER
        # -----------------------------------------------------

        try:

            with transaction.atomic():

                new_user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )

                new_user.is_staff = False
                new_user.is_superuser = False
                new_user.is_active = True

                new_user.save(
                    update_fields=[
                        "is_staff",
                        "is_superuser",
                        "is_active",
                    ]
                )

                # ---------------------------------------------
                # ORGANIZATION MEMBERSHIP
                # ---------------------------------------------

                OrganizationMember.objects.create(
                    organization=organization,
                    user=new_user,
                    role=organization_role,
                    is_active=True,
                )

                # ---------------------------------------------
                # DEPARTMENT MEMBERSHIP
                # ---------------------------------------------

                if department:

                    DepartmentMember.objects.create(
                        department=department,
                        user=new_user,
                        role=department_role or "staff",
                        is_active=True,
                    )

                StaffContact.objects.update_or_create(
                    user=new_user,
                    defaults={
                        "whatsapp_number": whatsapp_number,
                    },
                )

        except Exception as e:

            messages.error(
                request,
                f"Unable to create user: {e}"
            )

            context = {
                "organization": organization,
                "departments": departments,
                "organization_roles": organization_roles,
                "department_roles": department_roles,
                "form_data": request.POST,
            }

            return render(
                request,
                "business_requests/add_department_member.html",
                context,
            )

        # -----------------------------------------------------
        # SUCCESS
        # -----------------------------------------------------

        messages.success(
            request,
            f"User {new_user.username} was created successfully."
        )

        return redirect(
            "business_requests:staff_management"
        )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    context = {
        "organization": organization,
        "departments": departments,
        "organization_roles": organization_roles,
        "department_roles": department_roles,
    }

    return render(
        request,
        "business_requests/add_department_member.html",
        context,
    )


@login_required
def edit_user(request, user_id):
    """
    Edit a user belonging to the current organization.

    Owners and Admins can edit organization users.
    The target user must belong to the current organization.
    """

    # ---------------------------------------------------------
    # DETERMINE CURRENT ORGANIZATION
    # ---------------------------------------------------------

    organization = get_user_organization(
        request.user,
        request=request,
    )

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an organization."
        )
        return redirect(
            "business_requests:business_dashboard"
        )

    # ---------------------------------------------------------
    # CHECK CURRENT USER PERMISSION
    # ---------------------------------------------------------

    current_membership = (
        OrganizationMember.objects
        .filter(
            organization=organization,
            user=request.user,
            is_active=True,
        )
        .first()
    )

    if not request.user.is_superuser:

        if not current_membership or current_membership.role not in [
            "owner",
            "admin",
        ]:
            messages.error(
                request,
                "You do not have permission to edit users."
            )

            return redirect(
                "business_requests:business_dashboard"
            )

    # ---------------------------------------------------------
    # GET TARGET USER'S ORGANIZATION MEMBERSHIP
    # ---------------------------------------------------------

    target_membership = get_object_or_404(
        OrganizationMember.objects.select_related("user"),
        organization=organization,
        user_id=user_id,
        is_active=True,
    )

    target_user = target_membership.user

    staff_contact = StaffContact.objects.filter(
        user=target_user
    ).first()

    # ---------------------------------------------------------
    # ORGANIZATION ROLES
    # ---------------------------------------------------------

    organization_roles = [
        (
            "admin",
            "Admin",
            "Full operational access, except ownership control.",
        ),
        (
            "manager",
            "Manager",
            "Manages day-to-day operations and assigned teams.",
        ),
        (
            "agent",
            "Agent",
            "Handles customers, requests and assigned work.",
        ),
        (
            "staff",
            "Staff",
            "Performs assigned operational duties.",
        ),
        (
            "viewer",
            "Viewer",
            "Read-only access to permitted information.",
        ),
    ]

    # ---------------------------------------------------------
    # DEPARTMENT ROLES
    # ---------------------------------------------------------

    department_roles = [
        ("manager", "Manager"),
        ("agent", "Agent"),
        ("staff", "Staff"),
        ("viewer", "Viewer"),
    ]

    # ---------------------------------------------------------
    # DEPARTMENTS
    # ---------------------------------------------------------

    departments = (
        Department.objects
        .filter(
            organization=organization,
            is_active=True,
        )
        .order_by("name")
    )

    # ---------------------------------------------------------
    # EXISTING DEPARTMENT MEMBERSHIP
    # ---------------------------------------------------------

    department_membership = (
        DepartmentMember.objects
        .filter(
            user=target_user,
            department__organization=organization,
            is_active=True,
        )
        .select_related("department")
        .first()
    )

    # ---------------------------------------------------------
    # POST
    # ---------------------------------------------------------

    if request.method == "POST":

        first_name = request.POST.get(
            "first_name",
            "",
        ).strip()

        last_name = request.POST.get(
            "last_name",
            "",
        ).strip()

        email = request.POST.get(
            "email",
            "",
        ).strip()

        whatsapp_number = request.POST.get(
            "whatsapp_number",
            "",
        ).strip()

        organization_role = request.POST.get(
            "organization_role",
            "",
        ).strip()

        department_id = request.POST.get(
            "department_id",
            "",
        ).strip()

        department_role = request.POST.get(
            "department_role",
            "",
        ).strip()

        errors = []

        # -----------------------------------------------------
        # VALIDATE ORGANIZATION ROLE
        # -----------------------------------------------------

        valid_organization_roles = {
            "admin",
            "manager",
            "agent",
            "staff",
            "viewer",
        }

        if organization_role not in valid_organization_roles:
            errors.append(
                "Please select a valid organization role."
            )

        # -----------------------------------------------------
        # OWNER PROTECTION
        # -----------------------------------------------------
        #
        # The normal edit form cannot change an Owner.
        # Ownership changes should be handled separately.
        #
        # -----------------------------------------------------

        if target_membership.role == "owner":

            if organization_role != "owner":
                errors.append(
                    "The organization Owner cannot be changed "
                    "from this page."
                )

        # -----------------------------------------------------
        # EMAIL
        # -----------------------------------------------------

        if not email:
            errors.append(
                "Email address is required."
            )

        elif User.objects.filter(
            email__iexact=email
        ).exclude(
            id=target_user.id
        ).exists():

            errors.append(
                "Another user already uses this email address."
            )

        # -----------------------------------------------------
        # DEPARTMENT
        # -----------------------------------------------------

        department = None

        if department_id:

            try:

                department = Department.objects.get(
                    id=department_id,
                    organization=organization,
                    is_active=True,
                )

            except Department.DoesNotExist:

                errors.append(
                    "The selected department is invalid."
                )

        # -----------------------------------------------------
        # DEPARTMENT ROLE
        # -----------------------------------------------------

        valid_department_roles = {
            "manager",
            "agent",
            "staff",
            "viewer",
        }

        if department_id:

            if department_role not in valid_department_roles:

                errors.append(
                    "Please select a valid department role."
                )

        # -----------------------------------------------------
        # OPERATIONAL ROLES REQUIRE DEPARTMENT
        # -----------------------------------------------------

        if organization_role in {
            "manager",
            "agent",
            "staff",
        }:

            if not department:

                errors.append(
                    "Please select a department for this "
                    "organization role."
                )

        # -----------------------------------------------------
        # PROTECT OWNER FROM BEING ASSIGNED A DEPARTMENT
        # -----------------------------------------------------

        if organization_role == "owner":

            department = None
            department_role = ""

        # -----------------------------------------------------
        # SAVE
        # -----------------------------------------------------

        if errors:

            for error in errors:
                messages.error(
                    request,
                    error,
                )

        else:

            try:

                with transaction.atomic():

                    # -----------------------------------------
                    # UPDATE USER
                    # -----------------------------------------

                    target_user.first_name = first_name
                    target_user.last_name = last_name
                    target_user.email = email

                    target_user.save(
                        update_fields=[
                            "first_name",
                            "last_name",
                            "email",
                        ]
                    )

                    StaffContact.objects.update_or_create(
                        user=target_user,
                        defaults={
                            "whatsapp_number": whatsapp_number,
                        },
                    )

                    # -----------------------------------------
                    # UPDATE ORGANIZATION ROLE
                    # -----------------------------------------

                    if target_membership.role != "owner":

                        target_membership.role = organization_role

                        target_membership.save(
                            update_fields=[
                                "role",
                                "updated_at",
                            ]
                        )

                    # -----------------------------------------
                    # REMOVE EXISTING DEPARTMENT MEMBERSHIP
                    # -----------------------------------------

                    DepartmentMember.objects.filter(
                        user=target_user,
                        department__organization=organization,
                    ).update(
                        is_active=False,
                    )

                    # -----------------------------------------
                    # CREATE / RESTORE DEPARTMENT MEMBERSHIP
                    # -----------------------------------------

                    if (
                        organization_role != "owner"
                        and department
                    ):

                        department_member = (
                            DepartmentMember.objects.filter(
                                department=department,
                                user=target_user,
                            ).first()
                        )

                        if department_member:

                            department_member.role = (
                                department_role or "staff"
                            )

                            department_member.is_active = True

                            department_member.save(
                                update_fields=[
                                    "role",
                                    "is_active",
                                    "updated_at",
                                ]
                            )

                        else:

                            DepartmentMember.objects.create(
                                department=department,
                                user=target_user,
                                role=(
                                    department_role
                                    or "staff"
                                ),
                                is_active=True,
                            )

                messages.success(
                    request,
                    (
                        f"User {target_user.username} "
                        f"was updated successfully."
                    ),
                )

                return redirect(
                    "business_requests:staff_management"
                )

            except Exception as exc:

                messages.error(
                    request,
                    f"Unable to update user: {exc}",
                )

    # ---------------------------------------------------------
    # TEMPLATE
    # ---------------------------------------------------------

    context = {
        "organization": organization,
        "target_user": target_user,
        "target_membership": target_membership,
        "department_membership": department_membership,
        "staff_contact": staff_contact,
        "departments": departments,
        "organization_roles": organization_roles,
        "department_roles": department_roles,
    }

    return render(
        request,
        "business_requests/edit_user.html",
        context,
    )

@login_required
def toggle_user_status(request, user_id):
    """
    Activate or deactivate a user's membership in the current organization.

    Owners and Admins can manage user status.
    Organization Owners cannot be deactivated from this page.
    """

    organization = get_user_organization(
        request.user,
        request=request,
    )

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an organization."
        )
        return redirect(
            "business_requests:business_dashboard"
        )

    # ---------------------------------------------------------
    # CHECK CURRENT USER PERMISSION
    # ---------------------------------------------------------

    current_membership = (
        OrganizationMember.objects
        .filter(
            organization=organization,
            user=request.user,
            is_active=True,
        )
        .first()
    )

    if not request.user.is_superuser:

        if not current_membership or current_membership.role not in [
            "owner",
            "admin",
        ]:
            messages.error(
                request,
                "You do not have permission to manage user status."
            )
            return redirect(
                "business_requests:business_dashboard"
            )

    # ---------------------------------------------------------
    # GET TARGET MEMBERSHIP
    # ---------------------------------------------------------

    target_membership = get_object_or_404(
        OrganizationMember.objects.select_related("user"),
        organization=organization,
        user_id=user_id,
    )

    target_user = target_membership.user

    # ---------------------------------------------------------
    # DO NOT ALLOW OWNER DEACTIVATION
    # ---------------------------------------------------------

    if target_membership.role == "owner":

        messages.error(
            request,
            "The organization Owner cannot be deactivated."
        )

        return redirect(
            "business_requests:staff_management"
        )

    # ---------------------------------------------------------
    # TOGGLE STATUS
    # ---------------------------------------------------------

    if target_membership.is_active:

        target_membership.is_active = False

        target_membership.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

        messages.success(
            request,
            f"{target_user.username} has been deactivated."
        )

    else:

        target_membership.is_active = True

        target_membership.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

        messages.success(
            request,
            f"{target_user.username} has been reactivated."
        )

    return redirect(
        "business_requests:staff_management"
    )
@transaction.atomic
def business_register(request):
    """
    Register a new business and create its owner account.

    Creates:
        1. Django User
        2. Organization
        3. OrganizationMember with Owner role
    """

    if request.method == "POST":

        business_name = request.POST.get(
            "business_name",
            ""
        ).strip()

        legal_name = request.POST.get(
            "legal_name",
            ""
        ).strip()

        email = request.POST.get(
            "email",
            ""
        ).strip()

        phone = request.POST.get(
            "phone",
            ""
        ).strip()

        country_id = request.POST.get(
            "country"
        )

        city = request.POST.get(
            "city",
            ""
        ).strip()

        industry = request.POST.get(
            "industry",
            ""
        ).strip()

        username = request.POST.get(
            "username",
            ""
        ).strip()

        password = request.POST.get(
            "password",
            ""
        )

        password_confirm = request.POST.get(
            "password_confirm",
            ""
        )

        # ---------------------------------------------
        # BASIC VALIDATION
        # ---------------------------------------------

        if not business_name:
            messages.error(
                request,
                "Business name is required.",
            )

            return redirect(
                "business_requests:business_register"
            )

        if not email:
            messages.error(
                request,
                "Email address is required.",
            )

            return redirect(
                "business_requests:business_register"
            )

        if not username:
            messages.error(
                request,
                "Username is required.",
            )

            return redirect(
                "business_requests:business_register"
            )

        if not password:
            messages.error(
                request,
                "Password is required.",
            )

            return redirect(
                "business_requests:business_register"
            )

        if password != password_confirm:
            messages.error(
                request,
                "Passwords do not match.",
            )

            return redirect(
                "business_requests:business_register"
            )

        # ---------------------------------------------
        # CHECK USERNAME
        # ---------------------------------------------

        if User.objects.filter(
            username__iexact=username
        ).exists():

            messages.error(
                request,
                "That username is already in use.",
            )

            return redirect(
                "business_requests:business_register"
            )

        # ---------------------------------------------
        # CHECK EMAIL
        # ---------------------------------------------

        if User.objects.filter(
            email__iexact=email
        ).exists():

            messages.error(
                request,
                "That email address is already registered.",
            )

            return redirect(
                "business_requests:business_register"
            )

        # ---------------------------------------------
        # COUNTRY
        # ---------------------------------------------

        country = None

        if country_id:

            country = get_object_or_404(
                Country,
                id=country_id,
                is_active=True,
            )

        # ---------------------------------------------
        # CREATE USER
        # ---------------------------------------------

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
        )

        # ---------------------------------------------
        # CREATE ORGANIZATION
        # ---------------------------------------------

        organization = Organization.objects.create(
            name=business_name,
            legal_name=legal_name or None,
            organization_type="business",
            phone=phone or None,
            email=email,
            country=country,
            city=city or None,
            industry=industry or None,
            status="active",
            is_verified=False,
        )

        # ---------------------------------------------
        # CREATE OWNER MEMBERSHIP
        # ---------------------------------------------

        OrganizationMember.objects.create(
            organization=organization,
            user=user,
            role="owner",
            is_active=True,
        )

        # ---------------------------------------------
        # LOG USER IN
        # ---------------------------------------------

        login(
            request,
            user,
        )

        messages.success(
            request,
            (
                f"Welcome to Faltasi, "
                f"{organization.name}."
            ),
        )

        return redirect(
            "business_requests:business_dashboard"
        )

    # ---------------------------------------------
    # GET REQUEST
    # ---------------------------------------------

    countries = (
        Country.objects
        .filter(is_active=True)
        .order_by("name")
    )

    context = {
        "countries": countries,
    }

    return render(
        request,
        "business_requests/business_register.html",
        context,
    )

@login_required
def business_profile(request):
    """
    Display and update the logged-in user's organization profile.
    """

    organization = get_user_organization(request.user, request=request,)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to a business organization."
        )
        return redirect("business_requests:business_dashboard")

    if request.method == "POST":
        organization.name = request.POST.get("name", "").strip()
        organization.legal_name = request.POST.get("legal_name", "").strip() or None
        organization.phone = request.POST.get("phone", "").strip() or None
        organization.secondary_phone = (
            request.POST.get("secondary_phone", "").strip() or None
        )
        organization.email = request.POST.get("email", "").strip() or None
        organization.secondary_email = (
            request.POST.get("secondary_email", "").strip() or None
        )
        organization.website = request.POST.get("website", "").strip() or None
        organization.region = request.POST.get("region", "").strip() or None
        organization.city = request.POST.get("city", "").strip() or None
        organization.address = request.POST.get("address", "").strip() or None
        organization.postal_code = (
            request.POST.get("postal_code", "").strip() or None
        )
        organization.industry = request.POST.get("industry", "").strip() or None
        organization.description = (
            request.POST.get("description", "").strip() or None
        )
        organization.timezone = (
            request.POST.get("timezone", "").strip() or None
        )
        organization.language = (
            request.POST.get("language", "").strip() or None
        )

        country_id = request.POST.get("country")

        if country_id:
            try:
                organization.country = Country.objects.get(
                    id=country_id,
                    is_active=True,
                )
            except Country.DoesNotExist:
                messages.error(request, "Selected country is invalid.")
                return redirect("business_requests:business_profile")
        else:
            organization.country = None

        if "logo" in request.FILES:
            organization.logo = request.FILES["logo"]

        if not organization.name:
            messages.error(request, "Business name is required.")
            return redirect("business_requests:business_profile")

        organization.save()

        messages.success(
            request,
            "Business profile updated successfully."
        )

        return redirect("business_requests:business_profile")

    countries = Country.objects.filter(
        is_active=True
    ).order_by("name")

    context = {
        "organization": organization,
        "countries": countries,
    }

    return render(
        request,
        "business_requests/business_profile.html",
        context,
    )

@login_required
def department_management(request):
    organization = get_user_organization(request.user, request=request,)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to a business organization."
        )
        return redirect("business_requests:business_dashboard")

    departments = Department.objects.filter(
        organization=organization
    ).order_by("name")

    return render(
        request,
        "business_requests/departments.html",
        {
            "organization": organization,
            "departments": departments,
        },
    )


@login_required
def department_add(request):
    """Create a department for the current organization."""

    organization = get_user_organization(request.user, request=request,)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to a business organization."
        )
        return redirect("business_requests:business_dashboard")

    membership = (
        OrganizationMember.objects
        .filter(
            organization=organization,
            user=request.user,
            is_active=True,
        )
        .first()
    )

    if not request.user.is_superuser:
        if not membership or membership.role not in ["owner", "admin"]:
            messages.error(
                request,
                "You do not have permission to add departments."
            )
            return redirect("business_requests:department_management")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()

        if not name:
            messages.error(
                request,
                "Department name is required."
            )

            return render(
                request,
                "business_requests/department_form.html",
                {
                    "organization": organization,
                    "department": None,
                    "form_title": "Add Department",
                },
            )

        if Department.objects.filter(
            organization=organization,
            name__iexact=name,
        ).exists():
            messages.error(
                request,
                f"A department named '{name}' already exists."
            )

            return render(
                request,
                "business_requests/department_form.html",
                {
                    "organization": organization,
                    "department": None,
                    "form_title": "Add Department",
                },
            )

        Department.objects.create(
            organization=organization,
            name=name,
            description=description,
            is_active=True,
        )

        messages.success(
            request,
            f"Department '{name}' was created successfully."
        )

        return redirect(
            "business_requests:department_management"
        )

    return render(
        request,
        "business_requests/department_form.html",
        {
            "organization": organization,
            "department": None,
            "form_title": "Add Department",
        },
    )


@login_required
def department_edit(request, department_id):
    """
    Edit a department belonging to the current organization.

    Only organization owners and administrators can edit departments.
    """

    print("\n========== DEPARTMENT EDIT DEBUG ==========")
    print("USER:", request.user.username)
    print("USER ID:", request.user.id)
    print("SUPERUSER:", request.user.is_superuser)
    print("DEPARTMENT ID:", department_id)

    # Show the user's organization memberships
    memberships_debug = list(
        request.user.organization_memberships.values(
            "organization_id",
            "organization__name",
            "role",
            "is_active",
        )
    )

    print("ORG MEMBERSHIPS:", memberships_debug)

    # ---------------------------------------------------------
    # STEP 1: Get the user's organization
    # ---------------------------------------------------------

    organization = get_user_organization(request.user, request=request,)

    print(
        "RESOLVED ORGANIZATION:",
        organization.id if organization else None,
    )

    print(
        "RESOLVED ORGANIZATION NAME:",
        organization.name if organization else None,
    )

    if not organization:
        print("RESULT: NO ORGANIZATION - REDIRECTING TO DASHBOARD")
        print("==========================================\n")

        messages.error(
            request,
            "Your account is not connected to a business organization."
        )

        return redirect(
            "business_requests:business_dashboard"
        )

    # ---------------------------------------------------------
    # STEP 2: Check organization membership
    # ---------------------------------------------------------

    membership = (
        OrganizationMember.objects
        .filter(
            organization=organization,
            user=request.user,
            is_active=True,
        )
        .first()
    )

    print(
        "MEMBERSHIP:",
        membership.id if membership else None,
    )

    print(
        "MEMBERSHIP ROLE:",
        membership.role if membership else None,
    )

    # ---------------------------------------------------------
    # STEP 3: Check permission
    # ---------------------------------------------------------

    if not request.user.is_superuser:

        if not membership:
            print("RESULT: NO ACTIVE MEMBERSHIP")
            print("REDIRECTING TO DEPARTMENTS")
            print("==========================================\n")

            messages.error(
                request,
                "You are not an active member of this organization."
            )

            return redirect(
                "business_requests:department_management"
            )

        if membership.role not in ["owner", "admin"]:
            print(
                "RESULT: INSUFFICIENT ROLE:",
                membership.role,
            )

            print("REDIRECTING TO DEPARTMENTS")
            print("==========================================\n")

            messages.error(
                request,
                "You do not have permission to edit departments."
            )

            return redirect(
                "business_requests:department_management"
            )

    # ---------------------------------------------------------
    # STEP 4: Get department
    # ---------------------------------------------------------

    department = get_object_or_404(
        Department,
        id=department_id,
        organization=organization,
    )

    print(
        "DEPARTMENT FOUND:",
        department.id,
        department.name,
    )

    # ---------------------------------------------------------
    # STEP 5: Handle form submission
    # ---------------------------------------------------------

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()

        print("POST NAME:", name)
        print("POST DESCRIPTION:", description)

        # Validate department name
        if not name:

            messages.error(
                request,
                "Department name is required."
            )

            return render(
                request,
                "business_requests/department_form.html",
                {
                    "organization": organization,
                    "department": department,
                    "form_title": "Edit Department",
                },
            )

        # -----------------------------------------------------
        # Prevent duplicate department names
        # -----------------------------------------------------

        duplicate = (
            Department.objects
            .filter(
                organization=organization,
                name__iexact=name,
            )
            .exclude(
                id=department.id
            )
            .exists()
        )

        if duplicate:

            messages.error(
                request,
                f"A department named '{name}' already exists."
            )

            return render(
                request,
                "business_requests/department_form.html",
                {
                    "organization": organization,
                    "department": department,
                    "form_title": "Edit Department",
                },
            )

        # -----------------------------------------------------
        # Update department
        # -----------------------------------------------------

        department.name = name
        department.description = description

        department.save()

        print(
            "DEPARTMENT UPDATED:",
            department.id,
            department.name,
        )

        messages.success(
            request,
            f"Department '{department.name}' was updated successfully."
        )

        print(
            "RESULT: SUCCESS - REDIRECTING TO DEPARTMENTS"
        )

        print("==========================================\n")

        return redirect(
            "business_requests:department_management"
        )

    # ---------------------------------------------------------
    # STEP 6: Display edit form
    # ---------------------------------------------------------

    print(
        "RESULT: DISPLAYING EDIT FORM"
    )

    print("==========================================\n")

    return render(
        request,
        "business_requests/department_form.html",
        {
            "organization": organization,
            "department": department,
            "form_title": "Edit Department",
        },
    )
@login_required
def department_toggle(request, department_id):
    """Activate or deactivate a department."""

    organization = get_user_organization(request.user, request=request,)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to a business organization."
        )
        return redirect("business_requests:business_dashboard")

    membership = (
        OrganizationMember.objects
        .filter(
            organization=organization,
            user=request.user,
            is_active=True,
        )
        .first()
    )

    if not request.user.is_superuser:
        if not membership or membership.role not in ["owner", "admin"]:
            messages.error(
                request,
                "You do not have permission to change department status."
            )
            return redirect("business_requests:department_management")

    department = get_object_or_404(
        Department,
        id=department_id,
        organization=organization,
    )

    department.is_active = not department.is_active
    department.save(update_fields=["is_active", "updated_at"])

    status = "activated" if department.is_active else "deactivated"

    messages.success(
        request,
        f"Department '{department.name}' has been {status}."
    )

    return redirect(
        "business_requests:department_management"
    )



@login_required
def upload_category_questions(request):
    """
    Platform Administrator:
    Upload an Excel file containing request categories
    and customer questions for a selected organization.
    """

    if not is_platform_administrator(request.user):

        messages.error(
            request,
            "You are not authorized to access this page.",
        )

        return redirect("business_requests:dashboard")

    if request.method == "POST":

        form = CategoryQuestionsUploadForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():

            organization = form.cleaned_data["organization"]
            excel_file = form.cleaned_data["excel_file"]

            try:

                result = import_categories_from_excel(
                    excel_file,
                    organization,
                )

                messages.success(
                    request,
                    (
                        f"Import completed successfully for "
                        f"{organization.name}."
                    ),
                )

                return render(
                    request,
                    "business_requests/upload_category_questions.html",
                    {
                        "form": CategoryQuestionsUploadForm(),
                        "organization": organization,
                        "result": result,
                    },
                )

            except ValueError as exc:

                messages.error(
                    request,
                    f"Import failed: {exc}",
                )

            except Exception:

                logger.exception(
                    "Category question import failed "
                    "for organization %s",
                    organization.id,
                )

                messages.error(
                    request,
                    (
                        "The import could not be completed. "
                        "Please check the Excel file and try again."
                    ),
                )

        else:

            messages.error(
                request,
                "Please correct the errors below and try again.",
            )

    else:

        form = CategoryQuestionsUploadForm()

    return render(
        request,
        "business_requests/upload_category_questions.html",
        {
            "form": form,
        },
    )
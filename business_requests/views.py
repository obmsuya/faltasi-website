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
)
from django.contrib.auth import login
from django.core.mail import send_mail
from django.utils import timezone
from whatsapp.models import Conversation, Message, WhatsAppPhoneNumber
from whatsapp.views import send_whatsapp_message
from django.conf import settings



def get_user_organization(user):
    """
    Return the organization that should be used for the current user.

    Normal users:
        Use their active organization membership.

    Superusers:
        Use the active platform-owner organization.
    """

    # Platform administrators
    if user.is_superuser:
        return (
            Organization.objects
            .filter(
                organization_type="platform_owner",
                status="active",
            )
            .order_by("id")
            .first()
        )

    # Normal organization users
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
def business_dashboard(request):
    """
    Main dashboard for an organization.

    Superusers currently use the Faltasi platform-owner
    organization.

    Normal users see only their own organization's data.
    """

    if request.user.is_superuser:

        organization = (
            Organization.objects
            .filter(
                organization_type="platform_owner",
                status="active",
            )
            .order_by("id")
            .first()
        )

        if not organization:
            messages.error(
                request,
                "No active platform owner organization was found.",
            )

            return redirect(
                "business_requests:dashboard"
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
                "accounts:login"
            )

    recent_requests = (
        BusinessRequest.objects
        .select_related(
            "customer",
            "department",
        )
        .filter(
            customer__organization=organization,
        )
        .order_by("-created_at")[:10]
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
        "recent_requests": recent_requests,
        "customer_count": customer_count,
        "request_count": request_count,
        "staff_count": staff_count,
        "department_count": department_count,
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
    Only requests belonging to the logged-in user's organization
    are displayed.
    """

    organization = get_user_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to a business organization."
        )
        return redirect("business_requests:business_dashboard")

    # Get requests belonging to this organization
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
        .filter(
            customer__organization_id=organization.id
        )
        .order_by("-created_at")
    )

    # Optional filters
    status = request.GET.get("status", "").strip()
    department_id = request.GET.get("department", "").strip()

    if status:
        requests = requests.filter(
            status=status
        )

    if department_id:
        requests = requests.filter(
            department_id=department_id,
            department__organization_id=organization.id,
        )

    # Departments belonging to this organization
    departments = (
        Department.objects
        .filter(
            organization_id=organization.id,
            is_active=True,
        )
        .order_by("name")
    )


    context = {
        "organization": organization,
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
def my_requests(request):
    """
    Display business requests assigned to the currently logged-in staff member.

    Staff can only see requests:
    - assigned to them
    - belonging to their organization
    - through a current assignment
    """

    organization = get_user_organization(request.user)

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
        "status_choices": BusinessRequest.STATUS_CHOICES,
    }

    return render(
        request,
        "business_requests/request_detail.html",
        context,
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

        organization = get_user_organization(request.user)

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

        organization = get_user_organization(request.user)

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
    Manage staff belonging to the currently logged-in organization.
    """

    # Determine the current organization
    if request.user.is_superuser:
        organization = (
            Organization.objects
            .filter(
                organization_type="platform_owner",
                status="active",
            )
            .order_by("id")
            .first()
        )
    else:
        organization = get_user_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to a business organization."
        )
        return redirect("business_requests:business_dashboard")

    # Organization members
    memberships = (
        OrganizationMember.objects
        .filter(
            organization=organization,
            is_active=True,
            user__is_active=True,
        )
        .select_related("user", "organization")
        .order_by("user__username")
    )

    # Users belonging to this organization.
    # This prevents one business from seeing another business's users.
    users = (
        User.objects
        .filter(
            organization_memberships__organization=organization,
            organization_memberships__is_active=True,
            is_active=True,
        )
        .distinct()
        .order_by("username")
    )

    # Departments belonging to this organization
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
        "memberships": memberships,
        "users": users,
        "departments": departments,
    }

    return render(
        request,
        "business_requests/staff.html",
        context,
    )

@login_required
def add_department_member(request):
    """
    Create a new staff user for the current organization and
    assign the user to a department.

    Only organization owners and administrators can perform
    this action.
    """

    # ---------------------------------------------------------
    # Determine organization
    # ---------------------------------------------------------

    if request.user.is_superuser:
        organization = (
            Organization.objects
            .filter(
                organization_type="platform_owner",
                status="active",
            )
            .order_by("id")
            .first()
        )
    else:
        organization = get_user_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to a business organization."
        )
        return redirect(
            "business_requests:business_dashboard"
        )

    # ---------------------------------------------------------
    # Check organization-level permission
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
        if not membership or membership.role not in ["owner", "admin"]:
            messages.error(
                request,
                "You do not have permission to manage staff."
            )
            return redirect(
                "business_requests:staff_management"
            )

    # ---------------------------------------------------------
    # Departments belonging ONLY to this organization
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
    # POST - create staff user
    # ---------------------------------------------------------

    if request.method == "POST":

        username = request.POST.get("username", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        password_confirm = request.POST.get(
            "password_confirm",
            ""
        )

        department_id = request.POST.get("department_id")
        role = request.POST.get("role", "staff")

        # -----------------------------------------------------
        # Validate required fields
        # -----------------------------------------------------

        if not username:
            messages.error(
                request,
                "Username is required."
            )
            return redirect(
                "business_requests:add_department_member"
            )

        if not email:
            messages.error(
                request,
                "Email address is required."
            )
            return redirect(
                "business_requests:add_department_member"
            )

        if not password:
            messages.error(
                request,
                "Password is required."
            )
            return redirect(
                "business_requests:add_department_member"
            )

        if password != password_confirm:
            messages.error(
                request,
                "Passwords do not match."
            )
            return redirect(
                "business_requests:add_department_member"
            )

        # -----------------------------------------------------
        # Validate department role
        # -----------------------------------------------------

        allowed_roles = {
            "manager",
            "agent",
            "staff",
            "viewer",
        }

        if role not in allowed_roles:
            messages.error(
                request,
                "Invalid department role."
            )
            return redirect(
                "business_requests:add_department_member"
            )

        # -----------------------------------------------------
        # Validate department belongs to organization
        # -----------------------------------------------------

        department = get_object_or_404(
            Department,
            id=department_id,
            organization=organization,
            is_active=True,
        )

        # -----------------------------------------------------
        # Prevent duplicate username
        # -----------------------------------------------------

        if User.objects.filter(
            username__iexact=username
        ).exists():

            messages.error(
                request,
                "A user with this username already exists."
            )

            return redirect(
                "business_requests:add_department_member"
            )

        # -----------------------------------------------------
        # Prevent duplicate email
        # -----------------------------------------------------

        if User.objects.filter(
            email__iexact=email
        ).exists():

            messages.error(
                request,
                "A user with this email address already exists."
            )

            return redirect(
                "business_requests:add_department_member"
            )

        # -----------------------------------------------------
        # Create Django user
        # -----------------------------------------------------

        new_user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

        # Staff users should not automatically be staff/superusers
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

        # -----------------------------------------------------
        # Create organization membership
        # -----------------------------------------------------

        OrganizationMember.objects.create(
            organization=organization,
            user=new_user,
            role="staff",
            is_active=True,
        )

        # -----------------------------------------------------
        # Create department membership
        # -----------------------------------------------------

        DepartmentMember.objects.create(
            department=department,
            user=new_user,
            role=role,
            is_active=True,
        )

        # -----------------------------------------------------
        # Success
        # -----------------------------------------------------

        messages.success(
            request,
            f"Staff member {new_user.username} was created "
            f"and assigned to {department.name}."
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
        "roles": [
            ("manager", "Manager"),
            ("agent", "Agent"),
            ("staff", "Staff"),
            ("viewer", "Viewer"),
        ],
    }

    return render(
        request,
        "business_requests/add_department_member.html",
        context,
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

    organization = get_user_organization(request.user)

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
    organization = get_user_organization(request.user)

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

    organization = get_user_organization(request.user)

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

    organization = get_user_organization(request.user)

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

    organization = get_user_organization(request.user)

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

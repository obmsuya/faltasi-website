from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from organizations.models import Organization, OrganizationMember
from whatsapp.models import Conversation, Message
from business_requests.models import BusinessRequest

from .forms import CustomerForm
from .models import Customer
from organizations.utils import (
    get_user_organization,
    is_platform_administrator,
)






def customers_visible_to(user):
    """Platform admins see all customers; staff see only their tenant."""
    if is_platform_administrator(user):
        return Customer.objects.select_related("organization").all()
    organization = get_user_organization(user)
    if not organization:
        return Customer.objects.none()
    return Customer.objects.filter(organization=organization)


@login_required
def customer_list(request):
    """List customers with strict tenant isolation."""
    platform_admin = is_platform_administrator(request.user)
    organization = None if platform_admin else get_user_organization(request.user)

    if not platform_admin and not organization:
        messages.error(request, "Your account is not connected to an active organization.")
        return redirect("accounts:login")

    customers = customers_visible_to(request.user).order_by("-created_at")

    search = request.GET.get("search", "").strip()
    if search:
        customers = customers.filter(
            Q(name__icontains=search)
            | Q(company__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )

    customer_type = request.GET.get("customer_type", "").strip()
    if customer_type:
        customers = customers.filter(customer_type=customer_type)

    status = request.GET.get("status", "").strip()
    if status:
        customers = customers.filter(status=status)

    relationship_stage = request.GET.get("relationship_stage", "").strip()
    if relationship_stage in dict(Customer.RELATIONSHIP_STAGE_CHOICES):
        customers = customers.filter(relationship_stage=relationship_stage)

    phone_status = request.GET.get("phone_status", "").strip()
    if phone_status in dict(Customer.PHONE_STATUS_CHOICES):
        customers = customers.filter(phone_status=phone_status)

    selected_organization = ""
    if platform_admin:
        selected_organization = request.GET.get("organization", "").strip()
        if selected_organization.isdigit():
            customers = customers.filter(organization_id=int(selected_organization))
        organizations = Organization.objects.filter(
            customers__isnull=False
        ).distinct().order_by("name")
        today = timezone.localdate()
        stats = {
            "total_customers": Customer.objects.count(),
            "customers_today": Customer.objects.filter(created_at__date=today).count(),
            "organizations_with_customers": Customer.objects.exclude(
                organization__isnull=True
            ).values("organization_id").distinct().count(),
        }
    else:
        organizations = Organization.objects.none()
        stats = {}

    paginator = Paginator(customers, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {
        "organization": organization,
        "platform_admin": platform_admin,
        "customers": page_obj,
        "page_obj": page_obj,
        "search": search,
        "selected_customer_type": customer_type,
        "selected_status": status,
        "selected_relationship_stage": relationship_stage,
        "selected_phone_status": phone_status,
        "selected_organization": selected_organization,
        "organizations": organizations,
        "stats": stats,
        "customer_type_choices": Customer._meta.get_field("customer_type").choices,
        "status_choices": Customer._meta.get_field("status").choices,
        "relationship_stage_choices": Customer.RELATIONSHIP_STAGE_CHOICES,
        "phone_status_choices": Customer.PHONE_STATUS_CHOICES,
    }
    return render(request, "customers/customer_list.html", context)


@login_required
def customer_create(request):
    """
    Create a new customer inside the user's organization.
    """

    organization = get_user_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an active organization.",
        )

        return redirect("accounts:login")

    if request.method == "POST":

        form = CustomerForm(
            request.POST,
        )

        if form.is_valid():

            customer = form.save(
                commit=False,
            )

            # IMPORTANT:
            # Never allow the form to decide the organization.
            customer.organization = organization
            customer.contact_source = "manual"
            customer.first_contact_at = timezone.now()
            if customer.phone:
                customer.phone_status = "active"
            else:
                customer.phone_status = "removed"

            customer.save()

            messages.success(
                request,
                "Customer was created successfully.",
            )

            return redirect(
                "customers:detail",
                customer_id=customer.id,
            )

    else:

        form = CustomerForm()

    context = {
        "organization": organization,
        "form": form,
        "page_title": "Add Customer",
    }

    return render(
        request,
        "customers/customer_form.html",
        context,
    )


@login_required
def customer_detail(request, customer_id):
    """
    Display one customer together with:

    - WhatsApp conversations
    - Business requests
    - Recent WhatsApp messages

    Everything is restricted to the user's organization.
    """

    platform_admin = is_platform_administrator(request.user)
    organization = None if platform_admin else get_user_organization(request.user)
    if not platform_admin and not organization:
        messages.error(request, "Your account is not connected to an active organization.")
        return redirect("accounts:login")

    customer = get_object_or_404(customers_visible_to(request.user), id=customer_id)
    # All related WhatsApp/request data must follow the customer's own tenant.
    organization = customer.organization

    # =====================================================
    # WHATSAPP CONVERSATIONS
    # =====================================================

    conversations = (
        Conversation.objects
        .filter(
            organization=organization,
            customer=customer,
        )
        .select_related(
            "whatsapp_phone_number",
            "business_request",
        )
        .order_by(
            "-last_message_at"
        )
    )

    # =====================================================
    # BUSINESS REQUESTS
    # =====================================================

    business_requests = (
        BusinessRequest.objects
        .filter(
            customer=customer,
        )
        .select_related(
            "category",
            "department",
        )
        .order_by(
            "-created_at"
        )
    )

    # =====================================================
    # RECENT WHATSAPP MESSAGES
    # =====================================================

    recent_messages = (
        Message.objects
        .filter(
            conversation__organization=organization,
            conversation__customer=customer,
        )
        .select_related(
            "conversation",
        )
        .order_by(
            "-created_at"
        )[:20]
    )

    # =====================================================
    # COUNTS
    # =====================================================

    conversation_count = conversations.count()

    business_request_count = business_requests.count()

    message_count = (
        Message.objects
        .filter(
            conversation__organization=organization,
            conversation__customer=customer,
        )
        .count()
    )

    # =====================================================
    # CONTEXT
    # =====================================================

    context = {
        "organization": organization,
        "customer": customer,

        "conversations": conversations,
        "business_requests": business_requests,
        "recent_messages": recent_messages,

        "conversation_count": conversation_count,
        "business_request_count": business_request_count,
        "message_count": message_count,
    }

    return render(
        request,
        "customers/customer_detail.html",
        context,
    )

@login_required
def customer_edit(request, customer_id):
    """
    Edit a customer belonging to the user's organization.
    """

    platform_admin = is_platform_administrator(request.user)
    organization = None if platform_admin else get_user_organization(request.user)
    if not platform_admin and not organization:
        messages.error(request, "Your account is not connected to an active organization.")
        return redirect("accounts:login")

    customer = get_object_or_404(customers_visible_to(request.user), id=customer_id)
    organization = customer.organization

    if request.method == "POST":

        form = CustomerForm(
            request.POST,
            instance=customer,
        )

        if form.is_valid():

            updated_customer = form.save(
                commit=False,
            )

            # Never let a form change the customer's tenant.
            updated_customer.organization = customer.organization
            if updated_customer.phone and updated_customer.phone != customer.phone:
                updated_customer.phone_status = "active"
            elif not updated_customer.phone:
                updated_customer.phone_status = "removed"

            updated_customer.save()

            messages.success(
                request,
                "Customer was updated successfully.",
            )

            return redirect(
                "customers:detail",
                customer_id=customer.id,
            )

    else:

        form = CustomerForm(
            instance=customer,
        )

    context = {
        "organization": organization,
        "customer": customer,
        "form": form,
        "page_title": "Edit Customer",
    }

    return render(
        request,
        "customers/customer_form.html",
        context,
    )


@login_required
def customer_delete(request, customer_id):
    """
    Delete a customer belonging to the user's organization.

    Only POST is accepted.
    """

    platform_admin = is_platform_administrator(request.user)
    organization = None if platform_admin else get_user_organization(request.user)
    if not platform_admin and not organization:
        messages.error(request, "Your account is not connected to an active organization.")
        return redirect("accounts:login")

    customer = get_object_or_404(customers_visible_to(request.user), id=customer_id)
    organization = customer.organization

    if request.method == "POST":

        customer.status = "inactive"
        if customer.phone:
            customer.phone_status = "inactive"
        customer.save(update_fields=["status", "phone_status", "updated_at"])

        messages.success(
            request,
            "Customer was deactivated. Conversation and business-request history has been preserved.",
        )

        return redirect(
            "customers:list"
        )

    return render(
        request,
        "customers/customer_confirm_delete.html",
        {
            "organization": organization,
            "customer": customer,
        },
    )



@login_required
def customer_phone_action(request, customer_id):
    """Manage a customer's phone channel without deleting CRM history."""
    if request.method != "POST":
        return redirect("customers:detail", customer_id=customer_id)

    customer = get_object_or_404(
        customers_visible_to(request.user),
        id=customer_id,
    )
    action = request.POST.get("action", "").strip()

    if action == "deactivate":
        if customer.phone:
            customer.phone_status = "inactive"
        else:
            messages.error(request, "This customer has no phone number to deactivate.")
            return redirect("customers:detail", customer_id=customer.id)

    elif action in {"reactivate", "unblock"}:
        if customer.phone:
            customer.phone_status = "active"
        else:
            messages.error(request, "Add a phone number before reactivating this contact.")
            return redirect("customers:edit", customer_id=customer.id)

    elif action == "block":
        if customer.phone:
            customer.phone_status = "blocked"
        else:
            messages.error(request, "This customer has no phone number to block.")
            return redirect("customers:detail", customer_id=customer.id)

    elif action == "remove":
        customer.phone = ""
        customer.phone_status = "removed"

    else:
        messages.error(request, "Unsupported phone-management action.")
        return redirect("customers:detail", customer_id=customer.id)

    customer.save(update_fields=["phone", "phone_status", "updated_at"])
    messages.success(request, "Customer phone settings were updated. Existing history was preserved.")
    return redirect("customers:detail", customer_id=customer.id)

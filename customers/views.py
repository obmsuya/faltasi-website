from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from organizations.models import Organization
from whatsapp.models import Conversation, Message
from business_requests.models import BusinessRequest

from .forms import CustomerForm
from .models import Customer




def get_user_organization(user):
    """
    Return the active organization belonging to the current user.

    Superusers use the active platform-owner organization.
    Normal users use their active organization membership.
    """

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
def customer_list(request):
    """
    Display customers belonging only to the user's organization.
    """

    organization = get_user_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an active organization.",
        )

        return redirect("accounts:login")

    customers = (
        Customer.objects
        .filter(
            organization=organization,
        )
        .order_by("-created_at")
    )

    # Search
    search = request.GET.get("search", "").strip()

    if search:
        customers = customers.filter(
            Q(name__icontains=search)
            | Q(company__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )

    # Customer type
    customer_type = request.GET.get(
        "customer_type",
        "",
    ).strip()

    if customer_type:
        customers = customers.filter(
            customer_type=customer_type,
        )

    # Status
    status = request.GET.get(
        "status",
        "",
    ).strip()

    if status:
        customers = customers.filter(
            status=status,
        )

    # Pagination
    paginator = Paginator(
        customers,
        20,
    )

    page_number = request.GET.get(
        "page",
    )

    page_obj = paginator.get_page(
        page_number,
    )

    context = {
        "organization": organization,
        "customers": page_obj,
        "page_obj": page_obj,
        "search": search,
        "selected_customer_type": customer_type,
        "selected_status": status,
        "customer_type_choices": Customer._meta.get_field(
            "customer_type"
        ).choices,
        "status_choices": Customer._meta.get_field(
            "status"
        ).choices,
    }

    return render(
        request,
        "customers/customer_list.html",
        context,
    )


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

    organization = get_user_organization(
        request.user
    )

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an active organization.",
        )

        return redirect("accounts:login")

    # =====================================================
    # CUSTOMER
    # =====================================================

    customer = get_object_or_404(
        Customer.objects.filter(
            organization=organization,
        ),
        id=customer_id,
    )

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

    organization = get_user_organization(
        request.user
    )

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an active organization.",
        )

        return redirect("accounts:login")

    customer = get_object_or_404(
        Customer.objects.filter(
            organization=organization,
        ),
        id=customer_id,
    )

    if request.method == "POST":

        form = CustomerForm(
            request.POST,
            instance=customer,
        )

        if form.is_valid():

            updated_customer = form.save(
                commit=False,
            )

            # Preserve organization.
            updated_customer.organization = organization

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

    organization = get_user_organization(
        request.user
    )

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an active organization.",
        )

        return redirect("accounts:login")

    customer = get_object_or_404(
        Customer.objects.filter(
            organization=organization,
        ),
        id=customer_id,
    )

    if request.method == "POST":

        customer.delete()

        messages.success(
            request,
            "Customer was deleted successfully.",
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



from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import message
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from organizations.models import OrganizationMember
from products.forms import ProductForm
from products.models import Product
from business_requests.views import get_user_organization
from organizations.models import Organization, OrganizationMember


def _organization_for_user(request):
    """Resolve the user's active organization and membership."""
    organization = get_user_organization(
        request.user,
        request=request,
    )

    if organization is None:
        return None, None

    membership = OrganizationMember.objects.filter(
        user=request.user,
        organization=organization,
        is_active=True,
    ).first()

    if membership is None:
        from business_requests.views import is_platform_administrator

        if not is_platform_administrator(request.user):
            return None, None

    return organization, membership


def _can_manage_products(user, membership):
    """Only owners, administrators, and managers may change products."""
    if user.is_superuser:
        return True

    from business_requests.views import is_platform_administrator

    if is_platform_administrator(user):
        return True

    return (
        membership is not None
        and membership.role in {"owner", "admin", "manager"}
    )


@login_required
def product_list(request):
    organization, membership = _organization_for_user(request)

    if organization is None:
        messages.error(
            request,
            "Your account is not assigned to an active organization.",
        )
        return redirect("business_requests:business_dashboard")

    products = (
        Product.objects.filter(
            organization=organization,
            deleted_at__isnull=True,
        )
        .select_related("category")
        .order_by("name")
    )

    return render(
        request,
        "products/product_list.html",
        {
            "organization": organization,
            "products": products,
            "can_manage_products": _can_manage_products(
                request.user,
                membership,
            ),
        },
    )


@login_required
def product_create(request):
    organization, membership = _organization_for_user(request)

    if organization is None:
        return HttpResponseForbidden(
            "No active organization is assigned to your account."
        )

    if not _can_manage_products(request.user, membership):
        return HttpResponseForbidden(
            "You are not authorized to add products."
        )

    if request.method == "POST":
        form = ProductForm(
            request.POST,
            request.FILES,
            organization=organization,
        )

        if form.is_valid():
            form.save()
            messages.success(request, "Product added successfully.")
            return redirect("products:product_list")
    else:
        form = ProductForm(organization=organization)

    return render(
        request,
        "products/product_form.html",
        {
            "form": form,
            "organization": organization,
            "page_title": "Add Product",
        },
    )


@login_required
def product_edit(request, product_id):
    organization, membership = _organization_for_user(request)

    if organization is None:
        return HttpResponseForbidden(
            "No active organization is assigned to your account."
        )

    if not _can_manage_products(request.user, membership):
        return HttpResponseForbidden(
            "You are not authorized to edit products."
        )

    product = get_object_or_404(
        Product,
        pk=product_id,
        organization=organization,
        deleted_at__isnull=True,
    )

    if request.method == "POST":
        form = ProductForm(
            request.POST,
            request.FILES,
            instance=product,
            organization=organization,
        )

        if form.is_valid():
            form.save()
            messages.success(request, "Product updated successfully.")
            return redirect("products:product_list")
    else:
        form = ProductForm(
            instance=product,
            organization=organization,
        )

    return render(
        request,
        "products/product_form.html",
        {
            "form": form,
            "product": product,
            "organization": organization,
            "page_title": "Edit Product",
        },
    )


@login_required
@require_POST
def product_toggle_status(request, product_id):
    organization, membership = _organization_for_user(request)

    if organization is None:
        return HttpResponseForbidden(
            "No active organization is assigned to your account."
        )

    if not _can_manage_products(request.user, membership):
        return HttpResponseForbidden(
            "You are not authorized to change product status."
        )

    product = get_object_or_404(
        Product,
        pk=product_id,
        organization=organization,
        deleted_at__isnull=True,
    )

    product.is_active = not product.is_active
    product.save(update_fields=["is_active", "updated_at"])

    messages.success(
        request,
        f"{product.name} is now "
        f"{'active' if product.is_active else 'inactive'}.",
    )

    return redirect("products:product_list")



@login_required
def product_share_whatsapp(request, product_id):
    import re

    from django.conf import settings
    from django.urls import reverse
    from customers.models import Customer
    from whatsapp.models import WhatsAppPhoneNumber
    from whatsapp.views import send_whatsapp_message

    organization, membership = _organization_for_user(request)

    if organization is None:
        return HttpResponseForbidden(
            "No active organization is assigned to your account."
        )

    if not _can_manage_products(request.user, membership):
        return HttpResponseForbidden(
            "You are not authorized to share products."
        )

    product = get_object_or_404(
        Product,
        pk=product_id,
        organization=organization,
        deleted_at__isnull=True,
        is_active=True,
        show_on_whatsapp=True,
    )

    customers = Customer.objects.filter(
        organization=organization,
        status="active",
    ).order_by("name")

    if request.method == "GET":
        return render(
            request,
            "products/product_share_whatsapp.html",
            {
                "organization": organization,
                "product": product,
                "customers": customers,
            },
        )

    customer_id = request.POST.get("customer_id", "").strip()
    recipient_name = request.POST.get("recipient_name", "").strip()
    recipient_phone = request.POST.get("recipient_phone", "").strip()

    customer = None

    if customer_id:
        customer = get_object_or_404(
            customers,
            pk=customer_id,
        )
        recipient_name = customer.name
        recipient_phone = customer.phone

    if not recipient_phone:
        messages.error(request, "Enter a customer's phone number.")
        return redirect(
            "products:product_share_whatsapp",
            product_id=product.id,
        )

    # Normalize Tanzanian numbers while allowing international numbers.
    recipient_phone = re.sub(r"[\s().-]", "", recipient_phone)

    if recipient_phone.startswith("+"):
        recipient_phone = recipient_phone[1:]
    elif recipient_phone.startswith("0"):
        recipient_phone = "255" + recipient_phone[1:]

    if not recipient_phone.isdigit() or not 8 <= len(recipient_phone) <= 15:
        messages.error(
            request,
            "Enter a valid phone number with its country code if needed.",
        )
        return redirect(
            "products:product_share_whatsapp",
            product_id=product.id,
        )

    platform_org = Organization.objects.filter(
        organization_type="platform_owner",
        status="active",
    ).order_by("created_at").first()

    if not platform_org:
        messages.error(
            request,
            "Faltasi's WhatsApp account is not configured.",
        )
        return redirect("products:product_list")

    whatsapp_phone = WhatsAppPhoneNumber.objects.filter(
        organization=platform_org,
        is_active=True,
        status="connected",
        phone_number_id__isnull=False,
    ).select_related(
        "whatsapp_business_account",
    ).order_by(
        "-is_default",
        "-created_at",
    ).first()

    if not whatsapp_phone:
        messages.error(
            request,
            "No connected Faltasi WhatsApp number is available.",
        )
        return redirect("products:product_list")

    product_url = request.build_absolute_uri(
        reverse("products:product_list")
    )

    price_text = (
        f"{product.currency} {product.price:,.2f}"
        if product.price is not None
        else "Price available on request"
    )

    description = (
        product.short_description
        or product.description
        or ""
    )

    message = (
        f"*{organization.name}*\n"
        f"*{product.name}*\n"
        f"{description}\n"
        f"Price: {price_text}\n"
        f"Availability: {product.get_availability_display()}\n"
        f"Contact us for more information.\n"
        f"{product_url}"
    )

    response = send_whatsapp_message(
        whatsapp_phone,
        recipient_phone,
        message,
    )

    if response is not None and response.status_code in (200, 201):
        if customer is None and recipient_name:
            # Save the new customer only when requested by the sender.
            if request.POST.get("save_customer") == "on":
                Customer.objects.get_or_create(
                    organization=organization,
                    phone=recipient_phone,
                    defaults={
                        "name": recipient_name,
                        "preferred_contact_method": "whatsapp",
                        "status": "active",
                    },
                )

        messages.success(
            request,
            f"WhatsApp accepted the product message for "
            f"{recipient_name or recipient_phone}.",
        )
    else:
        messages.error(
            request,
            "WhatsApp could not accept the message. Check the "
            "connected WhatsApp account and Meta API response.",
        )

    return redirect("products:product_list")
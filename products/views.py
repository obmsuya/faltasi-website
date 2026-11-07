
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import message
from django.core import signing
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST


from products.forms import ProductForm
from products.models import Product
from organizations.models import Organization, OrganizationMember
from organizations.utils import (
    get_user_organization,
    is_platform_administrator,
)





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

        if not is_platform_administrator(request.user):
            return None, None

    return organization, membership


def _can_manage_products(user, membership):
    """Only owners, administrators, and managers may change products."""
    if user.is_superuser:
        return True

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
    from django.utils import timezone
    from django.urls import reverse

    from customers.models import Customer
    from whatsapp.models import (
        WhatsAppPhoneNumber,
        Conversation,
        Message,
    )
    from whatsapp.views import send_whatsapp_template

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

    customers = (
        Customer.objects.filter(
            organization=organization,
            status="active",
            phone_status="active",
        )
        .exclude(phone__isnull=True)
        .exclude(phone__exact="")
        .order_by("name")
    )


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

    if customer_id:
        customer = get_object_or_404(customers, pk=customer_id)
        recipient_name = customer.name
        recipient_phone = customer.phone
    else:
        customer = None

    if not recipient_phone:
        messages.error(request, "Enter a customer's phone number.")
        return redirect(
            "products:product_share_whatsapp",
            product_id=product.id,
        )

    # Normalize Tanzanian numbers and international numbers.
    recipient_phone = re.sub(r"[\s().-]", "", recipient_phone)

    if recipient_phone.startswith("+"):
        recipient_phone = recipient_phone[1:]
    elif recipient_phone.startswith("0"):
        recipient_phone = "255" + recipient_phone[1:]

    if not recipient_phone.isdigit() or not 8 <= len(recipient_phone) <= 15:
        messages.error(request, "Enter a valid WhatsApp phone number.")
        return redirect(
            "products:product_share_whatsapp",
            product_id=product.id,
        )
    if customer is None:
        customer = customers.filter(phone=recipient_phone).first()
        if customer:
            recipient_name = customer.name

    # Marketing messages require recorded, explicit customer consent.
    # Non-subscribed customers receive a link to initiate consent themselves.

    if not customer:
        if request.POST.get("save_customer") == "on" and recipient_name:
            customer, _ = Customer.objects.get_or_create(
                organization=organization,
                phone=recipient_phone,
                defaults={
                    "name": recipient_name,
                    "preferred_contact_method": "whatsapp",
                    "status": "active",
                },
            )

    if not customer or not customer.whatsapp_marketing_opt_in:
        # Use only this organization's connected WhatsApp sender.
        subscription_phone = WhatsAppPhoneNumber.objects.filter(
            organization=organization,
            is_active=True,
            status="connected",
            phone_number_id__isnull=False,
            whatsapp_business_account__organization=organization,
            whatsapp_business_account__is_active=True,
            whatsapp_business_account__status="connected",
        ).select_related(
            "whatsapp_business_account",
        ).order_by(
            "-is_default",
            "-created_at",
        ).first()

        subscription_link = ""

        if subscription_phone and subscription_phone.phone_number:
            business_number = re.sub(
                r"\D",
                "",
                subscription_phone.phone_number,
            )

            if business_number:
                subscription_link = (
                    f"https://wa.me/{business_number}?text={quote('YES')}"
                )

        if not subscription_link:
            messages.error(
                request,
                "A connected WhatsApp business number is required "
                "to generate the subscription link.",
            )
            return redirect(
                "products:product_share_whatsapp",
                product_id=product.id,
            )

        return render(
            request,
            "products/product_share_whatsapp.html",
            {
                "organization": organization,
                "product": product,
                "customers": customers,
                "subscription_link": subscription_link,
                "subscription_recipient_name": (
                    recipient_name or (
                        customer.name if customer else ""
                    )
                ),
                "subscription_recipient_phone": recipient_phone,
            },
        )


    # Fail closed unless product-sharing template sending is enabled.
    if not getattr(
        settings,
        "WHATSAPP_PRODUCT_SHARE_TEMPLATE_ENABLED",
        False,
    ):
        messages.error(
            request,
            "WhatsApp product sharing is currently disabled."
        )
        return redirect(
            "products:product_share_whatsapp",
            product_id=product.id,
        )

    # Require an organization slug for the public product URL.
    if not organization.slug:
        messages.error(
            request,
            "Your organization needs a public URL slug before "
            "products can be shared."
        )
        return redirect(
            "products:product_share_whatsapp",
            product_id=product.id,
        )

    # Use only this organization's connected WhatsApp number.
    whatsapp_phone = WhatsAppPhoneNumber.objects.filter(
        organization=organization,
        is_active=True,
        status="connected",
        phone_number_id__isnull=False,
        whatsapp_business_account__organization=organization,
        whatsapp_business_account__is_active=True,
        whatsapp_business_account__status="connected",
    ).select_related(
        "whatsapp_business_account",
    ).order_by(
        "-is_default",
        "-created_at",
    ).first()

    if not whatsapp_phone:
        messages.error(
            request,
            "Your organization does not have a connected WhatsApp number."
        )
        return redirect(
            "products:product_share_whatsapp",
            product_id=product.id,
        )

    # Reuse the organization's active conversation with this customer.
    conversation = Conversation.objects.filter(
        organization=organization,
        whatsapp_phone_number=whatsapp_phone,
        customer=customer,
        phone_number=recipient_phone,
        status="active",
    ).first()

    if not conversation:
        conversation = Conversation.objects.create(
            organization=organization,
            whatsapp_phone_number=whatsapp_phone,
            customer=customer,
            phone_number=recipient_phone,
            whatsapp_user_id=recipient_phone,
            status="active",
        )

    # Product pricing.
    price_text = (
        f"{product.currency} {product.price:,.2f}"
        if product.price is not None
        else "Price available on request"
    )

    # Generate a signed, organization- and product-bound WhatsApp share URL.
    # This allows an authorized WhatsApp share without making the product
    # discoverable through an unrestricted public product URL.
    share_token = signing.dumps(
        {
            "organization_id": organization.id,
            "product_id": product.id,
        },
        salt="products.whatsapp_product_share",
        compress=True,
    )
    product_url = request.build_absolute_uri(
        reverse(
            "products:public_product_detail",
            kwargs={
                "organization_slug": organization.slug,
                "product_id": product.id,
            },
        )
        + f"?share={quote(share_token)}"
    )

    # Six parameters matching the approved Meta template.
    parameters = [
        recipient_name or customer.name or "Customer",
        organization.name,
        product.name,
        price_text,
        product.get_availability_display(),
        product_url,
    ]

    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(value)}
                for value in parameters
            ],
        }
    ]

    response = send_whatsapp_template(
        whatsapp_phone=whatsapp_phone,
        phone_number=recipient_phone,
        template_name="product_share_notification",
        language_code="en",
        components=components,
    )

    if response is None or response.status_code not in (200, 201):
        messages.error(
            request,
            "WhatsApp could not accept the product-sharing message. "
            "Check your organization's WhatsApp connection."
        )
        return redirect(
            "products:product_share_whatsapp",
            product_id=product.id,
        )

    try:
        response_data = response.json()
        whatsapp_message_id = (
            response_data.get("messages", [{}])[0].get("id")
        )
    except (ValueError, AttributeError, IndexError, TypeError):
        response_data = {}
        whatsapp_message_id = None

    # Record the outgoing template message.
    Message.objects.create(
        organization=organization,
        conversation=conversation,
        direction="outgoing",
        sender_type="faltasi",
        message_type="template",
        content="Marketing template: product_share_notification",
        whatsapp_message_id=whatsapp_message_id,
        delivery_status="sent",
        metadata={
            "template_name": "product_share_notification",
            "language_code": "en",
            "product_id": product.id,
            "product_url": product_url,
            "customer_consent": True,
            "provider_response": response_data,
            "sent_at": timezone.now().isoformat(),
        },
    )

    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=["last_message_at"])

    messages.success(
        request,
        f"Product-sharing message accepted by WhatsApp for "
        f"{recipient_name or customer.name or recipient_phone}."
    )

    return redirect("products:product_list")




def public_product_detail(request, organization_slug, product_id):
    organization = get_object_or_404(
        Organization,
        slug=organization_slug,
        status="active",
    )

    product = get_object_or_404(
        Product,
        pk=product_id,
        organization=organization,
        is_active=True,
        deleted_at__isnull=True,
        show_on_whatsapp=True,
    )

    # Faltasi products may be opened directly only when they are explicitly
    # approved for the public catalogue and website presentation.
    is_public_faltasi_product = (
        organization.organization_type == "platform_owner"
        and product.is_publicly_visible
        and product.show_on_website
    )

    # Other organizations' products (and non-public Faltasi products) require
    # a signed URL generated by the authorized WhatsApp sharing workflow.
    has_valid_share_token = False
    share_token = request.GET.get("share", "").strip()

    if share_token:
        try:
            token_data = signing.loads(
                share_token,
                salt="products.whatsapp_product_share",
            )
            has_valid_share_token = (
                token_data.get("organization_id") == organization.id
                and token_data.get("product_id") == product.id
            )
        except (signing.BadSignature, AttributeError, TypeError):
            has_valid_share_token = False

    if not (is_public_faltasi_product or has_valid_share_token):
        # Return 404 rather than revealing that a private product exists.
        from django.http import Http404
        raise Http404("Product not found.")

    return render(
        request,
        "products/public_product_detail.html",
        {
            "organization": organization,
            "product": product,
        },
    )

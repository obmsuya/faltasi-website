import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email

from business_requests.models import BusinessRequest
from customers.models import Customer
from organizations.models import Organization


def get_website_organization():
    """Return Faltasi's active platform-owner organization, never an arbitrary tenant."""
    organization_type = "platform_owner"
    status = "active"
    configured_slug = getattr(settings, "WEBSITE_ORGANIZATION_SLUG", "faltasi")

    organization = Organization.objects.filter(
        slug=configured_slug,
        organization_type=organization_type,
        status=status,
    ).first()
    if organization:
        return organization

    # Compatibility for existing installations whose Faltasi record has no slug.
    return Organization.objects.filter(
        name="Faltasi Innovations Limited",
        organization_type=organization_type,
        status=status,
    ).order_by("pk").first()


def validate_website_request(name, email, phone, message):
    """Validate public website enquiry and quotation contact details."""
    if not name:
        return "Please provide your name."
    if len(name) > 100:
        return "Your name must be 100 characters or fewer."
    if not message:
        return "Please provide a message."
    if len(message) > 5000:
        return "Your message must be 5,000 characters or fewer."
    if len(email) > 254:
        return "Please enter a valid email address."
    if email:
        try:
            validate_email(email)
        except ValidationError:
            return "Please enter a valid email address."
    if phone:
        cleaned_phone = re.sub(r"[\s().-]", "", phone)
        if not re.fullmatch(r"\+?[0-9]{7,15}", cleaned_phone):
            return "Please enter a valid phone number."
    return None


def create_website_request(
    *,
    organization,
    name,
    email="",
    phone="",
    message,
    product=None,
):
    """Create a tenant-scoped website inquiry or product quote request."""
    # An empty phone number is not a customer identifier. Create a separate
    # visitor record instead of merging unrelated visitors with blank phones.
    customer = None
    if phone:
        customer = Customer.objects.filter(
            phone=phone,
            organization=organization,
        ).first()

    if customer is None:
        customer = Customer.objects.create(
            organization=organization,
            phone=phone,
            name=name,
            email=email,
            preferred_contact_method="email",
            country=getattr(settings, "DEFAULT_COUNTRY", "Tanzania"),
            contact_source="website",
        )
    else:
        customer.name = name
        customer.email = email
        customer.preferred_contact_method = "email"
        customer.save(
            update_fields=["name", "email", "preferred_contact_method"]
        )

    business_request = BusinessRequest.objects.create(
        customer=customer,
        product=product,
        category=product.request_category if product else None,
        request_text=message,
        subject=product.name if product else getattr(
            settings, "WEBSITE_GENERAL_REQUEST_SUBJECT", "General Website Inquiry"
        ),
        status="new",
        priority="normal",
        source="website",
    )

    recipients = getattr(
        settings,
        "WEBSITE_REQUEST_NOTIFICATION_EMAILS",
        "faltasiinnovationsltd@gmail.com",
    )
    if isinstance(recipients, str):
        recipients = [address.strip() for address in recipients.split(",") if address.strip()]
    else:
        recipients = list(recipients or [])

    if recipients:
        send_mail(
            subject=getattr(
                settings,
                "WEBSITE_REQUEST_NOTIFICATION_SUBJECT",
                "New Website Quote Request - {product}" if product else "New General Website Inquiry",
            ).format(product=product.name if product else ""),
            message="\n".join(
                [
                    f"Customer Name: {name}",
                    f"Email: {email}",
                    f"Phone: {phone}",
                    f"Product: {product.name if product else 'Not specified'}",
                    f"Message:\n{message}",
                    f"Business Request ID: {business_request.pk}",
                ]
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=True,
        )

    if email:
        default_confirmation = (
            "Dear {customer_name},\n\n"
            "Thank you for contacting Faltasi Innovations Limited.\n\n"
            "We have received your request{product_reference}.\n\n"
            "Our team will review your request and contact you shortly.\n\n"
            "Regards,\n"
            "Faltasi Innovations Limited\n"
            "Dar es Salaam, Tanzania\n"
            "+255 653 397 942"
        )
        confirmation_body = getattr(
            settings,
            "WEBSITE_REQUEST_CONFIRMATION_BODY",
            default_confirmation,
        ) or default_confirmation
        product_reference = f" regarding {product.name}" if product else ""
        send_mail(
            subject=getattr(
                settings,
                "WEBSITE_REQUEST_CONFIRMATION_SUBJECT",
                "We Received Your Request - Faltasi Innovations Limited",
            ),
            message=confirmation_body.format(
                customer_name=name,
                organization_name=organization.name,
                product_name=product.name if product else "",
                product_reference=product_reference,
                request_id=business_request.pk,
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=True,
        )

    return business_request

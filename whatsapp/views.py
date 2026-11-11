from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction

import json
import requests
import re
import hmac
import hashlib
from urllib.parse import urlsplit

from .models import (
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
    WhatsAppConnection,
    Conversation,
    ConversationState,
    Message,
)
from customers.models import Customer
from products.models import Product
from business_requests.models import (
    BusinessRequest,
    RequestCategory,
    RequestAssignment,
    WorkflowStep,
    DepartmentMember,
)

from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.utils import timezone
from django.core.mail import send_mail


def verify_meta_webhook_signature(request):
    """Verify that a WhatsApp webhook POST came from Meta."""

    app_secret = getattr(settings, "WHATSAPP_APP_SECRET", "")
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not app_secret or not signature:
        return False

    expected_signature = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        request.body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)

def find_request_category(text, organization=None):
    """
    Identify a RequestCategory using keywords stored
    in the Django database.

    Categories and keywords are managed through
    Django Admin.

    If an organization is supplied, only categories
    belonging to that organization are searched.
    """

    if not text:
        return None

    message = text.lower().strip()

    categories = RequestCategory.objects.filter(
        is_active=True
    )

    # -----------------------------------------
    # ORGANIZATION ISOLATION
    # -----------------------------------------

    if organization:
        categories = categories.filter(
            organization=organization
        )

    categories = categories.order_by("name")

    best_category = None
    best_score = 0

    for category in categories:

        if not category.keywords:
            continue

        keywords = [
            keyword.strip().lower()
            for keyword in category.keywords.split(",")
            if keyword.strip()
        ]

        score = 0

        for keyword in keywords:

            if keyword in message:
                score += 1

        if score > best_score:

            best_score = score
            best_category = category

    if best_category:

        print(
            "CATEGORY IDENTIFIED:",
            best_category.name,
            "| ORGANIZATION:",
            best_category.organization.name,
            "| SCORE:",
            best_score,
        )

    else:

        print(
            "NO REQUEST CATEGORY IDENTIFIED",
            "| ORGANIZATION:",
            organization.name if organization else None,
        )

    return best_category

def normalize_phone_number(phone_number):
    """
    Normalize Tanzanian phone numbers to international format.

    Examples:
        0764819996  -> +255764819996
        255764819996 -> +255764819996
        +255764819996 -> +255764819996
    """

    if not phone_number:
        return ""

    phone = str(phone_number).strip()

    # Remove spaces, hyphens, brackets, etc.
    phone = re.sub(r"[^\d+]", "", phone)

    # Already international format
    if phone.startswith("+"):
        return phone

    # Tanzania number without +
    if phone.startswith("255"):
        return f"+{phone}"

    # Tanzania local format
    if phone.startswith("0") and len(phone) >= 9:
        return f"+255{phone[1:]}"

    # Fallback
    return phone



def _get_whatsapp_sender_credentials(whatsapp_phone):
    """
    Resolve credentials for the selected WhatsApp sender.

    Tenant isolation:
    - A tenant phone can only use its own organization's connection.
    - Faltasi global credentials are never substituted for another tenant.
    - Development fallback is allowed only when no phone record is supplied.
    """
    from django.conf import settings
    from whatsapp.models import WhatsAppConnection

    # Explicit local development fallback for legacy calls without a
    # database phone record. Never use this for a supplied tenant phone.
    if whatsapp_phone is None:
        if not settings.DEBUG:
            return None, None

        token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", None)
        phone_number_id = getattr(
            settings, "WHATSAPP_PHONE_NUMBER_ID", None
        )

        if token and phone_number_id:
            return token, phone_number_id

        return None, None

    organization = getattr(whatsapp_phone, "organization", None)
    business_account = getattr(
        whatsapp_phone, "whatsapp_business_account", None
    )

    if not organization or not business_account:
        return None, None

    # Validate ownership relationships.
    if (
        whatsapp_phone.organization_id
        != business_account.organization_id
    ):
        return None, None

    if organization.status != "active":
        return None, None

    if (
        not whatsapp_phone.is_active
        or whatsapp_phone.status != "connected"
        or not whatsapp_phone.phone_number_id
    ):
        return None, None

    if (
        not business_account.is_active
        or business_account.status != "connected"
    ):
        return None, None

    connection = (
        WhatsAppConnection.objects
        .filter(
            organization=organization,
            whatsapp_business_account=business_account,
            status="connected",
        )
        .first()
    )

    access_token = (
        connection.access_token
        if connection and connection.access_token
        else None
    )

    # Global credentials are reserved exclusively for Faltasi.
    is_platform_owner = (
        organization.organization_type == "platform_owner"
    )

    if not access_token and is_platform_owner:
        access_token = getattr(
            settings,
            "WHATSAPP_ACCESS_TOKEN",
            None,
        )

    if not access_token:
        return None, None

    return access_token, whatsapp_phone.phone_number_id


def customer_phone_allows_whatsapp(whatsapp_phone, phone_number):
    """
    Prevent outbound WhatsApp sends to inactive, blocked, or removed
    customer phone channels.

    Check both current customer records and retained conversation
    history within the receiving organization.

    Unknown recipients retain existing behavior.
    """
    if not whatsapp_phone or not phone_number:
        return False

    organization = whatsapp_phone.organization
    raw_phone = str(phone_number).strip()

    if not raw_phone:
        return False

    normalized = normalize_phone_number(raw_phone)

    candidates = {raw_phone}

    if normalized:
        candidates.add(str(normalized).strip())
        candidates.add(str(normalized).strip().lstrip("+"))

    candidates.discard("")

    # Check all customer records associated with this number.
    customers = Customer.objects.filter(
        organization=organization,
        phone__in=candidates,
    )

    for customer in customers:
        if (
            customer.phone_status != "active"
            or customer.status != "active"
        ):
            print(
                "WHATSAPP SEND BLOCKED:",
                "Customer ID:", customer.id,
                "Phone status:", customer.phone_status,
                "Customer status:", customer.status,
            )
            return False

    # Also check retained conversations. This catches removed phone
    # numbers and older customer records linked to the same number.
    prior_conversations = (
        Conversation.objects
        .filter(
            organization=organization,
            phone_number__in=candidates,
            customer__isnull=False,
        )
        .select_related("customer")
        .order_by("-last_message_at", "-id")
    )

    for conversation in prior_conversations:
        customer = conversation.customer

        if (
            customer.phone_status != "active"
            or customer.status != "active"
        ):
            print(
                "WHATSAPP SEND BLOCKED BY CONVERSATION HISTORY:",
                "Customer ID:", customer.id,
                "Phone status:", customer.phone_status,
                "Customer status:", customer.status,
            )
            return False

    return True

def send_whatsapp_template(
    whatsapp_phone,
    phone_number,
    template_name,
    language_code="en_US",
    components=None,
):
    """Send an approved WhatsApp template using the authorized sender."""
    import requests

    if not phone_number or not template_name:
        print("WHATSAPP TEMPLATE ERROR: Missing required parameters.")
        return None

    if not customer_phone_allows_whatsapp(
        whatsapp_phone,
        phone_number,
    ):
        print("WHATSAPP TEMPLATE BLOCKED: Customer phone is not active.")
        return None

    access_token, phone_number_id = (
        _get_whatsapp_sender_credentials(whatsapp_phone)
    )

    if not access_token or not phone_number_id:
        print("WHATSAPP TEMPLATE ERROR: Sender validation failed.")
        return None

    try:
        url = (
            f"https://graph.facebook.com/v26.0/"
            f"{phone_number_id}/messages"
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        template = {
            "name": str(template_name).strip(),
            "language": {
                "code": str(language_code).strip(),
            },
        }

        if components:
            template["components"] = components

        payload = {
            "messaging_product": "whatsapp",
            "to": str(phone_number).strip().lstrip("+"),
            "type": "template",
            "template": template,
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        print(
            "WHATSAPP TEMPLATE STATUS:",
            response.status_code,
        )

        return response

    except requests.RequestException as exc:
        print(
            "WHATSAPP TEMPLATE REQUEST ERROR:",
            exc.__class__.__name__,
        )
        return None

    except Exception as exc:
        print(
            "WHATSAPP TEMPLATE GENERAL ERROR:",
            exc.__class__.__name__,
        )
        return None

def send_whatsapp_message(whatsapp_phone, phone_number, message):
    """Send a WhatsApp text message using the authorized sender."""
    import requests

    if not phone_number or not message:
        print("WHATSAPP SEND ERROR: Recipient or message is empty.")
        return None

    if not customer_phone_allows_whatsapp(
        whatsapp_phone,
        phone_number,
    ):
        print("WHATSAPP SEND BLOCKED: Customer phone is not active.")
        return None

    access_token, phone_number_id = (
        _get_whatsapp_sender_credentials(whatsapp_phone)
    )

    if not access_token or not phone_number_id:
        print("WHATSAPP SEND ERROR: Sender validation failed.")
        return None

    try:
        url = (
            f"https://graph.facebook.com/v26.0/"
            f"{phone_number_id}/messages"
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": str(phone_number).strip().lstrip("+"),
            "type": "text",
            "text": {"body": message},
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        print("WHATSAPP SEND STATUS:", response.status_code)

        return response

    except requests.RequestException as exc:
        print(
            "WHATSAPP SEND REQUEST ERROR:",
            exc.__class__.__name__,
        )
        return None

    except Exception as exc:
        print(
            "WHATSAPP SEND GENERAL ERROR:",
            exc.__class__.__name__,
        )
        return None


def send_whatsapp_image(
    whatsapp_phone,
    phone_number,
    image_url,
    caption="",
):
    """Send a product image using the authorized WhatsApp sender."""
    import requests

    if not image_url or not phone_number:
        print("WHATSAPP IMAGE ERROR: Missing image or recipient.")
        return None

    if not customer_phone_allows_whatsapp(whatsapp_phone, phone_number):
        return None

    access_token, phone_number_id = (
        _get_whatsapp_sender_credentials(whatsapp_phone)
    )

    if not access_token or not phone_number_id:
        print("WHATSAPP IMAGE ERROR: Sender validation failed.")
        return None

    try:
        url = (
            f"https://graph.facebook.com/v26.0/"
            f"{phone_number_id}/messages"
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": str(phone_number).strip().lstrip("+"),
            "type": "image",
            "image": {"link": image_url},
        }

        if caption:
            payload["image"]["caption"] = caption[:1024]

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        print("WHATSAPP IMAGE STATUS:", response.status_code)

        return response

    except requests.RequestException as exc:
        print(
            "WHATSAPP IMAGE REQUEST ERROR:",
            exc.__class__.__name__,
        )
        return None

    except Exception as exc:
        print(
            "WHATSAPP IMAGE GENERAL ERROR:",
            exc.__class__.__name__,
        )
        return None


def send_product_marketing_template(
    customer,
    whatsapp_phone,
    phone_number,
    conversation,
    incoming_message_id,
):
    """
    Send and log the product marketing template.

    Explicit marketing consent and an active customer phone are both
    required. Duplicate sends and cross-organization sends are blocked.
    """

    if (
        not customer
        or not whatsapp_phone
        or not conversation
        or not phone_number
        or not incoming_message_id
    ):
        return False

    organization = customer.organization

    if not organization:
        print("MARKETING TEMPLATE BLOCKED: Customer has no organization.")
        return False

    # Enforce tenant isolation and conversation ownership.
    if (
        customer.organization_id != organization.id
        or conversation.organization_id != organization.id
        or whatsapp_phone.organization_id != organization.id
        or conversation.customer_id != customer.id
    ):
        print("MARKETING TEMPLATE BLOCKED: Organization or customer mismatch.")
        return False

    # Explicit marketing consent is mandatory.
    if not customer.whatsapp_marketing_opt_in:
        print("MARKETING TEMPLATE BLOCKED: No marketing consent.")
        return False

    # Customer and phone must both be active.
    if customer.status != "active":
        print("MARKETING TEMPLATE BLOCKED: Customer is inactive.")
        return False

    if customer.phone_status != "active":
        print("MARKETING TEMPLATE BLOCKED: Customer phone is not active.")
        return False

    # The recipient must match the customer's registered phone.
    recipient_normalized = normalize_phone_number(phone_number)
    customer_normalized = normalize_phone_number(customer.phone)
    conversation_normalized = normalize_phone_number(
        conversation.phone_number
    )

    if (
        not recipient_normalized
        or not customer_normalized
        or not conversation_normalized
        or recipient_normalized != customer_normalized
        or recipient_normalized != conversation_normalized
    ):
        print("MARKETING TEMPLATE BLOCKED: Recipient phone mismatch.")
        return False

    # Apply the shared phone-status restriction as well.
    if not customer_phone_allows_whatsapp(
        whatsapp_phone,
        phone_number,
    ):
        print("MARKETING TEMPLATE BLOCKED: Phone restriction.")
        return False

    # Prevent duplicate sends for the same incoming message.
    already_sent = Message.objects.filter(
        organization=organization,
        conversation=conversation,
        direction="outgoing",
        metadata__template_name="product_enquiry_response",
        metadata__triggered_by_incoming_message_id=incoming_message_id,
    ).exists()

    if already_sent:
        print("DUPLICATE MARKETING TEMPLATE PREVENTED.")
        return False

    response = send_whatsapp_template(
        whatsapp_phone=whatsapp_phone,
        phone_number=phone_number,
        template_name="product_enquiry_response",
        language_code="en",
        components=None,
    )

    if response is None or response.status_code != 200:
        print("PRODUCT MARKETING TEMPLATE FAILED.")
        return False

    try:
        response_data = response.json()
    except ValueError:
        response_data = {"raw_response": response.text}

    template_message_id = None

    try:
        template_message_id = (
            response_data.get("messages", [{}])[0].get("id")
        )
    except (IndexError, AttributeError, TypeError):
        pass

    Message.objects.create(
        organization=organization,
        conversation=conversation,
        direction="outgoing",
        sender_type="faltasi",
        message_type="text",
        content="Marketing template: product_enquiry_response",
        whatsapp_message_id=template_message_id,
        delivery_status="sent",
        metadata={
            "template_name": "product_enquiry_response",
            "language_code": "en",
            "triggered_by_incoming_message_id": incoming_message_id,
            "provider_response": response_data,
        },
    )

    print("PRODUCT MARKETING TEMPLATE SENT AND LOGGED.")
    return True

def get_public_product_image_url(product, request=None):
    """Return an absolute HTTPS image URL that Meta can attempt to fetch."""
    try:
        if not product or not product.image:
            return None
        image_url = product.image.url
    except (AttributeError, ValueError, OSError) as exc:
        print("PRODUCT IMAGE URL ERROR:", str(exc))
        return None

    # Image storage may return a relative media path.
    if not urlsplit(image_url).scheme and request is not None:
        image_url = request.build_absolute_uri(image_url)

    parsed_url = urlsplit(image_url)

    # WhatsApp Cloud API requires a publicly reachable HTTPS URL.
    if parsed_url.scheme.lower() != "https" or not parsed_url.netloc:
        print(
            "PRODUCT IMAGE SKIPPED: image URL must be an absolute HTTPS URL.",
            "| PRODUCT:",
            getattr(product, "name", None),
        )
        return None

    return image_url


def send_and_log_whatsapp_product_image(
    whatsapp_phone,
    phone_number,
    product,
    conversation,
    organization,
    request=None,
):
    """Send one verified product image and save the WhatsApp message record."""

    if not all([
        whatsapp_phone,
        phone_number,
        product,
        conversation,
        organization,
    ]):
        print("WHATSAPP PRODUCT IMAGE BLOCKED: Missing required information.")
        return False

    # Enforce tenant isolation.
    if (
        whatsapp_phone.organization_id != organization.id
        or conversation.organization_id != organization.id
        or product.organization_id != organization.id
    ):
        print("WHATSAPP PRODUCT IMAGE BLOCKED: Organization mismatch.")
        return False

    # Do not send to inactive, blocked, or removed customer phones.
    if not customer_phone_allows_whatsapp(
        whatsapp_phone,
        phone_number,
    ):
        print("WHATSAPP PRODUCT IMAGE BLOCKED: Customer phone is not active.")
        return False

    image_url = get_public_product_image_url(
        product,
        request=request,
    )

    if not image_url:
        return False

    caption_lines = [product.name]

    if product.brand:
        caption_lines.append(f"Brand: {product.brand}")

    if product.model:
        caption_lines.append(f"Model: {product.model}")

    if product.price is not None:
        caption_lines.append(
            f"Price: {product.currency} {product.price:,.2f}"
        )
    else:
        caption_lines.append("Price available on request")

    caption_lines.append(
        f"Availability: {product.get_availability_display()}"
    )

    caption = "\n".join(caption_lines)[:1024]

    response = send_whatsapp_image(
        whatsapp_phone,
        phone_number,
        image_url,
        caption=caption,
    )

    succeeded = (
        response is not None
        and response.status_code in (200, 201)
    )

    try:
        response_data = (
            response.json()
            if response is not None
            else {
                "error": "No response received from WhatsApp image endpoint."
            }
        )
    except ValueError:
        response_data = {"raw_response": response.text}

    whatsapp_message_id = None

    try:
        whatsapp_message_id = (
            response_data.get("messages", [{}])[0].get("id")
        )
    except (AttributeError, IndexError, TypeError):
        whatsapp_message_id = None

    Message.objects.create(
        organization=organization,
        conversation=conversation,
        direction="outgoing",
        sender_type="faltasi",
        message_type="image",
        content=caption,
        whatsapp_message_id=whatsapp_message_id,
        delivery_status="sent" if succeeded else "failed",
        metadata={
            "product_id": product.id,
            "product_sku": product.sku,
            "image_url": image_url,
            "whatsapp_response": response_data,
        },
    )

    if succeeded:
        from django.utils import timezone

        conversation.last_message_at = timezone.now()
        conversation.save(update_fields=["last_message_at"])
    else:
        print(
            "WHATSAPP PRODUCT IMAGE FAILED:",
            getattr(response, "status_code", None),
            response_data,
        )

    return succeeded

def get_or_create_conversation_state(conversation):
    """
    Get the ConversationState for a conversation.
    Create it if it does not exist.
    """
    state, created = ConversationState.objects.get_or_create(conversation=conversation)
    if created:
        print('CONVERSATION STATE CREATED:', state)
    else:
        print('CONVERSATION STATE FOUND:', state)
    return state

def process_whatsapp_marketing_consent(customer, text):
    """
    Process explicit WhatsApp marketing consent commands.

    YES  = subscribe
    NO   = decline the subscription invitation
    STOP = unsubscribe

    Marketing consent belongs to the customer's
    organization-specific record.
    """

    if not customer or not text:
        return None

    command = text.strip().upper()

    if command == "YES":

        if not customer.whatsapp_marketing_opt_in:
            customer.whatsapp_marketing_opt_in = True
            customer.whatsapp_marketing_opt_in_at = timezone.now()
            customer.whatsapp_marketing_opt_in_source = "whatsapp_reply"

        customer.whatsapp_marketing_opt_out_at = None
        customer.whatsapp_marketing_declined_at = None

        customer.save(update_fields=[
            "whatsapp_marketing_opt_in",
            "whatsapp_marketing_opt_in_at",
            "whatsapp_marketing_opt_in_source",
            "whatsapp_marketing_opt_out_at",
            "whatsapp_marketing_declined_at",
            "updated_at",
        ])

        return (
            "Asante kwa ku subscribe na account yetu. Faltasi Tunauza bidhaa"
            ""
            ""
            " zenye ubora wa juu na zilizoadimu. "
            "tutakutaarifu pindi zitakapo wasili."
        )

    if command == "NO":

        # NO declines an invitation; it is not an unsubscribe
        # command and must not revoke existing consent.
        if not customer.whatsapp_marketing_opt_in:
            customer.whatsapp_marketing_declined_at = timezone.now()

            customer.save(update_fields=[
                "whatsapp_marketing_declined_at",
                "updated_at",
            ])

        return (
            "Thank you for your response. You will not receive "
            "WhatsApp marketing messages from this business. "
            "You can still contact us for enquiries and support."
        )

    if command == "STOP":

        customer.whatsapp_marketing_opt_in = False
        customer.whatsapp_marketing_opt_out_at = timezone.now()

        customer.save(update_fields=[
            "whatsapp_marketing_opt_in",
            "whatsapp_marketing_opt_out_at",
            "updated_at",
        ])

        return (
            "You have successfully unsubscribed from marketing "
            "messages from this business. You can still contact "
            "us for product enquiries and support."
        )

    return None

def create_business_request(
    customer,
    text,
    category,
    conversation=None
):
    """
    Create or reuse a BusinessRequest for a WhatsApp conversation.

    Behavior:

    1. No category:
       Do not create a request.

    2. Existing request with SAME category:
       Continue using the existing request.

    3. Existing request with DIFFERENT category:
       Create a NEW BusinessRequest.

    4. No existing request:
       Create a NEW BusinessRequest.
    """

    # ---------------------------------------------------------
    # NO CATEGORY
    # ---------------------------------------------------------

    if not category:

        print(
            "NO REQUEST CATEGORY IDENTIFIED"
        )

        return None
    if (
        not customer.organization_id
        or not category.organization_id
        or customer.organization_id != category.organization_id
    ):
        print("REQUEST REJECTED: ORGANIZATION MISMATCH")
        return None

    if (
        category.department_id
        and category.department.organization_id
        != category.organization_id
    ):
        print("REQUEST REJECTED: DEPARTMENT ORGANIZATION MISMATCH")
        return None


    # ---------------------------------------------------------
    # CHECK EXISTING REQUEST
    # ---------------------------------------------------------

    if conversation and conversation.business_request:

        existing_request = (
            conversation.business_request
        )

        print(
            "EXISTING CONVERSATION REQUEST FOUND:",
            existing_request
        )

        # -----------------------------------------------------
        # SAME CATEGORY
        # -----------------------------------------------------

        if (
            existing_request.category_id
            == category.id
        ):

            print(
                "SAME CATEGORY - CONTINUING EXISTING REQUEST:",
                category.name
            )

            return existing_request


        # -----------------------------------------------------
        # DIFFERENT CATEGORY
        # -----------------------------------------------------

        print(
            "NEW CATEGORY DETECTED:",
            category.name
        )

        print(
            "PREVIOUS CATEGORY:",
            existing_request.category
        )

        print(
            "CREATING NEW BUSINESS REQUEST..."
        )


    # ---------------------------------------------------------
    # CREATE NEW BUSINESS REQUEST
    # ---------------------------------------------------------

    business_request = (
        BusinessRequest.objects.create(
            customer=customer,
            request_text=text,
            subject=category.name,
            category=category,
            department=category.department,
            status="new",
            priority="normal",
            source="whatsapp",
        )
    )


    print(
        "BUSINESS REQUEST CREATED:",
        business_request
    )

    print(
        "REQUEST CATEGORY:",
        category.name
    )

    print(
        "REQUEST DEPARTMENT:",
        category.department
    )


    return business_request

def get_whatsapp_phone_number(phone_number_id):
    """
    Find the WhatsApp phone number configuration from
    Meta's phone_number_id.
    """

    if not phone_number_id:
        print("NO WHATSAPP PHONE NUMBER ID FOUND")
        return None

    try:
        whatsapp_phone = (
            WhatsAppPhoneNumber.objects
            .select_related(
                "organization",
                "whatsapp_business_account",
            )
            .get(
                phone_number_id=phone_number_id,
                is_active=True,
            )
        )

        print("WHATSAPP PHONE FOUND:", whatsapp_phone)
        print("ORGANIZATION:", whatsapp_phone.organization)
        print(
            "WABA:",
            whatsapp_phone.whatsapp_business_account,
        )

        return whatsapp_phone

    except WhatsAppPhoneNumber.DoesNotExist:

        print(
            "NO WHATSAPP PHONE CONFIGURED FOR PHONE NUMBER ID:",
            phone_number_id,
        )

        return None

    except WhatsAppPhoneNumber.MultipleObjectsReturned:

        print(
            "ERROR: MULTIPLE WHATSAPP PHONES FOUND FOR PHONE NUMBER ID:",
            phone_number_id,
        )

        return None

def is_new_request_message(
    text,
    current_category=None,
    current_field=None,
    organization=None
):
    """
    Determine whether an incoming message appears to start
    a new business request instead of answering the current question.

    The function is intentionally conservative.

    Important behavior:
    - If there is no active request, a detected category starts a new request.
    - If the detected category is the same as the current category,
      continue the current request.
    - If the customer is answering a text field, continue the current request.
    - Location, address, name, email, phone, and other field answers
      should not easily be interpreted as new requests.
    - A new request requires stronger evidence.
    """

    if not text or not text.strip():
        return False

    normalized = text.lower().strip()

    detected_category = find_request_category(
        text,
        organization=organization
    )

    # -----------------------------------------------------
    # No detected category
    #
    # Without a category, we normally cannot confidently say
    # that the customer is starting a new request.
    # -----------------------------------------------------

    if not detected_category:
        return False

    # -----------------------------------------------------
    # No active category
    #
    # If there is no current request and we detected a
    # category, this is a new request.
    # -----------------------------------------------------

    if not current_category:
        return True

    # -----------------------------------------------------
    # Same category
    #
    # The customer is most likely continuing the current
    # request.
    # -----------------------------------------------------

    if detected_category.id == current_category.id:
        return False

    # -----------------------------------------------------
    # If we are currently collecting a field, be conservative.
    #
    # A customer can mention another product/service while
    # answering a field. We should not immediately create
    # another request unless there is strong evidence.
    # -----------------------------------------------------

    if current_field:

        # -------------------------------------------------
        # Text fields
        # -------------------------------------------------

        if current_field.field_type == "text":
            return False

        # -------------------------------------------------
        # Location/address fields
        #
        # Location answers can contain many words and may
        # accidentally contain category keywords.
        # -------------------------------------------------

        field_name = (
            getattr(current_field, "name", None)
            or getattr(current_field, "field_name", None)
            or getattr(current_field, "key", None)
            or ""
        )

        field_name_normalized = field_name.lower().strip()

        location_keywords = [
            "location",
            "address",
            "area",
            "city",
            "region",
            "place",
            "where",
        ]

        if any(
            keyword in field_name_normalized
            for keyword in location_keywords
        ):
            return False

        # -------------------------------------------------
        # Validate the current field.
        # -------------------------------------------------

        valid, cleaned_value = (
            validate_request_field_value(
                current_field,
                text
            )
        )

        print(
            "NEW REQUEST FIELD VALIDATION:",
            valid,
            cleaned_value
        )

        # If the customer provided a valid answer to the
        # current field, it is NOT a new request.
        if valid:
            return False

    # -----------------------------------------------------
    # Strong phrases indicating a NEW request
    # -----------------------------------------------------

    explicit_new_request_phrases = [
        "i also need",
        "i also want",
        "i also would like",
        "i'd also like",
        "i would also like",

        "i need another",
        "i want another",

        "another request",
        "another service",
        "another product",

        "different request",
        "different service",
        "different product",

        "actually i need",
        "actually i want",
        "actually i would like",
        "actually i'd like",

        "by the way i need",
        "by the way i want",
        "by the way i'd like",

        "can you also provide",
        "can you also help",

        "i need a separate",
        "i want a separate",
    ]

    if any(
        phrase in normalized
        for phrase in explicit_new_request_phrases
    ):
        return True

    # -----------------------------------------------------
    # Strong request language
    #
    # Only use this when the customer has NOT successfully
    # answered the current field.
    # -----------------------------------------------------

    request_phrases = [
        "i need",
        "i want",
        "i would like",
        "i'd like",
        "looking for",
        "can you provide",
        "can you help",
        "quotation for",
        "quote for",
    ]

    if any(
        phrase in normalized
        for phrase in request_phrases
    ):
        return True

    # -----------------------------------------------------
    # Default
    #
    # Continue the current request unless there is strong
    # evidence that the customer started another request.
    # -----------------------------------------------------

    return False
def process_request_fields(category, state, text):
    """
    Handle category-specific questions using RequestField
    and ConversationState.
    """
    collected_data = state.data or {}
    waiting_for = state.waiting_for
    if waiting_for:
        try:
            field = category.request_fields.get(name=waiting_for, is_active=True)
        except Exception:
            field = None
        if field:
            if not field.is_required:
                normalized = text.lower().strip()
                skip_values = ['no', 'no budget', "i don't know", 'i dont know', 'not sure', 'not certain', 'no idea', 'i have no idea', "don't have a budget", 'dont have a budget', "i don't have a budget", 'i dont have a budget', 'not decided', 'not decided yet']
                if normalized in skip_values:
                    collected_data[waiting_for] = None
                    update_conversation_state(state, data=collected_data)
                else:
                    valid, cleaned_value = validate_request_field_value(field, text)
                    if valid:
                        collected_data[waiting_for] = cleaned_value
                        update_conversation_state(state, data=collected_data)
                    else:
                        return f'Iâ€™m sorry, I didnâ€™t quite understand that.\n\n{field.question}'
            else:
                valid, cleaned_value = validate_request_field_value(field, text)
                if not valid:
                    return f'Iâ€™m sorry, I didnâ€™t quite understand that answer.\n\n{field.question}'
                collected_data[waiting_for] = cleaned_value
                update_conversation_state(state, data=collected_data)
    next_field = get_next_missing_request_field(category, collected_data)
    if next_field:
        update_conversation_state(state, current_step='collecting_details', waiting_for=next_field.name, data=collected_data)
        return next_field.question
    update_conversation_state(state, current_step='details_collected', waiting_for=None, data=collected_data)
    return 'Thank you. We now have the information we need. Our team will review your request and get back to you shortly.'

def update_business_request_details(business_request, state):
    """
    Add the customer's collected conversation details
    to the BusinessRequest.
    """

    if not business_request or not state:
        return business_request

    collected_data = state.data or {}

    if not collected_data:
        return business_request

    # Keep the original customer request
    original_request = collected_data.get("request_text")

    if not original_request:
        original_request = business_request.request_text

    # Build a readable summary
    details = []

    for field_name, value in collected_data.items():

        # Don't display internal conversation values
        if field_name in [
            "request_text",
            "category",
            "business_request_id",
        ]:
            continue

        # Convert internal values into human-readable values
        display_value = value

        if value is True:
            display_value = "Yes"
        elif value is False:
            display_value = "No"
        elif value is None:
            display_value = "Not provided"

        details.append(
            f"{field_name.replace('_', ' ').title()}: {display_value}"
        )

    if details:
        business_request.request_text = (
            f"{original_request}\n\n"
            "Collected Details:\n"
            + "\n".join(details)
        )

        business_request.save(
            update_fields=["request_text", "updated_at"]
        )

    print(
        "BUSINESS REQUEST UPDATED WITH DETAILS:",
        business_request
    )

    return business_request

def create_request_workflow(business_request):
    """
    Create the initial workflow for a business request and automatically
    assign it to the active department member with the fewest active requests.

    A staff notification is sent only when a new staff assignment is created.
    Existing assignments do not trigger duplicate notifications.
    """

    # ---------------------------------------------------------
    # 1. Get department
    # ---------------------------------------------------------

    department = business_request.department

    if not department:
        print("========== WORKFLOW ERROR ==========")
        print(
            f"Request #{business_request.id} has no department."
        )
        return None

    organization = department.organization

    print("========== CREATE REQUEST WORKFLOW ==========")
    print("REQUEST:", business_request.id)
    print("ORGANIZATION:", organization.name)
    print("DEPARTMENT:", department.name)

    # ---------------------------------------------------------
    # 2. Check whether this request already has a current
    #    assignment
    # ---------------------------------------------------------

    current_assignment = (
        RequestAssignment.objects
        .filter(
            request=business_request,
            is_current=True,
        )
        .select_related(
            "assigned_to",
            "department",
        )
        .first()
    )

    new_staff_assignment = False

    if current_assignment:

        assigned_user = current_assignment.assigned_to

        print(
            "CURRENT ASSIGNMENT ALREADY EXISTS:",
            current_assignment.id,
        )

        if assigned_user:
            print(
                "ALREADY ASSIGNED TO:",
                assigned_user.username,
                assigned_user.get_full_name(),
            )
        else:
            print(
                "CURRENT ASSIGNMENT HAS NO STAFF MEMBER."
            )

    else:

        # -----------------------------------------------------
        # 3. Find active members of this department
        # -----------------------------------------------------

        department_members = (
            DepartmentMember.objects
            .filter(
                department=department,
                is_active=True,
                user__is_active=True,
                user__organization_memberships__organization=organization,
                user__organization_memberships__is_active=True,
            )
            .select_related("user")
            .distinct()
        )

        print(
            "ACTIVE DEPARTMENT MEMBERS:",
            department_members.count(),
        )

        # -----------------------------------------------------
        # 4. Find staff member with fewest active requests
        # -----------------------------------------------------

        selected_member = None
        selected_active_count = None

        for member in department_members:

            active_request_count = (
                RequestAssignment.objects
                .filter(
                    assigned_to=member.user,
                    is_current=True,
                    request__status__in=[
                        "new",
                        "in_progress",
                    ],
                )
                .count()
            )

            print(
                "STAFF:",
                member.user.username,
                "| ACTIVE REQUESTS:",
                active_request_count,
            )

            if (
                selected_member is None
                or active_request_count < selected_active_count
            ):
                selected_member = member
                selected_active_count = active_request_count

        # -----------------------------------------------------
        # 5. Create assignment
        # -----------------------------------------------------

        if selected_member:

            assigned_user = selected_member.user

            print(
                "AUTO ASSIGNING TO:",
                assigned_user.username,
                assigned_user.get_full_name(),
            )

            print(
                "ACTIVE REQUEST COUNT:",
                selected_active_count,
            )

            current_assignment = (
                RequestAssignment.objects.create(
                    request=business_request,
                    department=department,
                    assigned_to=assigned_user,
                    is_current=True,
                    assigned_at=timezone.now(),
                    notes=(
                        "Automatically assigned based on "
                        "current staff workload."
                    ),
                )
            )

            new_staff_assignment = True

            print(
                "ASSIGNMENT CREATED:",
                current_assignment.id,
            )

        else:

            assigned_user = None

            print(
                "NO ACTIVE STAFF AVAILABLE FOR DEPARTMENT:",
                department.name,
            )

            current_assignment = (
                RequestAssignment.objects.create(
                    request=business_request,
                    department=department,
                    assigned_to=None,
                    is_current=True,
                    assigned_at=timezone.now(),
                    notes=(
                        "Waiting for an available department "
                        "staff member."
                    ),
                )
            )

            print(
                "UNASSIGNED REQUEST CREATED:",
                current_assignment.id,
            )

    # ---------------------------------------------------------
    # 6. Create or update Department Review workflow
    # ---------------------------------------------------------

    workflow_step = (
        WorkflowStep.objects
        .filter(
            request=business_request,
            name="Department Review",
        )
        .first()
    )

    if not workflow_step:

        workflow_step = WorkflowStep.objects.create(
            request=business_request,
            name="Department Review",
            status="active",
            assigned_to=assigned_user,
        )

        print(
            "WORKFLOW STEP CREATED:",
            workflow_step.id,
        )

    else:

        if workflow_step.assigned_to != assigned_user:

            workflow_step.assigned_to = assigned_user

            workflow_step.save(
                update_fields=[
                    "assigned_to",
                ]
            )

            print(
                "WORKFLOW STEP ASSIGNMENT UPDATED:",
                workflow_step.id,
            )

        else:

            print(
                "WORKFLOW STEP ALREADY CORRECTLY ASSIGNED:",
                workflow_step.id,
            )

    # ---------------------------------------------------------
    # 7. Update request status
    # ---------------------------------------------------------

    if assigned_user:

        if business_request.status != "in_progress":

            business_request.status = "in_progress"

            business_request.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            print(
                "REQUEST STATUS UPDATED:",
                business_request.status,
            )

        else:

            print(
                "REQUEST STATUS:",
                business_request.status,
            )

    else:

        print(
            "REQUEST HAS NO STAFF ASSIGNED."
        )

        print(
            "REQUEST STATUS REMAINS:",
            business_request.status,
        )

    # ---------------------------------------------------------
    # 8. Notify staff only when a NEW assignment was created
    # ---------------------------------------------------------

    if new_staff_assignment and assigned_user:

        print(
            "SENDING STAFF ASSIGNMENT NOTIFICATION..."
        )

        notification_result = notify_assigned_staff(
            business_request,
            current_assignment,
        )

        print(
            "STAFF NOTIFICATION RESULT:",
            notification_result,
        )

    elif assigned_user:

        print(
            "STAFF NOTIFICATION SKIPPED:",
            "assignment already existed.",
        )

    else:

        print(
            "STAFF NOTIFICATION SKIPPED:",
            "no staff member assigned.",
        )

    print("==============================================")

    return current_assignment


def notify_assigned_staff(business_request, assignment):
    """
    Notify the staff member assigned to a business request.

    The notification is sent by email when:
    - an assignment exists
    - a staff member is assigned
    - the staff member has an email address
    """

    if not assignment:
        print("NOTIFICATION SKIPPED: No assignment.")
        return False

    assigned_user = assignment.assigned_to

    if not assigned_user:
        print("NOTIFICATION SKIPPED: No staff member assigned.")
        return False

    if not assigned_user.email:
        print(
            "NOTIFICATION SKIPPED:",
            assigned_user.username,
            "has no email address."
        )
        return False

    customer = business_request.customer
    department = business_request.department

    subject = (
        f"New Business Request #{business_request.id} "
        f"Assigned to You"
    )

    message = f"""
Hello {assigned_user.get_full_name() or assigned_user.username},

A new business request has been assigned to you.

Request ID:
#{business_request.id}

Subject:
{business_request.subject or "No subject"}

Department:
{department.name if department else "Not specified"}

Customer:
{customer.name if customer else "Not specified"}

Customer Phone:
{customer.phone if customer else "Not specified"}

Request:
{business_request.request_text}

Priority:
{business_request.priority}

Status:
{business_request.status}

Please log in to the Faltasi platform to review and process this request.

Regards,
Faltasi WhatsApp Platform
""".strip()

    try:

        send_mail(
            subject=subject,
            message=message,
            from_email=None,
            recipient_list=[assigned_user.email],
            fail_silently=False,
        )

        print("========== STAFF NOTIFICATION ==========")
        print(
            "NOTIFICATION SENT TO:",
            assigned_user.email,
        )
        print(
            "REQUEST:",
            business_request.id,
        )
        print(
            "STAFF:",
            assigned_user.username,
        )
        print("========================================")

        return True

    except Exception as e:

        print("========== STAFF NOTIFICATION ERROR ==========")
        print("ERROR:", str(e))
        print("==============================================")

        return False

@csrf_exempt

def get_ai_product_reply(text, organization, state, current_message_id):
    """
    Provide optional AI assistance for questions about an already
    selected WhatsApp product.

    AI is allowed only in an idle or completed product conversation.
    Django retains control of all business-request and product workflows.
    """
    if not text or not organization or not state:
        return None

    state_data = state.data if isinstance(state.data, dict) else {}

    if not state_data.get("selected_whatsapp_product_id"):
        return None

    # Never allow product AI to take over a business-request workflow.
    if state_data.get("category") or state_data.get("business_request_id"):
        return None

    # A pending field means the customer is expected to answer the
    # existing workflow, not receive an AI product response.
    if getattr(state, "waiting_for", None):
        return None

    # Also inspect the linked conversation. The database relationship
    # is authoritative even if state JSON is incomplete.
    conversation = getattr(state, "conversation", None)

    if conversation is not None:
        if getattr(conversation, "business_request_id", None):
            return None

        if getattr(conversation, "business_request", None):
            return None

    # Permit only a genuinely idle state or a completed product flow.
    # Unknown/future workflow states are blocked by default.
    allowed_steps = {
        None,
        "whatsapp_product_completed",
    }

    if getattr(state, "current_step", None) not in allowed_steps:
        return None

    try:
        from .ai_service import interpret_product_message

        result = interpret_product_message(
            text,
            organization,
            state,
            current_message_id=current_message_id,
        )

        if not isinstance(result, dict):
            return None

        if result.get("action") not in {
            "answer_product",
            "clarify_product",
        }:
            return None

        answer = result.get("answer")

        if not isinstance(answer, str):
            return None

        answer = answer.strip()

        if not answer or len(answer) > 2000:
            return None

        return answer

    except Exception:
        # AI is optional. Preserve the existing WhatsApp fallback
        # if configuration, provider, validation or database errors occur.
        import logging
        logging.getLogger(__name__).exception(
            "WhatsApp AI product assistance failed; using normal fallback."
        )
        return None


@csrf_exempt
def webhook(request):

    """

    WhatsApp Cloud API webhook.



    Handles:

    - Meta webhook verification

    - Multi-business WhatsApp routing

    - Incoming WhatsApp text messages

    - Duplicate message protection

    - Organization-specific customers

    - Organization-specific conversations

    - Conversation state

    - Request category detection

    - BusinessRequest creation/reuse

    - RequestField-based information collection

    - New request detection

    - Automatic WhatsApp replies

    - Outgoing message logging

    """



    # =====================================================

    # META WEBHOOK VERIFICATION

    # =====================================================



    if request.method == "GET":



        verify_token = request.GET.get("hub.verify_token")

        challenge = request.GET.get("hub.challenge")



        print("VERIFY TOKEN RECEIVED")

        print("CHALLENGE:", challenge)



        if verify_token and challenge:



            if verify_token == settings.WHATSAPP_VERIFY_TOKEN:



                print("VERIFICATION SUCCESS")



                return HttpResponse(challenge)



            print("VERIFICATION FAILED")



            return HttpResponse(

                "Invalid verify token",

                status=403,

            )



        return HttpResponse("OK", status=200)



    # =====================================================

    # ONLY POST REQUESTS ARE ACCEPTED

    # =====================================================



    if request.method != "POST":
        return HttpResponse(status=405)
    # Verify Meta's signature before processing any POST data.
    if not verify_meta_webhook_signature(request):
        return HttpResponse("Invalid webhook signature", status=403)



    print("========== WHATSAPP POST RECEIVED ==========")



    try:



        # =================================================

        # READ REQUEST BODY

        # =================================================



        body = request.body.decode(

            "utf-8",

            errors="replace",

        )



        print("WEBHOOK BODY RECEIVED")



        data = json.loads(body)



        print(

            "WEBHOOK JSON:",

            json.dumps(

                data,

                indent=2,

            ),

        )



        # =================================================

        # READ WEBHOOK STRUCTURE

        # =================================================



        entry = data.get("entry", [])



        if not entry:



            print("NO WEBHOOK ENTRY FOUND")



            return JsonResponse({

                "status": "ok",

            })



        changes = entry[0].get("changes", [])



        if not changes:



            print("NO WEBHOOK CHANGES FOUND")



            return JsonResponse({

                "status": "ok",

            })



        value = changes[0].get("value", {})



        # =================================================

        # IDENTIFY THE WHATSAPP PHONE NUMBER

        # =================================================



        metadata = value.get("metadata", {})



        phone_number_id = metadata.get(

            "phone_number_id"

        )



        print(

            "META PHONE NUMBER ID:",

            phone_number_id,

        )



        if not phone_number_id:



            print(

                "NO PHONE NUMBER ID FOUND IN WEBHOOK"

            )



            return JsonResponse({

                "status": "ok",

                "message": "No phone number ID found",

            })



        # =================================================

        # FIND WHATSAPP PHONE NUMBER

        # =================================================



        try:



            whatsapp_phone = (

                WhatsAppPhoneNumber.objects

                .select_related(

                    "organization",

                    "whatsapp_business_account",

                )

                .get(

                    phone_number_id=phone_number_id,
                )

            )



        except WhatsAppPhoneNumber.DoesNotExist:



            print(

                "UNKNOWN WHATSAPP PHONE NUMBER:",

                phone_number_id,

            )



            return JsonResponse({

                "status": "ok",

                "message": "Unknown WhatsApp phone number",

            })



        except WhatsAppPhoneNumber.MultipleObjectsReturned:



            print(

                "MULTIPLE WHATSAPP PHONE NUMBERS FOUND:",

                phone_number_id,

            )



            return JsonResponse({

                "status": "ok",

                "message": "Multiple WhatsApp phone numbers found",

            })



        # =================================================

        # IDENTIFY ORGANIZATION

        # =================================================



        organization = whatsapp_phone.organization



        whatsapp_business_account = (

            whatsapp_phone.whatsapp_business_account

        )



        print(

            "WHATSAPP PHONE:",

            whatsapp_phone,

        )



        print(

            "ORGANIZATION:",

            organization,

        )



        print(

            "WHATSAPP BUSINESS ACCOUNT:",

            whatsapp_business_account,

        )
        # Security: verify that the phone number and
        # WhatsApp Business Account belong to one organization.
        if (
            whatsapp_phone.organization_id
            != whatsapp_business_account.organization_id
        ):
            print(
                "WHATSAPP ORGANIZATION MISMATCH:",
                whatsapp_phone.id,
            )
            return JsonResponse(
                {
                    "status": "ok",
                    "message": "WhatsApp organization mismatch",
                },
                status=403,
            )






        # =================================================
        # PROCESS OUTGOING MESSAGE DELIVERY STATUSES
        # =================================================

        statuses = value.get("statuses", [])

        if statuses:
            print("WHATSAPP STATUS UPDATE RECEIVED")

            for status_item in statuses:
                whatsapp_message_id = status_item.get("id")
                new_status = status_item.get("status")

                print("MESSAGE ID:", whatsapp_message_id)
                print("NEW STATUS:", new_status)
                print("RECIPIENT ID:", status_item.get("recipient_id"))

                if new_status == "failed":
                    print("WHATSAPP DELIVERY FAILURE DETAILS:", flush=True)
                    print(
                        json.dumps(
                            status_item.get("errors", []),
                            indent=2,
                            ensure_ascii=False,
                        ),
                         flush=True,
                    )

                allowed_statuses = {
                    "sent",
                    "delivered",
                    "read",
                    "failed",
                }

                if (
                    not whatsapp_message_id
                    or new_status not in allowed_statuses
                ):
                    print("INVALID OR INCOMPLETE STATUS UPDATE")
                    continue

                saved_message = Message.objects.filter(
                    organization=organization,
                    whatsapp_message_id=whatsapp_message_id,
                    direction="outgoing",
                ).first()

                if not saved_message:
                    print(
                        "OUTGOING MESSAGE NOT FOUND:",
                        whatsapp_message_id,
                    )
                    continue

                current_status = saved_message.delivery_status

                # Do not allow an older status to overwrite
                # a more advanced status.
                status_order = {
                    "pending": 0,
                    "sent": 1,
                    "delivered": 2,
                    "read": 3,
                    "failed": 4,
                }

                if current_status == "failed":
                    print("MESSAGE ALREADY MARKED FAILED")
                    continue

                if (
                    new_status != "failed"
                    and status_order.get(new_status, 0)
                    < status_order.get(current_status, 0)
                ):
                    print("OLDER STATUS IGNORED")
                    continue

                if (
                    new_status == "failed"
                    and current_status in {"delivered", "read"}
                ):
                    print("FAILURE STATUS IGNORED: MESSAGE ALREADY DELIVERED")
                    continue

                saved_message.delivery_status = new_status

                message_metadata = saved_message.metadata or {}
                message_metadata["whatsapp_status_update"] = status_item
                saved_message.metadata = message_metadata

                saved_message.save(
                    update_fields=[
                        "delivery_status",
                        "metadata",
                    ]
                )

                print(
                    "MESSAGE STATUS UPDATED:",
                    current_status,
                    "->",
                    new_status,
                )




        # =================================================

        # GET MESSAGES

        # =================================================



        messages = value.get("messages", [])
        # =================================================
        # VALIDATE INCOMING WHATSAPP CONNECTION
        # =================================================

        if messages:

            connection_is_valid = (
                organization.status == "active"
                and whatsapp_phone.is_active
                and whatsapp_phone.status == "connected"
                and whatsapp_business_account.is_active
                and whatsapp_business_account.status == "connected"
            )

            if not connection_is_valid:
                print(
                    "INCOMING MESSAGE REJECTED: "
                    "WHATSAPP CONNECTION INACTIVE"
                )

                return JsonResponse({
                    "status": "ok",
                    "message": "WhatsApp connection is inactive",
                })



        if not messages:



            print(

                "NO WHATSAPP MESSAGE FOUND"

            )



            return JsonResponse({

                "status": "ok",

            })



        # =================================================

        # PROCESS FIRST MESSAGE

        # =================================================



        message = messages[0]



        whatsapp_message_id = message.get("id")



        print(

            "WHATSAPP MESSAGE ID:",

            whatsapp_message_id,

        )



        # =================================================

        # DUPLICATE MESSAGE PROTECTION

        # =================================================



        if whatsapp_message_id:



            existing_message = (

                Message.objects.filter(
                    organization=organization,
                    whatsapp_message_id=whatsapp_message_id
                ).first()

            )



            if existing_message:



                print(

                    "DUPLICATE MESSAGE IGNORED:",

                    whatsapp_message_id,

                )



                return JsonResponse({

                    "status": "ok",

                    "duplicate": True,

                })



        # =================================================

        # MESSAGE INFORMATION

        # =================================================



        sender = normalize_phone_number(

            message.get("from")

        )



        message_type = message.get("type")



        print(

            "SENDER:",

            sender,

        )



        print(

            "MESSAGE TYPE:",

            message_type,

        )



        # =================================================

        # CURRENT SYSTEM SUPPORTS TEXT MESSAGES

        # =================================================



        if message_type != "text":



            print(

                "NON-TEXT MESSAGE RECEIVED:",

                message_type,

            )



            return JsonResponse({

                "status": "ok",

                "message": "Non-text message received",

            })



        # =================================================

        # GET TEXT

        # =================================================



        text = (

            message

            .get("text", {})

            .get("body", "")

            .strip()

        )



        print(

            "MESSAGE TEXT:",

            text,

        )



        if not sender:



            print(

                "NO SENDER FOUND"

            )



            return JsonResponse({

                "status": "ok",

            })



        if not text:



            print(

                "EMPTY TEXT MESSAGE"

            )



            return JsonResponse({

                "status": "ok",

            })



        # =================================================

        # FIND OR CREATE CUSTOMER

        # =================================================



        customer = (

            Customer.objects

            .filter(

                organization=organization,

                phone=sender,

            )

            .first()

        )



        if customer:



            print(

                "EXISTING CUSTOMER:",

                customer,

            )



        else:



            customer = Customer.objects.create(

                organization=organization,

                phone=sender,

                name="WhatsApp Customer",

                customer_type="individual",

                preferred_contact_method="whatsapp",

                status="active",

                relationship_stage="visitor",

                phone_status="active",

                contact_source="whatsapp",

                first_contact_at=timezone.now(),

                last_interaction_at=timezone.now(),

            )



            print(

                "NEW CUSTOMER CREATED:",

                customer,

            )



        # Record inbound activity without changing relationship stage,
        # phone status, or WhatsApp marketing consent.
        customer.last_interaction_at = timezone.now()
        if not customer.first_contact_at:
            customer.first_contact_at = timezone.now()
        customer.save(update_fields=["last_interaction_at", "first_contact_at", "updated_at"])

        # =================================================

        # FIND ACTIVE CONVERSATION

        # =================================================



        conversation = (

            Conversation.objects

            .filter(

                organization=organization,

                whatsapp_phone_number=whatsapp_phone,

                customer=customer,

                phone_number=sender,

                status="active",

            )

            .first()

        )







        # Reuse an active conversation when one already exists.
        # Only look for a website request and create a conversation
        # when the customer does not yet have an active conversation.
        if not conversation:
            open_request = (
                BusinessRequest.objects
                .filter(
                    customer=customer,
                    category__organization=organization,
                    source="website",
                    status__in=[
                        "new",
                        "in_progress",
                        "waiting_customer",
                        "waiting_approval",
                    ],
                )
                .order_by("-created_at")
                .first()
            )

            print("OPEN BUSINESS REQUEST FOUND:", open_request)

            conversation = Conversation.objects.create(
                organization=organization,
                whatsapp_phone_number=whatsapp_phone,
                customer=customer,
                phone_number=sender,
                whatsapp_user_id=sender,
                business_request=open_request,
                status="active",
            )

            print("NEW CONVERSATION CREATED:", conversation)
            print("LINKED BUSINESS REQUEST:", conversation.business_request)

        # =================================================

        # GET OR CREATE CONVERSATION STATE

        # =================================================



        state = get_or_create_conversation_state(

            conversation

        )

        # =================================================
        # RESTORE LINKED WEBSITE REQUEST CATEGORY
        # =================================================

        if conversation.business_request:

            linked_request = conversation.business_request
            linked_category = linked_request.category
            state_data = state.data or {}

            if linked_category and not state_data.get("category"):

                state_data["category"] = linked_category.name
                state_data["business_request_id"] = linked_request.id

                state.data = state_data
                state.current_step = None
                state.waiting_for = None

                state.save()

                print("RESTORED LINKED REQUEST CATEGORY:", linked_category)
                print("RESTORED BUSINESS REQUEST:", linked_request)




        print(

            "CURRENT STEP:",

            state.current_step,

        )



        print(

            "WAITING FOR:",

            state.waiting_for,

        )



        print(

            "STATE DATA:",

            state.data,

        )



        # =================================================

        # SAVE INCOMING MESSAGE

        # =================================================



        incoming_message = Message.objects.create(

            organization=organization,

            conversation=conversation,

            direction="incoming",

            sender_type="customer",

            message_type=message_type,

            content=text,

            delivery_status="delivered",

            whatsapp_message_id=whatsapp_message_id,

            metadata=message,

        )



        print(

            "INCOMING MESSAGE SAVED:",

            incoming_message,

        )
        print("DEBUG SAVED MESSAGE CONVERSATION ID:", incoming_message.conversation_id)
        print("DEBUG WEBHOOK CONVERSATION ID:", conversation.id)



        # =================================================

        # UPDATE CONVERSATION ACTIVITY

        # =================================================



        conversation.save(

            update_fields=[

                "last_message_at",

            ]

        )



        # =================================================

        # GET CURRENT STATE DATA

        # =================================================



        state_data = state.data or {}



        stored_category_name = (

            state_data.get("category")

        )



        current_category = None



        # =================================================

        # RESTORE CURRENT CATEGORY

        # =================================================



        if stored_category_name:



            try:



                current_category = (

                    RequestCategory.objects.get(

                        name=stored_category_name,

                        organization=organization,

                        is_active=True,

                    )

                )



                print(

                    "CURRENT CATEGORY RESTORED:",

                    current_category,

                )



            except RequestCategory.DoesNotExist:



                current_category = None



                print(

                    "STORED CATEGORY NO LONGER EXISTS"

                )



        # =================================================

        # DETECT CATEGORY FROM NEW MESSAGE

        # =================================================

        # Product images are sent only when the normal product search
        # produces a list of WhatsApp-enabled products.
        # Product images are sent only when the normal product search
        # produces a list of WhatsApp-enabled products.
        product_images_to_send = []
        should_send_product_marketing_template = False

        # =================================================
        # PROCESS WHATSAPP MARKETING CONSENT
        # =================================================

        consent_reply = process_whatsapp_marketing_consent(
            customer,
            text,
        )

        if consent_reply is not None:

            reply = consent_reply
            product_flow_handled = True
            detected_category = None

            print("WHATSAPP MARKETING CONSENT PROCESSED:", customer)

        elif conversation.handling_mode == "human":

            # A human agent owns this conversation. Incoming messages
            # are already saved; do not run AI or business workflows.
            reply = None
            product_flow_handled = True
            detected_category = None

            print("AUTOMATION PAUSED: CONVERSATION IS HUMAN-HANDLED")

        else:

            # =================================================
            # NORMAL PRODUCT CONVERSATION
            # =================================================

            state_data_for_handover = (
                state.data if isinstance(state.data, dict) else {}
            )
            active_workflow = bool(
                state.current_step
                or state.waiting_for
                or state_data_for_handover.get("category")
                or state_data_for_handover.get("business_request_id")
                or state_data_for_handover.get("selected_whatsapp_product_id")
                or conversation.business_request_id
            )

            handover_language = None
            if active_workflow:
                handover_language = get_ai_human_support_language(
                    text,
                    organization,
                    state,
                    incoming_message.id if incoming_message else None,
                )

            if handover_language:
                conversation.handling_mode = "human"
                conversation.save(update_fields=["handling_mode"])
                product_flow_reply = _human_handover_acknowledgement(
                    handover_language
                )
                print("HUMAN HANDOVER ACTIVATED:", conversation.id)
            else:
                product_flow_reply = handle_whatsapp_product_conversation(
                    text,
                    organization,
                    state,
                )

            product_flow_handled = product_flow_reply is not None

            if product_flow_handled:
                reply = product_flow_reply
                detected_category = None
            else:
                detected_category = find_request_category(
                    text,
                    organization=organization,
                )

                # Existing deterministic category detection remains
                # the first choice. AI is only a guarded fallback.
                general_ai_result = None
                general_ai_attempted = False

                if detected_category is None and not current_category:
                    # Interpret the idle message once before deciding
                    # whether it needs category or product handling.
                    general_ai_attempted = True

                    general_ai_result = get_ai_general_interpretation(
                        text,
                        organization,
                        state,
                        incoming_message.id if incoming_message else None,
                    )

                    if general_ai_result:
                        intent = general_ai_result.get("intent")

                        if intent == "human_support":
                            conversation.handling_mode = "human"
                            conversation.save(update_fields=["handling_mode"])
                            reply = _human_handover_acknowledgement(
                                general_ai_result.get("language", "sw")
                            )
                            detected_category = None
                            product_flow_handled = True

                        elif general_ai_result.get("action") == "reply":
                            reply = general_ai_result["answer"]
                            detected_category = None
                            product_flow_handled = True

                        elif intent in {
                            "service_enquiry",
                            "business_request",
                        }:
                            ai_category_result = get_ai_request_category_reply(
                                text,
                                organization,
                                state,
                                incoming_message.id if incoming_message else None,
                            )

                            if ai_category_result:
                                if ai_category_result.get("clarification"):
                                    reply = ai_category_result["clarification"]
                                    detected_category = None
                                    product_flow_handled = True
                                else:
                                    detected_category = ai_category_result.get(
                                        "category"
                                    )

        print("DETECTED CATEGORY:", detected_category)


        # =================================================

        # IDENTIFY CURRENT REQUEST FIELD

        # =================================================



        current_field = None



        if not product_flow_handled and current_category and state.waiting_for:


            try:



                current_field = (

                    current_category

                    .request_fields

                    .get(

                        name=state.waiting_for,

                        is_active=True,

                    )

                )



                print(

                    "CURRENT FIELD:",

                    current_field,

                )



            except Exception:



                current_field = None



                print(

                    "CURRENT FIELD NOT FOUND:",

                    state.waiting_for,

                )



        # =================================================

        # DETERMINE WHETHER MESSAGE STARTS NEW REQUEST

        # =================================================



        new_request = False



        # -------------------------------------------------

        # CASE 1:

        # No current category.

        # -------------------------------------------------



        if not product_flow_handled and not current_category:



            if detected_category:



                new_request = True



                print(

                    "NEW REQUEST DETECTED - "

                    "NO CURRENT CATEGORY"

                )



        # -------------------------------------------------

        # CASE 2:

        # Existing active request.

        # -------------------------------------------------



        elif not product_flow_handled:



            # ---------------------------------------------

            # DIFFERENT CATEGORY

            # ---------------------------------------------



            if (

                detected_category

                and detected_category.id

                != current_category.id

            ):



                new_request = (

                    is_new_request_message(

                        text,

                        current_category=current_category,

                        current_field=current_field,

                        organization=organization,

                    )

                )



                print(

                    "DIFFERENT CATEGORY DETECTED"

                )



                print(

                    "NEW REQUEST DECISION:",

                    new_request,

                )



            # ---------------------------------------------

            # SAME CATEGORY

            # ---------------------------------------------



            elif (

                detected_category

                and detected_category.id

                == current_category.id

                and state.waiting_for

            ):



                normalized_text = (

                    text.lower().strip()

                )



                request_phrases = [

                    "i need",

                    "i want",

                    "i would like",

                    "i'd like",

                    "looking for",

                    "i am looking for",

                    "i'm looking for",

                    "can you provide",

                    "can you help",

                    "i need a quote",

                    "i need quotation",

                    "quotation for",

                    "quote for",

                ]



                has_request_phrase = any(

                    phrase in normalized_text

                    for phrase in request_phrases

                )



                explicit_new_request_phrases = [

                    "i also need",

                    "i also want",

                    "i also would like",

                    "i'd also like",

                    "i would also like",

                    "actually i need",

                    "actually i want",

                    "actually i would like",

                    "another request",

                    "another service",

                    "another product",

                    "different request",

                    "different service",

                    "different product",

                    "by the way i need",

                    "by the way i want",

                    "can you also provide",

                    "can you also help",

                ]



                has_explicit_new_request_phrase = any(

                    phrase in normalized_text

                    for phrase in explicit_new_request_phrases

                )



                if current_field:



                    # ---------------------------------

                    # TEXT FIELD

                    # ---------------------------------



                    if current_field.field_type == "text":



                        if has_explicit_new_request_phrase:



                            new_request = True



                            print(

                                "EXPLICIT NEW REQUEST "

                                "DETECTED WHILE ANSWERING "

                                "TEXT FIELD"

                            )



                        elif (

                            state.waiting_for

                            == "location"

                            and detected_category

                            and has_request_phrase

                        ):



                            new_request = True



                            print(

                                "REQUEST STATEMENT DETECTED "

                                "INSTEAD OF LOCATION ANSWER"

                            )



                    # ---------------------------------

                    # NUMBER / YES-NO / OTHER FIELD

                    # ---------------------------------



                    else:



                        valid, cleaned_value = (

                            validate_request_field_value(

                                current_field,

                                text,

                            )

                        )



                        print(

                            "CURRENT FIELD VALIDATION:",

                            valid,

                            cleaned_value,

                        )



                        if (

                            not valid

                            and has_request_phrase

                        ):



                            new_request = True



                            print(

                                "INVALID FIELD ANSWER WITH "

                                "REQUEST LANGUAGE - "

                                "NEW REQUEST"

                            )



        print(

            "CURRENT CATEGORY:",

            current_category,

        )



        print(

            "CURRENT FIELD:",

            current_field,

        )



        print(

            "DETECTED CATEGORY:",

            detected_category,

        )



        print(

            "NEW REQUEST:",

            new_request,

        )



        # =================================================

        # HANDLE NEW REQUEST

        # =================================================



        if not product_flow_handled and new_request:



            print(

                "STARTING NEW BUSINESS REQUEST"

            )



            category = detected_category

            if category and (
                customer.organization_id != organization.id
                or category.organization_id != organization.id
                or (
                    category.department_id
                    and category.department.organization_id != organization.id
                )
            ):
                print("REQUEST REJECTED: ORGANIZATION MISMATCH")
                category = None



            if not category:



                print(

                    "NEW REQUEST FLAGGED BUT "

                    "NO CATEGORY FOUND"

                )



                reply = process_customer_message(

                    text

                )



            else:

                # -----------------------------------------
                # CREATE NEW BUSINESS REQUEST
                # -----------------------------------------
                business_request = BusinessRequest.objects.create(
                    customer=customer,
                    request_text=text,
                    subject=category.name,
                    category=category,
                    department=category.department,
                    status="new",
                    priority="normal",
                    source="whatsapp",
                )

                print(
                    "NEW BUSINESS REQUEST CREATED:",
                    business_request,
                )


                # -----------------------------------------
                                # LINK CONVERSATION TO REQUEST

                # -----------------------------------------



                conversation.business_request = (

                    business_request

                )



                conversation.save(

                    update_fields=[

                        "business_request",

                    ]

                )



                # -----------------------------------------

                # RESET CONVERSATION STATE

                # -----------------------------------------



                state_data = {

                    "request_text": text,

                    "category": category.name,

                    "business_request_id": (

                        business_request.id

                    ),

                }



                state.current_step = None

                state.waiting_for = None

                state.data = state_data



                state.save()



                print(

                    "CONVERSATION STATE RESET "

                    "FOR NEW REQUEST"

                )



                # -----------------------------------------

                # AUTOMATIC REPLY

                # -----------------------------------------



                if category:



                    # -------------------------------------------------

                    # IMPORTANT:

                    # If this is a brand-new BusinessRequest, the

                    # incoming message is the REQUEST itself.

                    #

                    # Do NOT use that message as the answer to the

                    # first field (for example, location).

                    # -------------------------------------------------



                    is_new_business_request = (

                        business_request is not None

                        and state_data.get(

                            "business_request_id"

                        ) == business_request.id

                        and state_data.get(

                            "request_text"

                        ) == text

                        and not state_data.get(

                            "location"

                        )

                        and state.waiting_for is None

                    )



                    if is_new_business_request:



                        print(

                            "NEW BUSINESS REQUEST DETECTED - "

                            "DO NOT USE ORIGINAL MESSAGE AS "

                            "FIELD ANSWER"

                        )



                        reply = process_request_fields(

                            category,

                            state,

                            None

                        )



                    else:



                        reply = process_request_fields(

                            category,

                            state,

                            text

                        )



                    # -----------------------------------------

                    # UPDATE BUSINESS REQUEST

                    # -----------------------------------------



                    if business_request:



                        update_business_request_details(

                            business_request,

                            state

                        )



                        if (

                            state.current_step

                            == "details_collected"

                        ):



                            create_request_workflow(

                                business_request

                            )



        # =================================================

        # CONTINUE CURRENT REQUEST

        # =================================================



        elif not product_flow_handled and current_category:



            category = current_category



            print(

                "CONTINUING CURRENT REQUEST:",

                category,

            )



            # ---------------------------------------------

            # GET CURRENT BUSINESS REQUEST

            # ---------------------------------------------



            business_request = (

                conversation.business_request

            )



            # ---------------------------------------------

            # RECOVER BUSINESS REQUEST IF MISSING

            # ---------------------------------------------



            if not business_request:



                business_request = (

                    create_business_request(

                        customer,

                        text,

                        category,

                        conversation,

                    )

                )



                if business_request:



                    conversation.business_request = (

                        business_request

                    )



                    conversation.save(

                        update_fields=[

                            "business_request",

                        ]

                    )



            # ---------------------------------------------

            # PROCESS CURRENT FIELD

            # ---------------------------------------------



            reply = process_request_fields(

                category,

                state,

                text,

            )



            # ---------------------------------------------

            # UPDATE BUSINESS REQUEST

            # ---------------------------------------------



            if business_request:



                update_business_request_details(

                    business_request,

                    state,

                )



                if (

                    state.current_step

                    == "details_collected"

                ):



                    create_request_workflow(

                        business_request

                    )



        # =================================================

        # FIRST MESSAGE / CATEGORY DETECTED

        # =================================================



        elif not product_flow_handled and detected_category:


            category = detected_category



            print(

                "FIRST REQUEST CATEGORY DETECTED:",

                category,

            )



            business_request = (

                create_business_request(

                    customer,

                    text,

                    category,

                    conversation,

                )

            )



            # ---------------------------------------------

            # SAVE INITIAL STATE

            # ---------------------------------------------



            state_data = {

                "request_text": text,

                "category": category.name,

                "business_request_id": (

                    business_request.id

                    if business_request

                    else None

                ),

            }



            state.current_step = None

            state.waiting_for = None

            state.data = state_data



            state.save()



            # ---------------------------------------------

            # LINK BUSINESS REQUEST

            # ---------------------------------------------



            if business_request:



                conversation.business_request = (

                    business_request

                )



                conversation.save(

                    update_fields=[

                        "business_request",

                    ]

                )



                print(

                    "CONVERSATION LINKED TO REQUEST:",

                    business_request,

                )



            # ---------------------------------------------

            # AUTOMATIC REPLY

            # ---------------------------------------------



            if category:



                is_new_business_request = (

                    business_request is not None

                    and state_data.get(

                        "business_request_id"

                    ) == business_request.id

                    and state_data.get(

                        "request_text"

                    ) == text

                    and not state_data.get(

                        "location"

                    )

                    and state.waiting_for is None

                )



                if is_new_business_request:



                    print(

                        "NEW BUSINESS REQUEST DETECTED - "

                        "DO NOT USE ORIGINAL MESSAGE AS "

                        "FIELD ANSWER"

                    )



                    reply = process_request_fields(

                        category,

                        state,

                        None

                    )



                else:



                    reply = process_request_fields(

                        category,

                        state,

                        text

                    )



                # ---------------------------------------------

                # UPDATE BUSINESS REQUEST

                # ---------------------------------------------



                if business_request:



                    update_business_request_details(

                        business_request,

                        state,

                    )



                    if (

                        state.current_step

                        == "details_collected"

                    ):



                        create_request_workflow(

                            business_request

                        )



        # =================================================

        # NO CATEGORY IDENTIFIED

        # =================================================



        elif not product_flow_handled:



            print(

                "NO CATEGORY IDENTIFIED - "

                "USING FALLBACK"

            )



            ai_reply = get_ai_product_reply(
                text,
                organization,
                state,
                incoming_message.id if incoming_message else None,
            )

            if ai_reply:
                reply = ai_reply
                product_reply = None
            else:
                general_ai_reply = None

                # Reuse the earlier interpretation. Only call the
                # backward-compatible helper if interpretation was
                # not attempted earlier in this webhook path.
                if not general_ai_attempted:
                    general_ai_reply = get_ai_general_reply(
                        text,
                        organization,
                        state,
                        incoming_message.id if incoming_message else None,
                    )

                if general_ai_reply:
                    reply = general_ai_reply
                    product_reply = None
                else:
                    # First preserve the existing literal catalogue search.
                    product_reply = search_whatsapp_products(
                        text,
                        organization,
                        state,
                    )

                    if product_reply:
                        reply = product_reply
                    else:
                        # AI discovery is only a fallback when literal
                        # catalogue search finds no matching products.
                        discovery = get_ai_product_discovery_reply(
                            text,
                            organization,
                            state,
                            incoming_message.id if incoming_message else None,
                        )

                        if discovery:
                            reply = discovery["reply"]
                            product_reply = discovery["product_reply"]
                        else:
                            reply = process_customer_message(text)
            should_send_product_marketing_template = bool(
                product_reply
                and customer
                and customer.whatsapp_marketing_opt_in
                and whatsapp_message_id
            )

            if product_reply and state is not None:
                displayed_product_ids = (state.data or {}).get(
                    "whatsapp_product_ids", []
                )
                products_by_id = Product.objects.filter(
                    organization=organization,
                    id__in=displayed_product_ids,
                    is_active=True,
                    deleted_at__isnull=True,
                    show_on_whatsapp=True,
                ).in_bulk()

                # Preserve the same order used in the customer-facing list.
                product_images_to_send = [
                    products_by_id[product_id]
                    for product_id in displayed_product_ids
                    if product_id in products_by_id
                ]

        marketing_invitation_included = False

        if (
            customer
            and customer.phone_status == "active"
            and customer.status == "active"
            and not customer.whatsapp_marketing_opt_in
            and not customer.whatsapp_marketing_invitation_sent_at
            and not customer.whatsapp_marketing_declined_at
            and not customer.whatsapp_marketing_opt_out_at
        ):
            organization_language = (
                getattr(customer.organization, "language", None) or ""
            ).strip().lower().replace("-", "_")

            if organization_language.startswith("en"):
                marketing_invitation = (
                    "\n\nWould you like to receive WhatsApp marketing messages?\n\n"
                    "Reply YES to subscribe or NO to decline."
                )
            else:
                marketing_invitation = (
                    "\n\nPia tuna bidhaa nyingi ambazo nina uhakika utazifurahia\n\n"
                    "Nijibu YES kukubali au NO kukataa."
                )

            reply = (reply or "") + marketing_invitation
            marketing_invitation_included = True

            print(
                "WHATSAPP MARKETING INVITATION INCLUDED:",
                customer,
            )



        # =================================================

        # SEND AUTOMATIC WHATSAPP REPLY

        # =================================================



        print(

            "SENDING AUTOMATIC REPLY..."

        )



        print(

            "REPLY:",

            reply,

        )



        # -------------------------------------------------

        # Send through the business-specific WhatsApp

        # connection.

        # -------------------------------------------------



        response = (
            send_whatsapp_message(
                whatsapp_phone,
                sender,
                reply,
            )
            if reply
            else None
        )



        # =================================================

        # SAVE OUTGOING MESSAGE

        # =================================================



        if (

            response is not None

            and response.status_code == 200

        ):



            try:



                response_data = response.json()



            except ValueError:



                response_data = {

                    "raw_response": response.text,

                }



            outgoing_whatsapp_message_id = None



            try:



                outgoing_whatsapp_message_id = (

                    response_data

                    .get("messages", [{}])[0]

                    .get("id")

                )



            except (

                IndexError,

                AttributeError,

                TypeError,

            ):



                outgoing_whatsapp_message_id = None



            outgoing_message = Message.objects.create(

                organization=organization,

                conversation=conversation,

                direction="outgoing",

                sender_type="faltasi",

                message_type="text",

                content=reply,

                whatsapp_message_id=(

                    outgoing_whatsapp_message_id

                ),

                delivery_status="sent",

                metadata=response_data,

            )



            print(

                "OUTGOING MESSAGE SAVED:",

                outgoing_message,

            )


            # STAGE 4: Record successful invitation
            if marketing_invitation_included:
                customer.whatsapp_marketing_invitation_sent_at = timezone.now()

                customer.save(
                    update_fields=[
                        "whatsapp_marketing_invitation_sent_at",
                        "updated_at",
                    ]
                )

                print(
                    "WHATSAPP MARKETING INVITATION RECORDED:",
                    customer,
                )

            # Update conversation activity timestamp
            conversation.save(
                update_fields=[
                    "last_message_at",
                ]
            )


            # Update conversation activity timestamp



            conversation.save(

                update_fields=[

                    "last_message_at",

                ]

            )

            # Send the real product images after the numbered text list.
            # The selected product can then be chosen using the same numbers.
            for product in product_images_to_send:
                send_and_log_whatsapp_product_image(
                    whatsapp_phone=whatsapp_phone,
                    phone_number=sender,
                    product=product,
                    conversation=conversation,
                    organization=organization,
                    request=request,
                )
            if should_send_product_marketing_template:
                send_product_marketing_template(
                    customer=customer,
                    whatsapp_phone=whatsapp_phone,
                    phone_number=sender,
                    conversation=conversation,
                    incoming_message_id=whatsapp_message_id,
                )
        else:
            print(
                "OUTGOING MESSAGE WAS NOT SAVED "
                "BECAUSE WHATSAPP SEND FAILED"
            )

            if response is not None:
                print("META HTTP STATUS:", response.status_code)
                print("META RESPONSE:", response.text)
            else:
                print("META RESPONSE: NO RESPONSE RECEIVED")



        # =================================================

        # RESPOND TO META

        # =================================================



        return JsonResponse({

            "status": "ok",

        })



    # =====================================================

    # INVALID JSON

    # =====================================================



    except json.JSONDecodeError as e:



        print(

            "JSON ERROR:",

            str(e),

        )



        return JsonResponse(

            {

                "error": "Invalid JSON",

            },

            status=400,

        )



    # =====================================================

    # GENERAL WEBHOOK ERROR

    # =====================================================



    except Exception as e:



        print(

            "WEBHOOK ERROR:",

            str(e),

        )



        return JsonResponse(

            {

                "error": "Webhook processing failed",

            },

            status=500,

        )


def handle_whatsapp_product_conversation(text, organization, state):
    """Handle product selection and follow-up questions in Swahili."""
    if not text or not organization or not state:
        return None

    step = state.current_step
    data = dict(state.data or {})
    normalized = text.strip().lower()

    # Only handle replies belonging to this product conversation.
    if step not in {
        "whatsapp_product_selection",
        "whatsapp_product_quantity",
        "whatsapp_product_next_action",
    }:
        return None

    def save_state(new_step, waiting_for, updates=None):
        current_data = dict(state.data or {})
        if updates:
            current_data.update(updates)
        state.current_step = new_step
        state.waiting_for = waiting_for
        state.data = current_data
        state.save()

    # STEP 1: Customer chooses one of the displayed products.
    if step == "whatsapp_product_selection":
        product_ids = data.get("whatsapp_product_ids", [])
        selected_id = None

        # Accept a displayed number such as "1".
        if normalized.isdigit():
            choice = int(normalized)
            if 1 <= choice <= len(product_ids):
                selected_id = product_ids[choice - 1]

        # Also accept the product name.
        if selected_id is None:
            for product in Product.objects.filter(
                organization=organization,
                id__in=product_ids,
                is_active=True,
                deleted_at__isnull=True,
                show_on_whatsapp=True,
            ):
                if normalized == product.name.lower():
                    selected_id = product.id
                    break

        if selected_id is None:
            return (
                "Samahani ðŸ˜Š Sijaweza kutambua bidhaa uliyochagua. "
                "Tafadhali jibu kwa namba ya bidhaa kwenye orodha, "
                "au andika jina lake."
            )

        product = Product.objects.filter(
            organization=organization,
            id=selected_id,
            is_active=True,
            deleted_at__isnull=True,
            show_on_whatsapp=True,
        ).first()

        if not product:
            save_state(None, None, {
                "whatsapp_product_ids": [],
                "selected_whatsapp_product_id": None,
            })
            return (
                "Samahani, bidhaa hiyo haipatikani kwa sasa. "
                "Tafadhali tuambie bidhaa nyingine unayohitaji."
            )

        save_state(
            "whatsapp_product_quantity",
            "product_quantity",
            {
                "selected_whatsapp_product_id": product.id,
                "selected_whatsapp_product_name": product.name,
            },
        )

        return (
            f"Asante! ðŸ˜Š Umechagua {product.name}.\n\n"
            "Unahitaji kiasi gani? Tafadhali taja idadi unayohitaji."
        )

    # STEP 2: Capture quantity.
    if step == "whatsapp_product_quantity":
        import re

        quantity_match = re.search(r"\d+", normalized)
        if not quantity_match or int(quantity_match.group()) < 1:
            return (
                "Tafadhali tuambie idadi unayohitaji, "
                "kwa mfano vipande 10."
            )

        quantity = int(quantity_match.group())
        save_state(
            "whatsapp_product_next_action",
            "product_next_action",
            {"whatsapp_product_quantity": quantity},
        )

        return (
            f"Sawa, umehitaji kiasi cha {quantity}. ðŸ˜Š\n\n"
            "Ungependa nikusaidie kupata nukuu ya bei, "
            "kuulizia upatikanaji na delivery, au kuwasiliana "
            "na timu yetu ya mauzo?\n\n"
            "Andika: Bei, Delivery, au Mauzo."
        )

    # STEP 3: Ask what assistance the customer needs.
    if step == "whatsapp_product_next_action":
        if any(word in normalized for word in (
            "bei", "quotation", "quote", "nukuu", "gharama",
        )):
            action = "quotation"
            response = (
                "Asante! ðŸ˜Š Tumepokea ombi lako la nukuu ya bei. "
                "Timu yetu ya mauzo itakusaidia kuthibitisha bei."
            )
        elif any(word in normalized for word in (
            "delivery", "usafiri", "kusafirisha", "kuleta",
        )):
            action = "delivery"
            response = (
                "Sawa! ðŸ˜Š Tunaweza kukusaidia kuhusu delivery. "
                "Tafadhali tueleze eneo unalotaka bidhaa ipelekwe."
            )
        elif any(word in normalized for word in (
            "mauzo", "sales", "mtu", "wakala", "ongea",
        )):
            action = "sales"
            response = (
                "Sawa kabisa! ðŸ˜Š Tutakusaidia kuwasiliana na "
                "mwakilishi wetu wa mauzo."
            )
        elif any(word in normalized for word in (
            "ufungaji", "installation", "kufunga", "fundi",
        )):
            action = "installation"
            response = (
                "Sawa! ðŸ˜Š Tafadhali tueleze eneo la ufungaji "
                "ili timu yetu iweze kukushauri."
            )
        else:
            return (
                "Ungependa nukuu ya bei, delivery, au kuzungumza "
                "na timu ya mauzo? Unaweza pia kuomba ufungaji "
                "ikiwa huduma hiyo inahitajika."
            )

        save_state(
            "whatsapp_product_completed",
            None,
            {"whatsapp_product_action": action},
        )

        return response

    return None


def search_whatsapp_products(text, organization, state=None):
    """Search WhatsApp-enabled products and remember the displayed choices."""
    if not text or not organization:
        return None

    stop_words = {
        "i", "me", "my", "we", "you", "a", "an", "the", "am",
        "is", "are", "need", "want", "looking", "for", "please",
        "can", "could", "do", "have", "get", "buy", "to", "some",
        "any", "your", "and", "or", "of", "with", "would", "like",
        "hello", "hi", "hey", "what", "how", "much", "price", "prices",
    }

    terms = list(dict.fromkeys(
        word for word in re.findall(r"[a-zA-Z0-9]+", text.lower())
        if len(word) > 1 and word not in stop_words
    ))

    if not terms:
        return None

    fields = (
        "name", "brand", "model", "sku",
        "short_description", "description", "category__name",
    )

    query = Q()
    for term in terms:
        for field in fields:
            query |= Q(**{f"{field}__icontains": term})

    products = Product.objects.filter(
        organization=organization,
        is_active=True,
        deleted_at__isnull=True,
        show_on_whatsapp=True,
    ).filter(query).select_related("category").distinct()

    def score(product):
        searchable = " ".join((
            product.name or "",
            product.brand or "",
            product.model or "",
            product.sku or "",
            product.short_description or "",
            product.description or "",
            product.category.name if product.category else "",
        )).lower()

        result = sum(term in searchable for term in terms)

        if all(term in (product.name or "").lower() for term in terms):
            result += 10

        return result

    matches = sorted(
        products,
        key=lambda p: (-score(p), p.display_order, p.name.lower()),
    )[:5]

    if not matches:
        return None

    # Remember the exact choices for this conversation.
    if state is not None:
        state_data = dict(state.data or {})
        state_data["whatsapp_product_ids"] = [p.id for p in matches]
        state.current_step = "whatsapp_product_selection"
        state.waiting_for = "product_selection"
        state.data = state_data
        state.save()

    lines = ["Here are some products matching your request:", ""]

    for number, product in enumerate(matches, start=1):
        lines.append(f"{number}. {product.name}")

        if product.brand:
            lines.append(f"   Brand: {product.brand}")

        if product.model:
            lines.append(f"   Model: {product.model}")

        price = (
            f"{product.currency} {product.price:,.2f}"
            if product.price is not None
            else "Price available on request"
        )

        lines.append(f"   Price: {price}")
        lines.append(f"   Availability: {product.get_availability_display()}")
        lines.append("")



    # Share only the catalogue belonging to this organization.
    catalogue_url = None

    if organization.organization_type == "platform_owner":
        catalogue_url = "https://www.faltasi.com/products/"

    else:
        organization_settings = (
            organization.settings
            if isinstance(organization.settings, dict)
            else {}
        )

        if organization_settings.get("public_catalogue_enabled") is True:
            configured_url = organization_settings.get(
                "public_catalogue_url"
            )

            if (
                isinstance(configured_url, str)
                and configured_url.startswith("https://")
                and configured_url.strip() == configured_url
            ):
                catalogue_url = configured_url

    if catalogue_url:
        lines.extend([
            "View our catalogue:",
            catalogue_url,
            "",
        ])

    lines.append(
        "Reply with the product number (for example, 1) "
        "or its name to continue."
    )

    return "\n".join(lines)


def process_customer_message(text):
    """Return a simple fallback when no request category is identified."""
    if not text or not text.strip():
        return 'Thank you for contacting Faltasi Innovations Limited. Please tell us what you need and we will be happy to help.'
    return 'Habari yako.\n\nNikusaidie nini?'

def update_conversation_state(state, current_step=None, waiting_for='__UNCHANGED__', data=None):
    """
    Update the conversation state and save it.

    waiting_for behavior:
    - "__UNCHANGED__" = keep the existing value
    - None = clear the value
    - any other value = set the value
    """
    if current_step is not None:
        state.current_step = current_step
    if waiting_for != '__UNCHANGED__':
        state.waiting_for = waiting_for
    if data is not None:
        existing_data = state.data or {}
        existing_data.update(data)
        state.data = existing_data
    state.save()
    print('CONVERSATION STATE UPDATED:', state)
    print('CURRENT STEP:', state.current_step)
    print('WAITING FOR:', state.waiting_for)
    print('STATE DATA:', state.data)
    return state

def get_required_request_fields(category):
    """
    Get the active required fields for a request category
    from Django Admin, in the configured order.
    """
    if not category:
        return []
    return list(category.request_fields.filter(is_active=True).order_by('order', 'id'))

def validate_request_field_value(field, text):
    """
    Validate a customer's answer according to the RequestField type.

    Returns:
        (True, cleaned_value) -> valid answer
        (False, None) -> invalid answer
    """
    if not field or text is None:
        return (False, None)
    value = text.strip()
    if not value:
        return (False, None)
    if field.field_type == 'text':
        return (True, value)
    if field.field_type == 'number':
        number_words = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20}
        number_match = re.search('\\d+(?:\\.\\d+)?', value)
        if number_match:
            number = float(number_match.group())
            if number.is_integer():
                number = int(number)
            return (True, number)
        normalized = value.lower()
        for word, number in number_words.items():
            if re.search(f'\\b{word}\\b', normalized):
                return (True, number)
        return (False, None)
    if field.field_type == 'yes_no':
        normalized = value.lower().strip()
        yes_values = ['yes', 'y', 'yeah', 'yep', 'sure', 'correct', 'of course', 'please do', 'i do', 'i need it', 'i need installation', 'needed', 'required']
        no_values = ['no', 'n', 'nope', 'not needed', 'not required', "i don't", 'dont', "don't", 'not necessary']
        if normalized in yes_values:
            return (True, True)
        if normalized in no_values:
            return (True, False)
        yes_phrases = ['yes, please', 'yes please', 'i need', 'i want', 'please do', 'go ahead', 'install it', 'install', 'installation required', 'i need installation']
        for phrase in yes_phrases:
            if phrase in normalized:
                return (True, True)
        no_phrases = ['no, thanks', 'no thanks', "i don't need", 'i dont need', 'i do not need', 'not necessary', 'not required', 'without installation', 'installation not required']
        for phrase in no_phrases:
            if phrase in normalized:
                return (True, False)
        return (False, None)
    if field.field_type == 'choice':
        return (True, value)
    return (True, value)

def get_next_missing_request_field(category, collected_data):
    """
    Find the next required RequestField that has not
    yet been answered by the customer.
    """
    if not category:
        return None
    fields = get_required_request_fields(category)
    for field in fields:
        if field.name not in collected_data:
            return field
    return None

def get_next_request_question(category, collected_data):
    """
    Return the next required question that has not
    yet been answered.
    """
    field = get_next_missing_request_field(category, collected_data)
    if field:
        return field.question
    return None

# FALTASI DEPLOYMENT TEST - 09 OCTOBER 2026


def get_ai_general_interpretation(
    text,
    organization,
    state,
    current_message_id,
):
    """
    Interpret an idle WhatsApp message once.

    Returns the validated intent and action so the webhook can
    reuse the result without making a second general AI request.
    """
    if not text or not organization or not state:
        return None

    state_data = state.data if isinstance(state.data, dict) else {}

    if (
        state_data.get("selected_whatsapp_product_id")
        or state_data.get("category")
        or state_data.get("business_request_id")
        or getattr(state, "waiting_for", None)
    ):
        return None

    conversation = getattr(state, "conversation", None)

    if conversation is None:
        return None

    if getattr(conversation, "organization_id", None) != organization.pk:
        return None

    if (
        getattr(conversation, "business_request_id", None)
        or getattr(conversation, "business_request", None)
    ):
        return None

    if getattr(state, "current_step", None) not in {
        None,
        "whatsapp_product_completed",
    }:
        return None

    try:
        from .ai_service import interpret_general_message

        result = interpret_general_message(
            text,
            organization,
            state,
            current_message_id=current_message_id,
        )

        if not isinstance(result, dict):
            return None

        action = result.get("action")
        intent = result.get("intent")
        answer = result.get("answer")

        if action == "reply":
            if intent not in {
                "greeting",
                "general_enquiry",
                "unclear",
            }:
                return None

            if not isinstance(answer, str):
                return None

            answer = answer.strip()

            if not answer or len(answer) > 1000:
                return None

        elif action == "route_existing":
            if intent not in {
                "product_enquiry",
                "service_enquiry",
                "business_request",
                "human_support",
                "workflow_input",
            }:
                return None

            if answer != "":
                return None

        else:
            return None

        return {
            "action": action,
            "intent": intent,
            "answer": answer,
        }

    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "General WhatsApp AI interpretation failed."
        )
        return None


def _human_handover_acknowledgement(language="sw"):
    """Return a natural acknowledgement without promising staff availability."""
    if language == "en":
        return "Thanks for letting us know. We’ll continue helping you here."
    if language == "mixed":
        return "Sawa, tumekuelewa. We’ll continue helping you hapa."
    return "Sawa, tumekuelewa. Tutaendelea kukusaidia hapa."


def get_ai_human_support_language(
    text,
    organization,
    state,
    current_message_id,
):
    """Return the customer's language when AI identifies a human-support request."""
    if not text or not organization or not state:
        return None

    conversation = getattr(state, "conversation", None)
    if (
        conversation is None
        or getattr(conversation, "organization_id", None) != organization.pk
    ):
        return None

    try:
        from .ai_service import interpret_general_message

        result = interpret_general_message(
            text,
            organization,
            state,
            current_message_id=current_message_id,
        )

        if not (
            isinstance(result, dict)
            and result.get("action") == "route_existing"
            and result.get("intent") == "human_support"
            and result.get("answer") == ""
        ):
            return None

        language = result.get("language", "sw")
        return language if language in {"sw", "en", "mixed"} else "sw"

    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "WhatsApp human-support intent interpretation failed."
        )
        return None


def get_ai_human_support_intent(
    text,
    organization,
    state,
    current_message_id,
):
    """Keep the existing Boolean helper interface for compatibility."""
    return get_ai_human_support_language(
        text,
        organization,
        state,
        current_message_id,
    ) is not None


def get_ai_general_reply(text, organization, state, current_message_id):
    """Backward-compatible helper for callers expecting a reply only."""

    result = get_ai_general_interpretation(
        text,
        organization,
        state,
        current_message_id,
    )

    if result and result.get("action") == "reply":
        return result["answer"]

    return None


def get_ai_product_discovery_reply(
    text,
    organization,
    state,
    current_message_id,
):
    """
    Use AI to interpret a new product request when literal catalogue
    search has no result. Django performs and validates the actual search.
    """
    if not text or not organization or not state:
        return None

    state_data = state.data if isinstance(state.data, dict) else {}

    # Do not interrupt an existing product selection or business workflow.
    if (
        state_data.get("selected_whatsapp_product_id")
        or state_data.get("category")
        or state_data.get("business_request_id")
        or getattr(state, "waiting_for", None)
    ):
        return None

    conversation = getattr(state, "conversation", None)

    if conversation is None:
        return None

    if (
        getattr(conversation, "business_request_id", None)
        or getattr(conversation, "business_request", None)
    ):
        return None

    if getattr(state, "current_step", None) not in {
        None,
        "whatsapp_product_completed",
    }:
        return None

    try:
        from .ai_service import interpret_product_discovery

        result = interpret_product_discovery(
            text,
            organization,
            state,
            current_message_id=current_message_id,
        )

        if not isinstance(result, dict):
            return None

        action = result.get("action")

        if action == "clarify":
            clarification = result.get("clarification")

            if (
                isinstance(clarification, str)
                and clarification.strip()
                and len(clarification.strip()) <= 500
            ):
                return {
                    "reply": clarification.strip(),
                    "product_reply": None,
                }

            return None

        if action == "search":
            search_query = result.get("search_query")

            if (
                not isinstance(search_query, str)
                or not search_query.strip()
                or len(search_query.strip()) > 300
            ):
                return None

            # Django searches the real organization-owned catalogue.
            # The AI never supplies or controls product IDs.
            product_reply = search_whatsapp_products(
                search_query.strip(),
                organization,
                state,
            )

            if product_reply:
                return {
                    "reply": product_reply,
                    "product_reply": product_reply,
                }

            return None

        return None

    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Product discovery AI failed; using existing fallback."
        )
        return None


# =========================================================
# PHASE 3C: SAFE DJANGO REQUEST CATEGORY INTEGRATION
# =========================================================

def get_ai_request_category_reply(
    text,
    organization,
    state,
    current_message_id=None,
):
    """
    Ask AI to interpret a new request only when the WhatsApp
    conversation is genuinely idle.

    Django validates the returned category against the current
    organization's active RequestCategory records.
    """
    if not text or not organization or not state:
        return None

    state_data = state.data if isinstance(state.data, dict) else {}

    # Never interrupt an existing request or product workflow.
    if state_data.get("category"):
        return None

    if state_data.get("business_request_id"):
        return None

    if state_data.get("selected_whatsapp_product_id"):
        return None

    if state_data.get("whatsapp_product_ids"):
        return None

    if getattr(state, "waiting_for", None):
        return None

    conversation = getattr(state, "conversation", None)

    if conversation is None:
        return None

    if getattr(conversation, "organization_id", None) != organization.pk:
        return None

    if getattr(conversation, "business_request_id", None):
        return None

    if getattr(conversation, "business_request", None):
        return None

    allowed_steps = {
        None,
        "whatsapp_product_completed",
    }

    if getattr(state, "current_step", None) not in allowed_steps:
        return None

    try:
        from .ai_service import interpret_request_category

        # Fetch at most 31 so that an oversized category list is
        # rejected rather than silently omitting valid categories.
        category_records = list(
            RequestCategory.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by("name")[:31]
        )

        if not category_records or len(category_records) > 30:
            return None

        candidates = [
            {
                "id": item.pk,
                "name": item.name,
            }
            for item in category_records
        ]

        result = interpret_request_category(
            text,
            organization,
            state,
            candidates,
            current_message_id=current_message_id,
        )

        if not isinstance(result, dict):
            return None

        action = result.get("action")

        if action == "clarify":
            clarification = result.get("clarification")

            if (
                isinstance(clarification, str)
                and clarification.strip()
                and len(clarification.strip()) <= 500
            ):
                return {
                    "category": None,
                    "clarification": clarification.strip(),
                }

            return None

        if action != "match":
            return None

        category_id = result.get("category_id")

        if (
            isinstance(category_id, bool)
            or not isinstance(category_id, int)
        ):
            return None

        # Revalidate against the database. The AI response is never
        # trusted as proof that a category exists or is authorized.
        category = RequestCategory.objects.filter(
            pk=category_id,
            organization=organization,
            is_active=True,
        ).first()

        if not category:
            return None

        if (
            category.department_id
            and category.department.organization_id != organization.pk
        ):
            return None

        return {
            "category": category,
            "clarification": None,
        }

    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "WhatsApp AI category interpretation failed; "
            "using existing category routing."
        )
        return None

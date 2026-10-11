"""Utilities for creating and sending organization owner onboarding messages."""
import secrets
import string

from django.conf import settings
from django.utils import timezone
import requests

from .models import Organization, OrganizationMember, OrganizationOnboardingMessage


def generate_temporary_password(length=14):
    """Generate a one-time password without storing it in plaintext in the database."""
    alphabet = string.ascii_letters + string.digits + "!@#$%_-"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in password) and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password) and any(c in "!@#$%_-" for c in password)):
            return password


def _normalize_phone(phone_number):
    import re
    phone = re.sub(r"[^\d+]", "", str(phone_number or "").strip())
    if phone.startswith("+"):
        return phone[1:]
    if phone.startswith("255"):
        return phone
    if phone.startswith("0"):
        return "255" + phone[1:]
    return phone


def send_owner_onboarding(organization, membership, username, temporary_password, attempt_number=1):
    """Send onboarding through Faltasi's connected WhatsApp account and log the API result.

    Only provider identifiers and outcome details are stored. The temporary password
    is never written to the onboarding log or printed to application logs.
    """
    import requests
    from whatsapp.models import WhatsAppPhoneNumber, WhatsAppConnection

    record = OrganizationOnboardingMessage.objects.create(
        organization=organization,
        membership=membership,
        recipient_phone=membership.phone_number,
        status="pending",
        attempt_number=attempt_number,
    )

    platform_org = Organization.objects.filter(
        organization_type="platform_owner", status="active"
    ).order_by("created_at").first()
    if not platform_org:
        record.status = "failed"
        record.error_message = "No active platform-owner organization was found."
        record.save(update_fields=["status", "error_message"])
        return record

    sender_phone = WhatsAppPhoneNumber.objects.filter(
        organization=platform_org,
        is_active=True,
        status="connected",
        phone_number_id__isnull=False,
    ).select_related("whatsapp_business_account").order_by("-is_default", "-created_at").first()
    if not sender_phone:
        record.status = "failed"
        record.error_message = "No active connected WhatsApp phone number is configured for Faltasi."
        record.save(update_fields=["status", "error_message"])
        return record

    connection = WhatsAppConnection.objects.filter(
        organization=platform_org,
        whatsapp_business_account=sender_phone.whatsapp_business_account,
        status="connected",
    ).first()
    if not connection or not connection.access_token:
        record.status = "failed"
        record.error_message = "Faltasi WhatsApp connection or access token is unavailable."
        record.save(update_fields=["status", "error_message"])
        return record

    recipient = _normalize_phone(membership.phone_number)
    login_url = getattr(settings, "OWNER_LOGIN_URL", "https://www.faltasi.com/accounts/login/")
    owner_name = membership.user.get_full_name() or membership.user.username
    text_body = (
        f"Hello {owner_name},\n\nYour organization account for {organization.name} has been created on Faltasi.\n\n"
        f"Username: {username}\nTemporary password: {temporary_password}\nLogin: {login_url}\n\n"
        "For your security, you must change this temporary password immediately after your first login. "
        "Do not share these credentials with anyone."
    )
    template_name = getattr(settings, "WHATSAPP_ONBOARDING_TEMPLATE_NAME", "").strip()
    if template_name:
        language = getattr(settings, "WHATSAPP_ONBOARDING_TEMPLATE_LANGUAGE", "en")
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": [{
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": owner_name},
                        {"type": "text", "text": organization.name},
                        {"type": "text", "text": username},
                        {"type": "text", "text": temporary_password},
                    ],
                }],
            },
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": text_body},
        }

    url = f"https://graph.facebook.com/v26.0/{sender_phone.phone_number_id}/messages"
    record.attempted_at = timezone.now()
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {connection.access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        # Do not log request payloads because they contain temporary credentials.
        record.status = "failed"
        record.error_message = f"WhatsApp request failed: {exc.__class__.__name__}. Check server connectivity and logs."
        record.save(update_fields=["status", "error_message", "attempted_at"])
        return record

    if response.status_code in (200, 201):
        try:
            data = response.json()
        except ValueError:
            data = {}
        items = data.get("messages", []) if isinstance(data, dict) else []
        record.provider_message_id = items[0].get("id", "") if items else ""
        record.status = "accepted"
        record.error_message = ""
    else:
        record.status = "failed"
        # Meta's error response is safe to store; never store the submitted payload.
        record.error_message = f"WhatsApp API returned HTTP {response.status_code}: {response.text[:1000]}"
    record.save(update_fields=["status", "provider_message_id", "error_message", "attempted_at"])
    return record

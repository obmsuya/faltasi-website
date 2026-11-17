
from datetime import datetime

import requests

from celery import shared_task
from django.conf import settings
from django.db.models import Q

from organizations.models import OrganizationMember
from whatsapp.models import (
    Conversation,
    Message,
    WhatsAppPhoneNumber,
)


def _get_current_handover(conversation_id, handover_timestamp):
    """
    Return the conversation only if this is still its current
    active human handover.
    """
    try:
        handover_at = datetime.fromisoformat(handover_timestamp)
    except (TypeError, ValueError):
        return None

    return Conversation.objects.filter(
        id=conversation_id,
        status="active",
        handling_mode="human",
        handover_at=handover_at,
        organization__isnull=False,
    ).first()


def _has_staff_replied(conversation):
    return Message.objects.filter(
        conversation=conversation,
        organization_id=conversation.organization_id,
        direction="outgoing",
        sender_type="agent",
        created_at__gte=conversation.handover_at,
    ).exists()


@shared_task
def send_handover_reminder(conversation_id, handover_timestamp):
    """
    Send the 15-minute WhatsApp reminder to opted-in
    owners, administrators and managers.
    """
    conversation = _get_current_handover(
        conversation_id,
        handover_timestamp,
    )

    if not conversation or _has_staff_replied(conversation):
        return

    template_name = getattr(
        settings,
        "WHATSAPP_HANDOVER_ALERT_TEMPLATE_NAME",
        "",
    )

    if not template_name:
        return

    organization = conversation.organization

    recipients = OrganizationMember.objects.filter(
        organization=organization,
        is_active=True,
        user__is_active=True,
        whatsapp_notifications_opt_in=True,
        role__in=["owner", "admin", "manager"],
    ).exclude(
        Q(phone_number__isnull=True) | Q(phone_number="")
    )

    whatsapp_phone = (
        WhatsAppPhoneNumber.objects.filter(
            organization=organization,
            is_active=True,
            status="connected",
        )
        .order_by("-is_default")
        .first()
    )

    if not whatsapp_phone:
        return

    # Reuse the existing tenant-specific credential validation.
    from whatsapp.views import _get_whatsapp_sender_credentials

    access_token, phone_number_id = (
        _get_whatsapp_sender_credentials(whatsapp_phone)
    )

    if not access_token or not phone_number_id:
        return

    language_code = getattr(
        settings,
        "WHATSAPP_HANDOVER_ALERT_LANGUAGE",
        "en_US",
    )

    url = (
        f"https://graph.facebook.com/v26.0/"
        f"{phone_number_id}/messages"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    for member in recipients:
        payload = {
            "messaging_product": "whatsapp",
            "to": member.phone_number.strip().lstrip("+"),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code,
                },
            },
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code != 200:
                print(
                    "HANDOVER REMINDER FAILED:",
                    member.id,
                    response.status_code,
                    response.text[:500],
                )

        except requests.RequestException as exc:
            print(
                "HANDOVER REMINDER ERROR:",
                member.id,
                str(exc),
            )


@shared_task
def return_handover_to_ai(conversation_id, handover_timestamp):
    """
    Return the conversation to AI after 30 minutes,
    but only if staff have not replied.
    """
    conversation = _get_current_handover(
        conversation_id,
        handover_timestamp,
    )

    if not conversation:
        return

    if _has_staff_replied(conversation):
        return

    conversation.handling_mode = "ai"
    conversation.handover_at = None

    conversation.save(
        update_fields=[
            "handling_mode",
            "handover_at",
        ]
    )

    print(
        "WHATSAPP HANDOVER TIMED OUT; AI RESTORED:",
        conversation.id,
    )

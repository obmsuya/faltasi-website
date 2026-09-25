from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from organizations.models import Organization
from .models import Conversation, Message
from .views import send_whatsapp_message


def get_user_organization(user):
    """
    Return the active organization for the logged-in user.
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
def conversation_list(request):
    """
    Display all WhatsApp conversations belonging
    to the logged-in organization.
    """

    organization = get_user_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an active organization.",
        )
        return redirect("accounts:login")

    conversations = (
        Conversation.objects
        .filter(
            organization=organization,
        )
        .select_related(
            "customer",
            "whatsapp_phone_number",
            "business_request",
        )
        .order_by(
            "-last_message_at",
            "-id",
        )
    )

    search = request.GET.get("search", "").strip()

    if search:
        conversations = conversations.filter(
            customer__name__icontains=search
        ) | conversations.filter(
            phone_number__icontains=search
        )

        conversations = conversations.distinct()

    status = request.GET.get("status", "").strip()

    if status:
        conversations = conversations.filter(
            status=status
        )

    context = {
        "organization": organization,
        "conversations": conversations,
        "search": search,
        "selected_status": status,
        "status_choices": Conversation.STATUS_CHOICES,
    }

    return render(
        request,
        "whatsapp/conversation_list.html",
        context,
    )


@login_required
def conversation_detail(request, conversation_id):
    """
    Display one WhatsApp conversation and its messages.

    The conversation is always restricted to the
    logged-in user's organization.
    """

    organization = get_user_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an active organization.",
        )
        return redirect("accounts:login")

    conversation = get_object_or_404(
        Conversation.objects
        .filter(
            organization=organization,
        )
        .select_related(
            "customer",
            "whatsapp_phone_number",
            "business_request",
        ),
        id=conversation_id,
    )

    conversation_messages = (
        Message.objects
        .filter(
            conversation=conversation,
        )
        .order_by(
            "created_at",
            "id",
        )
    )

    context = {
        "organization": organization,
        "conversation": conversation,
        "conversation_messages": conversation_messages,
    }

    return render(
        request,
        "whatsapp/conversation_detail.html",
        context,
    )


@login_required
def send_conversation_message(request, conversation_id):
    """
    Send a text reply to the customer through WhatsApp.
    """

    organization = get_user_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an active organization.",
        )
        return redirect("accounts:login")

    conversation = get_object_or_404(
        Conversation.objects
        .filter(
            organization=organization,
        )
        .select_related(
            "customer",
            "whatsapp_phone_number",
        ),
        id=conversation_id,
    )

    if request.method != "POST":
        return redirect(
            "whatsapp:conversation_detail",
            conversation_id=conversation.id,
        )

    message_text = request.POST.get(
        "message",
        "",
    ).strip()

    if not message_text:
        messages.error(
            request,
            "Please enter a message.",
        )

        return redirect(
            "whatsapp:conversation_detail",
            conversation_id=conversation.id,
        )

    whatsapp_phone = conversation.whatsapp_phone_number

    if not whatsapp_phone:
        messages.error(
            request,
            "This conversation is not connected to a WhatsApp phone number.",
        )

        return redirect(
            "whatsapp:conversation_detail",
            conversation_id=conversation.id,
        )

    response = send_whatsapp_message(
        whatsapp_phone,
        conversation.phone_number,
        message_text,
    )

    if response is None:
        messages.error(
            request,
            "WhatsApp message could not be sent.",
        )

        return redirect(
            "whatsapp:conversation_detail",
            conversation_id=conversation.id,
        )

    if response.status_code != 200:
        messages.error(
            request,
            "WhatsApp rejected the message.",
        )

        return redirect(
            "whatsapp:conversation_detail",
            conversation_id=conversation.id,
        )

    try:
        response_data = response.json()
    except ValueError:
        response_data = {}

    whatsapp_message_id = None

    try:
        whatsapp_message_id = (
            response_data
            .get("messages", [{}])[0]
            .get("id")
        )
    except (IndexError, AttributeError):
        pass

    Message.objects.create(
        organization=organization,
        conversation=conversation,
        direction="outgoing",
        sender_type="agent",
        message_type="text",
        content=message_text,
        whatsapp_message_id=whatsapp_message_id,
        delivery_status="sent",
        metadata=response_data,
    )

    conversation.save(
        update_fields=[
            "last_message_at",
        ]
    )

    messages.success(
        request,
        "WhatsApp message sent successfully.",
    )

    return redirect(
        "whatsapp:conversation_detail",
        conversation_id=conversation.id,
    )


@login_required
def close_conversation(request, conversation_id):
    """
    Close an active conversation.
    """

    organization = get_user_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Your account is not connected to an active organization.",
        )
        return redirect("accounts:login")

    conversation = get_object_or_404(
        Conversation.objects.filter(
            organization=organization,
        ),
        id=conversation_id,
    )

    if request.method == "POST":
        conversation.status = "closed"
        conversation.save(
            update_fields=[
                "status",
            ]
        )

        messages.success(
            request,
            "Conversation closed successfully.",
        )

    return redirect(
        "whatsapp:conversation_detail",
        conversation_id=conversation.id,
    )
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from organizations.models import OrganizationMember
from organizations.utils import (
    get_user_organization,
    is_platform_administrator,
)
from products.models import Product
from .models import ChannelConnection, ProductChannelPublication


CHANNELS = [
    ("website", "Website"),
    ("whatsapp", "WhatsApp"),
    ("instagram", "Instagram"),
    ("facebook", "Facebook"),
    ("tiktok", "TikTok"),
    ("google_business_profile", "Google Business Profile"),
    ("google_merchant_center", "Google Merchant Center"),
]


def _active_organization(request):
    organization = get_user_organization(request.user, request=request)
    if organization is None:
        return None, None
    membership = OrganizationMember.objects.filter(
        user=request.user,
        organization=organization,
        is_active=True,
    ).first()
    if membership is None and not is_platform_administrator(request.user):
        return None, None
    return organization, membership


def _can_manage_channels(user, membership):
    return bool(
        user.is_superuser
        or is_platform_administrator(user)
        or (membership and membership.role in {"owner", "admin", "manager"})
    )


@login_required
def channel_dashboard(request):
    organization, membership = _active_organization(request)
    if organization is None:
        return HttpResponseForbidden("No active organization is assigned to your account.")

    products = Product.objects.filter(
        organization=organization,
        deleted_at__isnull=True,
    ).order_by("name")

    connections = {
        connection.provider: connection
        for connection in ChannelConnection.objects.filter(organization=organization)
    }
    connection_status = {
        provider: connections[provider].get_status_display() if provider in connections else "Not connected"
        for provider, _label in ChannelConnection.PROVIDER_CHOICES
    }

    publication_map = {}
    for publication in ProductChannelPublication.objects.filter(
        product__organization=organization,
        product__deleted_at__isnull=True,
    ):
        publication_map[(publication.product_id, publication.channel)] = publication

    product_rows = []
    for product in products:
        product_rows.append({
            "product": product,
            "website_enabled": product.show_on_website,
            "whatsapp_enabled": product.show_on_whatsapp,
            "public_visible": bool(
                organization.organization_type == "platform_owner"
                and product.is_publicly_visible
            ),
            "public_visibility_locked": organization.organization_type != "platform_owner",
            "publications": {
                channel: publication_map.get((product.id, channel))
                for channel, _label in CHANNELS
                if channel not in {"website", "whatsapp"}
            },
        })

    return render(request, "channels/dashboard.html", {
        "organization": organization,
        "product_rows": product_rows,
        "channels": CHANNELS,
        "connections": connections,
        "connection_status": connection_status,
        "can_manage_channels": _can_manage_channels(request.user, membership),
    })


@login_required
@require_POST
def toggle_product_channel(request, product_id, channel):
    organization, membership = _active_organization(request)
    if organization is None:
        return HttpResponseForbidden("No active organization is assigned to your account.")
    if not _can_manage_channels(request.user, membership):
        return HttpResponseForbidden("You are not authorized to manage channel settings.")

    product = get_object_or_404(
        Product,
        pk=product_id,
        organization=organization,
        deleted_at__isnull=True,
    )
    enabled = request.POST.get("enabled") == "1"

    if channel == "website":
        product.show_on_website = enabled
        # This setting controls website presentation only. It never grants
        # public catalogue visibility.
        product.save(update_fields=["show_on_website", "updated_at"])
    elif channel == "whatsapp":
        product.show_on_whatsapp = enabled
        product.save(update_fields=["show_on_whatsapp", "updated_at"])
    elif channel in dict(ProductChannelPublication.CHANNEL_CHOICES):
        publication, _created = ProductChannelPublication.objects.get_or_create(
            product=product,
            channel=channel,
        )
        publication.is_enabled = enabled
        if not enabled:
            publication.status = "unpublished"
        else:
            connected = ChannelConnection.objects.filter(
                organization=organization,
                provider=channel,
                status="connected",
            ).exists()
            publication.status = "pending" if connected else "draft"
        publication.last_error = ""
        publication.save(update_fields=["is_enabled", "status", "last_error", "updated_at"])
    else:
        return HttpResponseForbidden("Unsupported channel.")

    messages.success(request, "Channel setting updated.")
    return redirect("channels:dashboard")

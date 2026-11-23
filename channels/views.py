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
from .registry import (
    CHANNEL_REGISTRY,
    CHANNEL_BY_KEY,
    PROVIDER_CHANNELS,
)


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
    connection_cards = []
    for provider in PROVIDER_CHANNELS:
        connection = connections.get(provider["key"])
        connection_cards.append({
            "key": provider["key"],
            "label": provider["label"],
            "status": connection.get_status_display() if connection else "Not connected",
            "connection": connection,
            "setup_message": (
                "Authorization and publishing integration are not configured yet."
                if not connection or connection.status != "connected"
                else "Account authorization is recorded; publishing still requires its provider integration."
            ),
        })

    publication_map = {
        (publication.product_id, publication.channel): publication
        for publication in ProductChannelPublication.objects.filter(
            product__organization=organization,
            product__deleted_at__isnull=True,
        )
    }

    product_rows = []
    for product in products:
        cells = []
        for channel in CHANNEL_REGISTRY:
            kind = channel["kind"]
            cell = {"key": channel["key"], "label": channel["label"], "kind": kind}
            if kind == "product_flag":
                cell["enabled"] = bool(getattr(product, channel["product_field"]))
            elif kind == "visibility":
                cell["visible"] = bool(
                    organization.organization_type == "platform_owner"
                    and product.is_publicly_visible
                )
                cell["locked"] = organization.organization_type != "platform_owner"
            else:
                publication = publication_map.get((product.pk, channel["key"]))
                cell["publication"] = publication
                cell["enabled"] = bool(publication and publication.is_enabled)
            cells.append(cell)
        product_rows.append({"product": product, "cells": cells})

    return render(request, "channels/dashboard.html", {
        "organization": organization,
        "product_rows": product_rows,
        "channel_columns": CHANNEL_REGISTRY,
        "connection_cards": connection_cards,
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
    definition = CHANNEL_BY_KEY.get(channel)
    if not definition or definition["kind"] == "visibility":
        return HttpResponseForbidden("Unsupported channel.")

    enabled = request.POST.get("enabled") == "1"
    if definition["kind"] == "product_flag":
        field_name = definition["product_field"]
        setattr(product, field_name, enabled)
        product.save(update_fields=[field_name, "updated_at"])
    elif definition["kind"] == "publication":
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

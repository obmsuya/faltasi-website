"""Organization-configured product discovery for customer messaging."""

from decimal import Decimal

from products.models import Product, ProductDiscoverySettings
from products.services.public_data import (
    clean_public_product_data,
    format_public_product_json,
)
from products.services.search import search_organization_products


def get_product_discovery_settings(organization):
    if not organization:
        return None
    return ProductDiscoverySettings.objects.filter(
        organization=organization,
        is_active=True,
    ).first()


def _language_messages(configuration, language=None):
    messages = configuration.messages if isinstance(configuration.messages, dict) else {}
    language = str(language or configuration.default_language or "sw").lower()
    language = "en" if language.startswith("en") else "sw"
    selected = messages.get(language)
    if not isinstance(selected, dict):
        selected = messages.get(configuration.default_language, {})
    return selected if isinstance(selected, dict) else {}


def get_product_discovery_message(configuration, message_key, language=None):
    if not configuration:
        return None
    message = _language_messages(configuration, language).get(message_key)
    return message.strip() if isinstance(message, str) and message.strip() else None


def _phrases(configuration, field_name):
    values = getattr(configuration, field_name, []) if configuration else []
    if not isinstance(values, list):
        return set()
    return {str(value).strip().casefold().strip(" .,!?:;") for value in values if str(value).strip()}


def classify_product_discovery_response(text, configuration):
    normalized = str(text or "").strip().casefold().strip(" .,!?:;")
    if not normalized or not configuration:
        return None
    if normalized in _phrases(configuration, "yes_phrases"):
        return "yes"
    if normalized in _phrases(configuration, "no_phrases"):
        return "no"
    return None


def _format_product(product, configuration, language=None, *, include_prompt=True):
    messages = _language_messages(configuration, language)
    labels = messages.get("labels", {})
    labels = labels if isinstance(labels, dict) else {}
    lines = []

    intro = messages.get("intro")
    if isinstance(intro, str) and intro.strip():
        lines.append(intro.strip())
    lines.append(product.name)

    for field_name in ("brand", "model", "manufacturer"):
        value = getattr(product, field_name, None)
        label = labels.get(field_name)
        if value and label:
            lines.append(f"{label}: {value}")

    description = product.short_description or product.description
    description_label = labels.get("description")
    if description and description_label:
        maximum = max(1, min(int(configuration.max_description_chars or 1), 4000))
        lines.extend(("", f"{description_label}:", str(description).strip()[:maximum]))

    for field_name in ("specifications", "additional_information"):
        value = clean_public_product_data(getattr(product, field_name, None) or {})
        heading = labels.get(field_name)
        details = format_public_product_json(value, messages.get("attribute_labels", {}))
        if heading and details:
            lines.extend(("", f"{heading}:", *details))

    price_label = labels.get("price")
    if price_label:
        if product.price is None:
            price_value = messages.get("price_on_request")
        else:
            price_value = f"{product.currency} {Decimal(str(product.price)):,.2f}"
        if price_value:
            lines.extend(("", f"{price_label}: {price_value}"))

    availability_label = labels.get("availability")
    if availability_label:
        lines.append(f"{availability_label}: {product.get_availability_display()}")

    prompt = messages.get("another_option_prompt") if include_prompt else None
    if isinstance(prompt, str) and prompt.strip():
        lines.extend(("", prompt.strip()))

    return "\n".join(lines) if lines else None



def format_whatsapp_product_caption(product, organization):
    """Build the WhatsApp image caption from organization-owned labels."""
    configuration = get_product_discovery_settings(organization)
    if not configuration or not product:
        return None

    messages = _language_messages(configuration, getattr(organization, "language", None))
    labels = messages.get("labels", {})
    labels = labels if isinstance(labels, dict) else {}
    lines = [product.name]

    for field_name in ("brand", "model"):
        value = getattr(product, field_name, None)
        label = labels.get(field_name)
        if value and label:
            lines.append(f"{label}: {value}")

    price_label = labels.get("price")
    if price_label:
        if product.price is None:
            price_value = messages.get("price_on_request")
        else:
            price_value = f"{product.currency} {Decimal(str(product.price)):,.2f}"
        if price_value:
            lines.append(f"{price_label}: {price_value}")

    availability_label = labels.get("availability")
    if availability_label:
        lines.append(f"{availability_label}: {product.get_availability_display()}")

    return "\n".join(lines)[:1024]

def _clear_discovery_state(state, data):
    for key in ("whatsapp_product_remaining_ids", "whatsapp_product_ids", "whatsapp_product_discovery"):
        data.pop(key, None)
    state.data = data
    state.current_step = "whatsapp_product_completed"
    state.waiting_for = None
    state.save()


def handle_product_discovery_followup(text, organization, state):
    """Handle configured yes/no responses while another product is offered."""
    data = dict(state.data or {})
    discovery = data.get("whatsapp_product_discovery")
    if not isinstance(discovery, dict) or discovery.get("status") != "awaiting_next_option":
        return {"handled": False, "reply": None}

    configuration = get_product_discovery_settings(organization)
    response = classify_product_discovery_response(text, configuration)
    if not response:
        return {"handled": False, "reply": None}

    language = getattr(organization, "language", None)
    if response == "no":
        reply = get_product_discovery_message(configuration, "thank_you", language)
        _clear_discovery_state(state, data)
        return {"handled": True, "reply": reply}

    remaining_ids = data.get("whatsapp_product_remaining_ids", discovery.get("remaining_product_ids", []))
    remaining_ids = remaining_ids if isinstance(remaining_ids, list) else []
    next_product = None
    while remaining_ids and next_product is None:
        next_id = remaining_ids.pop(0)
        next_product = Product.objects.filter(
            organization=organization,
            pk=next_id,
            is_active=True,
            deleted_at__isnull=True,
            show_on_whatsapp=True,
        ).first()

    if next_product is None:
        reply = get_product_discovery_message(configuration, "no_more_options", language)
        _clear_discovery_state(state, data)
        return {"handled": True, "reply": reply}

    data["whatsapp_product_ids"] = [next_product.pk]
    data["whatsapp_product_remaining_ids"] = remaining_ids
    data["whatsapp_product_discovery"] = {
        "status": "awaiting_next_option",
        "current_product_id": next_product.pk,
        "remaining_product_ids": remaining_ids,
    }
    state.data = data
    state.current_step = "whatsapp_product_completed"
    state.waiting_for = None
    state.save()
    return {"handled": True, "reply": _format_product(next_product, configuration, language)}


def search_and_prepare_whatsapp_product(
    text, organization, state=None, *, price_preference="relevance", max_price=None
):
    """Search the tenant catalogue and prepare the first configured product reply."""
    if not text or not organization:
        return None

    configuration = get_product_discovery_settings(organization)
    if not configuration:
        return None

    search_options = {}
    if price_preference != "relevance":
        search_options["price_preference"] = price_preference
    if max_price is not None:
        search_options["max_price"] = max_price

    results = search_organization_products(
        organization,
        text,
        limit=configuration.max_results,
        **search_options,
    )
    if not results:
        return None

    product_ids = [item.get("id") for item in results if item.get("id") is not None]
    products_by_id = Product.objects.filter(
        organization=organization,
        pk__in=product_ids,
        is_active=True,
        deleted_at__isnull=True,
        show_on_whatsapp=True,
    ).select_related("category").in_bulk()
    matches = [products_by_id[item_id] for item_id in product_ids if item_id in products_by_id]
    if not matches:
        return None

    product = matches[0]
    remaining_ids = [item.pk for item in matches[1:]]
    if state is not None:
        data = dict(state.data or {})
        data.pop("whatsapp_product_discovery", None)
        for key in (
            "selected_whatsapp_product_id", "selected_whatsapp_product_name",
            "whatsapp_product_quantity", "whatsapp_product_action",
        ):
            data.pop(key, None)
        data["whatsapp_product_ids"] = [product.pk]
        data["whatsapp_product_remaining_ids"] = remaining_ids
        data["whatsapp_product_discovery"] = {
            "status": "awaiting_next_option",
            "current_product_id": product.pk,
            "remaining_product_ids": remaining_ids,
        }
        state.current_step = "whatsapp_product_completed"
        state.waiting_for = None
        state.data = data
        state.save()

    return _format_product(product, configuration, getattr(organization, "language", None))

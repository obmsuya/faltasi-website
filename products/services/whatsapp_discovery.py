"""Organization-configured product discovery for customer messaging."""

from decimal import Decimal, InvalidOperation
import math
import re

from django.db.models import CharField, Q
from django.db.models.functions import Cast

from products.models import Product, ProductDiscoverySettings
from products.services.public_data import (
    clean_public_product_data,
    format_public_product_json,
)


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


def _discovery_tokens(value):
    return list(dict.fromkeys(re.findall(r"[a-z0-9]+", str(value or "").casefold())))


def _product_search_text(product):
    values = [
        product.name, product.sku, product.barcode, product.brand, product.model,
        product.manufacturer, product.short_description, product.description,
        product.category.name if product.category else "",
        str(product.specifications or {}), str(product.additional_information or {}),
    ]
    return " ".join(str(value or "") for value in values).casefold()


def _valid_price(value):
    if value is None:
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return price if price.is_finite() and price >= 0 else None


def _apply_relative_price_tier(products, preference):
    """Apply economical/mid-range/premium tiers from real prices per currency."""
    if preference not in {"economical", "mid_range", "premium"}:
        return products
    by_currency = {}
    for product in products:
        price = _valid_price(product.price)
        if price is not None:
            by_currency.setdefault(str(product.currency or "").upper(), []).append((price, product))
    selected_ids = set()
    tier_index = {"economical": 0, "mid_range": 1, "premium": 2}[preference]
    for entries in by_currency.values():
        unique_prices = sorted({price for price, _ in entries})
        if len(unique_prices) <= 1:
            selected_ids.update(product.pk for _, product in entries)
            continue
        tiers = {}
        for index, price in enumerate(unique_prices):
            tier = min(2, (index * 3) // len(unique_prices))
            tiers[price] = tier
        available_tiers = set(tiers.values())
        chosen_tier = tier_index
        if chosen_tier not in available_tiers:
            chosen_tier = min(available_tiers, key=lambda item: (abs(item - tier_index), item))
        selected_ids.update(
            product.pk for price, product in entries if tiers[price] == chosen_tier
        )
    # Products without a valid selling price cannot be compared in price tiers.
    return [product for product in products if product.pk in selected_ids]


def _search_catalogue(organization, query, *, price_preference="any", min_price=None,
                      max_price=None, specification_requirements=None, limit=5):
    """Fresh WhatsApp-only matching; does not use the legacy shared ranking."""
    tokens = _discovery_tokens(query)
    if not organization or not tokens:
        return []
    settings = get_product_discovery_settings(organization)
    max_candidates = min(max(int(getattr(settings, "max_candidates", 500) or 500), 1), 2000)
    fields = (
        "name", "sku", "barcode", "brand", "model", "manufacturer",
        "short_description", "description", "category__name",
        "_specifications_text", "_additional_information_text",
    )
    condition = Q()
    for token in tokens:
        for field in fields:
            condition |= Q(**{f"{field}__icontains": token})
    queryset = Product.objects.filter(
        organization=organization, is_active=True, deleted_at__isnull=True,
        show_on_whatsapp=True,
    ).annotate(
        _specifications_text=Cast("specifications", output_field=CharField()),
        _additional_information_text=Cast("additional_information", output_field=CharField()),
    ).filter(condition).select_related("category").distinct().order_by("pk")
    candidates = list(queryset[:max_candidates])

    required = [str(item).strip().casefold() for item in (specification_requirements or [])
                if isinstance(item, str) and item.strip()]
    scored = []
    for product in candidates:
        corpus = _product_search_text(product)
        if required and not all(item in corpus for item in required):
            continue
        matched = sum(1 for token in tokens if token in corpus)
        minimum_matches = 1 if len(tokens) <= 3 else max(2, math.ceil(len(tokens) * 0.35))
        if matched < minimum_matches:
            continue
        score = matched / len(tokens)
        # Exact product identity terms carry more weight than descriptive overlap.
        identity = " ".join(str(value or "") for value in (
            product.name, product.brand, product.model, product.sku, product.barcode,
        )).casefold()
        identity_matches = sum(1 for token in tokens if token in identity)
        score += identity_matches * 0.35
        scored.append((product, score))

    min_value, max_value = _valid_price(min_price), _valid_price(max_price)
    if min_price is not None and min_value is None:
        return []
    if max_price is not None and max_value is None:
        return []
    if min_value is not None or max_value is not None:
        filtered = []
        for product, score in scored:
            price = _valid_price(product.price)
            if price is None:
                continue
            if min_value is not None and price < min_value:
                continue
            if max_value is not None and price > max_value:
                continue
            filtered.append((product, score))
        scored = filtered

    products = [product for product, _ in scored]
    if price_preference in {"economical", "mid_range", "premium"} and not (min_value is not None or max_value is not None):
        products = _apply_relative_price_tier(products, price_preference)
    score_by_id = {product.pk: score for product, score in scored}

    if price_preference in {"lowest", "economical"}:
        products.sort(key=lambda p: (_valid_price(p.price) is None, _valid_price(p.price) or Decimal("0"), -score_by_id[p.pk], p.display_order, p.name.casefold()))
    elif price_preference in {"premium"}:
        products.sort(key=lambda p: (_valid_price(p.price) is None, -(_valid_price(p.price) or Decimal("0")), -score_by_id[p.pk], p.display_order, p.name.casefold()))
    elif price_preference == "mid_range":
        products.sort(key=lambda p: (_valid_price(p.price) is None, abs((_valid_price(p.price) or Decimal("0"))), -score_by_id[p.pk], p.display_order, p.name.casefold()))
    else:
        products.sort(key=lambda p: (-score_by_id[p.pk], p.display_order, p.name.casefold()))
    return products[:max(1, min(int(limit or 5), 20))]


def search_and_prepare_whatsapp_product(
    text, organization, state=None, *, price_preference="any", min_price=None,
    max_price=None, specification_requirements=None,
):
    """Search real tenant products and prepare the first product reply."""
    if not text or not organization:
        return None
    configuration = get_product_discovery_settings(organization)
    if not configuration:
        return None
    matches = _search_catalogue(
        organization, text, price_preference=price_preference,
        min_price=min_price, max_price=max_price,
        specification_requirements=specification_requirements,
        limit=configuration.max_results,
    )
    if not matches:
        return None
    product = matches[0]
    remaining_ids = [item.pk for item in matches[1:]]
    if state is not None:
        data = dict(state.data or {})
        data.pop("whatsapp_product_discovery", None)
        for key in ("selected_whatsapp_product_id", "selected_whatsapp_product_name", "whatsapp_product_quantity", "whatsapp_product_action"):
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

"""Canonical tenant-scoped product catalogue search."""

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.conf import settings
from django.db.models import CharField, Q
from django.db.models.functions import Cast

from products.models import Product, ProductDiscoverySettings

MAX_QUERY_LENGTH = 500


def _tokens(query):
    if not query:
        return []
    query = str(query)[:MAX_QUERY_LENGTH].lower()
    return list(dict.fromkeys(re.findall(r"[a-z0-9]+", query)))


def _safe_limit(limit, default, maximum=20):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(limit, maximum))


def _matching_q(fields, tokens):
    condition = Q()
    for field in fields:
        for token in tokens:
            condition |= Q(**{f"{field}__icontains": token})
    return condition


def get_public_product_image_url(product):
    """
    Return only HTTPS product image URLs from Faltasi's approved
    public Cloudflare R2 media domain.
    """
    if not product.image or not product.image.name:
        return None

    try:
        url = product.image.url
        parsed = urlsplit(str(url))
        media_base = urlsplit(str(getattr(settings, "MEDIA_URL", "")))
    except Exception:
        return None

    if (
        parsed.scheme.lower() != "https"
        or not media_base.netloc
        or parsed.netloc.lower() != media_base.netloc.lower()
        or not parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None

    return str(url)

def _normalize_relevance_token(token):
    """Normalize simple English plurals for product-query matching."""
    token = str(token).lower()
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("ches", "shes", "xes", "zes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token

def _relevance_tokens(value):
    return {
        _normalize_relevance_token(token)
        for token in _tokens(value)
    }

def search_organization_products(
    organization,
    query,
    limit=None,
    *,
    price_preference="relevance",
    max_price=None,
):
    """
    Canonical organization-scoped product search.

    Used by customer-facing WhatsApp product discovery and internal
    Product Knowledge retrieval.

    Returns selling information only. Never returns cost price or
    other internal financial fields.
    """
    tokens = _tokens(query)

    if not tokens or organization is None:
        return []

    discovery_settings = ProductDiscoverySettings.objects.filter(
        organization_id=getattr(organization, "pk", None),
        is_active=True,
    ).first() or ProductDiscoverySettings()
    configured_stop_words = (
        discovery_settings.search_stop_words
        if discovery_settings and isinstance(discovery_settings.search_stop_words, list)
        else []
    )
    ignored_tokens = {
        _normalize_relevance_token(str(item).strip().lower())
        for item in configured_stop_words
        if str(item).strip()
    }

    query_tokens = {
        _normalize_relevance_token(token)
        for token in tokens
        if token not in ignored_tokens
    }

    if not query_tokens:
        return []

    limit = _safe_limit(
        limit,
        default=discovery_settings.max_results,
    )

    fields = [
        "name",
        "sku",
        "barcode",
        "brand",
        "model",
        "manufacturer",
        "short_description",
        "description",
        "category__name",
        "_specifications_text",
        "_additional_information_text",
    ]

    # Strict organization and product visibility boundaries.
    queryset = Product.objects.filter(
        organization=organization,
        is_active=True,
        deleted_at__isnull=True,
        show_on_whatsapp=True,
    ).annotate(
        _specifications_text=Cast(
            "specifications",
            output_field=CharField(),
        ),
        _additional_information_text=Cast(
            "additional_information",
            output_field=CharField(),
        ),
    ).filter(
        # Use normalized query tokens so singular/plural variants such as
        # "laptop" and "laptops" can find the same products.
        _matching_q(fields, query_tokens)
    ).select_related(
        "category"
    ).order_by("pk")

    maximum_candidates = _safe_limit(
        discovery_settings.max_candidates,
        default=500,
        maximum=2000,
    )
    candidates = list(queryset[:maximum_candidates])
    results = []

    long_query_threshold = max(1, int(discovery_settings.minimum_query_tokens_for_long_query))
    minimum_matches = (
        max(1, int(discovery_settings.minimum_matches_for_long_query))
        if len(query_tokens) >= long_query_threshold
        else 1
    )
    required_coverage = (
        float(discovery_settings.long_query_required_coverage)
        if len(query_tokens) >= long_query_threshold
        else float(discovery_settings.short_query_required_coverage)
    )
    required_coverage = max(0.0, min(required_coverage, 1.0))

    for product in candidates:
        specifications = product.specifications or {}
        additional_information = product.additional_information or {}

        searchable_values = {
            "name": product.name or "",
            "sku": product.sku or "",
            "barcode": product.barcode or "",
            "brand": product.brand or "",
            "model": product.model or "",
            "manufacturer": product.manufacturer or "",
            "short_description": product.short_description or "",
            "description": product.description or "",
            "specifications": str(specifications),
            "additional_information": str(additional_information),
            "category": (
                product.category.name if product.category else ""
            ),
        }

        field_tokens = {
            field: _relevance_tokens(value)
            for field, value in searchable_values.items()
        }

        # Prefer matches in product identity fields. Keep description and
        # technical-detail matching as a fallback so customers can still find
        # products by a feature that is not repeated in the product name.
        identity_fields = (
            "name",
            "category",
            "brand",
            "model",
            "sku",
            "barcode",
            "manufacturer",
        )
        identity_tokens = set().union(
            *(field_tokens[field] for field in identity_fields)
        )
        matched_identity_tokens = query_tokens.intersection(identity_tokens)

        all_product_tokens = set().union(*field_tokens.values())
        matched_tokens = query_tokens.intersection(all_product_tokens)
        coverage = len(matched_tokens) / len(query_tokens)

        if (
            len(matched_tokens) < minimum_matches
            or coverage < required_coverage
        ):
            continue

        # Identity matches receive a large ranking advantage. If any identity
        # matches exist, supporting-only matches are removed below; otherwise
        # they remain available as the fallback search tier.
        weights = (
            discovery_settings.relevance_weights
            if isinstance(discovery_settings.relevance_weights, dict)
            else {}
        )
        score = 0
        for field, weight in weights.items():
            if field not in field_tokens:
                continue
            try:
                configured_weight = int(weight)
            except (TypeError, ValueError, OverflowError):
                continue
            score += len(query_tokens.intersection(field_tokens[field])) * configured_weight
        score += round(coverage * int(discovery_settings.coverage_bonus_multiplier))
        identity_match = bool(matched_identity_tokens)
        if identity_match:
            score += int(discovery_settings.identity_match_bonus)

        normalized_query = " ".join(sorted(query_tokens))
        normalized_name = " ".join(_tokens(product.name or ""))
        if normalized_query and normalized_query in normalized_name:
            score += int(discovery_settings.exact_name_match_bonus)

        results.append({
            "source": "product",
            "id": product.pk,
            "name": product.name,
            "sku": product.sku,
            "brand": product.brand,
            "model": product.model,
            "category": searchable_values["category"] or None,
            "description": (
                product.short_description or product.description
            ),
            "price": (
                str(product.price)
                if product.price is not None else None
            ),
            "currency": product.currency,
            "unit": product.unit,
            "availability": product.availability,
            "availability_display": product.get_availability_display(),
            "specifications": specifications,
            "additional_information": additional_information,
            "image_url": get_public_product_image_url(product),
            "display_order": product.display_order,
            "score": score,
            "_identity_match": identity_match,
        })

    # Do not mix unrelated supporting-text matches into a result set when
    # there are direct product identity matches. Use supporting matches only
    # when the query cannot be matched to any product identity fields.
    if any(item["_identity_match"] for item in results):
        results = [
            item for item in results
            if item["_identity_match"]
        ]

    for item in results:
        item.pop("_identity_match", None)

    # Optional customer price constraints use selling price only.
    # Keep the existing relevance ranking unchanged by default.
    if max_price is not None:
        try:
            maximum = Decimal(str(max_price))
        except (InvalidOperation, TypeError, ValueError):
            return []

        if not maximum.is_finite() or maximum < 0:
            return []

        budget_matches = []
        for item in results:
            raw_price = item.get("price")
            if raw_price is None:
                continue
            try:
                selling_price = Decimal(str(raw_price))
            except (InvalidOperation, TypeError, ValueError):
                continue
            if selling_price.is_finite() and selling_price <= maximum:
                budget_matches.append(item)

        results = budget_matches

    if price_preference == "lowest":
        def selling_price_key(item):
            raw_price = item.get("price")
            if raw_price is None:
                return (1, Decimal("0"), -item["score"],
                        item["display_order"], (item["name"] or "").lower())
            try:
                price = Decimal(str(raw_price))
            except (InvalidOperation, TypeError, ValueError):
                return (1, Decimal("0"), -item["score"],
                        item["display_order"], (item["name"] or "").lower())
            if not price.is_finite():
                return (1, Decimal("0"), -item["score"],
                        item["display_order"], (item["name"] or "").lower())
            return (0, price, -item["score"],
                    item["display_order"], (item["name"] or "").lower())

        results.sort(key=selling_price_key)
    else:
        results.sort(
            key=lambda item: (
                -item["score"],
                item["display_order"],
                (item["name"] or "").lower(),
            )
        )

    return results[:limit]

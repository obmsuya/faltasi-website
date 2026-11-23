
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.db.models import CharField, Q
from django.db.models.functions import Cast

from products.models import Product
from business_requests.models import RequestCategory
from .models import ProductKnowledgeDocument, ProductKnowledgeChunk


MAX_QUERY_LENGTH = 500
DEFAULT_LIMIT = 5


PUBLIC_PRODUCT_MEDIA_HOST = "media.faltasi.com"


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
    except Exception:
        return None

    if (
        parsed.scheme.lower() != "https"
        or parsed.netloc.lower() != PUBLIC_PRODUCT_MEDIA_HOST
        or not parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None

    return str(url)


def _tokens(query):
    """Convert a query into unique, lowercase search terms."""
    if not query:
        return []

    query = str(query)[:MAX_QUERY_LENGTH].lower()
    return list(dict.fromkeys(re.findall(r"[a-z0-9]+", query)))


def _safe_limit(limit, default=DEFAULT_LIMIT, maximum=20):
    """Prevent invalid or excessively large result limits."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return default

    return max(1, min(limit, maximum))


def _matching_q(fields, tokens):
    """Build a database-level OR filter for the supplied fields and terms."""
    condition = Q()

    for field in fields:
        for token in tokens:
            condition |= Q(**{f"{field}__icontains": token})

    return condition




def search_document_chunks(
    organization,
    query,
    limit=DEFAULT_LIMIT,
    *,
    can_access_admin_only=False,
    customer_facing=False,
):
    """
    Search chunks from ready, active documents in one organization.

    Pending or indexed documents are eligible because chunks are stored
    locally. Failed, archived, inactive, and deleted documents are excluded.
    """
    tokens = _tokens(query)

    if not tokens or organization is None:
        return []

    limit = _safe_limit(limit)

    queryset = ProductKnowledgeChunk.objects.filter(
        organization=organization,
        document__organization=organization,
        document__status=ProductKnowledgeDocument.Status.READY,
        document__index_status__in=[
            ProductKnowledgeDocument.IndexStatus.PENDING,
            ProductKnowledgeDocument.IndexStatus.INDEXED,
        ],
        document__is_active=True,
        document__deleted_at__isnull=True,
    ).filter(
        _matching_q(["text", "section_title"], tokens)
    )

    if not can_access_admin_only:
        queryset = queryset.filter(
            document__access_level=ProductKnowledgeDocument.AccessLevel.EMPLOYEE
        )

    # WhatsApp customers may only receive documents explicitly classified
    # as FAQs. Other Employee Access documents remain internal to AI STAFF.
    if customer_facing:
        queryset = queryset.filter(
            document__document_type=ProductKnowledgeDocument.DocumentType.FAQ
        )

    queryset = queryset.select_related("document")

    candidates = list(
        queryset.order_by(
            "document_id",
            "chunk_index",
            "pk",
        )[:500]
    )
    normalized_query = str(query).strip().lower()
    results = []

    for chunk in candidates:
        text = chunk.text.lower()
        matched_tokens = [token for token in tokens if token in text]

        if not matched_tokens:
            continue

        score = len(matched_tokens)

        if normalized_query and normalized_query in text:
            score += 10

        results.append({
            "source": "document",
            "document_id": chunk.document_id,
            "title": chunk.document.title,
            "document_type": chunk.document.document_type,
            "chunk_id": chunk.pk,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "section_title": chunk.section_title,
            "text": chunk.text,
            "score": score,
        })


    results.sort(
        key=lambda item: (
            -item["score"],
            item["title"].lower(),
            item["document_id"],
            item["chunk_index"],
            item["chunk_id"],
        )
    )

    return results[:limit]


def get_request_categories(organization, query=None, limit=20):
    """
    Return Excel-configured request categories and active questions.

    This function reads the database populated by the existing Excel
    importer. It never creates, changes, or hardcodes request questions.
    """
    if organization is None:
        return []

    tokens = _tokens(query) if query else []
    limit = _safe_limit(limit, default=20, maximum=100)

    queryset = RequestCategory.objects.filter(
        organization=organization,
        is_active=True,
    ).select_related(
        "department"
    ).prefetch_related(
        "request_fields"
    )

    if tokens:
        queryset = queryset.filter(
            _matching_q(
                [
                    "name",
                    "description",
                    "keywords",
                    "department__name",
                ],
                tokens,
            )
        )

    results = []

    for category in queryset:
        fields = [
            field
            for field in category.request_fields.all()
            if field.is_active
        ]

        category_text = " ".join([
            category.name or "",
            category.description or "",
            category.keywords or "",
            category.department.name if category.department else "",
        ]).lower()

        score = sum(
            1 for token in tokens if token in category_text
        )

        results.append({
            "source": "excel_request_configuration",
            "id": category.pk,
            "name": category.name,
            "description": category.description,
            "keywords": category.keywords,
            "department": (
                category.department.name
                if category.department else None
            ),
            "questions": [
                {
                    "name": field.name,
                    "question": field.question,
                    "field_type": field.field_type,
                    "required": field.is_required,
                    "order": field.order,
                }
                for field in sorted(
                    fields,
                    key=lambda item: (item.order, item.pk),
                )
            ],
            "score": score,
        })

    results.sort(
        key=lambda item: (-item["score"], item["name"].lower())
    )
    return results[:limit]



def retrieve_knowledge(
    organization,
    query,
    product_limit=5,
    document_limit=5,
    category_limit=5,
    *,
    can_access_admin_only=False,
    customer_facing=False,
):
    """
    Retrieve organization-specific products, document passages, and
    configured request categories for the AI knowledge assistant.

    Product retrieval uses the shared canonical organization-scoped
    product search engine.
    """
    if organization is None or not _tokens(query):
        return {
            "query": str(query or "")[:MAX_QUERY_LENGTH],
            "products": [],
            "documents": [],
            "request_categories": [],
        }

    return {
        "query": str(query)[:MAX_QUERY_LENGTH],
        "products": (
            search_organization_products(
                organization,
                query,
                limit=product_limit,
            )
            if product_limit is not None and int(product_limit) > 0
            else []
        ),
        "documents": (
            search_document_chunks(
                organization,
                query,
                limit=document_limit,
                can_access_admin_only=can_access_admin_only,
                customer_facing=customer_facing,
            )
            if document_limit is not None and int(document_limit) > 0
            else []
        ),
        "request_categories": (
            get_request_categories(
                organization,
                query,
                limit=category_limit,
            )
            if category_limit is not None and int(category_limit) > 0
            else []
        ),
    }

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
    limit=DEFAULT_LIMIT,
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

    # Remove conversational words that should not influence matching.
    ignored_tokens = {
        "a", "an", "and", "are", "available", "can", "do", "for",
        "me", "my", "of", "please", "show", "the", "to", "what",
        "which", "with", "would", "you", "your", "find", "get", "need",

        # Common Swahili conversational words.
        "nataka", "kununua", "ninataka", "ninahitaji", "nahitaji",
        "naomba", "tafadhali", "bei", "ya", "za", "na", "ni",
        "kwa", "yangu", "una", "unazo", "onyesha",
    }

    query_tokens = {
        _normalize_relevance_token(token)
        for token in tokens
        if token not in ignored_tokens
    }

    if not query_tokens:
        return []

    limit = _safe_limit(limit)

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

    candidates = list(queryset[:500])
    results = []

    minimum_matches = 2 if len(query_tokens) >= 3 else 1
    required_coverage = (
        0.5 if len(query_tokens) >= 3
        else 1 / len(query_tokens)
    )

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
        weights = {
            "name": 25,
            "category": 18,
            "brand": 14,
            "model": 14,
            "sku": 10,
            "barcode": 10,
            "manufacturer": 8,
            "short_description": 3,
            "description": 2,
            "specifications": 1,
            "additional_information": 1,
        }

        score = sum(
            len(query_tokens.intersection(field_tokens[field])) * weight
            for field, weight in weights.items()
        )
        score += round(coverage * 10)
        identity_match = bool(matched_identity_tokens)
        if identity_match:
            score += 1000

        normalized_query = " ".join(sorted(query_tokens))
        normalized_name = " ".join(_tokens(product.name or ""))
        if normalized_query and normalized_query in normalized_name:
            score += 20

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

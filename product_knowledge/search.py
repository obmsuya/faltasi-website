
import re

from django.db.models import Q

from products.models import Product
from business_requests.models import RequestCategory
from .models import ProductKnowledgeDocument, ProductKnowledgeChunk


MAX_QUERY_LENGTH = 500
DEFAULT_LIMIT = 5


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


def search_products(organization, query, limit=DEFAULT_LIMIT):
    """
    Search WhatsApp-visible products for one organization.

    Filtering occurs in the database before results are ranked.
    No AI API calls are made.
    """
    tokens = _tokens(query)

    if not tokens or organization is None:
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
    ]

    queryset = Product.objects.filter(
        organization=organization,
        is_active=True,
        deleted_at__isnull=True,
        show_on_whatsapp=True,
    ).filter(_matching_q(fields, tokens))

    # JSON specifications are included in ranking after database filtering.
    candidates = list(queryset[:200])
    normalized_query = str(query).strip().lower()
    results = []

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
        }

        searchable_text = " ".join(
            str(value) for value in searchable_values.values()
        ).lower()

        matched_tokens = [
            token for token in tokens if token in searchable_text
        ]

        if not matched_tokens:
            continue

        score = len(matched_tokens)
        name = (product.name or "").lower()

        if normalized_query == name:
            score += 20
        elif normalized_query in name:
            score += 10

        for field in ("sku", "barcode", "model", "brand"):
            value = str(searchable_values[field]).lower()

            if value and any(token in value for token in tokens):
                score += 3

        results.append({
            "source": "product",
            "id": product.pk,
            "name": product.name,
            "sku": product.sku,
            "brand": product.brand,
            "model": product.model,
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
            "specifications": specifications,
            "additional_information": additional_information,
            "score": score,
        })

    results.sort(
        key=lambda item: (-item["score"], item["name"].lower())
    )
    return results[:limit]


def search_document_chunks(
    organization,
    query,
    limit=DEFAULT_LIMIT,
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
    ).select_related("document")

    candidates = list(queryset[:500])
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
        key=lambda item: (-item["score"], item["title"].lower())
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
):
    """
    Retrieve product records, document passages, and Excel-configured
    request categories for a single customer query.

    This function prepares local knowledge only. It does not call an AI
    provider or send messages to WhatsApp.
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
        "products": search_products(
            organization, query, limit=product_limit
        ),
        "documents": search_document_chunks(
            organization, query, limit=document_limit
        ),
        "request_categories": get_request_categories(
            organization, query, limit=category_limit
        ),
    }

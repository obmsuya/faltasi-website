
import re

from django.db.models import Q

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




def _search_products_for_knowledge(organization, query, limit):
    """Search the full business question, then its individual terms."""
    try:
        maximum = max(1, int(limit))
    except (TypeError, ValueError, OverflowError):
        maximum = 5

    results = search_organization_products(organization, query, limit=maximum)
    if results:
        return results[:maximum]

    tokens = list(dict.fromkeys(_tokens(query)))
    collected = []
    seen_ids = set()
    for token in tokens:
        for product in search_organization_products(
            organization, token, limit=maximum
        ):
            product_id = product.get("id")
            if product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            collected.append(product)
            if len(collected) >= maximum:
                return collected
    return collected


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
            _search_products_for_knowledge(
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

def search_organization_products(
    organization,
    query,
    limit=None,
    *,
    price_preference="relevance",
    max_price=None,
):
    """Compatibility entry point; catalogue search is owned by Products."""
    from products.services.search import search_organization_products as service
    return service(
        organization,
        query,
        limit=limit,
        price_preference=price_preference,
        max_price=max_price,
    )

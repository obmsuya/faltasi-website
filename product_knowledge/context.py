
"""
Build a safe, organization-specific context for the Faltasi AI assistant.

This module retrieves and formats existing data only. It does not call
an external AI API, modify the database, or send customer messages.
"""

from decimal import Decimal

from .search import MAX_QUERY_LENGTH, retrieve_knowledge
from products.services.search import search_organization_products


MAX_CONTEXT_CHARS = 18000
MAX_DESCRIPTION_CHARS = 1200
MAX_DOCUMENT_CHARS = 3500

from products.services.public_data import clean_public_product_data


def _sanitize_product_data(value):
    """Compatibility wrapper around the canonical Products sanitizer."""
    return clean_public_product_data(value)


def _clean(value):
    """Convert supported values into readable text."""
    if value is None:
        return ""

    if isinstance(value, Decimal):
        return format(value, "f")

    if isinstance(value, dict):
        parts = []

        for key, item in _sanitize_product_data(value).items():
            cleaned = _clean(item)
            if cleaned:
                parts.append(f"{key}: {cleaned}")

        return "; ".join(parts)

    if isinstance(value, (list, tuple)):
        parts = []

        for item in value:
            cleaned = _clean(item)
            if cleaned:
                parts.append(cleaned)

        return "; ".join(parts)

    return str(value).strip()


def _add_line(lines, label, value, max_length=None):
    """Add a labelled, non-empty value with an optional length limit."""
    cleaned = _clean(value)

    if not label or not cleaned:
        return

    if max_length is not None:
        cleaned = cleaned[:max_length]

    lines.append(f"{label}: {cleaned}")


def _format_product(product, labels, max_description_chars):
    """Format product values using the selected organization's labels."""
    lines = []
    _add_line(lines, labels.get("product", ""), product.get("name"))
    _add_line(lines, labels.get("sku", ""), product.get("sku"))
    _add_line(lines, labels.get("brand", ""), product.get("brand"))
    _add_line(lines, labels.get("model", ""), product.get("model"))
    _add_line(lines, labels.get("description", ""), product.get("description"), max_length=max_description_chars)
    _add_line(lines, labels.get("price", ""), product.get("price"))
    _add_line(lines, labels.get("currency", ""), product.get("currency"))
    _add_line(lines, labels.get("unit", ""), product.get("unit"))
    _add_line(lines, labels.get("availability", ""), product.get("availability"))
    _add_line(lines, labels.get("specifications", ""), product.get("specifications"), max_length=max_description_chars)
    _add_line(lines, labels.get("additional_information", ""), product.get("additional_information"), max_length=max_description_chars)
    return "\n".join(lines)


def _format_document(document, labels, max_document_chars):
    """Format an untrusted document excerpt using configured labels."""
    lines = []
    _add_line(lines, labels.get("document", ""), document.get("title"))
    _add_line(lines, labels.get("document_type", ""), document.get("document_type"))
    _add_line(lines, labels.get("page", ""), document.get("page_number"))
    _add_line(lines, labels.get("section", ""), document.get("section_title"))
    content = _clean(document.get("text"))
    excerpt_label = labels.get("untrusted_reference_excerpt", "")
    if content and excerpt_label:
        lines.append(f"{excerpt_label}: " + content[:max_document_chars])
    return "\n".join(lines)


def _format_category(category, labels, max_description_chars):
    """Format configured business request questions without inventing fields."""
    lines = []
    _add_line(lines, labels.get("request_category", ""), category.get("name"))
    _add_line(lines, labels.get("department", ""), category.get("department"))
    _add_line(lines, labels.get("description", ""), category.get("description"), max_length=max_description_chars)
    questions = category.get("questions") or []
    if questions:
        configured_label = labels.get("configured_questions", "")
        if configured_label:
            lines.append(configured_label + ":")
        for question in sorted(questions, key=lambda item: item.get("order", 0)):
            question_text = _clean(question.get("question"))
            field_name = _clean(question.get("name"))
            field_type = _clean(question.get("field_type"))
            required = question.get("required")
            if not question_text:
                continue
            details = []
            if field_name and labels.get("field"):
                details.append(f"{labels['field']}={field_name}")
            if field_type and labels.get("type"):
                details.append(f"{labels['type']}={field_type}")
            if required and labels.get("required"):
                details.append(labels["required"])
            suffix = f" ({', '.join(details)})" if details else ""
            lines.append(f"- {question_text[:max_description_chars]}{suffix}")
    return "\n".join(lines)


def _validate_context_limit(max_chars, maximum=MAX_CONTEXT_CHARS):
    """Validate a tenant limit and enforce the platform safety ceiling."""
    try:
        max_chars = int(max_chars)
        maximum = int(maximum)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("The context character limit must be a valid integer.") from exc
    if max_chars <= 0 or maximum <= 0:
        raise ValueError("The context character limit must be greater than zero.")
    return min(max_chars, maximum, MAX_CONTEXT_CHARS)


def _build_bounded_context(
    query,
    sections,
    max_chars,
    *,
    instructions,
    question_label,
    truncation_marker,
):
    """
    Keep the applicable safety instructions and question intact.

    Retrieved reference sections are shortened first. If the fixed
    instructions and question cannot fit, fail explicitly.
    """
    fixed_sections = [
        instructions,
        f"{question_label}\n{query}",
    ]

    fixed_context = "\n\n".join(fixed_sections)

    if len(fixed_context) > max_chars:
        raise ValueError(
            "The configured context limit is too small to preserve "
            "the safety instructions and employee question."
        )

    full_context = "\n\n".join(sections)

    if len(full_context) <= max_chars:
        return full_context

    remaining_sections = [
        section
        for section in sections[len(fixed_sections):]
        if section and section.strip()
    ]

    if not remaining_sections:
        return fixed_context

    remaining_context = "\n\n".join(remaining_sections)

    separator = "\n\n"
    available_chars = (
        max_chars
        - len(fixed_context)
        - len(separator)
        - len(truncation_marker)
    )

    if available_chars <= 0:
        # Preserve the safety rules and query without adding a marker
        # that would cause the configured limit to be exceeded.
        return fixed_context

    shortened_references = remaining_context[:available_chars]

    context_text = (
        fixed_context
        + separator
        + shortened_references
        + truncation_marker
    )

    # Defensive final check. Never cut the fixed safety instructions.
    if len(context_text) > max_chars:
        raise ValueError(
            "Unable to fit the context within the configured limit "
            "without removing safety instructions."
        )

    return context_text




def _search_products_for_knowledge(organization, query, limit):
    """
    Search product knowledge through the canonical Products search service.

    Business questions can combine product terms with context terms. Search
    the complete query first, then individual terms if needed. Products still
    owns tenant scope, visibility, stop words and ranking.
    """
    try:
        maximum = max(1, int(limit))
    except (TypeError, ValueError, OverflowError):
        maximum = 5

    results = search_organization_products(organization, query, limit=maximum)
    if results:
        return results[:maximum]

    tokens = list(dict.fromkeys(
        __import__("re").findall(r"[a-z0-9]+", str(query or "").casefold())
    ))
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


def _is_product_question(query, organization=None, settings=None):
    """Use organization-configured terms/phrases and canonical product search."""
    normalized = " ".join(str(query or "").casefold().split())
    if not normalized:
        return False

    # Product intent configuration is optional. Configured terms and phrases
    # can identify broad product questions, while an exact organization-scoped
    # catalogue match can identify a product question without sales keywords.
    terms = (
        settings.product_intent_terms
        if settings and isinstance(settings.product_intent_terms, list)
        else []
    )
    phrases = (
        settings.product_intent_phrases
        if settings and isinstance(settings.product_intent_phrases, list)
        else []
    )
    tokens = set(__import__("re").findall(r"[a-z0-9]+", normalized))
    configured_terms = {str(item).casefold().strip() for item in terms if str(item).strip()}
    if tokens & configured_terms:
        return True
    if any(str(phrase).casefold().strip() in normalized for phrase in phrases if str(phrase).strip()):
        return True
    if organization is not None:
        return bool(_search_products_for_knowledge(organization, query, limit=1))
    return False


def build_knowledge_context(
    organization,
    query,
    product_limit=None,
    document_limit=None,
    category_limit=None,
    max_chars=None,
    *,
    can_access_admin_only=False,
    customer_facing=False,
    include_products=True,
    include_categories=True,
):
    """Build a bounded knowledge context using the organization's settings."""
    from .models import ProductKnowledgeSettings

    if organization is None or not getattr(organization, "pk", None):
        raise ValueError("A saved organization is required.")

    configuration = ProductKnowledgeSettings.objects.filter(
        organization=organization,
        is_active=True,
    ).first()
    if not configuration:
        raise ValueError("Product Knowledge settings are not configured for this organization.")

    labels = configuration.labels if isinstance(configuration.labels, dict) else {}
    context_instructions = (
        configuration.customer_instructions
        if customer_facing
        else configuration.employee_instructions
    )
    question_label = labels.get("customer_question" if customer_facing else "employee_question")
    if not context_instructions.strip() or not question_label:
        raise ValueError("Product Knowledge instructions and question labels must be configured.")

    context_limit = _validate_context_limit(
        max_chars if max_chars is not None else configuration.max_context_chars,
        configuration.max_context_chars,
    )
    description_limit = _validate_context_limit(
        configuration.max_description_chars,
        MAX_DESCRIPTION_CHARS,
    )
    document_text_limit = _validate_context_limit(
        configuration.max_document_chars,
        MAX_DOCUMENT_CHARS,
    )
    product_limit = product_limit if product_limit is not None else configuration.product_limit
    document_limit = document_limit if document_limit is not None else configuration.document_limit
    category_limit = category_limit if category_limit is not None else configuration.category_limit

    query = _clean(query)[:MAX_QUERY_LENGTH]
    truncation_marker = configuration.truncation_marker or ""

    if not query:
        retrieval = {
            "query": "",
            "products": [],
            "documents": [],
            "request_categories": [],
        }
        sections = [context_instructions]
        return {
            "query": "",
            "instructions": context_instructions,
            "retrieval": retrieval,
            "context_text": _build_bounded_context(
                query="",
                sections=sections,
                max_chars=context_limit,
                instructions=context_instructions,
                question_label=question_label,
                truncation_marker=truncation_marker,
            ),
        }

    product_question = include_products and _is_product_question(
        query,
        organization=organization,
        settings=configuration,
    )
    retrieval = retrieve_knowledge(
        organization=organization,
        query=query,
        product_limit=product_limit if product_question else 0,
        document_limit=document_limit,
        category_limit=category_limit,
        can_access_admin_only=can_access_admin_only,
        customer_facing=customer_facing,
    )

    if not product_question:
        retrieval["products"] = []
    else:
        retrieval["products"] = [
            _sanitize_product_data(product)
            for product in retrieval.get("products", [])
        ]

    sections = [context_instructions, f"{question_label}\n{query}"]
    products = retrieval.get("products", [])
    if products:
        formatted_products = [
            _format_product(product, labels, description_limit)
            for product in products
        ]
        section_label = labels.get("product_section", "")
        if section_label:
            sections.append(section_label + "\n" + "\n\n".join(item for item in formatted_products if item))

    documents = retrieval.get("documents", [])
    if documents:
        formatted_documents = [
            _format_document(document, labels, document_text_limit)
            for document in documents
        ]
        section_label = labels.get("documents_section", "")
        if section_label:
            sections.append(section_label + "\n" + "\n\n".join(item for item in formatted_documents if item))

    categories = retrieval.get("request_categories", []) if include_categories else []
    if not include_categories:
        retrieval["request_categories"] = []
    if categories:
        formatted_categories = [
            _format_category(category, labels, description_limit)
            for category in categories
        ]
        section_label = labels.get("request_categories_section", "")
        if section_label:
            sections.append(section_label + "\n" + "\n\n".join(item for item in formatted_categories if item))

    context_text = _build_bounded_context(
        query=query,
        sections=sections,
        max_chars=context_limit,
        instructions=context_instructions,
        question_label=question_label,
        truncation_marker=truncation_marker,
    )
    return {
        "query": query,
        "instructions": context_instructions,
        "retrieval": retrieval,
        "context_text": context_text,
    }

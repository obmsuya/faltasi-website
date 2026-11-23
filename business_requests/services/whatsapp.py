"""WhatsApp-facing Business Request question and answer services.

Business Requests owns category matching, field validation, question
progression and persistence. WhatsApp views should coordinate these
services rather than maintain a second set of request rules.
"""

from decimal import Decimal, InvalidOperation
import re

from business_requests.models import BusinessRequest, RequestCategory
from business_requests.whatsapp_config import get_whatsapp_message, get_whatsapp_phrases


def find_request_category(text, organization):
    """Match only active request categories belonging to the given tenant."""
    if not text or not organization:
        return None

    normalized = str(text).casefold().strip()
    if not normalized:
        return None

    categories = RequestCategory.objects.filter(
        organization=organization,
        is_active=True,
    ).order_by("name", "pk")

    best_category = None
    best_score = 0
    for category in categories:
        keywords = [
            item.strip().casefold()
            for item in (category.keywords or "").split(",")
            if item.strip()
        ]
        score = sum(1 for keyword in keywords if keyword in normalized)
        if score > best_score:
            best_category = category
            best_score = score

    return best_category


def _configured_values(rules, key):
    values = rules.get(key, []) if isinstance(rules, dict) else []
    if not isinstance(values, list):
        return set()
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def validate_request_field_value(field, text):
    """Validate using only the rules configured on the RequestField."""
    if not field or text is None:
        return False, None

    value = str(text).strip()
    if not value:
        return False, None

    rules = field.validation_rules if isinstance(field.validation_rules, dict) else {}

    if field.field_type == "text":
        try:
            minimum = rules.get("min_length")
            maximum = rules.get("max_length")
            if minimum is not None and len(value) < int(minimum):
                return False, None
            if maximum is not None and len(value) > int(maximum):
                return False, None
        except (ValueError, TypeError):
            return False, None
        return True, value

    if field.field_type == "number":
        number_match = re.search(r"\d+(?:\.\d+)?", value)
        if number_match:
            try:
                number = Decimal(number_match.group())
            except (InvalidOperation, ValueError):
                return False, None
        else:
            number_words = rules.get("number_words", {})
            if not isinstance(number_words, dict):
                return False, None
            number = None
            normalized = value.casefold()
            for word, mapped_value in number_words.items():
                if re.search(rf"\b{re.escape(str(word).casefold())}\b", normalized):
                    try:
                        number = Decimal(str(mapped_value))
                    except (InvalidOperation, ValueError):
                        return False, None
                    break
            if number is None:
                return False, None
        if not number.is_finite():
            return False, None
        try:
            minimum = rules.get("min")
            maximum = rules.get("max")
            if minimum is not None and number < Decimal(str(minimum)):
                return False, None
            if maximum is not None and number > Decimal(str(maximum)):
                return False, None
        except (InvalidOperation, ValueError, TypeError):
            return False, None
        cleaned = int(number) if number == number.to_integral_value() else float(number)
        return True, cleaned

    normalized = value.casefold().strip()
    if field.field_type == "yes_no":
        yes_values = _configured_values(rules, "yes_values")
        no_values = _configured_values(rules, "no_values")
        yes_phrases = _configured_values(rules, "yes_phrases")
        no_phrases = _configured_values(rules, "no_phrases")
        if normalized in yes_values or any(phrase in normalized for phrase in yes_phrases):
            return True, True
        if normalized in no_values or any(phrase in normalized for phrase in no_phrases):
            return True, False
        return False, None

    if field.field_type == "choice":
        choices = rules.get("choices", [])
        if not isinstance(choices, list) or not choices:
            return True, value
        configured = {str(choice).strip().casefold(): str(choice).strip() for choice in choices if str(choice).strip()}
        selected = configured.get(normalized)
        return (True, selected) if selected is not None else (False, None)

    return True, value


def get_required_request_fields(category):
    if not category:
        return []
    return list(category.request_fields.filter(is_active=True).order_by("order", "pk"))


def get_next_missing_request_field(category, collected_data):
    collected_data = collected_data if isinstance(collected_data, dict) else {}
    for field in get_required_request_fields(category):
        if field.name not in collected_data and field.is_required:
            return field
        if field.name not in collected_data and not field.is_required:
            return field
    return None


def get_next_request_question(category, collected_data):
    field = get_next_missing_request_field(category, collected_data)
    return field.question if field else None


def _field_retry_message(field, organization, language):
    configured = field.retry_message_en if str(language or "").lower().startswith("en") else field.retry_message_sw
    if not configured:
        configured = get_whatsapp_message(organization, "request_field_retry", language)
    return configured or ""


def _completion_message(organization, language):
    return get_whatsapp_message(organization, "request_completed", language) or ""


def process_request_fields(category, state, text, *, organization=None, language=None):
    """Save the current answer and return the next configured question."""
    if not category or not state:
        return ""

    organization = organization or category.organization
    collected_data = dict(state.data or {})
    waiting_for = state.waiting_for

    if waiting_for:
        field = category.request_fields.filter(name=waiting_for, is_active=True).first()
        if field and text is not None:
            rules = field.validation_rules if isinstance(field.validation_rules, dict) else {}
            skip_values = _configured_values(rules, "skip_values")
            normalized = str(text).strip().casefold()

            if not field.is_required and normalized in skip_values:
                collected_data[waiting_for] = None
            else:
                valid, cleaned_value = validate_request_field_value(field, text)
                if not valid:
                    retry = _field_retry_message(field, organization, language)
                    return "\n\n".join(part for part in (retry, field.question) if part)
                collected_data[waiting_for] = cleaned_value

            state.data = collected_data
            state.save(update_fields=["data", "updated_at"])

    next_field = get_next_missing_request_field(category, collected_data)
    if next_field:
        state.current_step = "collecting_details"
        state.waiting_for = next_field.name
        state.data = collected_data
        state.save(update_fields=["current_step", "waiting_for", "data", "updated_at"])
        return next_field.question

    state.current_step = "details_collected"
    state.waiting_for = None
    state.data = collected_data
    state.save(update_fields=["current_step", "waiting_for", "data", "updated_at"])
    return _completion_message(organization, language)


def is_new_request_message(text, current_category=None, current_field=None, organization=None):
    """Detect new requests using configured phrases and the active field rules."""
    if not text or not organization:
        return False

    detected_category = find_request_category(text, organization)
    if not detected_category:
        return False

    normalized = str(text).casefold().strip()
    explicit_phrases = get_whatsapp_phrases(organization, "explicit_new_request_phrases")
    request_phrases = get_whatsapp_phrases(organization, "request_phrases")
    has_explicit = any(phrase in normalized for phrase in explicit_phrases)
    has_request_phrase = any(phrase in normalized for phrase in request_phrases)

    if not current_category:
        return True

    same_category = detected_category.pk == current_category.pk
    if current_field:
        rules = current_field.validation_rules if isinstance(current_field.validation_rules, dict) else {}
        if same_category:
            if current_field.field_type == "text":
                if rules.get("allow_new_request_interruption"):
                    return has_explicit or has_request_phrase
                return has_explicit
            valid, _ = validate_request_field_value(current_field, text)
            if valid:
                return False
            return has_explicit or has_request_phrase

        if rules.get("prevent_new_request_interruption"):
            return False
        if current_field.field_type == "text":
            return False
        valid, _ = validate_request_field_value(current_field, text)
        if valid:
            return False

    if same_category:
        return has_explicit if current_field else False

    return has_explicit or has_request_phrase


def update_business_request_details(business_request, state):
    """Append collected answers using configured labels and field metadata."""
    if not business_request or not state:
        return business_request

    data = state.data if isinstance(state.data, dict) else {}
    if not data:
        return business_request

    original_request = data.get("request_text") or business_request.request_text
    category = business_request.category
    fields = {
        field.name: field
        for field in get_required_request_fields(category)
    } if category else {}
    organization = business_request.customer.organization
    language = getattr(organization, "language", "sw")
    yes_label = get_whatsapp_message(organization, "request_yes_label", language)
    no_label = get_whatsapp_message(organization, "request_no_label", language)
    missing_label = get_whatsapp_message(organization, "request_not_provided_label", language)
    heading = get_whatsapp_message(organization, "request_collected_details_heading", language)

    details = []
    for key, value in data.items():
        if key in {"request_text", "category", "business_request_id"}:
            continue
        field = fields.get(key)
        label = (field.display_label if field else "") or str(key).replace("_", " ").title()
        if value is True:
            display_value = yes_label or str(value)
        elif value is False:
            display_value = no_label or str(value)
        elif value is None:
            display_value = missing_label or str(value)
        else:
            display_value = value
        details.append(f"{label}: {display_value}")

    if details:
        details_text = "\n".join(details)
        if heading:
            details_text = f"{heading}:\n" + details_text
        business_request.request_text = f"{original_request}\n\n{details_text}"
        business_request.save(update_fields=["request_text", "updated_at"])

    return business_request


def create_business_request(customer, text, category, conversation=None):
    """Create or reuse a request only within the customer's organization."""
    if not customer or not category or customer.organization_id != category.organization_id:
        return None
    if category.department_id and category.department.organization_id != category.organization_id:
        return None
    if conversation and conversation.business_request_id:
        existing = conversation.business_request
        if existing and existing.category_id == category.pk and existing.customer_id == customer.pk:
            return existing
    return BusinessRequest.objects.create(
        customer=customer,
        request_text=text,
        subject=category.name,
        category=category,
        department=category.department,
        source="whatsapp",
    )

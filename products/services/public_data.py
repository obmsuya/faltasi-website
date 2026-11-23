"""Safe serialization of customer-visible product data."""

from datetime import date, datetime
from decimal import Decimal


SENSITIVE_PRODUCT_FIELD_TERMS = {
    "cost", "wholesale", "purchase", "buying", "supplier",
    "profit", "margin", "markup", "internalprice",
}
MAX_PUBLIC_PRODUCT_TEXT_CHARS = 4000


def _normalize_key(value):
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _is_sensitive_key(key):
    normalized = _normalize_key(key)
    return any(term in normalized for term in SENSITIVE_PRODUCT_FIELD_TERMS)


def clean_public_product_data(value, depth=0):
    """Recursively remove internal financial and supplier information."""
    if depth > 8:
        return None
    if isinstance(value, dict):
        return {
            str(key)[:100]: clean_public_product_data(item, depth + 1)
            for key, item in value.items()
            if not _is_sensitive_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [clean_public_product_data(item, depth + 1) for item in value[:100]]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return value[:MAX_PUBLIC_PRODUCT_TEXT_CHARS]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:500]


def format_public_product_json(value, labels=None, depth=0):
    """Format already-sanitized JSON values without inventing field labels."""
    labels = labels if isinstance(labels, dict) else {}
    if value is None or depth > 4:
        return []
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if item is None or item == "":
                continue
            label = labels.get(str(key), str(key))
            if isinstance(item, (dict, list, tuple)):
                nested = format_public_product_json(item, labels, depth + 1)
                if nested:
                    lines.append(f"{label}:")
                    lines.extend(f"  {line}" for line in nested)
            else:
                lines.append(f"{label}: {item}")
            if len(lines) >= 20:
                break
        return lines
    if isinstance(value, (list, tuple)):
        lines = []
        for item in value[:15]:
            if isinstance(item, (dict, list, tuple)):
                lines.extend(format_public_product_json(item, labels, depth + 1))
            elif item is not None and item != "":
                lines.append(str(item))
        return lines
    return [str(value)]

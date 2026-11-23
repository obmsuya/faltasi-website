
from .models import WhatsAppAutomationSettings


def get_whatsapp_automation_settings(organization):
    """
    Return active WhatsApp automation settings for one organization.
    Never use another organization's configuration.
    """
    organization_id = getattr(organization, "pk", None)
    if not organization_id or not hasattr(organization, "_meta"):
        return None

    return WhatsAppAutomationSettings.objects.filter(
        organization_id=organization_id,
        is_active=True,
    ).first()


def get_whatsapp_message(organization, message_type, language="sw"):
    """
    Retrieve a configured customer-facing message.
    Returns None when no message is configured.
    """
    config = get_whatsapp_automation_settings(organization)

    if not config:
        return None

    language = (language or config.default_language or "sw").lower()

    if language.startswith("mixed"):
        language = "mixed"
    elif language.startswith("en"):
        language = "en"
    else:
        language = "sw"

    field_name = f"{message_type}_message_{language}"

    return getattr(config, field_name, None) or None


def get_whatsapp_phrases(organization, field_name):
    """
    Retrieve configured phrases for one organization.
    """
    config = get_whatsapp_automation_settings(organization)

    if not config:
        return []

    phrases = getattr(config, field_name, [])

    if not isinstance(phrases, list):
        return []

    return [
        phrase.strip().lower()
        for phrase in phrases
        if isinstance(phrase, str) and phrase.strip()
    ]


def get_whatsapp_language_phrases(organization, field_name):
    """Retrieve configured language-keyed phrases for one organization."""
    config = get_whatsapp_automation_settings(organization)
    if not config:
        return {}
    phrases = getattr(config, field_name, {})
    if not isinstance(phrases, dict):
        return {}
    return {
        language: [
            phrase.strip().casefold()
            for phrase in values
            if isinstance(phrase, str) and phrase.strip()
        ]
        for language, values in phrases.items()
        if isinstance(values, list)
    }

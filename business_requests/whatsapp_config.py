
from .models import WhatsAppAutomationSettings


def get_whatsapp_automation_settings(organization):
    """
    Return active WhatsApp automation settings for one organization.
    Never use another organization's configuration.
    """
    if not organization:
        return None

    return WhatsAppAutomationSettings.objects.filter(
        organization=organization,
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

    if language.startswith("en"):
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

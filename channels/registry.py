"""Single registry of channel capabilities used by models and views.

Adding a provider here makes it visible in channel settings only. It does not
claim that an external publishing integration exists; a provider must still
have an implemented authorization/synchronization service before publishing.
"""

CHANNEL_REGISTRY = (
    {
        "key": "website",
        "label": "Website",
        "kind": "product_flag",
        "product_field": "show_on_website",
        "connection_required": False,
    },
    {
        "key": "public_catalogue",
        "label": "Public catalogue",
        "kind": "visibility",
        "connection_required": False,
    },
    {
        "key": "whatsapp",
        "label": "WhatsApp",
        "kind": "product_flag",
        "product_field": "show_on_whatsapp",
        "connection_required": False,
    },
    {
        "key": "instagram",
        "label": "Instagram",
        "kind": "publication",
        "connection_required": True,
    },
    {
        "key": "facebook",
        "label": "Facebook",
        "kind": "publication",
        "connection_required": True,
    },
    {
        "key": "tiktok",
        "label": "TikTok",
        "kind": "publication",
        "connection_required": True,
    },
    {
        "key": "google_business_profile",
        "label": "Google Business Profile",
        "kind": "publication",
        "connection_required": True,
    },
    {
        "key": "google_merchant_center",
        "label": "Google Merchant Center",
        "kind": "publication",
        "connection_required": True,
    },
)

CHANNEL_BY_KEY = {item["key"]: item for item in CHANNEL_REGISTRY}
PROVIDER_CHANNELS = tuple(
    item for item in CHANNEL_REGISTRY if item["connection_required"]
)
PRODUCT_PUBLICATION_CHANNELS = tuple(
    item for item in CHANNEL_REGISTRY if item["kind"] == "publication"
)
CHANNEL_CHOICES = tuple((item["key"], item["label"]) for item in CHANNEL_REGISTRY)
PROVIDER_CHOICES = tuple((item["key"], item["label"]) for item in PROVIDER_CHANNELS)
PUBLICATION_CHOICES = tuple(
    (item["key"], item["label"]) for item in PRODUCT_PUBLICATION_CHANNELS
)

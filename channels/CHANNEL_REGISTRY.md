# Channel Registry

`channels/registry.py` is the single source for channel keys, labels, and
capabilities. `ChannelConnection` and `ProductChannelPublication` derive their
model choices from this registry, and the dashboard renders its columns from
the same definitions.

The registry distinguishes:

- Product flags such as Website and WhatsApp. These control existing product
  fields (`show_on_website` and `show_on_whatsapp`).
- Public catalogue visibility. This remains a separate platform-owner-only
  visibility rule and is not toggled by the Website setting.
- External publication providers. These have connection and publication
  records, but an enabled setting or a `connected` record does not prove that
  OAuth authorization or publishing synchronization is implemented. The
  dashboard explicitly shows this distinction.

A new external provider should be added to the registry only alongside its
provider-specific authorization, credential storage, and publishing service.

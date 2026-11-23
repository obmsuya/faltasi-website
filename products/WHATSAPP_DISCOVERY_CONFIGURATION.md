# Product Discovery Configuration

Product discovery presentation and response phrases are configured per
organization in Django Admin under **Products > Product Discovery Settings**.

- `yes_phrases` and `no_phrases` define accepted replies to the next-option prompt.
- `messages` contains customer-facing messages and labels for each language.
- `search_stop_words` controls conversational words ignored by catalogue search.
- `max_results` controls the number of matching products retained for the
  one-at-a-time discovery flow.
- `max_description_chars` limits the description length sent in a product reply.
- `max_candidates`, query-match thresholds, coverage thresholds, relevance
  weights and match bonuses control the catalogue ranking algorithm.

The migration creates default settings for organizations that already exist.
New organizations must receive a Product Discovery Settings record during
onboarding and have the phrases/messages reviewed before WhatsApp discovery is
enabled. Product search always rechecks organization ownership, active status,
soft deletion and `show_on_whatsapp` before formatting a product.

Product JSON data is sanitized by `products.services.public_data` before it is
shown to customers or included in WhatsApp AI context. Cost, wholesale,
purchase, supplier, profit, margin, markup and internal-price keys are removed
recursively.

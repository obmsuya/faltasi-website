# Product Knowledge / AI STAFF Configuration

Each organization must have one active **Product Knowledge Settings** record.
The record is organization-scoped and controls the employee/customer AI
instructions, product-intent terms, context labels, and retrieval limits.

- `employee_instructions`: AI STAFF policy and answer instructions for staff.
- `customer_instructions`: customer-facing WhatsApp knowledge-answer policy.
- `product_intent_terms` and `product_intent_phrases`: terms used to decide
  when the product catalogue should be included in employee knowledge context.
- `labels`: display labels for product, document, and Business Request sources.
- `max_context_chars`, `max_description_chars`, `max_document_chars`: context
  limits. The application still enforces its platform safety ceilings.
- `product_limit`, `document_limit`, `category_limit`: retrieval limits.
- `truncation_marker`: text appended when reference content is shortened.

The migration creates settings for organizations that already exist and seeds
the current AI STAFF and customer-facing rules. New organizations must receive
a settings record during onboarding before AI STAFF or customer knowledge
answers are enabled.

The document access policy remains exactly two levels: **Employee Access** and
**Admin Only**. Organization membership and permissions are enforced by the
calling views; editable AI instructions cannot grant access to Admin Only
documents or another organization's records.

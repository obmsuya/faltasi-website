# Business Request WhatsApp Configuration

Business Request questions and answer rules are owned by `business_requests`.
WhatsApp views call the Business Request services; they do not define the
questions, accepted answers, skip phrases, or completion message.

## RequestField configuration

Edit a `RequestField` under Django Admin. The `question` is the customer-facing
question. `display_label` is used when the collected answer is appended to the
request record. `validation_rules` is JSON configuration:

### Text

```json
{"min_length": 2, "max_length": 500}
```

### Number

```json
{"min": 1, "max": 500, "number_words": {"one": 1, "two": 2, "three": 3}}
```

### Yes / No

```json
{"yes_values": ["yes", "ndiyo"], "no_values": ["no", "hapana"], "yes_phrases": ["go ahead"], "no_phrases": ["not required"]}
```

### Choice

```json
{"choices": ["Retail", "Wholesale", "Distributor"]}
```

### Optional field skip values

Add `skip_values` to the same JSON object for an optional field:

```json
{"skip_values": ["not sure", "sijui", "no budget"]}
```

A field can combine `skip_values` with its normal type rules. The migration
seeds the existing yes/no values and phrases, optional-skip phrases, English
number-word rules, and location-field interruption protection from the previous
implementation. A Choice field with a configured `choices` list validates
against that list; a legacy Choice field with no list continues to accept
free text until its options are configured.

`retry_message_sw` and `retry_message_en` override the organization-level
retry message for that field.

## WhatsAppAutomationSettings

Each organization has its own `WhatsAppAutomationSettings` record. It owns:

- request phrases and explicit new-request phrases;
- request-field retry and completion messages in Swahili and English;
- human-handover messages and language-specific handover phrases;
- marketing consent confirmation messages;
- yes/no/not-provided labels and the collected-details heading;
- the initial workflow step name, description, order and assignment notes;
- manual-assignment audit-note templates;
- assignment email and WhatsApp message templates, plus the configured missing-value label.

The migration creates or initializes settings for organizations that already
exist. New organizations should receive a settings record during organization
onboarding and have its messages and phrase lists reviewed before WhatsApp
automation is enabled.

Assignment email templates support these placeholders:

`{staff_name}`, `{request_id}`, `{subject}`, `{department}`, `{customer_name}`,
`{customer_phone}`, `{request_text}`, `{priority}`, `{status}`, and
`{organization_name}`.

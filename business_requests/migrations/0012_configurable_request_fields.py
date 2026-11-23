# Generated for configurable Business Request WhatsApp question handling.
from django.db import migrations, models


def seed_default_request_configuration(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    AutomationSettings = apps.get_model("business_requests", "WhatsAppAutomationSettings")
    RequestField = apps.get_model("business_requests", "RequestField")

    request_phrases = [
        "i need", "i want", "i would like", "i'd like", "looking for",
        "i am looking for", "i'm looking for", "can you provide", "can you help",
        "i need a quote", "i need quotation", "quotation for", "quote for",
        "nahitaji", "nataka", "ningependa", "naomba huduma", "naomba bei",
    ]
    explicit_new_request_phrases = [
        "i also need", "i also want", "i also would like", "i'd also like",
        "i would also like", "i need another", "i want another", "another request",
        "another service", "another product", "different request", "different service",
        "different product", "actually i need", "actually i want", "actually i would like",
        "by the way i need", "by the way i want", "can you also provide",
        "can you also help", "i need a separate", "i want a separate",
        "pia nahitaji", "pia nataka", "huduma nyingine", "bidhaa nyingine",
    ]
    yes_values = ["yes", "y", "yeah", "yep", "sure", "correct", "of course", "please do", "i do", "i need it", "i need installation", "needed", "required", "ndiyo", "ndio", "naam", "sawa"]
    no_values = ["no", "n", "nope", "not needed", "not required", "i don't", "dont", "don't", "not necessary", "hapana", "sihitaji", "si lazima"]
    yes_phrases = ["yes, please", "yes please", "i need", "i want", "please do", "go ahead", "install it", "install", "installation required", "i need installation"]
    no_phrases = ["no, thanks", "no thanks", "i don't need", "i dont need", "i do not need", "not necessary", "not required", "without installation", "installation not required"]
    skip_values = [
        "no", "no budget", "i don't know", "i dont know", "not sure", "not certain",
        "no idea", "i have no idea", "don't have a budget", "dont have a budget",
        "i don't have a budget", "i dont have a budget", "not decided", "not decided yet",
        "sijui", "bado sijajua", "sina bajeti", "hakuna bajeti",
    ]
    number_words = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20,
    }

    defaults = {
        "general_fallback_message_sw": "Asante kwa ujumbe wako. Tumepokea taarifa zako.",
        "general_fallback_message_en": "Thank you for your message. We have received it.",
        "request_not_understood_message_sw": "Samahani, sijaweza kutambua huduma unayoihitaji. Tafadhali eleza huduma au bidhaa unayotafuta kwa maelezo zaidi.",
        "request_not_understood_message_en": "Sorry, I could not identify the service you need. Please describe the service or product you are looking for.",
        "request_phrases": request_phrases,
        "explicit_new_request_phrases": explicit_new_request_phrases,
        "request_field_retry_message_sw": "Samahani, sijaelewa jibu lako. Tafadhali jaribu tena.",
        "request_field_retry_message_en": "Sorry, I could not understand your answer. Please try again.",
        "request_completed_message_sw": "Asante. Tumepokea taarifa zako. Timu yetu itapitia ombi lako na tutakujibu hivi karibuni.",
        "request_completed_message_en": "Thank you. We have received your details. Our team will review your request and get back to you shortly.",
        "request_yes_label_sw": "Ndiyo",
        "request_yes_label_en": "Yes",
        "request_no_label_sw": "Hapana",
        "request_no_label_en": "No",
        "request_not_provided_label_sw": "Haijatolewa",
        "request_not_provided_label_en": "Not provided",
        "request_collected_details_heading_sw": "Taarifa zilizokusanywa",
        "request_collected_details_heading_en": "Collected Details",
        "human_handover_message_sw": "Sawa, tumekuelewa. Tutaendelea kukusaidia hapa.",
        "human_handover_message_en": "Thanks for letting us know. We’ll continue helping you here.",
        "human_handover_message_mixed": "Sawa, tumekuelewa. We’ll continue helping you hapa.",
        "human_handover_phrases": {
            "sw": [
                "naomba niongee na mtu", "naomba kuongea na mtu", "naomba nizungumze na mtu",
                "naomba kuzungumza na mtu", "nataka kuongea na mtu", "nataka kuzungumza na mtu",
                "naomba kuongea na mfanyakazi", "naomba kuongea na ofisi", "naomba msaada wa mtu",
                "niunganishe na mtu", "nipe mtu wa kuongea naye", "naomba ongea na mtu",
                "naomba ongea na mfanyakazi", "naomba kuongeza na mtu", "naomba uniongezee mtu",
                "naomba mtu wa kunisaidia", "ongeza mtu kwenye mazungumzo", "niunge na mtu",
            ],
            "en": [
                "speak to a human", "talk to a human", "speak with a human", "talk with a human",
                "speak to an agent", "talk to an agent", "speak to a person", "talk to a person",
                "speak to someone", "talk to someone", "human support", "customer care agent",
                "real person", "add a person", "add someone", "connect me to an agent",
            ],
        },
        "marketing_invitation_message_sw": "Pia tuna bidhaa nyingi ambazo nina uhakika utazifurahia. Je, ungependa kupokea taarifa za bidhaa na ofa zetu kupitia WhatsApp? Nijibu YES kukubali au NO kukataa.",
        "marketing_invitation_message_en": "We also have many products we believe you will enjoy. Would you like to receive WhatsApp marketing messages? Reply YES to subscribe or NO to decline.",
        "marketing_opt_in_confirmation_message_sw": "Asante. Umejiunga kupokea taarifa za matangazo kupitia WhatsApp.",
        "marketing_opt_in_confirmation_message_en": "Thank you. You have opted in to receive WhatsApp marketing updates.",
        "marketing_opt_out_confirmation_message_sw": "Umeondolewa kwenye orodha ya matangazo ya WhatsApp.",
        "marketing_opt_out_confirmation_message_en": "You have been unsubscribed from WhatsApp marketing messages.",
        "marketing_declined_confirmation_message_sw": "Asante kwa kutujibu. Hutapokea matangazo bila kutoa ridhaa yako.",
        "marketing_declined_confirmation_message_en": "Thank you for responding. You will not receive marketing messages.",
        "workflow_review_step_name": "Department Review",
        "workflow_review_step_description": "Review the customer's request and process the request.",
        "workflow_review_step_order": 1,
        "assignment_whatsapp_message_template": (
            "Hello {staff_name}, a business request has been assigned to you.\n\n"
            "Request: #{request_id}\nSubject: {subject}\nDepartment: {department}\n"
            "Customer: {customer_name}\nCustomer phone: {customer_phone}\n\n"
            "Please open your business dashboard to review and process it."
        ),
        "manual_assignment_notes_template": "Assigned to {assigned_to} by {assigned_by}.",
        "assignment_notes": "Automatically assigned based on current staff workload.",
        "unassigned_notes": "Waiting for an available department staff member.",
        "assignment_email_subject_template": "New Business Request #{request_id} Assigned to You",
        "assignment_email_body_template": (
            "Hello {staff_name},\n\nA new business request has been assigned to you.\n\n"
            "Request ID:\n#{request_id}\n\nSubject:\n{subject}\n\n"
            "Department:\n{department}\n\nCustomer:\n{customer_name}\n\n"
            "Customer Phone:\n{customer_phone}\n\nRequest:\n{request_text}\n\n"
            "Priority:\n{priority}\n\nStatus:\n{status}\n\n"
            "Please log in to {organization_name} to review and process this request.\n\n"
            "Regards,\n{organization_name} WhatsApp Platform"
        ),
        "assignment_email_missing_value": "Not specified",
    }

    for organization in Organization.objects.all().iterator():
        config, created = AutomationSettings.objects.get_or_create(
            organization_id=organization.pk,
            defaults=defaults,
        )
        if not created:
            changed = []
            for key, value in defaults.items():
                if not getattr(config, key, None):
                    setattr(config, key, value)
                    changed.append(key)
            if changed:
                config.save(update_fields=changed)

    for field in RequestField.objects.all().iterator():
        rules = field.validation_rules if isinstance(field.validation_rules, dict) else {}
        changed = False
        if field.field_type == "yes_no":
            if not rules.get("yes_values"):
                rules["yes_values"] = yes_values
                changed = True
            if not rules.get("no_values"):
                rules["no_values"] = no_values
                changed = True
            if not rules.get("yes_phrases"):
                rules["yes_phrases"] = yes_phrases
                changed = True
            if not rules.get("no_phrases"):
                rules["no_phrases"] = no_phrases
                changed = True
        if field.field_type == "number" and not rules.get("number_words"):
            rules["number_words"] = number_words
            changed = True
        if not field.is_required and not rules.get("skip_values"):
            rules["skip_values"] = skip_values
            changed = True
        field_name = (field.name or "").casefold()
        location_terms = ("location", "address", "area", "city", "region", "place", "where")
        if field.field_type == "text" and field_name == "location":
            if not rules.get("allow_new_request_interruption"):
                rules["allow_new_request_interruption"] = True
                changed = True
        elif field.field_type != "text" and any(term in field_name for term in location_terms):
            if not rules.get("prevent_new_request_interruption"):
                rules["prevent_new_request_interruption"] = True
                changed = True
        if changed:
            field.validation_rules = rules
            field.save(update_fields=["validation_rules"])


class Migration(migrations.Migration):
    dependencies = [("business_requests", "0011_whatsappautomationsettings")]

    operations = [
        migrations.AddField(
            model_name="requestfield",
            name="display_label",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="requestfield",
            name="validation_rules",
            field=models.JSONField(blank=True, default=dict, help_text="Configured rules. Supported keys: min, max, min_length, max_length, choices, yes_values, no_values, yes_phrases, no_phrases, number_words, skip_values, prevent_new_request_interruption and allow_new_request_interruption."),
        ),
        migrations.AddField(
            model_name="requestfield",
            name="retry_message_sw",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestfield",
            name="retry_message_en",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_field_retry_message_sw",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_field_retry_message_en",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_completed_message_sw",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_yes_label_sw",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_yes_label_en",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_no_label_sw",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_no_label_en",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_not_provided_label_sw",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_not_provided_label_en",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_collected_details_heading_sw",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_collected_details_heading_en",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="human_handover_message_sw",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="human_handover_message_en",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="human_handover_message_mixed",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="human_handover_phrases",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="marketing_opt_in_confirmation_message_sw",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="marketing_opt_in_confirmation_message_en",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="marketing_opt_out_confirmation_message_sw",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="marketing_opt_out_confirmation_message_en",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="marketing_declined_confirmation_message_sw",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="marketing_declined_confirmation_message_en",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="request_completed_message_en",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="workflow_review_step_name",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="workflow_review_step_description",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="workflow_review_step_order",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="assignment_whatsapp_message_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="manual_assignment_notes_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="assignment_notes",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="unassigned_notes",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="assignment_email_subject_template",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="assignment_email_body_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="whatsappautomationsettings",
            name="assignment_email_missing_value",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.RunPython(seed_default_request_configuration, migrations.RunPython.noop),
    ]

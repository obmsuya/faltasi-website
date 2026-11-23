from django.db import migrations, models
import django.db.models.deletion


def seed_product_discovery_settings(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Settings = apps.get_model("products", "ProductDiscoverySettings")

    defaults = {
        "default_language": "sw",
        "yes_phrases": [
            "yes", "yeah", "yep", "sure", "okay", "ok", "another", "next",
            "show me another", "yes please", "another one", "show another",
            "ndio", "ndiyo", "ndio tafadhali", "endelea", "ongeza", "na nyingine",
        ],
        "no_phrases": [
            "no", "no thanks", "no thank you", "not interested", "no more",
            "that is all", "that's all", "thats all", "hapana", "hapana asante",
            "basi", "imetosha", "sihitaji", "sitaki",
        ],
        "search_stop_words": [
            "a", "an", "and", "are", "available", "can", "do", "for", "me", "my",
            "of", "please", "show", "the", "to", "what", "which", "with", "would",
            "you", "your", "find", "get", "need", "nataka", "kununua", "ninataka",
            "ninahitaji", "nahitaji", "naomba", "tafadhali", "bei", "ya", "za", "na",
            "ni", "kwa", "yangu", "una", "unazo", "onyesha",
        ],
        "relevance_weights": {
            "name": 25, "category": 18, "brand": 14, "model": 14,
            "sku": 10, "barcode": 10, "manufacturer": 8,
            "short_description": 3, "description": 2,
            "specifications": 1, "additional_information": 1,
        },
        "messages": {
            "sw": {
                "intro": "Hii hapa bidhaa inayolingana na ulichotafuta:",
                "another_option_prompt": "Je, ungependa kuona chaguo jingine?",
                "thank_you": "Asante kwa kuwasiliana nasi. Tujulishe ukihitaji msaada zaidi.",
                "no_more_options": "Hizi ndizo bidhaa zinazolingana tulizonazo kwa sasa. Tujulishe kama unahitaji msaada zaidi.",
                "price_on_request": "Bei inapatikana kwa maombi",
                "labels": {
                    "brand": "Chapa", "model": "Modeli", "manufacturer": "Mtengenezaji",
                    "description": "Maelezo", "specifications": "Sifa",
                    "additional_information": "Taarifa za ziada", "price": "Bei",
                    "availability": "Upatikanaji",
                },
            },
            "en": {
                "intro": "Here is a product that matches your request:",
                "another_option_prompt": "Would you like to see another option?",
                "thank_you": "Thank you for your interest. Please let us know if you need anything else.",
                "no_more_options": "Those are all the matching options we currently have. Please let us know if you need anything else.",
                "price_on_request": "Price available on request",
                "labels": {
                    "brand": "Brand", "model": "Model", "manufacturer": "Manufacturer",
                    "description": "Description", "specifications": "Specifications",
                    "additional_information": "Additional information", "price": "Price",
                    "availability": "Availability",
                },
            },
        },
        "is_active": True,
    }

    for organization in Organization.objects.all().iterator():
        Settings.objects.get_or_create(organization_id=organization.pk, defaults=defaults)


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0006_alter_product_show_on_website"),
        ("organizations", "0004_organizationmember_whatsapp_notifications_opt_in"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductDiscoverySettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("default_language", models.CharField(default="sw", max_length=10)),
                ("yes_phrases", models.JSONField(blank=True, default=list)),
                ("no_phrases", models.JSONField(blank=True, default=list)),
                ("search_stop_words", models.JSONField(blank=True, default=list)),
                ("messages", models.JSONField(blank=True, default=dict, help_text="Customer-facing product discovery messages and display labels by language.")),
                ("max_results", models.PositiveSmallIntegerField(default=5)),
                ("max_description_chars", models.PositiveSmallIntegerField(default=1500)),
                ("max_candidates", models.PositiveSmallIntegerField(default=500)),
                ("minimum_query_tokens_for_long_query", models.PositiveSmallIntegerField(default=3)),
                ("minimum_matches_for_long_query", models.PositiveSmallIntegerField(default=2)),
                ("long_query_required_coverage", models.FloatField(default=0.5)),
                ("short_query_required_coverage", models.FloatField(default=1.0)),
                ("relevance_weights", models.JSONField(blank=True, default=dict)),
                ("identity_match_bonus", models.PositiveIntegerField(default=1000)),
                ("coverage_bonus_multiplier", models.PositiveSmallIntegerField(default=10)),
                ("exact_name_match_bonus", models.PositiveSmallIntegerField(default=20)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="product_discovery_settings", to="organizations.organization")),
            ],
            options={
                "verbose_name": "Product Discovery Settings",
                "verbose_name_plural": "Product Discovery Settings",
            },
        ),
        migrations.RunPython(seed_product_discovery_settings, migrations.RunPython.noop),
    ]

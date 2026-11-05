from django.db import migrations, models


def enable_existing_faltasi_public_products(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    Organization = apps.get_model("organizations", "Organization")
    faltasi_ids = Organization.objects.filter(
        organization_type="platform_owner",
        status="active",
    ).values_list("id", flat=True)
    Product.objects.filter(
        organization_id__in=faltasi_ids,
        show_on_website=True,
        is_active=True,
        deleted_at__isnull=True,
    ).update(is_publicly_visible=True)


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0003_organization_created_by_organization_updated_by_and_more"),
        ("products", "0004_organizationcategoryassignment"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="is_publicly_visible",
            field=models.BooleanField(
                default=False,
                help_text="Explicit permission for public listing on Faltasi's public product catalogue. This is separate from website presentation visibility.",
            ),
        ),
        migrations.RunPython(enable_existing_faltasi_public_products, migrations.RunPython.noop),
    ]

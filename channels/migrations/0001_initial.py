from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("organizations", "0003_organization_created_by_organization_updated_by_and_more"),
        ("products", "0005_product_is_publicly_visible"),
    ]
    operations = [
        migrations.CreateModel(
            name="ChannelConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("instagram", "Instagram"), ("facebook", "Facebook"), ("tiktok", "TikTok"), ("google_business_profile", "Google Business Profile"), ("google_merchant_center", "Google Merchant Center")], max_length=40)),
                ("external_account_id", models.CharField(blank=True, default="", max_length=255)),
                ("account_name", models.CharField(blank=True, default="", max_length=255)),
                ("status", models.CharField(choices=[("pending", "Pending authorization"), ("connected", "Connected"), ("expired", "Authorization expired"), ("disconnected", "Disconnected"), ("error", "Connection error")], default="pending", max_length=20)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("connected_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_connections", to="organizations.organization")),
            ],
            options={"ordering": ["provider", "account_name"], "constraints": [models.UniqueConstraint(fields=("organization", "provider", "external_account_id"), name="unique_org_channel_external_account")]},
        ),
        migrations.CreateModel(
            name="ProductChannelPublication",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("channel", models.CharField(choices=[("instagram", "Instagram"), ("facebook", "Facebook"), ("tiktok", "TikTok"), ("google_business_profile", "Google Business Profile"), ("google_merchant_center", "Google Merchant Center")], max_length=40)),
                ("is_enabled", models.BooleanField(default=False)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("pending", "Pending publication"), ("published", "Published"), ("failed", "Failed"), ("unpublished", "Unpublished")], default="draft", max_length=20)),
                ("external_product_id", models.CharField(blank=True, default="", max_length=255)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_publications", to="products.product")),
            ],
            options={"ordering": ["channel", "product__name"], "constraints": [models.UniqueConstraint(fields=("product", "channel"), name="unique_product_channel_publication")]},
        ),
    ]

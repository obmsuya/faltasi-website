from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("product_knowledge", "0002_alter_productknowledgedocument_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="productknowledgedocument",
            name="access_level",
            field=models.CharField(
                choices=[("employee", "Employee Access"), ("admin_only", "Admin Only")],
                db_index=True,
                default="admin_only",
                max_length=20,
            ),
        ),
    ]

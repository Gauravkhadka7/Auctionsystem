from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0004_product_extension_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="latitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="location_name",
            field=models.CharField(
                blank=True,
                help_text="Human-readable location, e.g. 'Kathmandu, Nepal'",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="longitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="pickup_available",
            field=models.BooleanField(default=False),
        ),
    ]

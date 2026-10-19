from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0002_product_extension_minutes_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="product",
            name="extension_minutes",
        ),
    ]

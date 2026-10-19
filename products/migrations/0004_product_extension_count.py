from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0003_remove_product_extension_minutes_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="extension_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Times auction_end was pushed back by a last-second bid.",
            ),
        ),
    ]

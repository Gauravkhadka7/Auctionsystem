from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="extension_minutes",
            field=models.PositiveIntegerField(default=5),
        ),
        migrations.AddField(
            model_name="product",
            name="view_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]

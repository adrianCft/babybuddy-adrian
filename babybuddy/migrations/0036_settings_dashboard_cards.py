from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("babybuddy", "0035_alter_settings_language")]

    operations = [
        migrations.AddField(
            model_name="settings",
            name="dashboard_cards",
            field=models.JSONField(
                blank=True,
                null=True,
                default=None,
                verbose_name="Favorite home cards",
            ),
        ),
    ]

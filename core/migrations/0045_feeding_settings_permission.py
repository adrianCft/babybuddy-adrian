from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0044_healthvisit_specialty")]

    operations = [
        # Match the existing django-dbsettings permission; no activity rows change.
        migrations.AlterModelOptions(
            name="feeding",
            options={
                "verbose_name": "Feeding",
                "verbose_name_plural": "Feedings",
                "ordering": ["-start"],
                "permissions": [
                    ("can_edit_feeding_settings", "Can edit Feeding settings")
                ],
                "default_permissions": ("view", "add", "change", "delete"),
            },
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0043_health_records"),
    ]

    operations = [
        migrations.AddField(
            model_name="healthvisit",
            name="specialty",
            field=models.CharField(
                blank=True, null=True, max_length=255, verbose_name="Specialty"
            ),
        ),
    ]

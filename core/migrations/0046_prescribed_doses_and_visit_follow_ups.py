import django.db.models.deletion
from django.db import migrations, models

DOSAGE_UNITS = [
    ("mg", "MG"),
    ("ml", "ML"),
    ("g", "g"),
    ("tablets", "Tablets"),
    ("drops", "Drops"),
]


class Migration(migrations.Migration):
    dependencies = [("core", "0045_feeding_settings_permission")]

    operations = [
        migrations.AddField(
            model_name="healthvisit",
            name="follow_up_time",
            field=models.TimeField(
                blank=True, null=True, verbose_name="Follow-up time"
            ),
        ),
        migrations.AddField(
            model_name="healthvisit",
            name="follow_up_of",
            field=models.OneToOneField(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="follow_up_visit",
                to="core.healthvisit",
            ),
        ),
        migrations.AddField(
            model_name="prescription",
            name="dosage",
            field=models.FloatField(
                blank=True, null=True, verbose_name="Prescribed dose"
            ),
        ),
        migrations.AddField(
            model_name="prescription",
            name="dosage_unit",
            field=models.CharField(
                blank=True,
                choices=DOSAGE_UNITS,
                max_length=20,
                null=True,
                verbose_name="Dosage Unit",
            ),
        ),
        # Unit choices are validated by Django; the database column stays the same.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="medication",
                    name="dosage_unit",
                    field=models.CharField(
                        blank=True,
                        choices=DOSAGE_UNITS,
                        default="",
                        max_length=20,
                        verbose_name="Dosage Unit",
                    ),
                )
            ]
        ),
    ]

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0041_saved_dishes")]
    operations = [
        migrations.CreateModel(
            name="GrowthProfile",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "reference_system",
                    models.CharField(
                        choices=[
                            (
                                "aragon",
                                "Aragon Child Health Record (WHO, birth to 2 years)",
                            ),
                            ("who", "WHO 2006 (birth to 5 years)"),
                        ],
                        default="aragon",
                        max_length=16,
                    ),
                ),
                (
                    "sex",
                    models.CharField(
                        blank=True,
                        choices=[("girl", "Girl"), ("boy", "Boy")],
                        max_length=4,
                    ),
                ),
                (
                    "weight_unit",
                    models.CharField(
                        blank=True,
                        choices=[("kg", "kg"), ("g", "g")],
                        max_length=2,
                    ),
                ),
                (
                    "height_unit",
                    models.CharField(
                        choices=[("cm", "cm")], default="cm", max_length=2
                    ),
                ),
                (
                    "birth_status",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("term", "Born at term"),
                            ("preterm", "Born prematurely"),
                        ],
                        max_length=7,
                    ),
                ),
                (
                    "gestational_weeks",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                ("gestational_days", models.PositiveSmallIntegerField(default=0)),
                (
                    "child",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="growth_profile",
                        to="core.child",
                    ),
                ),
            ],
            options={"default_permissions": ()},
        ),
    ]

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0046_prescribed_doses_and_visit_follow_ups")]

    operations = [
        migrations.AddField(
            model_name="prescription",
            name="interval_hours",
            field=models.DecimalField(
                blank=True,
                decimal_places=3,
                max_digits=8,
                null=True,
                validators=[MinValueValidator(Decimal("0.001"))],
                verbose_name="Interval between doses (hours)",
            ),
        ),
    ]

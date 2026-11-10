from django.db import migrations, models
from django.utils import timezone
import babybuddy.settings_choices


class Migration(migrations.Migration):
    dependencies = [("babybuddy", "0036_settings_dashboard_cards")]

    operations = [
        # Choices and the default for new users are runtime metadata.
        # Existing language/timezone values and their columns stay untouched.
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="settings",
                    name="language",
                    field=models.CharField(
                        choices=babybuddy.settings_choices.languages,
                        default="en-US",
                        max_length=255,
                        verbose_name="Language",
                    ),
                ),
                migrations.AlterField(
                    model_name="settings",
                    name="timezone",
                    field=models.CharField(
                        choices=babybuddy.settings_choices.timezones,
                        default=timezone.get_default_timezone_name,
                        max_length=100,
                        verbose_name="Timezone",
                    ),
                ),
            ],
        ),
    ]

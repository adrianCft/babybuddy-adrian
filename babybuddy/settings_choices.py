"""Runtime choices without storing an operating-system-specific list in migrations."""

import zoneinfo
from django.conf import settings


def languages():
    return settings.LANGUAGES


def timezones():
    return [(name, name) for name in sorted(zoneinfo.available_timezones())]

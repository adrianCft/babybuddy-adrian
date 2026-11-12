from math import isfinite
from urllib.parse import urlencode

from django.db.models import F, Q, Window
from django.db.models.functions import RowNumber
from django.urls import reverse
from django.utils import timezone

from core.models import DosageUnit, Medication, Prescription
from core.navigation import contextual_url


def prescription_dose_url(request, prescription):
    query = urlencode(
        {"prescription": prescription.pk, "child": prescription.visit.child.slug}
    )
    return contextual_url(request, reverse("core:medication-add") + "?" + query)


def recorded_amount(dosage, unit):
    if (
        dosage is not None
        and isfinite(dosage)
        and dosage > 0
        and unit in DosageUnit.values
    ):
        return dosage, unit
    return None


def dose_suggestion(dosage, unit, origin, hours):
    amount = recorded_amount(dosage, unit)
    if amount or hours:
        return (*(amount or (None, None)), origin, hours)
    return None


def dose_suggestions(user, at, names):
    """Return complete, child-specific doses entered in records the user can read."""
    defaults = {}
    # The form shows seconds; a dose recorded in that same second is available.
    cutoff = min(at + timezone.timedelta(seconds=1), timezone.now())
    if user.has_perm("core.view_prescription"):
        day = timezone.localdate(at)
        prescriptions = (
            Prescription.objects.exclude(visit__status="cancelled")
            .filter(
                Q(start_date__lte=day)
                | Q(start_date__isnull=True, visit__date__lte=cutoff),
                Q(end_date__isnull=True) | Q(end_date__gte=day),
            )
            .values_list(
                "visit__child_id", "name", "dosage", "dosage_unit", "interval_hours"
            )
        )
        for child_id, name, dosage, unit, hours in prescriptions.iterator():
            key = (child_id, name.casefold())
            suggestion = dose_suggestion(dosage, unit, "prescription", hours)
            previous = defaults.setdefault(key, suggestion)
            if previous and suggestion and previous != suggestion:
                # The name alone cannot identify which prescription is intended.
                defaults[key] = (
                    (*previous[:3], None) if previous[:3] == suggestion[:3] else None
                )

    if user.has_perm("core.view_medication"):
        doses = (
            Medication.objects.filter(time__lte=cutoff)
            .annotate(
                latest=Window(
                    expression=RowNumber(),
                    partition_by=["child_id", "name"],
                    order_by=[F("time").desc(), F("pk").desc()],
                )
            )
            .filter(latest=1)
            .order_by("-time", "-pk")
            .values_list(
                "child_id", "name", "dosage", "dosage_unit", "next_dose_interval"
            )
        )
        for child_id, name, dosage, unit, interval in doses.iterator():
            hours = (
                interval.total_seconds() / 3600
                if interval and interval.total_seconds() > 0
                else None
            )
            defaults.setdefault(
                (child_id, name.casefold()),
                dose_suggestion(dosage, unit, "history", hours),
            )

    aliases = {}
    for name in names:
        aliases.setdefault(name.casefold(), []).append(name)
    by_child = {}
    for (child_id, key), suggestion in defaults.items():
        if suggestion:
            by_child.setdefault(child_id, {}).update(
                dict.fromkeys(aliases.get(key, ()), suggestion)
            )
    return by_child

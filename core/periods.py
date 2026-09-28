"""Read-only calendar summaries. Missing records never mean a complete day."""

import calendar
from datetime import timedelta
from statistics import median

from django.utils import timezone
from django.utils.translation import gettext as _

from core import models
from core.daily import day_bounds, total_covered
from core.utils import duration_string


def period_bounds(day, period):
    if period == "week":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    start = day.replace(day=1)
    return start, day.replace(day=calendar.monthrange(day.year, day.month)[1])


def display_value(kind, value):
    if kind == "sleep":
        return duration_string(timedelta(seconds=value), "m")
    return f"{value:g}"


def read_days(first, last, children, user):
    """One query per permitted type for every child and day in the window."""
    kinds = [
        ("sleep", models.Sleep, _("Recorded sleep")),
        ("feeding", models.Feeding, _("Feedings started")),
        ("meal", models.Meal, _("Meals")),
        ("diaperchange", models.DiaperChange, _("Diaper Changes")),
        ("medication", models.Medication, _("Medications")),
        ("note", models.Note, _("Notes")),
    ]
    kinds = [item for item in kinds if user.has_perm(f"core.view_{item[0]}")]
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    bounds = {day: day_bounds(day) for day in days}
    data = {
        child.pk: {
            day: {kind: [] if kind == "sleep" else 0 for kind, _, _ in kinds}
            for day in days
        }
        for child in children
    }
    if not days or not children:
        return data, kinds
    start, end = bounds[first][0], bounds[last][1]
    for kind, model, _label in kinds:
        query = model.objects.filter(child_id__in=data)
        if kind == "sleep":
            query = query.filter(start__lt=end, end__gt=start)
            for row in query.only("child_id", "start", "end"):
                for day, (left, right) in bounds.items():
                    a, b = max(row.start, left), min(row.end, right)
                    if b > a:
                        data[row.child_id][day][kind].append((a, b))
        else:
            field = "start" if kind == "feeding" else "time"
            query = query.filter(**{f"{field}__gte": start, f"{field}__lt": end})
            for child_id, moment in query.values_list("child_id", field):
                data[child_id][timezone.localdate(moment)][kind] += 1
    for by_day in data.values():
        for values in by_day.values():
            if "sleep" in values:
                values["sleep"] = total_covered(values["sleep"]).total_seconds()
    return data, kinds


def build_period_summary(day, period, children, user, today=None):
    today = today or timezone.localdate()
    first, last = period_bounds(day, period)
    cutoff = min(last, today)
    previous_first, previous_last = period_bounds(first - timedelta(days=1), period)
    # Compare equivalent elapsed calendar days, including a partial current day.
    previous_cutoff = min(previous_last, previous_first + (cutoff - first))
    forecast_end = min(last, today - timedelta(days=1))
    forecast_start = forecast_end - timedelta(days=27)
    read_first = min(previous_first, forecast_start)
    data, kinds = read_days(read_first, cutoff, children, user)
    groups = []
    for child in children:
        rows, cards, forecasts = [], [], []
        by_day = data[child.pk]
        valid_days = [d for d in by_day if max(first, child.birth_date) <= d <= cutoff]
        for d in valid_days:
            rows.append(
                {
                    "date": d,
                    "partial": d == today,
                    "values": [
                        {
                            "kind": kind,
                            "label": label,
                            "value": (
                                display_value(kind, by_day[d][kind])
                                if by_day[d][kind]
                                else "—"
                            ),
                        }
                        for kind, _, label in kinds
                    ],
                }
            )
        for kind, _, label in kinds:
            values = [by_day[d][kind] for d in valid_days]
            observed = [v for v in values if v > 0]
            old = [
                by_day[d][kind]
                for d in by_day
                if max(previous_first, child.birth_date) <= d <= previous_cutoff
            ]
            old_observed = [v for v in old if v > 0]
            average = sum(observed) / len(observed) if observed else None
            old_average = (
                sum(old_observed) / len(old_observed) if old_observed else None
            )
            cards.append(
                {
                    "kind": kind,
                    "label": label,
                    "total": display_value(kind, sum(values)),
                    "days": len(observed),
                    "calendar_days": len(valid_days),
                    "average": (
                        display_value(kind, round(average, 1))
                        if average is not None
                        else "—"
                    ),
                    "previous_average": (
                        display_value(kind, round(old_average, 1))
                        if old_average is not None
                        else "—"
                    ),
                    "previous_days": len(old_observed),
                    "change": (
                        round((average / old_average - 1) * 100, 1)
                        if average is not None and old_average
                        else None
                    ),
                }
            )
            if kind in {"sleep", "feeding", "meal", "diaperchange"}:
                history = [
                    by_day[d][kind]
                    for d in by_day
                    if max(forecast_start, child.birth_date) <= d <= forecast_end
                    and by_day[d][kind] > 0
                ]
                forecasts.append(
                    {
                        "kind": kind,
                        "label": label,
                        "days": len(history),
                        "ready": len(history) >= 7,
                        "typical": (
                            display_value(kind, median(history)) if history else "—"
                        ),
                        "low": display_value(kind, min(history)) if history else "—",
                        "high": display_value(kind, max(history)) if history else "—",
                    }
                )
        groups.append(
            {"child": child, "cards": cards, "rows": rows, "forecasts": forecasts}
        )
    return {
        "groups": groups,
        "first": first,
        "last": last,
        "cutoff": cutoff,
        "partial": last >= today,
        "previous_first": previous_first,
        "previous_cutoff": previous_cutoff,
        "forecast_start": forecast_start,
        "forecast_end": forecast_end,
        "forecast_until": forecast_end + timedelta(days=7),
        "has_permissions": bool(kinds),
    }

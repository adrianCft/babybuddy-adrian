"""Read-only daily totals and visual events, using the viewer's local day."""

from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.db.models import Q
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.translation import gettext as _

from core import models
from core.utils import duration_string


def day_bounds(day):
    zone = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), zone)
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), zone)
    # UTC arithmetic is essential on 23/25-hour days.
    return start.astimezone(dt_timezone.utc), end.astimezone(dt_timezone.utc)


def total_covered(intervals):
    """Sum the union of intervals, so imported overlaps do not double-count sleep."""
    total = timedelta()
    stop = None
    for start, end in sorted(intervals):
        if stop is None or start >= stop:
            total += end - start
        elif end > stop:
            total += end - stop
        stop = max(stop, end) if stop is not None else end
    return total


def _number(value):
    # Preserve the precision entered by the caregiver, especially medication doses.
    return formats.number_format(value)


def _details(instance, kind):
    details = []
    if kind == "meal":
        if instance.dish_names:
            details.append(", ".join(instance.dish_names))
        details.append(", ".join(food.name for food in instance.foods.all()))
        if instance.quantity:
            details.append(
                _("Approximate quantity") + ": " + instance.get_quantity_display()
            )
    elif kind == "feeding":
        details.append(
            instance.get_type_display() + " · " + instance.get_method_display()
        )
        if instance.amount is not None:
            details.append(_("Amount") + ": " + _number(instance.amount))
    elif kind == "diaperchange":
        details.extend(str(value) for value in instance.attributes())
    elif kind == "medication":
        if instance.dosage is not None:
            details.append(
                _("Dosage")
                + ": "
                + _number(instance.dosage)
                + " "
                + instance.get_dosage_unit_display()
            )
    elif kind == "temperature":
        details.append(_("Temperature") + ": " + _number(instance.temperature))
    elif kind == "pumping":
        details.append(_("Amount") + ": " + _number(instance.amount))
    elif kind == "tummytime" and instance.milestone:
        details.append(instance.milestone)
    elif kind == "note":
        details.append(instance.note)
    elif kind == "sleep" and instance.wakeups:
        details.append(_("Wake-ups") + ": " + str(instance.wakeups))
    if getattr(instance, "notes", None):
        details.append(instance.notes)
    return details


def build_daily_summary(day, children, user, now=None):
    start, end = day_bounds(day)
    now = (now or timezone.now()).astimezone(dt_timezone.utc)
    seconds = (end - start).total_seconds()
    specs = [
        ("sleep", models.Sleep, _("Sleep"), True),
        ("feeding", models.Feeding, _("Feedings"), True),
        ("meal", models.Meal, _("Meals"), False),
        ("diaperchange", models.DiaperChange, _("Diaper Changes"), False),
        ("medication", models.Medication, _("Medications"), False),
        ("note", models.Note, _("Notes"), False),
        ("temperature", models.Temperature, _("Temperature"), False),
        ("pumping", models.Pumping, _("Pumping"), True),
        ("tummytime", models.TummyTime, _("Tummy Time"), True),
    ]
    specs = [spec for spec in specs if user.has_perm(f"core.view_{spec[0]}")]
    groups = {
        child.pk: {"child": child, "lanes": {}, "records": {}, "events": []}
        for child in children
    }
    for kind, model, label, interval in specs:
        for group in groups.values():
            group["lanes"][kind] = {"kind": kind, "label": label, "events": []}
            group["records"][kind] = []
        queryset = model.objects.filter(child_id__in=groups).prefetch_related("tags")
        if interval:
            queryset = (
                queryset.filter(start__lt=end)
                .filter(Q(end__gt=start) | Q(start__gte=start, end__gte=start))
                .order_by("start", "pk")
            )
        else:
            queryset = queryset.filter(time__gte=start, time__lt=end).order_by(
                "time", "pk"
            )
        if kind == "meal":
            queryset = queryset.prefetch_related("foods")
        for instance in queryset:
            group = groups[instance.child_id]
            group["records"][kind].append(instance)
            actual_start = (instance.start if interval else instance.time).astimezone(
                dt_timezone.utc
            )
            actual_end = (
                instance.end.astimezone(dt_timezone.utc) if interval else actual_start
            )
            title = label
            if kind == "meal":
                title = instance.get_meal_type_display()
            elif kind == "medication":
                title = instance.name
            elif kind == "sleep" and instance.nap:
                title = _("Nap")
            event = _event(
                kind, instance.pk, title, actual_start, actual_end, start, end
            )
            event["details"] = _details(instance, kind)
            event["tags"] = list(instance.tags.all())
            event["edit_url"] = (
                reverse(f"core:{kind}-update", args=[instance.pk])
                if user.has_perm(f"core.change_{kind}")
                else None
            )
            group["events"].append(event)
            group["lanes"][kind]["events"].append(event)

    if "sleep" in {spec[0] for spec in specs} and user.has_perm("core.view_timer"):
        timers = models.Timer.objects.filter(
            child_id__in=groups,
            name=models.Timer.SLEEP_NAME,
            active=True,
            start__lt=min(end, now),
        )
        for timer in timers:
            if now <= start:
                continue
            event = _event(
                "sleep",
                f"timer-{timer.pk}",
                _("Sleep in progress"),
                timer.start.astimezone(dt_timezone.utc),
                now,
                start,
                end,
            )
            event.update(
                ongoing=True,
                details=[_("Provisional time, excluded from recorded sleep.")],
                tags=[],
                edit_url=None,
            )
            group = groups[timer.child_id]
            group["events"].append(event)
            group["lanes"]["sleep"]["events"].append(event)

    for group in groups.values():
        group["cards"] = _cards(group["records"], start, end)
        group["events"].sort(key=lambda event: (event["clipped_start"], event["id"]))
        group["lanes"] = list(group["lanes"].values())
        # Give nearby points / overlapping intervals separate rows and usable targets.
        for lane in group["lanes"]:
            stops = []
            for event in sorted(lane["events"], key=lambda item: item["left"]):
                hit_width = max(event["width"], 6.5)
                visual_left = min(event["left"], 100 - hit_width)
                row = next(
                    (i for i, stop in enumerate(stops) if stop <= visual_left),
                    len(stops),
                )
                if row == len(stops):
                    stops.append(0)
                stops[row] = visual_left + hit_width + 0.5
                event["row"] = row
                event["top"] = 8 + row * 38
                event["hit_left"] = visual_left
                event["hit_width"] = hit_width
                event["marker_left"] = (event["left"] - visual_left) / hit_width * 100
            lane["height"] = max(1, len(stops)) * 38 + 16
        group["event_count"] = len(group["events"])
        del group["records"]

    ticks = []
    cursor = start
    while cursor < end:
        ticks.append(
            {
                "left": (cursor - start).total_seconds() / seconds * 100,
                "label": timezone.localtime(cursor).strftime("%H:%M"),
            }
        )
        cursor += timedelta(hours=3)
    ticks.append({"left": 100, "label": "24:00"})
    return {
        "groups": list(groups.values()),
        "ticks": ticks,
        "day_hours": int(seconds / 3600),
        "has_permissions": bool(specs),
        "has_events": any(group["events"] for group in groups.values()),
        "now_left": (
            (now - start).total_seconds() / seconds * 100
            if start <= now < end
            else None
        ),
    }


def _event(kind, pk, title, actual_start, actual_end, start, end):
    clipped_start, clipped_end = max(actual_start, start), min(actual_end, end)
    elapsed = max(timedelta(), clipped_end - clipped_start)
    seconds = (end - start).total_seconds()
    return {
        "id": f"daily-{kind}-{pk}",
        "kind": kind,
        "title": title,
        "start": timezone.localtime(actual_start),
        "end": timezone.localtime(actual_end),
        "clipped_start": clipped_start,
        "is_interval": actual_end > actual_start,
        "continued_before": actual_start < start,
        "continued_after": actual_end >= end,
        "duration": duration_string(elapsed, "m"),
        "left": (clipped_start - start).total_seconds() / seconds * 100,
        "width": elapsed.total_seconds() / seconds * 100,
        "ongoing": False,
    }


def _cards(records, start, end):
    cards = []
    if "sleep" in records:
        sleeps = records["sleep"]
        covered = total_covered(
            [
                (
                    max(row.start.astimezone(dt_timezone.utc), start),
                    min(row.end.astimezone(dt_timezone.utc), end),
                )
                for row in sleeps
                if row.end > row.start
            ]
        )
        cards.append(
            {
                "kind": "sleep",
                "label": _("Recorded sleep"),
                "value": duration_string(covered, "m"),
                "detail": _("Naps: %(count)s")
                % {"count": sum(row.nap for row in sleeps)},
            }
        )
    if "feeding" in records:
        feedings = [row for row in records["feeding"] if start <= row.start < end]
        bottles = [
            row.amount
            for row in feedings
            if row.method == "bottle" and row.amount is not None
        ]
        cards.append(
            {
                "kind": "feeding",
                "label": _("Feedings started"),
                "value": len(feedings),
                "detail": (
                    (
                        _("Bottle amount recorded: %(amount)s")
                        % {"amount": _number(sum(bottles))}
                    )
                    if bottles
                    else _("No bottle amount recorded")
                ),
            }
        )
    if "meal" in records:
        meals = records["meal"]
        food_count = len({food.pk for meal in meals for food in meal.foods.all()})
        cards.append(
            {
                "kind": "meal",
                "label": _("Meals"),
                "value": len(meals),
                "detail": _("Different foods: %(total)s") % {"total": food_count},
            }
        )
    if "diaperchange" in records:
        diapers = records["diaperchange"]
        cards.append(
            {
                "kind": "diaperchange",
                "label": _("Diaper Changes"),
                "value": len(diapers),
                "detail": _("Wet: %(wet)s · Solid: %(solid)s")
                % {
                    "wet": sum(row.wet for row in diapers),
                    "solid": sum(row.solid for row in diapers),
                },
            }
        )
    for kind, label in [("medication", _("Medications")), ("note", _("Notes"))]:
        if kind in records:
            cards.append({"kind": kind, "label": label, "value": len(records[kind])})
    return cards

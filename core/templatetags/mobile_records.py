"""Compact, read-only presentation of the same records as desktop lists."""

from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from django import template
from django.core.exceptions import FieldDoesNotExist
from django.db.models import prefetch_related_objects
from django.urls import reverse
from django.utils import formats
from django.utils.translation import gettext as _

from core.models import Child
from core.medications import prescription_dose_url
from core.navigation import contextual_url
from core.templatetags.datetime import datetime_short
from core.utils import duration_string

register = template.Library()

# Route, visible detail fields. No new detail/update endpoints are introduced.
RECORDS = {
    "bmi": ("bmi", ("bmi",)),
    "child": ("child", ("birth_date",)),
    "childfoodprofile": (
        "child-food-profile",
        (
            "taste",
            "tolerance",
            "first_consumed",
            "last_consumed",
            "consumption_count",
            "updated",
        ),
    ),
    "diaperchange": ("diaperchange", ("wet", "solid", "color", "amount")),
    "dish": ("dish", ()),
    "feeding": ("feeding", ("end", "duration", "method", "type", "amount")),
    "food": ("food", ("category", "allergen")),
    "headcircumference": ("head-circumference", ("head_circumference",)),
    "healthvisit": (
        "visit",
        (
            "kind",
            "status",
            "specialty",
            "professional",
            "center",
            "symptoms",
            "assessment",
            "tests",
            "instructions",
            "follow_up",
            "follow_up_time",
        ),
    ),
    "height": ("height", ("height",)),
    "meal": ("meal", ("meal_type", "quantity", "preparation")),
    "medication": (
        "medication",
        ("dosage", "dosage_unit", "next_dose_interval", "next_dose_time"),
    ),
    "note": ("note", ()),
    "prescription": (
        "prescription",
        ("dosage", "dosage_unit", "instructions", "start_date", "end_date"),
    ),
    "pumping": ("pumping", ("end", "duration", "amount")),
    "sleep": ("sleep", ("end", "duration", "nap", "wakeups")),
    "tag": ("tag", ("color", "core_tagged_items__count", "last_used")),
    "temperature": ("temperature", ("temperature",)),
    "timer": ("timer", ("duration", "user_username")),
    "tummytime": ("tummytime", ("end", "duration", "milestone")),
    "vaccination": ("vaccination", ("dose", "status", "center", "batch", "next_date")),
    "weight": ("weight", ("weight",)),
}


def display_value(value):
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    if isinstance(value, datetime):
        return datetime_short(value)
    if isinstance(value, date):
        return formats.date_format(value, "SHORT_DATE_FORMAT")
    if isinstance(value, time):
        return formats.time_format(value, "TIME_FORMAT")
    if isinstance(value, timedelta):
        return duration_string(value, "m")
    if isinstance(value, (int, float)):
        return formats.localize(value)
    return str(value)


def field_value(obj, name):
    value = getattr(obj, name, None)
    if callable(value):
        value = value()
    display = getattr(obj, "get_" + name + "_display", None)
    return display() if display else display_value(value)


def field_label(obj, name):
    labels = {
        "professional": _("Person's name"),
        "first_consumed": _("First intake"),
        "last_consumed": _("Last intake"),
        "consumption_count": _("Times consumed"),
        "core_tagged_items__count": _("Items Tagged"),
        "duration": _("Duration"),
        "user_username": _("User"),
        "next_dose_time": _("Next Dose"),
    }
    if name in labels:
        return labels[name]
    try:
        return obj._meta.get_field(name).verbose_name
    except FieldDoesNotExist:
        return name


def record_title(obj):
    model = obj._meta.model_name
    if model == "healthvisit":
        return obj.reason
    if model == "medication":
        return obj.name
    if model == "childfoodprofile":
        return str(obj.food)
    if model == "meal":
        return ", ".join(obj.dish_names) or obj.get_meal_type_display() or _("Meal")
    if model == "feeding":
        return obj.get_type_display()
    if model == "sleep":
        return _("Nap") if obj.nap else _("Sleep")
    if model == "diaperchange":
        return " · ".join(
            label
            for active, label in ((obj.wet, _("Wet")), (obj.solid, _("Solid")))
            if active
        ) or str(obj)
    if model == "note":
        return obj.note[:100]
    if model in ("bmi", "headcircumference", "height", "temperature", "weight"):
        name = RECORDS[model][1][0]
        return "%s: %s" % (obj._meta.verbose_name, field_value(obj, name))
    return str(obj)


@register.inclusion_tag("core/mobile_record_cards.html", takes_context=True)
def mobile_record_cards(context, objects):
    objects = list(objects)
    request = context["request"]
    cards = []
    if objects:
        related = {field.name for field in objects[0]._meta.get_fields()}
        relations = [
            name
            for name in ("tags", "photos", "foods", "child", "food", "user")
            if name in related
        ]
        if "visit" in related:
            relations.append("visit__child")
        prefetch_related_objects(objects, *relations)
    previous_day = None
    for obj in objects:
        model = obj._meta.model_name
        route, names = RECORDS[model]
        # The existing head circumference views use a legacy permission name.
        permission = "head_circumference" if model == "headcircumference" else model
        key = obj.slug if model in ("child", "tag") else obj.pk
        child = (
            obj.visit.child if model == "prescription" else getattr(obj, "child", None)
        )
        recorded_at = (
            obj.visit.date
            if model == "prescription"
            else next(
                (
                    getattr(obj, name)
                    for name in ("time", "date", "start", "updated")
                    if getattr(obj, name, None)
                ),
                None,
            )
        )
        fields = [
            (field_label(obj, name), field_value(obj, name))
            for name in names
            if (name != "specialty" or obj.kind == "specialist")
            and (
                name not in ("follow_up", "follow_up_time")
                or not hasattr(obj, "follow_up_visit")
            )
        ]
        card = {
            "object": obj,
            "model": model,
            "title": record_title(obj),
            "child": child,
            "date": display_value(recorded_at),
            "fields": [(label, value) for label, value in fields if value != ""],
            "notes": getattr(obj, "notes", "") or (obj.note if model == "note" else ""),
            "tags": obj.tags.all() if "tags" in related else (),
            "photos": obj.photos.all() if "photos" in related else (),
            "image": obj.image if model == "note" and obj.image else None,
        }
        if request.user.has_perm("core.change_" + permission):
            card["update_url"] = contextual_url(
                request, "core:" + route + "-update", key
            )
        if model != "childfoodprofile" and request.user.has_perm(
            "core.delete_" + permission
        ):
            card["delete_url"] = contextual_url(
                request, "core:" + route + "-delete", key
            )
        if model in ("healthvisit", "vaccination", "prescription", "timer", "tag"):
            card["detail_url"] = contextual_url(
                request, "core:" + route + "-detail", key
            )
        elif model == "child":
            card["detail_url"] = contextual_url(request, "core:child", key)
        if model == "prescription" and request.user.has_perm("core.add_medication"):
            card["dose_url"] = prescription_dose_url(request, obj)
        if hasattr(obj, "status"):
            card["status"] = obj.get_status_display()
        elif hasattr(obj, "active"):
            card["status"] = _("Active") if obj.active else _("Inactive")
        if model in ("feeding", "sleep", "pumping", "tummytime", "timer"):
            card["summary"] = field_value(obj, "duration")
        if model in ("meal", "dish"):
            card["foods"] = list(obj.foods.all())
            card["summary"] = ", ".join(food.name for food in card["foods"])
        if model == "meal":
            card["meal_foods"] = list(obj.mealfood_set.all())
        if model == "child":
            card["picture"] = obj.picture
        if model == "meal" and getattr(obj, "local_date", None) != previous_day:
            previous_day = obj.local_date
            card["group_date"] = previous_day
            card["day_summary"] = getattr(obj, "day_summary", None)
        cards.append(card)
    return {
        "cards": cards,
        "empty_message": context.get("empty_message", _("No records yet.")),
    }


@register.inclusion_tag("core/quick_record_links.html", takes_context=True)
def quick_record_links(context):
    user = context["request"].user
    child = context.get("selected_child") or context.get("child")
    obj = context.get("object")
    if not isinstance(child, Child):
        child = obj if isinstance(obj, Child) else getattr(obj, "child", None)
    suffix = "?" + urlencode({"child": child.slug}) if isinstance(child, Child) else ""
    specs = [
        ("meal", "meal", "feeding", _("Meal"), True),
        ("feeding", "feeding", "feeding", _("Milk feeding"), True),
        ("diaperchange", "diaperchange", "diaperchange", _("Diaper"), True),
        ("sleep", "sleep", "sleep", _("Sleep"), True),
        ("medication", "medication", "medication", _("Medication"), True),
        ("feeding", "bottle-feeding", "feeding", _("Bottle Feeding"), True),
        ("healthvisit", "visit", "medication", _("Medical visit"), False),
        ("vaccination", "vaccination", "medication", _("Vaccination"), False),
        ("weight", "weight", "weight", _("Weight"), False),
        ("height", "height", "height", _("Height"), False),
        (
            "head_circumference",
            "head-circumference",
            "head-circumference",
            _("Head Circumference"),
            False,
        ),
        ("temperature", "temperature", "temperature", _("Temperature"), False),
        ("pumping", "pumping", "pumping", _("Pumping"), False),
        ("note", "note", "note", _("Note"), False),
        ("tummytime", "tummytime", "tummytime", _("Tummy Time"), False),
    ]
    links = [
        {
            "url": contextual_url(
                context["request"], reverse("core:" + route + "-add") + suffix
            ),
            "icon": icon,
            "label": label,
            "primary": primary,
        }
        for permission, route, icon, label, primary in specs
        if user.has_perm("core.add_" + permission)
    ]
    return {
        "primary_links": [link for link in links if link["primary"]],
        "other_links": [link for link in links if not link["primary"]],
    }

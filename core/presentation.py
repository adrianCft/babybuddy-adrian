"""Shared labels and filter summaries. No record data is changed here."""

from datetime import date, datetime

from django import forms
from django.http import QueryDict
from django.utils.formats import date_format
from django.utils import timezone
from django.utils.translation import gettext as _


def submit_label(model, updating=False):
    labels = {
        "healthvisit": _("Save visit"),
        "vaccination": _("Save vaccination"),
        "prescription": _("Save prescription"),
        "medication": _("Record dose"),
        "meal": _("Save meal"),
        "feeding": _("Save feeding"),
        "diaperchange": _("Save diaper change"),
        "sleep": _("Save sleep"),
        "food": _("Save food"),
        "dish": _("Save dish"),
        "childfoodprofile": _("Save food profile"),
        "child": _("Save child"),
        "weight": _("Save weight"),
        "height": _("Save height"),
        "headcircumference": _("Save head circumference"),
        "bmi": _("Save BMI"),
        "temperature": _("Save temperature"),
        "pumping": _("Save pumping"),
        "tummytime": _("Save tummy time"),
        "note": _("Save note"),
        "tag": _("Save tag"),
        "timer": _("Save timer"),
    }
    name = getattr(getattr(model, "_meta", None), "model_name", "")
    if name == "medication" and updating:
        return _("Save dose")
    return labels.get(name, _("Save"))


def record_value(value):
    if isinstance(value, datetime):
        return date_format(timezone.localtime(value), "SHORT_DATETIME_FORMAT")
    if isinstance(value, date):
        return date_format(value, "DATE_FORMAT")
    return value


def _filter_display(field, value):
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    if isinstance(value, (date, datetime)):
        return date_format(value, "DATE_FORMAT")
    if isinstance(field, forms.ModelMultipleChoiceField):
        return ", ".join(field.label_from_instance(item) for item in value)
    if isinstance(field, forms.ModelChoiceField):
        return field.label_from_instance(value)
    choices = dict(getattr(field, "choices", ()))
    if isinstance(value, (list, tuple)):
        return ", ".join(str(choices.get(item, item)) for item in value)
    return str(choices.get(value, value))


def filter_context(request, filterset):
    form = filterset.form
    form.is_valid()
    chips = []
    for name, field in form.fields.items():
        if name == "child":
            continue
        if isinstance(field.widget, forms.Select):
            unset = "unknown" if isinstance(field, forms.NullBooleanField) else ""
            field.widget.choices = [
                (key, _("Any") if key == unset else label)
                for key, label in field.widget.choices
            ]
        value = form.cleaned_data.get(name)
        if value is None or value == "" or value == [] or value == ():
            continue
        text = _filter_display(field, value)
        if not text:
            continue
        query = request.GET.copy()
        query.pop("page", None)
        query.pop("clear_filters", None)
        query[name] = ""
        query["filtered"] = "1"
        chips.append(
            {
                "name": name,
                "label": field.label,
                "value": text,
                "remove_url": request.path + "?" + query.urlencode(),
            }
        )
    clear = QueryDict(mutable=True)
    clear["clear_filters"] = "1"
    child = form.cleaned_data.get("child")
    if "child" in form.fields:
        clear["child"] = str(child.pk) if child is not None else ""
    if "date" in form.fields:
        clear["date"] = ""
    scoped_records = filterset.queryset
    if child is not None and "child" in filterset.filters:
        scoped_records = filterset.filters["child"].filter(scoped_records, child)
    return {
        "active_filters": chips,
        "clear_filters_url": request.path + "?" + clear.urlencode(),
        "empty_message": (
            _("No results with these filters.")
            if (chips or form.errors) and scoped_records.exists()
            else _("No records yet.")
        ),
    }

"""A small personal home layout built from the existing dashboard cards."""

from django import forms
from django.db.models import F, Window
from django.db.models.functions import Lower, RowNumber
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import HealthVisit, Medication, Timer
from core.navigation import contextual_url, effective_url
from dashboard.templatetags import cards

DEFAULT_CARDS = [
    "feeding-last",
    "diaper-change-last",
    "meal-summary",
    "sleep-last",
    "medication-last",
]
MAX_FAVORITES = 6
HOME_HEADINGS = {
    "feeding-last": (_("Feedings"), "core:feeding-list"),
    "diaper-change-last": (_("Diapers"), "core:diaperchange-list"),
    "meal-summary": (_("Meals"), "core:meal-list"),
    "sleep-last": (_("Sleep"), "core:sleep-list"),
    "medication-last": (_("Medication"), "core:medication-list"),
    "pumping-last": (_("Pumping"), "core:pumping-list"),
}
SPECS = [
    ("feeding-last", _("Last Feeding"), ("feeding",), "feeding_last"),
    (
        "diaper-change-last",
        _("Last Diaper Change"),
        ("diaperchange",),
        "diaperchange_last",
    ),
    ("meal-summary", _("Meals"), ("meal",), "meal_summary"),
    ("sleep-last", _("Last Sleep"), ("sleep",), "sleep_last"),
    ("medication-last", _("Last medication dose"), ("medication",), "medication_last"),
    ("pumping-last", _("Last Pumping"), ("pumping",), "pumping_last"),
    ("pumping-recent", _("Recent Pumping"), ("pumping",), "pumping_recent"),
    (
        "feeding-last-method",
        _("Last Feeding Method"),
        ("feeding",),
        "feeding_last_method",
    ),
    ("feeding-recent", _("Recent Feedings"), ("feeding",), "feeding_recent"),
    (
        "statistics",
        _("Statistics"),
        (
            "feeding",
            "diaperchange",
            "sleep",
            "weight",
            "height",
            "headcircumference",
            "bmi",
        ),
        "statistics",
    ),
    ("sleep-recent", _("Recent Sleep"), ("sleep",), "sleep_recent"),
    ("sleep-naps-day", _("Today's Naps"), ("sleep",), "sleep_naps_day"),
    ("tummytime-day", _("Today's Tummy Time"), ("tummytime",), "tummytime_day"),
    (
        "diaperchange-types",
        _("Diaper Changes"),
        ("diaperchange",),
        "diaperchange_types",
    ),
    ("breastfeeding", _("Breastfeeding"), ("feeding",), "breastfeeding"),
]


def available_cards(user):
    return [
        {"key": key, "label": label, "loader": loader}
        for key, label, permissions, loader in SPECS
        if all(user.has_perm("core.view_" + permission) for permission in permissions)
    ]


def favorite_keys(user, available):
    saved = user.settings.dashboard_cards
    values = saved if isinstance(saved, list) else DEFAULT_CARDS
    allowed = {card["key"] for card in available}
    return list(
        dict.fromkeys(key for key in values if isinstance(key, str) and key in allowed)
    )[:MAX_FAVORITES]


class HomeLayoutForm(forms.Form):
    cards = forms.MultipleChoiceField(required=False)
    hide_empty = forms.BooleanField(
        required=False,
        label=_("Hide Empty Dashboard Cards"),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, user, **kwargs):
        available = available_cards(user)
        kwargs.setdefault(
            "initial",
            {
                "cards": favorite_keys(user, available),
                "hide_empty": user.settings.dashboard_hide_empty,
            },
        )
        super().__init__(*args, **kwargs)
        self.fields["cards"].choices = [
            (card["key"], card["label"]) for card in available
        ]

    def clean_cards(self):
        selected = self.cleaned_data["cards"]
        if len(selected) > MAX_FAVORITES:
            raise forms.ValidationError(_("Choose up to 6 favorite cards."))
        if len(selected) != len(set(selected)):
            raise forms.ValidationError(_("Choose each card only once."))
        return selected


def pending_dose(child, now):
    latest_doses = (
        Medication.objects.filter(child=child, time__lte=now)
        .annotate(
            latest=Window(
                expression=RowNumber(),
                partition_by=Lower("name"),
                order_by=[F("time").desc(), F("pk").desc()],
            )
        )
        .filter(latest=1)
    )
    return min(
        (
            dose
            for dose in latest_doses
            if dose.next_dose_time and dose.next_dose_time > now
        ),
        key=lambda dose: dose.next_dose_time,
        default=None,
    )


def home_layout(request, child, form=None):
    user = request.user
    available = available_cards(user)
    favorites = favorite_keys(user, available)
    by_key = {card["key"]: card for card in available}

    def rendered(card):
        loader = getattr(cards, "card_" + card["loader"])
        if card["key"] == "sleep-last":
            data = loader({"request": request}, child, internal_only=True)
            # Keep the current sleep in the compact status; this card shows
            # the last completed sleep without repeating timer controls.
            data.update(timer=None, can_start=False, can_finish=False)
        else:
            data = loader({"request": request}, child)
        if data.get("empty") and data.get("hide_empty"):
            return None
        data.update(
            request=request, child=child, next=effective_url(request), home_card=True
        )
        if card["key"] in HOME_HEADINGS:
            label, target = HOME_HEADINGS[card["key"]]
            data.update(home_label=label, home_list_url=contextual_url(request, target))
        return {
            **card,
            "html": render_to_string(
                "cards/" + card["loader"] + ".html", data, request=request
            ),
        }

    selected = [by_key[key] for key in favorites]
    others = [card for card in available if card["key"] not in favorites]
    layout_form = form or HomeLayoutForm(user=user)
    checked = list(dict.fromkeys(layout_form["cards"].value() or []))
    rows = [by_key[key] for key in checked if key in by_key]
    rows += [card for card in available if card["key"] not in checked]
    can_view_visits = user.has_perm("core.view_healthvisit")
    can_add_visit = user.has_perm("core.add_healthvisit")
    now = timezone.now()
    next_visit = (
        HealthVisit.objects.filter(child=child, status="planned", date__gte=now)
        .order_by("date", "pk")
        .first()
        if can_view_visits
        else None
    )
    return {
        "show_visit_card": can_view_visits or can_add_visit,
        "can_view_visits": can_view_visits,
        "can_add_visit": can_add_visit,
        "next_visit": next_visit,
        "visit_reminder": (
            next_visit
            if next_visit
            and timezone.localdate(next_visit.date)
            <= timezone.localdate(now) + timezone.timedelta(days=5)
            else None
        ),
        "pending_dose": (
            pending_dose(child, now) if user.has_perm("core.view_medication") else None
        ),
        "favorites": [item for card in selected if (item := rendered(card))],
        "others": [item for card in others if (item := rendered(card))],
        "selected_rows": [card for card in rows if card["key"] in checked],
        "available_rows": [card for card in rows if card["key"] not in checked],
        "form": layout_form,
    }


def sleep_status(request, child):
    user = request.user
    can_start = user.has_perm("core.add_timer") and user.has_perm("core.add_sleep")
    can_finish = user.has_perm("core.add_sleep")
    can_view = user.has_perm("core.view_sleep") or user.has_perm("core.view_timer")
    timer = None
    if can_view or can_finish:
        timer = (
            Timer.objects.filter(child=child, name=Timer.SLEEP_NAME, active=True)
            .order_by("-start")
            .first()
        )
    return {
        "timer": timer,
        "can_start": can_start,
        "can_finish": can_finish,
        "visible": can_view or can_start or can_finish,
        "next": effective_url(request),
    }

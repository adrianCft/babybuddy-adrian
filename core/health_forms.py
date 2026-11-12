from datetime import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.forms.utils import from_current_timezone
from django.utils.translation import gettext_lazy as _
from babybuddy.widgets import DateInput, DateTimeInput, TimeInput
from core import models
from core.forms import CoreModelForm
from core.photo_forms import PhotoFormMixin
from core.widgets import ChildRadioSelect


class HealthVisitForm(PhotoFormMixin, CoreModelForm):
    photo_owner = "visit"
    specialties = {
        "pediatrics": _("Pediatrics"),
        "allergy": _("Allergy and immunology"),
        "cardiology": _("Cardiology"),
        "dermatology": _("Dermatology"),
        "gastroenterology": _("Gastroenterology"),
        "neurology": _("Neurology"),
        "ophthalmology": _("Ophthalmology"),
        "ent": _("Otolaryngology"),
        "orthopedics": _("Orthopedics and traumatology"),
        "pulmonology": _("Pulmonology"),
        "dentistry": _("Pediatric dentistry"),
    }
    specialty_choice = forms.ChoiceField(
        label=_("Specialty"),
        required=False,
        choices=[
            ("", "---------"),
            *specialties.items(),
            ("other", _("Other specialty")),
        ],
    )
    fieldsets = [
        {
            "fields": [
                "child",
                "date",
                "kind",
                "specialty_choice",
                "specialty",
                "status",
                "reason",
                "professional",
            ],
            "layout": "visit",
        },
        {
            "title": _("Visit results"),
            "fields": ["center", "symptoms", "assessment", "tests"],
            "layout": "section",
        },
        {
            "title": _("Follow-up"),
            "fields": ["instructions", "follow_up", "follow_up_time"],
            "layout": "section",
        },
    ]

    class Meta:
        model = models.HealthVisit
        # Reuse the existing column so previously recorded names are retained.
        fields = [
            "child",
            "date",
            "kind",
            "specialty",
            "status",
            "reason",
            "professional",
            "center",
            "symptoms",
            "assessment",
            "tests",
            "instructions",
            "follow_up",
            "follow_up_time",
        ]
        labels = {
            "professional": _("Person's name"),
            "specialty": _("Specify the specialty"),
        }
        widgets = {
            "child": ChildRadioSelect(),
            "date": DateTimeInput(),
            "follow_up": DateInput(),
            "follow_up_time": TimeInput(attrs={"step": 1}),
            **{
                field: forms.Textarea(attrs={"rows": 3})
                for field in ("symptoms", "assessment", "tests", "instructions")
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.follow_up_of_id or (
            self.instance.pk and hasattr(self.instance, "follow_up_visit")
        ):
            self.fields["child"].disabled = True
        specialty = self.initial.get("specialty")
        if specialty:
            self.initial["specialty_choice"] = next(
                (
                    key
                    for key, label in self.specialties.items()
                    if specialty.casefold() == str(label).casefold()
                ),
                "other",
            )

    def clean(self):
        cleaned = super().clean()
        follow_up_date = cleaned.get("follow_up")
        follow_up_time = cleaned.get("follow_up_time")
        if follow_up_date and follow_up_time is not None:
            try:
                from_current_timezone(datetime.combine(follow_up_date, follow_up_time))
            except ValidationError as error:
                self.add_error("follow_up_time", error)

        choice = cleaned.get("specialty_choice")
        if choice in self.specialties:
            if choice != self.initial.get("specialty_choice"):
                cleaned["specialty"] = str(self.specialties[choice])
            else:
                cleaned["specialty"] = self.initial["specialty"]
        elif (
            choice == "other"
            and cleaned.get("kind") == "specialist"
            and "specialty" in cleaned
            and not cleaned["specialty"]
        ):
            self.add_error("specialty", _("Enter the specialty."))
        return cleaned


class PrescriptionForm(PhotoFormMixin, CoreModelForm):
    photo_owner = "prescription"
    fieldsets = [
        {
            "fields": [
                "name",
                "dosage",
                "dosage_unit",
                "interval_hours",
                "instructions",
            ],
            "layout": "required",
        },
        {
            "title": _("Dates and notes"),
            "fields": ["start_date", "end_date", "notes"],
            "layout": "section",
        },
    ]

    class Meta:
        model = models.Prescription
        # The view binds the visit, never a hidden client-provided child/visit.
        fields = [
            "name",
            "dosage",
            "dosage_unit",
            "interval_hours",
            "instructions",
            "start_date",
            "end_date",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"list": "medication-names", "autocomplete": "off"}
            ),
            "dosage": forms.NumberInput(attrs={"inputmode": "decimal"}),
            "interval_hours": forms.NumberInput(attrs={"inputmode": "decimal"}),
            "start_date": DateInput(),
            "end_date": DateInput(),
            "instructions": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class PrescriptionInlineForm(PhotoFormMixin, forms.ModelForm):
    """Compact prescription rows shown while recording a medical visit."""

    photo_owner = "prescription"

    class Meta(PrescriptionForm.Meta):
        widgets = {
            **PrescriptionForm.Meta.widgets,
            "instructions": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


PrescriptionInlineFormSet = inlineformset_factory(
    models.HealthVisit,
    models.Prescription,
    form=PrescriptionInlineForm,
    extra=0,
    # Prescriptions have their own detail/delete screens; keeping deletion out
    # of this compact visit form avoids exposing formset internals here.
    can_delete=False,
)


class VaccinationForm(PhotoFormMixin, CoreModelForm):
    photo_owner = "vaccination"
    fieldsets = [
        {"fields": ["child", "name", "dose", "date", "status"], "layout": "required"},
        {
            "title": _("Vaccination details"),
            "fields": ["center", "batch", "next_date", "notes"],
            "layout": "section",
        },
    ]

    class Meta:
        model = models.Vaccination
        fields = [
            "child",
            "name",
            "dose",
            "date",
            "status",
            "center",
            "batch",
            "next_date",
            "notes",
        ]
        widgets = {
            "child": ChildRadioSelect(),
            "date": DateInput(),
            "next_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

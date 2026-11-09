from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _
from babybuddy.widgets import DateInput, DateTimeInput
from core import models
from core.forms import CoreModelForm
from core.photo_forms import PhotoFormMixin
from core.widgets import ChildRadioSelect


class HealthVisitForm(PhotoFormMixin, CoreModelForm):
    photo_owner = "visit"

    class Meta:
        model = models.HealthVisit
        # The professional is intentionally kept in the database for backwards
        # compatibility, but is no longer part of the user-facing form.
        fields = ["child", "date", "kind", "status", "reason", "center",
                  "symptoms", "assessment", "tests", "instructions", "follow_up"]
        widgets = {
            "child": ChildRadioSelect(), "date": DateTimeInput(), "follow_up": DateInput(),
            **{field: forms.Textarea(attrs={"rows": 3}) for field in
               ("symptoms", "assessment", "tests", "instructions")},
        }


class PrescriptionForm(PhotoFormMixin, forms.ModelForm):
    photo_owner = "prescription"

    class Meta:
        model = models.Prescription
        # The view binds the visit, never a hidden client-provided child/visit.
        fields = ["name", "instructions", "start_date", "end_date", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"list": "medication-names", "autocomplete": "off"}),
            "start_date": DateInput(), "end_date": DateInput(),
            "instructions": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class PrescriptionInlineForm(forms.ModelForm):
    """Compact prescription rows shown while recording a medical visit."""

    class Meta:
        model = models.Prescription
        fields = ["name", "instructions", "start_date", "end_date", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "off"}),
            "start_date": DateInput(), "end_date": DateInput(),
            "instructions": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


PrescriptionInlineFormSet = inlineformset_factory(
    models.HealthVisit,
    models.Prescription,
    form=PrescriptionInlineForm,
    extra=1,
    # Prescriptions have their own detail/delete screens; keeping deletion out
    # of this compact visit form avoids exposing formset internals here.
    can_delete=False,
)


class VaccinationForm(PhotoFormMixin, CoreModelForm):
    photo_owner = "vaccination"

    class Meta:
        model = models.Vaccination
        fields = ["child", "name", "dose", "date", "status", "center", "batch", "next_date", "notes"]
        widgets = {
            "child": ChildRadioSelect(), "date": DateInput(), "next_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

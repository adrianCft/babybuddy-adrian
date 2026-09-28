from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from babybuddy.mixins import PermissionRequiredMixin
from core.growth import build_growth
from core.models import Child, GrowthProfile


class GrowthProfileForm(forms.ModelForm):
    class Meta:
        model = GrowthProfile
        fields = [
            "reference_system",
            "sex",
            "weight_unit",
            "height_unit",
            "birth_status",
            "gestational_weeks",
            "gestational_days",
        ]
        labels = {
            "reference_system": _("Growth reference"),
            "sex": _("Reference sex"),
            "weight_unit": _("Unit of saved weights"),
            "height_unit": _("Unit of saved lengths / heights"),
            "birth_status": _("Birth history"),
            "gestational_weeks": _("Gestational weeks at birth"),
            "gestational_days": _("Additional gestational days"),
        }
        help_texts = {
            "weight_unit": _(
                "Applies to all existing measurements; does not change their stored values."
            ),
            "gestational_weeks": _(
                "Only for premature births: 22 to 36 completed weeks."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-select"
                if isinstance(field.widget, forms.Select)
                else "form-control"
            )
        self.fields["gestational_days"].required = False
        self.fields["height_unit"].widget = forms.HiddenInput()
        self.fields["gestational_days"].widget.attrs.update(min=0, max=6)
        self.fields["gestational_weeks"].widget.attrs.update(min=22, max=36)

    def clean(self):
        data = super().clean()
        days = data.get("gestational_days") or 0
        data["gestational_days"] = days
        if not 0 <= days <= 6:
            self.add_error("gestational_days", _("Enter a value from 0 to 6."))
        if data.get("birth_status") == "preterm":
            weeks = data.get("gestational_weeks")
            if weeks is None or not 22 <= weeks <= 36:
                self.add_error(
                    "gestational_weeks",
                    _("Enter 22 to 36 completed weeks for a premature birth."),
                )
        else:
            data["gestational_weeks"] = None
            data["gestational_days"] = 0
        return data


class GrowthOverview(PermissionRequiredMixin, TemplateView):
    permission_required = ("core.view_child",)
    template_name = "core/growth_summary.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        child = get_object_or_404(
            Child.objects.select_related("growth_profile"), slug=self.kwargs["slug"]
        )
        growth = build_growth(child, self.request.user)
        context.update(child=child, growth=growth)
        context.setdefault("form", GrowthProfileForm(instance=growth["profile"]))
        return context

    def post(self, request, *args, **kwargs):
        if not request.user.has_perm("core.change_child"):
            raise PermissionDenied
        child = get_object_or_404(
            Child.objects.select_related("growth_profile"), slug=kwargs["slug"]
        )
        profile = getattr(child, "growth_profile", None) or GrowthProfile(child=child)
        form = GrowthProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(
                request, _("Growth reference saved. Measurements were not changed.")
            )
            return redirect("core:growth-summary", slug=child.slug)
        return self.render_to_response(self.get_context_data(form=form), status=400)

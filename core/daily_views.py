from datetime import date, timedelta
from urllib.parse import urlencode

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from babybuddy.mixins import PermissionRequiredMixin
from core.daily import build_daily_summary
from core.models import Child


class DailyFilterForm(forms.Form):
    date = forms.DateField(
        label=_("Date"),
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "class": "form-control", "min": "1900-01-01"},
        ),
    )
    child = forms.ModelChoiceField(
        label=_("Child"),
        required=False,
        empty_label=_("All children"),
        queryset=Child.objects.order_by("first_name", "last_name", "pk"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def clean_date(self):
        day = self.cleaned_data["date"]
        if day < date(1900, 1, 1) or day > timezone.localdate():
            raise forms.ValidationError(_("Choose a date between 1900 and today."))
        return day


class DailySummary(PermissionRequiredMixin, TemplateView):
    permission_required = ("core.view_child",)
    template_name = "core/daily_summary.html"

    def get(self, request, *args, **kwargs):
        today = timezone.localdate()
        data = request.GET.copy()
        data.setdefault("date", today.isoformat())
        children = list(Child.objects.order_by("first_name", "last_name", "pk"))
        if "child" not in data and len(children) == 1:
            data["child"] = str(children[0].pk)
        form = DailyFilterForm(data)
        form.fields["date"].widget.attrs["max"] = today.isoformat()
        context = self.get_context_data(form=form, today=today)
        if not form.is_valid():
            return self.render_to_response(context, status=400)
        day = form.cleaned_data["date"]
        child = form.cleaned_data["child"]
        selected = [child] if child else children
        child_value = str(child.pk) if child else ""

        def link(value):
            return "?" + urlencode({"date": value.isoformat(), "child": child_value})

        context.update(
            day=day,
            selected_child=child,
            is_today=day == today,
            previous_url=(
                link(day - timedelta(days=1)) if day > date(1900, 1, 1) else None
            ),
            next_url=link(day + timedelta(days=1)) if day < today else None,
            today_url=link(today),
            daily=build_daily_summary(day, selected, request.user),
        )
        return self.render_to_response(context)

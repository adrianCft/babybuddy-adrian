from datetime import date, timedelta
from urllib.parse import urlencode

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from babybuddy.mixins import PermissionRequiredMixin
from core.daily_views import DailyFilterForm
from core.models import Child
from core.periods import build_period_summary, period_bounds


class PeriodFilterForm(DailyFilterForm):
    period = forms.ChoiceField(
        label=_("Period"),
        choices=[("week", _("Week")), ("month", _("Month"))],
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class PeriodSummary(PermissionRequiredMixin, TemplateView):
    permission_required = ("core.view_child",)
    template_name = "core/period_summary.html"

    def get(self, request, *args, **kwargs):
        today = timezone.localdate()
        data = request.GET.copy()
        data.setdefault("date", today.isoformat())
        data.setdefault("period", "week")
        children = list(Child.objects.order_by("first_name", "last_name", "pk"))
        if "child" not in data and len(children) == 1:
            data["child"] = str(children[0].pk)
        form = PeriodFilterForm(data)
        form.fields["date"].widget.attrs["max"] = today.isoformat()
        context = self.get_context_data(form=form)
        if not form.is_valid():
            return self.render_to_response(context, status=400)
        day, child, period = (
            form.cleaned_data[key] for key in ("date", "child", "period")
        )

        def link(value):
            return "?" + urlencode(
                {
                    "date": value.isoformat(),
                    "child": child.pk if child else "",
                    "period": period,
                }
            )

        first, last = period_bounds(day, period)
        context.update(
            summary=build_period_summary(
                day, period, [child] if child else children, request.user, today
            ),
            selected_child=child,
            day=day,
            period=period,
            previous_url=(
                link(first - timedelta(days=1)) if first > date(1900, 1, 1) else None
            ),
            next_url=link(last + timedelta(days=1)) if last < today else None,
            today_url=link(today),
        )
        return self.render_to_response(context)

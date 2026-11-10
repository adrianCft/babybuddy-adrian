# -*- coding: utf-8 -*-
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.utils.translation import gettext as _
from django.urls import reverse
from django.views.generic.base import TemplateView
from django.views.generic.detail import DetailView

from babybuddy.mixins import LoginRequiredMixin, PermissionRequiredMixin
from core.models import Child, Timer
from core.navigation import contextual_url, navigation
from dashboard.home import HomeLayoutForm, home_layout, sleep_status


class Dashboard(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/dashboard.html"

    # Show the overall dashboard or a child dashboard if one Child instance.
    def get(self, request, *args, **kwargs):
        children = Child.objects.count()
        if children == 0:
            return HttpResponseRedirect(reverse("babybuddy:welcome"))
        child = navigation(request)["child"]
        if child:
            return HttpResponseRedirect(
                contextual_url(
                    request,
                    "dashboard:dashboard-child",
                    child.slug,
                    remember_return=False,
                )
            )
        return super(Dashboard, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(Dashboard, self).get_context_data(**kwargs)
        context["objects"] = Child.objects.all().order_by(
            "last_name", "first_name", "id"
        )
        timers = {}
        user = self.request.user
        if user.has_perm("core.view_sleep") or user.has_perm("core.view_timer"):
            for timer in Timer.objects.filter(
                name=Timer.SLEEP_NAME, active=True
            ).order_by("start"):
                timers[timer.child_id] = timer
        context["objects"] = list(context["objects"])
        for child in context["objects"]:
            child.active_sleep = timers.get(child.pk)
        return context


class ChildDashboard(PermissionRequiredMixin, DetailView):
    model = Child
    permission_required = ("core.view_child",)
    template_name = "dashboard/child.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["home"] = home_layout(
            self.request, self.object, kwargs.get("layout_form")
        )
        context["home_sleep"] = sleep_status(self.request, self.object)
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.POST.get("reset_home") == "1":
            request.user.settings.dashboard_cards = None
            request.user.settings.save(update_fields=["dashboard_cards"])
        else:
            form = HomeLayoutForm(request.POST, user=request.user)
            if not form.is_valid():
                return self.render_to_response(
                    self.get_context_data(layout_form=form), status=400
                )
            request.user.settings.dashboard_cards = form.cleaned_data["cards"]
            request.user.settings.dashboard_hide_empty = form.cleaned_data["hide_empty"]
            request.user.settings.save(
                update_fields=["dashboard_cards", "dashboard_hide_empty"]
            )
        messages.success(request, _("Home updated."))
        return HttpResponseRedirect(
            contextual_url(
                request,
                "dashboard:dashboard-child",
                self.object.slug,
                remember_return=False,
            )
        )

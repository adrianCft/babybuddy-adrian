"""Shared navigation context, kept in the session and explicit return links."""

from datetime import date, datetime
from urllib.parse import unquote, urlsplit, urlunsplit

import django_filters
from django import forms
from django.core.exceptions import FieldDoesNotExist
from django.db import models as django_models
from django.http import HttpResponseRedirect, QueryDict
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from django.utils.translation import gettext_lazy as _

from core.models import Child

SESSION_KEY = "record_navigation"
CHILD_PAGES = {
    "core:child": "core:timeline",
    "dashboard:dashboard-child": "dashboard:dashboard",
    "core:growth-summary": "core:growth-index",
}
DAY_PAGES = {"core:daily-summary", "core:period-summary", "core:timeline", "core:child"}


def parse_day(value):
    try:
        result = date.fromisoformat(value)
        return result if date(1900, 1, 1) <= result <= timezone.localdate() else None
    except (TypeError, ValueError):
        return None


def _remember(request, **changes):
    session = getattr(request, "session", None)
    if session is None:
        return
    old = session.get(SESSION_KEY, {})
    updated = {**old, **changes}
    if updated != old:
        session[SESSION_KEY] = updated


def navigation(request):
    if hasattr(request, "record_navigation"):
        return request.record_navigation
    children = list(Child.objects.order_by("first_name", "last_name", "pk"))
    saved = getattr(request, "session", {}).get(SESSION_KEY, {})
    match = getattr(request, "resolver_match", None)
    view_name = match.view_name if match else ""
    explicit = "child" in request.GET
    child_value = request.GET.get("child") if explicit else saved.get("child")
    if view_name in CHILD_PAGES and not explicit:
        child_value = match.kwargs.get("slug")
    child = next((c for c in children if child_value in (str(c.pk), c.slug)), None)
    if child_value is None and len(children) == 1:
        child = children[0]
    day_value = request.GET.get("date") if "date" in request.GET else saved.get("date")
    day = parse_day(day_value)
    if request.method == "GET":
        if children and (child or child_value in (None, "")):
            _remember(request, child=str(child.pk) if child else "")
        if "date" in request.GET and (day or day_value == ""):
            _remember(request, date=day.isoformat() if day else "")
    request.record_navigation = {
        "children": children,
        "child": child,
        "date": day,
        "view_name": view_name,
        "today": timezone.localdate(),
        "date_required": view_name in DAY_PAGES,
    }
    return request.record_navigation


def effective_url(request):
    query = request.GET.copy()
    query.pop("clear_filters", None)
    return request.path + ("?" + query.urlencode() if query else "")


def safe_return_url(request):
    value = request.POST.get("next", request.GET.get("next", ""))
    if not value or len(value) > 8192 or not value.startswith("/"):
        return ""
    if value.startswith("//") or "\\" in value or any(ord(c) < 32 for c in value):
        return ""
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return ""
    try:
        match = resolve(unquote(parts.path))
    except Resolver404:
        return ""
    if (
        match.namespace not in ("core", "dashboard")
        and match.view_name != "babybuddy:root-router"
    ):
        return ""
    if match.url_name.endswith(("-add", "-update", "-delete", "-quick", "-restart")):
        return ""
    return value


def contextual_url(request, target, *args, remember_return=True, **kwargs):
    """Add only context understood by the destination, never copy arbitrary filters."""
    url = (
        str(target)
        if str(target).startswith("/")
        else reverse(target, args=args, kwargs=kwargs)
    )
    parts = urlsplit(url)
    try:
        match = resolve(unquote(parts.path))
    except Resolver404:
        return url
    if match.namespace not in ("core", "dashboard") or match.url_name in (
        "health-photo",
        "food-quick-add",
        "dish-quick-add",
        "timer-add-quick",
        "sleep-finish-quick",
    ):
        return url
    if not getattr(request, "resolver_match", None):
        return url
    state = navigation(request)
    query = QueryDict(parts.query, mutable=True)
    if "child" not in query:
        child = state["child"]
        if match.view_name in CHILD_PAGES:
            child = next(
                (c for c in state["children"] if c.slug == match.kwargs["slug"]), child
            )
        query["child"] = (
            (child.slug if match.url_name.endswith("-add") else str(child.pk))
            if child
            else ""
        )
    day = state["date"]
    if day and "date" not in query and match.view_name != "dashboard:daycare":
        query["date"] = day.isoformat()
    is_action = match.url_name.endswith(("-add", "-update", "-delete"))
    is_detail = match.url_name in (
        "visit-detail",
        "vaccination-detail",
        "prescription-detail",
    )
    if remember_return and (is_action or is_detail) and "next" not in query:
        current = getattr(request, "resolver_match", None)
        if current and not current.url_name.endswith(("-add", "-update", "-delete")):
            # Detail pages can link to each other; keep their original return
            # destination instead of nesting an ever-growing chain of URLs.
            previous = (
                safe_return_url(request)
                if is_detail and current.url_name.endswith("-detail")
                else ""
            )
            query["next"] = previous or effective_url(request)
        elif safe_return_url(request):
            query["next"] = safe_return_url(request)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, query.urlencode(), parts.fragment)
    )


def date_filter_class(base, model):
    """Give dated record lists the same optional day filter as the summaries."""
    if "child" not in base.base_filters or "date" in base.base_filters:
        return base
    path = "visit__date" if model._meta.model_name == "prescription" else None
    field = None
    for name in ("time", "date", "start"):
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        if isinstance(field, django_models.DateField):
            path = name
            break
    if not path:
        return base
    lookup = (
        "date"
        if path == "visit__date" or isinstance(field, django_models.DateTimeField)
        else "exact"
    )
    return type(
        "Context" + base.__name__,
        (base,),
        {
            "date": django_filters.DateFilter(
                field_name=path,
                lookup_expr=lookup,
                label=_("Day"),
                widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            ),
        },
    )


def list_context(view, kwargs):
    request = view.request
    state = navigation(request)
    allowed = (
        kwargs["filterset_class"].base_filters
        if "filterset_class" in kwargs
        else view.get_filterset_class().base_filters
    )
    state["date_filter"] = "date" in allowed
    saved = getattr(request, "session", {}).get(SESSION_KEY, {}).get("filters", {})
    key = request.resolver_match.view_name
    old = saved.get(key, {})
    data = request.GET.copy()
    if "clear_filters" in data:
        data.pop("clear_filters", None)
        old = {}
    elif not data.get("filtered"):
        for name, values in old.items():
            if name not in data and name in allowed:
                data.setlist(name, values)
    if "child" in allowed and "child" not in data:
        data["child"] = str(state["child"].pk) if state["child"] else ""
    if "date" in allowed and "date" not in data and state["date"]:
        data["date"] = state["date"].isoformat()
    remembered = {
        name: [v[:512] for v in values[:20]]
        for name, values in data.lists()
        if name in allowed and name not in ("child", "date") and any(values)
    }
    if remembered != saved.get(key, {}):
        _remember(request, filters={**saved, key: remembered})
    request.GET = data
    kwargs["data"] = data
    return kwargs


class NavigationMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if not request.user.is_authenticated or match.namespace not in (
            "core",
            "dashboard",
        ):
            return None
        if match.url_name in ("health-photo", "food-quick-add", "dish-quick-add"):
            return None
        state = navigation(request)
        if request.method != "GET":
            return None
        if match.view_name in CHILD_PAGES and "child" in request.GET:
            child = state["child"]
            if child and child.slug != view_kwargs["slug"]:
                target = reverse(
                    match.view_name, kwargs={**view_kwargs, "slug": child.slug}
                )
                return HttpResponseRedirect(
                    contextual_url(request, target, remember_return=False)
                )
            if request.GET.get("child") == "":
                return HttpResponseRedirect(
                    contextual_url(
                        request, CHILD_PAGES[match.view_name], remember_return=False
                    )
                )
        if match.view_name in DAY_PAGES:
            data = request.GET.copy()
            data.setdefault("child", str(state["child"].pk) if state["child"] else "")
            data.setdefault("date", (state["date"] or state["today"]).isoformat())
            request.GET = data
            state["display_date"] = parse_day(data.get("date"))
        return None

    def process_template_response(self, request, response):
        if not hasattr(request, "record_navigation") or not response.context_data:
            return response
        obj = response.context_data.get("object")
        child = obj if isinstance(obj, Child) else getattr(obj, "child", None)
        if getattr(getattr(obj, "_meta", None), "model_name", None) == "prescription":
            child = obj.visit.child
        if isinstance(child, Child):
            request.record_navigation["child"] = child
            if request.method == "GET":
                _remember(request, child=str(child.pk))
        return response


def navigation_context(request):
    if not hasattr(request, "record_navigation"):
        return {}
    state = request.record_navigation
    day = state.get("display_date", state["date"])
    hidden = [
        (name, value)
        for name, values in request.GET.lists()
        if name not in ("child", "date", "page", "next", "clear_filters")
        for value in values
    ]
    return {"record_context": {**state, "display_date": day, "hidden": hidden}}


class ReturnContextMixin:
    def get_success_url(self):
        return safe_return_url(self.request) or super().get_success_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get("form")
        child_field = form.fields.get("child") if form is not None else None
        if isinstance(child_field, forms.ModelChoiceField):
            # Keep the original field, choices, initial value and validation.
            # HTML's form attribute includes the header control in the POST
            # without navigating away or discarding an unfinished form.
            child_field.empty_label = _("Child")
            child_field.widget = forms.Select(
                attrs={
                    "form": "bb-record-form",
                    "class": "form-select",
                    "title": child_field.label,
                },
                choices=child_field.choices,
            )
            context["header_child_field"] = form["child"]
        return_url = safe_return_url(self.request)
        from core.presentation import submit_label

        context.setdefault(
            "submit_label",
            submit_label(
                getattr(self, "model", None),
                updating=bool(getattr(self, "object", None)),
            ),
        )
        fallback = getattr(self, "success_url", None)
        if not fallback and getattr(self, "route", None):
            fallback = reverse("core:" + self.route + "-list")
        context["return_url"] = return_url
        context["cancel_url"] = return_url or (
            contextual_url(self.request, fallback, remember_return=False)
            if fallback
            else reverse("dashboard:dashboard")
        )
        return context


def context_initial(view, initial):
    """Prefill dates only on new records; existing times and timer durations win."""
    state = navigation(view.request)
    day = state["date"]
    if not day or view.request.GET.get("timer"):
        return initial
    now = timezone.localtime()
    at_day = timezone.make_aware(datetime.combine(day, now.time().replace(tzinfo=None)))
    for name in ("date", "time", "start", "end"):
        try:
            field = view.model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        if isinstance(field, django_models.DateTimeField):
            initial.setdefault(name, at_day)
        elif isinstance(field, django_models.DateField):
            initial.setdefault(name, day)
    return initial

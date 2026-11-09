from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView, TemplateView
import django_filters

from babybuddy.mixins import PermissionRequiredMixin
from babybuddy.views import BabyBuddyFilterView, BabyBuddyPaginatedView
from core import models
from core.health_forms import (
    HealthVisitForm,
    PrescriptionForm,
    PrescriptionInlineFormSet,
    VaccinationForm,
)
from core.views import CoreAddView, CoreUpdateView, CoreDeleteView


class VisitFilter(django_filters.FilterSet):
    reason = django_filters.CharFilter(lookup_expr="icontains", label=_("Reason for visit"))

    class Meta:
        model = models.HealthVisit
        fields = ["child", "kind", "status", "reason"]


class VaccinationFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains", label=_("Vaccine"))

    class Meta:
        model = models.Vaccination
        fields = ["child", "status", "name"]


class PrescriptionFilter(django_filters.FilterSet):
    child = django_filters.ModelChoiceFilter(field_name="visit__child", queryset=models.Child.objects.all(), label=_("Child"))
    name = django_filters.CharFilter(lookup_expr="icontains", label=_("Medication Name"))

    class Meta:
        model = models.Prescription
        fields = ["child", "name"]


class HealthAccess(PermissionRequiredMixin):
    def has_permission(self):
        return any(self.request.user.has_perm("core.view_" + name) for name in (
            "healthvisit", "vaccination", "prescription", "medication", "weight",
            "height", "head_circumference", "bmi", "temperature",
        ))


class HealthOverview(HealthAccess, TemplateView):
    template_name = "core/health/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["children"] = models.Child.objects.all()
        child_id = self.request.GET.get("child")
        if child_id and not child_id.isdecimal():
            raise Http404
        child = get_object_or_404(models.Child, pk=child_id) if child_id else None
        context["selected_child"] = child
        today = timezone.localdate()
        def scoped(qs):
            return qs.filter(child=child) if child else qs
        if self.request.user.has_perm("core.view_healthvisit"):
            visits = scoped(models.HealthVisit.objects.select_related("child"))
            context["upcoming_visits"] = visits.filter(status="planned").order_by("date")[:8]
            context["recent_visits"] = visits.filter(status="completed").order_by("-date")[:5]
            context["follow_ups"] = visits.filter(status="completed", follow_up__gte=today).order_by("follow_up")[:5]
        if self.request.user.has_perm("core.view_vaccination"):
            vaccines = scoped(models.Vaccination.objects.select_related("child"))
            context["upcoming_vaccines"] = vaccines.filter(status="planned").order_by("date")[:8]
            context["next_vaccines"] = vaccines.filter(status="administered", next_date__gte=today).order_by("next_date")[:5]
        growth = []
        for baby in ([child] if child else context["children"]):
            measures = []
            for model in (models.Weight, models.Height, models.HeadCircumference):
                if self.request.user.has_perm("core.view_" + model._meta.model_name):
                    measurement = model.objects.filter(child=baby).order_by("-date", "-pk").first()
                    if measurement:
                        measures.append((model._meta.verbose_name, measurement.date))
            growth.append((baby, measures))
        context["growth_children"] = growth
        return context


class HealthRecordContext:
    route = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(title=self.model._meta.verbose_name_plural, route=self.route,
                       list_url=reverse("core:" + self.route + "-list"))
        user = self.request.user
        context["can_add"] = user.has_perm("core.add_" + self.model._meta.model_name)
        context["can_change"] = user.has_perm("core.change_" + self.model._meta.model_name)
        context["can_delete"] = user.has_perm("core.delete_" + self.model._meta.model_name)
        if self.route != "prescription":
            context["add_url"] = reverse("core:" + self.route + "-add")
        obj = getattr(self, "object", None)
        if obj:
            context["detail_url"] = reverse("core:" + self.route + "-detail", args=[obj.pk])
            context["update_url"] = reverse("core:" + self.route + "-update", args=[obj.pk])
            context["delete_url"] = reverse("core:" + self.route + "-delete", args=[obj.pk])
            context["details"] = [(field.verbose_name, getattr(obj, "get_" + field.name + "_display", lambda: getattr(obj, field.name))())
                                  for field in obj._meta.fields if field.name not in ("id", "visit")]
            if self.route == "visit":
                context["delete_blocked"] = obj.prescriptions.exists()
                if user.has_perm("core.view_prescription"):
                    context["prescriptions"] = obj.prescriptions.all()
        return context

    def get_success_url(self):
        return reverse("core:" + self.route + "-detail", args=[self.object.pk])


class RecordList(HealthRecordContext, PermissionRequiredMixin, BabyBuddyPaginatedView, BabyBuddyFilterView):
    template_name = "core/health/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["records"] = [{
            "object": obj, "child": obj.visit.child if self.route == "prescription" else obj.child,
            "date": obj.visit.date if self.route == "prescription" else obj.date,
            "url": reverse("core:" + self.route + "-detail", args=[obj.pk]),
        } for obj in context["object_list"]]
        return context


class VisitList(RecordList):
    model = models.HealthVisit
    route = "visit"
    permission_required = "core.view_healthvisit"
    filterset_class = VisitFilter
    queryset = models.HealthVisit.objects.select_related("child")


class VisitDetail(HealthRecordContext, PermissionRequiredMixin, DetailView):
    model = models.HealthVisit
    route = "visit"
    permission_required = "core.view_healthvisit"
    template_name = "core/health/detail.html"


class VisitAdd(HealthRecordContext, CoreAddView):
    model = models.HealthVisit
    route = "visit"
    permission_required = "core.add_healthvisit"
    form_class = HealthVisitForm
    template_name = "core/health/form.html"

    def get_prescription_formset(self, form=None):
        data = self.request.POST if "prescriptions-TOTAL_FORMS" in self.request.POST else None
        return PrescriptionInlineFormSet(
            data,
            instance=form.instance if form is not None else models.HealthVisit(),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["prescription_formset"] = self.get_prescription_formset(kwargs.get("form"))
        return context

    def form_valid(self, form):
        formset = self.get_prescription_formset(form)
        if formset.is_bound and not formset.is_valid():
            return self.form_invalid(form)
        response = super().form_valid(form)
        if formset.is_bound:
            formset.instance = self.object
            formset.save()
        return response


class VisitUpdate(HealthRecordContext, CoreUpdateView):
    model = models.HealthVisit
    route = "visit"
    permission_required = "core.change_healthvisit"
    form_class = HealthVisitForm
    template_name = "core/health/form.html"

    def get_prescription_formset(self, form=None):
        data = self.request.POST if "prescriptions-TOTAL_FORMS" in self.request.POST else None
        return PrescriptionInlineFormSet(
            data,
            instance=form.instance if form is not None else self.object,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["prescription_formset"] = self.get_prescription_formset(kwargs.get("form"))
        return context

    def form_valid(self, form):
        formset = self.get_prescription_formset(form)
        if formset.is_bound and not formset.is_valid():
            return self.form_invalid(form)
        response = super().form_valid(form)
        if formset.is_bound:
            formset.instance = self.object
            formset.save()
        return response


class RecordDelete(HealthRecordContext, CoreDeleteView):
    template_name = "core/health/confirm_delete.html"

    def get_success_url(self):
        return reverse("core:" + self.route + "-list")

class VisitDelete(RecordDelete):
    model = models.HealthVisit
    route = "visit"
    permission_required = "core.delete_healthvisit"

    def form_valid(self, form):
        if self.object.prescriptions.exists():
            return self.render_to_response(self.get_context_data(), status=409)
        return super().form_valid(form)


class VaccinationList(RecordList):
    model = models.Vaccination
    route = "vaccination"
    permission_required = "core.view_vaccination"
    filterset_class = VaccinationFilter
    queryset = models.Vaccination.objects.select_related("child")


class VaccinationDetail(HealthRecordContext, PermissionRequiredMixin, DetailView):
    model = models.Vaccination
    route = "vaccination"
    permission_required = "core.view_vaccination"
    template_name = "core/health/detail.html"


class VaccinationAdd(HealthRecordContext, CoreAddView):
    model = models.Vaccination
    route = "vaccination"
    permission_required = "core.add_vaccination"
    form_class = VaccinationForm
    template_name = "core/health/form.html"


class VaccinationUpdate(HealthRecordContext, CoreUpdateView):
    model = models.Vaccination
    route = "vaccination"
    permission_required = "core.change_vaccination"
    form_class = VaccinationForm
    template_name = "core/health/form.html"


class VaccinationDelete(RecordDelete):
    model = models.Vaccination
    route = "vaccination"
    permission_required = "core.delete_vaccination"


class PrescriptionList(RecordList):
    model = models.Prescription
    route = "prescription"
    permission_required = "core.view_prescription"
    filterset_class = PrescriptionFilter
    queryset = models.Prescription.objects.select_related("visit__child")


class PrescriptionDetail(HealthRecordContext, PermissionRequiredMixin, DetailView):
    model = models.Prescription
    route = "prescription"
    permission_required = "core.view_prescription"
    template_name = "core/health/detail.html"


class MedicationSuggestions:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        names = set()
        for model in (models.Medication, models.Prescription):
            if self.request.user.has_perm("core.view_" + model._meta.model_name):
                names.update(model.objects.values_list("name", flat=True))
        context["medication_names"] = sorted(names, key=str.casefold)
        return context


class PrescriptionAdd(MedicationSuggestions, HealthRecordContext, CoreAddView):
    model = models.Prescription
    route = "prescription"
    permission_required = ("core.add_prescription", "core.view_healthvisit")
    form_class = PrescriptionForm
    template_name = "core/health/form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.pop("child", None)
        kwargs.pop("timer", None)
        kwargs["instance"] = models.Prescription(visit=get_object_or_404(models.HealthVisit, pk=self.kwargs["visit_pk"]))
        return kwargs


class PrescriptionUpdate(MedicationSuggestions, HealthRecordContext, CoreUpdateView):
    model = models.Prescription
    route = "prescription"
    permission_required = "core.change_prescription"
    form_class = PrescriptionForm
    template_name = "core/health/form.html"


class PrescriptionDelete(RecordDelete):
    model = models.Prescription
    route = "prescription"
    permission_required = "core.delete_prescription"


class HealthPhotoView(PermissionRequiredMixin, View):
    def has_permission(self):
        self.photo = get_object_or_404(models.HealthPhoto, pk=self.kwargs["pk"])
        model = self.photo.owner._meta.model_name
        return any(self.request.user.has_perm("core." + action + "_" + model) for action in ("view", "change"))

    def get(self, request, *args, **kwargs):
        try:
            response = FileResponse(self.photo.image.open("rb"))
        except FileNotFoundError:
            raise Http404
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

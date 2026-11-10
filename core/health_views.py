from django.http import FileResponse, Http404
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from core.presentation import record_value
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView, TemplateView
import django_filters

from babybuddy.mixins import PermissionRequiredMixin
from babybuddy.views import BabyBuddyFilterView, BabyBuddyPaginatedView
from core import models
from core.medications import prescription_dose_url
from core.navigation import contextual_url, navigation, safe_return_url
from core.health_forms import (
    HealthVisitForm,
    PrescriptionForm,
    PrescriptionInlineFormSet,
    VaccinationForm,
)
from core.views import (
    CoreAddView,
    CoreUpdateView,
    CoreDeleteView,
    MedicationSuggestions,
)


class VisitFilter(django_filters.FilterSet):
    reason = django_filters.CharFilter(
        lookup_expr="icontains", label=_("Reason for visit")
    )

    class Meta:
        model = models.HealthVisit
        fields = ["child", "kind", "status", "reason"]


class VaccinationFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains", label=_("Vaccine"))

    class Meta:
        model = models.Vaccination
        fields = ["child", "status", "name"]


class PrescriptionFilter(django_filters.FilterSet):
    child = django_filters.ModelChoiceFilter(
        field_name="visit__child", queryset=models.Child.objects.all(), label=_("Child")
    )
    name = django_filters.CharFilter(
        lookup_expr="icontains", label=_("Medication Name")
    )

    class Meta:
        model = models.Prescription
        fields = ["child", "name"]


class HealthAccess(PermissionRequiredMixin):
    def has_permission(self):
        return any(
            self.request.user.has_perm("core.view_" + name)
            for name in (
                "healthvisit",
                "vaccination",
                "prescription",
                "medication",
                "weight",
                "height",
                "head_circumference",
                "bmi",
                "temperature",
            )
        )


class HealthOverview(HealthAccess, TemplateView):
    template_name = "core/health/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["children"] = models.Child.objects.all()
        child = navigation(self.request)["child"]
        context["selected_child"] = child
        today = timezone.localdate()

        def scoped(qs):
            return qs.filter(child=child) if child else qs

        if self.request.user.has_perm("core.view_healthvisit"):
            visits = scoped(models.HealthVisit.objects.select_related("child"))
            context["upcoming_visits"] = visits.filter(status="planned").order_by(
                "date"
            )[:8]
            context["recent_visits"] = visits.filter(status="completed").order_by(
                "-date"
            )[:5]
            context["follow_ups"] = visits.filter(
                status="completed", follow_up__gte=today
            ).order_by("follow_up")[:5]
        if self.request.user.has_perm("core.view_vaccination"):
            vaccines = scoped(models.Vaccination.objects.select_related("child"))
            context["upcoming_vaccines"] = vaccines.filter(status="planned").order_by(
                "date"
            )[:8]
            context["next_vaccines"] = vaccines.filter(
                status="administered", next_date__gte=today
            ).order_by("next_date")[:5]
        return context


class HealthRecordContext:
    route = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            title=self.model._meta.verbose_name_plural,
            route=self.route,
            list_url=contextual_url(
                self.request, "core:" + self.route + "-list", remember_return=False
            ),
        )
        user = self.request.user
        context["can_add"] = user.has_perm("core.add_" + self.model._meta.model_name)
        context["can_change"] = user.has_perm(
            "core.change_" + self.model._meta.model_name
        )
        context["can_delete"] = user.has_perm(
            "core.delete_" + self.model._meta.model_name
        )
        if self.route != "prescription":
            context["add_url"] = contextual_url(
                self.request, "core:" + self.route + "-add"
            )
        obj = getattr(self, "object", None)
        if obj:
            context["detail_url"] = contextual_url(
                self.request, "core:" + self.route + "-detail", obj.pk
            )
            context["update_url"] = contextual_url(
                self.request, "core:" + self.route + "-update", obj.pk
            )
            context["delete_url"] = contextual_url(
                self.request, "core:" + self.route + "-delete", obj.pk
            )
            context["details"] = [
                (
                    (
                        _("Person's name")
                        if field.name == "professional"
                        else field.verbose_name
                    ),
                    record_value(
                        getattr(
                            obj,
                            "get_" + field.name + "_display",
                            lambda: getattr(obj, field.name),
                        )()
                    ),
                )
                for field in obj._meta.fields
                if field.name not in ("id", "visit")
                and (field.name != "specialty" or obj.kind == "specialist")
            ]
            if self.route == "visit":
                context["delete_blocked"] = obj.prescriptions.exists()
                if user.has_perm("core.view_prescription"):
                    context["prescriptions"] = obj.prescriptions.all()
            if self.route == "prescription":
                if user.has_perm("core.add_medication"):
                    context["record_dose_url"] = prescription_dose_url(
                        self.request, obj
                    )
                if user.has_perm("core.view_medication"):
                    context["recent_doses"] = models.Medication.objects.filter(
                        child=obj.visit.child,
                        name__iexact=obj.name,
                    ).order_by("-time")[:5]
        context["return_url"] = safe_return_url(self.request)
        return context

    def get_success_url(self):
        return safe_return_url(self.request) or reverse(
            "core:" + self.route + "-detail", args=[self.object.pk]
        )


class RecordList(
    HealthRecordContext,
    PermissionRequiredMixin,
    BabyBuddyPaginatedView,
    BabyBuddyFilterView,
):
    template_name = "core/health/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["records"] = [
            {
                "object": obj,
                "child": obj.visit.child if self.route == "prescription" else obj.child,
                "date": obj.visit.date if self.route == "prescription" else obj.date,
                "url": contextual_url(
                    self.request, "core:" + self.route + "-detail", obj.pk
                ),
                "update_url": contextual_url(
                    self.request, "core:" + self.route + "-update", obj.pk
                ),
                "delete_url": contextual_url(
                    self.request, "core:" + self.route + "-delete", obj.pk
                ),
                "dose_url": (
                    prescription_dose_url(self.request, obj)
                    if self.route == "prescription"
                    and self.request.user.has_perm("core.add_medication")
                    else ""
                ),
            }
            for obj in context["object_list"]
        ]
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


class VisitPrescriptions:
    def get_prescription_formset(self, form=None):
        data = (
            self.request.POST
            if "prescriptions-TOTAL_FORMS" in self.request.POST
            else None
        )
        instance = form.instance if form is not None else getattr(self, "object", None)
        editable = self.request.user.has_perm("core.change_prescription")
        return PrescriptionInlineFormSet(
            data,
            files=self.request.FILES if data is not None else None,
            instance=instance or models.HealthVisit(),
            queryset=(
                models.Prescription.objects.prefetch_related("photos")
                if editable
                else models.Prescription.objects.none()
            ),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["prescription_formset"] = self.get_prescription_formset(
            kwargs.get("form")
        )
        context["can_add_prescription"] = self.request.user.has_perm(
            "core.add_prescription"
        )
        context["can_edit_prescription"] = self.request.user.has_perm(
            "core.change_prescription"
        )
        return context

    def form_valid(self, form):
        formset = self.get_prescription_formset(form)
        if formset.is_bound and formset.management_form.is_valid():
            allowed = (
                set(form.instance.prescriptions.values_list("pk", flat=True))
                if form.instance.pk
                else set()
            )
            for row in formset.forms:
                identity = row.data.get(row.add_prefix("id"))
                if identity:
                    if (
                        not self.request.user.has_perm("core.change_prescription")
                        or not identity.isdecimal()
                        or int(identity) not in allowed
                    ):
                        raise PermissionDenied
                elif row.has_changed() and not self.request.user.has_perm(
                    "core.add_prescription"
                ):
                    raise PermissionDenied
        if formset.is_bound and not formset.is_valid():
            return self.form_invalid(form)
        with transaction.atomic():
            response = super().form_valid(form)
            if formset.is_bound:
                formset.instance = self.object
                formset.save()
        return response


class VisitAdd(
    VisitPrescriptions, MedicationSuggestions, HealthRecordContext, CoreAddView
):
    model = models.HealthVisit
    route = "visit"
    permission_required = "core.add_healthvisit"
    form_class = HealthVisitForm
    template_name = "core/health/form.html"


class VisitUpdate(
    VisitPrescriptions, MedicationSuggestions, HealthRecordContext, CoreUpdateView
):
    model = models.HealthVisit
    route = "visit"
    permission_required = "core.change_healthvisit"
    form_class = HealthVisitForm
    template_name = "core/health/form.html"


class RecordDelete(HealthRecordContext, CoreDeleteView):
    template_name = "core/health/confirm_delete.html"

    def get_success_url(self):
        return safe_return_url(self.request) or reverse("core:" + self.route + "-list")


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
        kwargs["instance"] = models.Prescription(
            visit=get_object_or_404(models.HealthVisit, pk=self.kwargs["visit_pk"])
        )
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
        return any(
            self.request.user.has_perm("core." + action + "_" + model)
            for action in ("view", "change")
        )

    def get(self, request, *args, **kwargs):
        try:
            response = FileResponse(self.photo.image.open("rb"))
        except FileNotFoundError:
            raise Http404
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

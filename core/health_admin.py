from django.contrib import admin
from core import models


@admin.register(models.HealthVisit)
class HealthVisitAdmin(admin.ModelAdmin):
    list_display = ("child", "date", "kind", "status", "reason")
    list_filter = ("child", "kind", "status")
    search_fields = ("reason", "center", "assessment")


@admin.register(models.Vaccination)
class VaccinationAdmin(admin.ModelAdmin):
    list_display = ("child", "name", "dose", "date", "status")
    list_filter = ("child", "status")
    search_fields = ("name", "batch")


@admin.register(models.Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("name", "visit", "start_date", "end_date")
    list_filter = ("visit__child",)
    search_fields = ("name", "instructions")

"""Health records; existing measurements and administered doses remain independent."""
from uuid import uuid4
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class HealthVisit(models.Model):
    child = models.ForeignKey("core.Child", on_delete=models.CASCADE, verbose_name=_("Child"))
    date = models.DateTimeField(default=timezone.now, verbose_name=_("Date"))
    kind = models.CharField(max_length=20, choices=[
        ("checkup", _("Check-up")), ("illness", _("Illness")),
        ("emergency", _("Emergency visit")), ("specialist", _("Specialist")),
        ("other", _("Other")),
    ], default="checkup", verbose_name=_("Visit type"))
    status = models.CharField(max_length=16, choices=[
        ("planned", _("Scheduled")), ("completed", _("Completed")),
        ("cancelled", _("Cancelled")),
    ], default="planned", verbose_name=_("Status"))
    reason = models.CharField(max_length=255, verbose_name=_("Reason for visit"))
    center = models.CharField(max_length=255, blank=True, verbose_name=_("Medical center"))
    professional = models.CharField(max_length=255, blank=True, verbose_name=_("Professional"))
    symptoms = models.TextField(blank=True, verbose_name=_("Symptoms"))
    assessment = models.TextField(blank=True, verbose_name=_("What we were told / diagnosis"))
    tests = models.TextField(blank=True, verbose_name=_("Tests and results"))
    instructions = models.TextField(blank=True, verbose_name=_("Instructions and follow-up"))
    follow_up = models.DateField(blank=True, null=True, verbose_name=_("Follow-up date"))

    class Meta:
        ordering = ["-date", "-pk"]
        verbose_name = _("Medical visit")
        verbose_name_plural = _("Medical visits")

    def __str__(self):
        return self.reason

    def clean(self):
        super().clean()
        if self.date and self.status == "completed" and self.date > timezone.now():
            raise ValidationError({"date": _("A completed visit cannot be in the future.")})
        if self.date and self.follow_up and self.follow_up < timezone.localtime(self.date).date():
            raise ValidationError({"follow_up": _("Follow-up cannot precede the visit.")})


class Prescription(models.Model):
    visit = models.ForeignKey(HealthVisit, on_delete=models.CASCADE, related_name="prescriptions", verbose_name=_("Medical visit"))
    name = models.CharField(max_length=255, verbose_name=_("Medication Name"))
    instructions = models.TextField(verbose_name=_("Prescribed instructions"), help_text=_("Copy the dose, unit, frequency and route indicated by the professional."))
    start_date = models.DateField(blank=True, null=True, verbose_name=_("Start date"))
    end_date = models.DateField(blank=True, null=True, verbose_name=_("End date"))
    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    class Meta:
        ordering = ["-visit__date", "-pk"]
        verbose_name = _("Prescription")
        verbose_name_plural = _("Prescriptions")

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": _("End date cannot precede start date.")})


class Vaccination(models.Model):
    child = models.ForeignKey("core.Child", on_delete=models.CASCADE, verbose_name=_("Child"))
    name = models.CharField(max_length=255, verbose_name=_("Vaccine"))
    dose = models.CharField(max_length=100, blank=True, verbose_name=_("Vaccine dose"))
    date = models.DateField(default=timezone.localdate, verbose_name=_("Date"))
    status = models.CharField(max_length=16, choices=[
        ("planned", _("Scheduled")), ("administered", _("Administered")),
        ("cancelled", _("Cancelled")),
    ], default="planned", verbose_name=_("Status"))
    center = models.CharField(max_length=255, blank=True, verbose_name=_("Medical center"))
    batch = models.CharField(max_length=100, blank=True, verbose_name=_("Batch number"))
    next_date = models.DateField(blank=True, null=True, verbose_name=_("Next vaccination date"))
    notes = models.TextField(blank=True, verbose_name=_("Notes / reactions"))

    class Meta:
        ordering = ["-date", "-pk"]
        verbose_name = _("Vaccination")
        verbose_name_plural = _("Vaccinations")

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.date and self.status == "administered" and self.date > timezone.localdate():
            raise ValidationError({"date": _("An administered vaccine cannot be in the future.")})
        if self.date and self.next_date and self.next_date < self.date:
            raise ValidationError({"next_date": _("The next vaccination cannot precede this one.")})


def health_photo_path(instance, filename):
    return "health/photos/%s%s" % (uuid4().hex, Path(filename).suffix.lower())


class HealthPhoto(models.Model):
    visit = models.ForeignKey(HealthVisit, null=True, blank=True, on_delete=models.CASCADE, related_name="photos")
    prescription = models.ForeignKey(Prescription, null=True, blank=True, on_delete=models.CASCADE, related_name="photos")
    vaccination = models.ForeignKey(Vaccination, null=True, blank=True, on_delete=models.CASCADE, related_name="photos")
    medication = models.ForeignKey("core.Medication", null=True, blank=True, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=health_photo_path, verbose_name=_("Photo"))

    class Meta:
        ordering = ["pk"]
        default_permissions = ()
        constraints = [models.CheckConstraint(
            condition=(
                models.Q(visit__isnull=False, prescription__isnull=True, vaccination__isnull=True, medication__isnull=True)
                | models.Q(visit__isnull=True, prescription__isnull=False, vaccination__isnull=True, medication__isnull=True)
                | models.Q(visit__isnull=True, prescription__isnull=True, vaccination__isnull=False, medication__isnull=True)
                | models.Q(visit__isnull=True, prescription__isnull=True, vaccination__isnull=True, medication__isnull=False)
            ), name="health_photo_one_owner",
        )]

    def __str__(self):
        return str(_("Photo")) + " #" + str(self.pk)

    @property
    def owner(self):
        return self.visit or self.prescription or self.vaccination or self.medication


@receiver(post_delete, sender=HealthPhoto)
def remove_health_photo_file(sender, instance, **kwargs):
    if instance.image:
        storage, name = instance.image.storage, instance.image.name
        transaction.on_commit(lambda: storage.delete(name))

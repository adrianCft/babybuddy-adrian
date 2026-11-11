"""Health records; existing measurements and administered doses remain independent."""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class DosageUnit(models.TextChoices):
    MILLIGRAMS = "mg", _("MG")
    MILLILITERS = "ml", _("ML")
    GRAMS = "g", "g"
    TABLETS = "tablets", _("Tablets")
    DROPS = "drops", _("Drops")


class HealthVisit(models.Model):
    child = models.ForeignKey(
        "core.Child", on_delete=models.CASCADE, verbose_name=_("Child")
    )
    date = models.DateTimeField(default=timezone.now, verbose_name=_("Date"))
    kind = models.CharField(
        max_length=20,
        choices=[
            ("checkup", _("Check-up")),
            ("illness", _("Illness")),
            ("emergency", _("Emergency visit")),
            ("specialist", _("Specialist")),
            ("other", _("Other")),
        ],
        default="checkup",
        verbose_name=_("Visit type"),
    )
    specialty = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Specialty")
    )
    status = models.CharField(
        max_length=16,
        choices=[
            ("planned", _("Scheduled")),
            ("completed", _("Completed")),
            ("cancelled", _("Cancelled")),
        ],
        default="planned",
        verbose_name=_("Status"),
    )
    reason = models.CharField(max_length=255, verbose_name=_("Reason for visit"))
    center = models.CharField(
        max_length=255, blank=True, verbose_name=_("Medical center")
    )
    professional = models.CharField(
        max_length=255, blank=True, verbose_name=_("Professional")
    )
    symptoms = models.TextField(blank=True, verbose_name=_("Symptoms"))
    assessment = models.TextField(
        blank=True, verbose_name=_("What we were told / diagnosis")
    )
    tests = models.TextField(blank=True, verbose_name=_("Tests and results"))
    instructions = models.TextField(
        blank=True, verbose_name=_("Instructions and follow-up")
    )
    follow_up = models.DateField(
        blank=True, null=True, verbose_name=_("Follow-up date")
    )
    follow_up_time = models.TimeField(
        blank=True, null=True, verbose_name=_("Follow-up time")
    )
    follow_up_of = models.OneToOneField(
        "self",
        blank=True,
        null=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="follow_up_visit",
    )

    class Meta:
        ordering = ["-date", "-pk"]
        verbose_name = _("Medical visit")
        verbose_name_plural = _("Medical visits")

    def __str__(self):
        return self.reason

    @property
    def follow_up_datetime(self):
        if self.follow_up and self.follow_up_time is not None:
            return datetime.combine(self.follow_up, self.follow_up_time)
        return None

    def clean(self):
        super().clean()
        if self.date and self.status == "completed" and self.date > timezone.now():
            raise ValidationError(
                {"date": _("A completed visit cannot be in the future.")}
            )
        errors = {}
        if self.follow_up_time is not None and not self.follow_up:
            errors["follow_up"] = _("Enter a date for the follow-up time.")
        if self.date and self.follow_up:
            local_date = timezone.localtime(self.date).replace(tzinfo=None)
            if self.follow_up < local_date.date():
                errors["follow_up"] = _("Follow-up cannot precede the visit.")
            elif self.follow_up_datetime and self.follow_up_datetime < local_date:
                errors["follow_up_time"] = _("Follow-up cannot precede the visit.")
        if self.follow_up_of_id:
            if self.child_id != self.follow_up_of.child_id:
                errors["child"] = _("Linked visits must belong to the same child.")
            if self.date and self.date < self.follow_up_of.date:
                errors["date"] = _("Follow-up cannot precede the visit.")
        linked_visit = getattr(self, "follow_up_visit", None) if self.pk else None
        if linked_visit:
            if self.child_id != linked_visit.child_id:
                errors["child"] = _("Linked visits must belong to the same child.")
            if self.date and self.date > linked_visit.date:
                errors["date"] = _("This visit cannot be after its linked follow-up.")
        if errors:
            raise ValidationError(errors)


class Prescription(models.Model):
    visit = models.ForeignKey(
        HealthVisit,
        on_delete=models.CASCADE,
        related_name="prescriptions",
        verbose_name=_("Medical visit"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Medication Name"))
    dosage = models.FloatField(blank=True, null=True, verbose_name=_("Prescribed dose"))
    dosage_unit = models.CharField(
        max_length=20,
        choices=DosageUnit.choices,
        blank=True,
        null=True,
        verbose_name=_("Dosage Unit"),
    )
    instructions = models.TextField(
        verbose_name=_("Prescribed instructions"),
        help_text=_(
            "Copy the dose, unit, frequency and route indicated by the professional."
        ),
    )
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
        errors = {}
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = _("End date cannot precede start date.")
        if self.dosage is None and self.dosage_unit:
            errors["dosage"] = _("Enter the prescribed amount.")
        elif self.dosage is not None:
            if self.dosage <= 0:
                errors["dosage"] = _("Enter an amount greater than zero.")
            if not self.dosage_unit:
                errors["dosage_unit"] = _("Select the unit for this amount.")
        if errors:
            raise ValidationError(errors)


class Vaccination(models.Model):
    child = models.ForeignKey(
        "core.Child", on_delete=models.CASCADE, verbose_name=_("Child")
    )
    name = models.CharField(max_length=255, verbose_name=_("Vaccine"))
    dose = models.CharField(max_length=100, blank=True, verbose_name=_("Vaccine dose"))
    date = models.DateField(default=timezone.localdate, verbose_name=_("Date"))
    status = models.CharField(
        max_length=16,
        choices=[
            ("planned", _("Scheduled")),
            ("administered", _("Administered")),
            ("cancelled", _("Cancelled")),
        ],
        default="planned",
        verbose_name=_("Status"),
    )
    center = models.CharField(
        max_length=255, blank=True, verbose_name=_("Medical center")
    )
    batch = models.CharField(max_length=100, blank=True, verbose_name=_("Batch number"))
    next_date = models.DateField(
        blank=True, null=True, verbose_name=_("Next vaccination date")
    )
    notes = models.TextField(blank=True, verbose_name=_("Notes / reactions"))

    class Meta:
        ordering = ["-date", "-pk"]
        verbose_name = _("Vaccination")
        verbose_name_plural = _("Vaccinations")

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if (
            self.date
            and self.status == "administered"
            and self.date > timezone.localdate()
        ):
            raise ValidationError(
                {"date": _("An administered vaccine cannot be in the future.")}
            )
        if self.date and self.next_date and self.next_date < self.date:
            raise ValidationError(
                {"next_date": _("The next vaccination cannot precede this one.")}
            )


def health_photo_path(instance, filename):
    return "health/photos/%s%s" % (uuid4().hex, Path(filename).suffix.lower())


class HealthPhoto(models.Model):
    visit = models.ForeignKey(
        HealthVisit,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    prescription = models.ForeignKey(
        Prescription,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    vaccination = models.ForeignKey(
        Vaccination,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    medication = models.ForeignKey(
        "core.Medication",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    image = models.ImageField(upload_to=health_photo_path, verbose_name=_("Photo"))

    class Meta:
        ordering = ["pk"]
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        visit__isnull=False,
                        prescription__isnull=True,
                        vaccination__isnull=True,
                        medication__isnull=True,
                    )
                    | models.Q(
                        visit__isnull=True,
                        prescription__isnull=False,
                        vaccination__isnull=True,
                        medication__isnull=True,
                    )
                    | models.Q(
                        visit__isnull=True,
                        prescription__isnull=True,
                        vaccination__isnull=False,
                        medication__isnull=True,
                    )
                    | models.Q(
                        visit__isnull=True,
                        prescription__isnull=True,
                        vaccination__isnull=True,
                        medication__isnull=False,
                    )
                ),
                name="health_photo_one_owner",
            )
        ]

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

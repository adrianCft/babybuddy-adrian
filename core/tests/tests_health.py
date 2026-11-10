import io
from datetime import timedelta

from PIL import Image
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import models
from core.health_forms import VaccinationForm, HealthVisitForm, PrescriptionForm


def photo(name="photo.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class HealthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="health-user")
        cls.child = models.Child.objects.create(
            first_name="Test", birth_date=timezone.localdate() - timedelta(days=200)
        )
        cls.visit = models.HealthVisit.objects.create(
            child=cls.child,
            reason="Revisión",
            date=timezone.now() - timedelta(hours=1),
            status="completed",
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.override = override_settings(
            STORAGES={
                **settings.STORAGES,
                "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            }
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

    def grant(self, *permissions):
        self.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core", codename__in=permissions
            )
        )

    def vaccine_data(self, **kwargs):
        return {
            "child": self.child.pk,
            "name": "Vacuna de prueba",
            "date": timezone.localdate(),
            "status": "administered",
            **kwargs,
        }

    def test_permissions_cover_lists_mutations_and_photos(self):
        for name in (
            "health-overview",
            "visit-list",
            "vaccination-list",
            "prescription-list",
            "visit-add",
            "vaccination-add",
        ):
            self.assertEqual(
                self.client.get(reverse("core:" + name)).status_code, 403, name
            )
        self.assertEqual(
            self.client.post(
                reverse("core:visit-delete", args=[self.visit.pk])
            ).status_code,
            403,
        )
        attachment = models.HealthPhoto.objects.create(visit=self.visit, image=photo())
        url = reverse("core:health-photo", args=[attachment.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant("view_healthvisit")
        self.assertEqual(
            self.client.get(
                reverse("core:visit-detail", args=[self.visit.pk])
            ).status_code,
            200,
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        response.close()
        self.assertEqual(
            self.client.post(
                reverse("core:visit-delete", args=[self.visit.pk])
            ).status_code,
            403,
        )

    def test_vaccination_create_edit_remove_photos_and_delete(self):
        self.grant(
            "add_vaccination",
            "view_vaccination",
            "change_vaccination",
            "delete_vaccination",
        )
        response = self.client.post(
            reverse("core:vaccination-add"),
            self.vaccine_data(photos=[photo(), photo("second.png")]),
        )
        self.assertEqual(response.status_code, 302)
        vaccination = models.Vaccination.objects.get()
        self.assertEqual(vaccination.photos.count(), 2)
        for name in (
            "vaccination-list",
            "vaccination-detail",
            "vaccination-update",
            "vaccination-delete",
        ):
            args = [] if name.endswith("list") else [vaccination.pk]
            self.assertEqual(
                self.client.get(reverse("core:" + name, args=args)).status_code,
                200,
                name,
            )
        removed = vaccination.photos.first()
        kept = vaccination.photos.last()
        removed_path = removed.image.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("core:vaccination-update", args=[vaccination.pk]),
                self.vaccine_data(remove_photos=[removed.pk]),
            )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(removed.image.storage.exists(removed_path))
        self.assertTrue(vaccination.photos.filter(pk=kept.pk).exists())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("core:vaccination-delete", args=[vaccination.pk])
            )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(models.Vaccination.objects.exists())
        self.assertFalse(kept.image.storage.exists(kept.image.name))

    def test_visit_can_be_scheduled_completed_and_deleted(self):
        self.grant(
            "add_healthvisit",
            "view_healthvisit",
            "change_healthvisit",
            "delete_healthvisit",
        )
        data = {
            "child": self.child.pk,
            "date": timezone.now() + timedelta(days=1),
            "kind": "checkup",
            "status": "planned",
            "reason": "Nueva revisión",
        }
        response = self.client.post(reverse("core:visit-add"), data)
        self.assertEqual(response.status_code, 302)
        visit = models.HealthVisit.objects.get(reason="Nueva revisión")
        data.update(
            date=timezone.now() - timedelta(hours=1),
            status="completed",
            assessment="Informe de la consulta",
            instructions="Revisión posterior",
            photos=[photo()],
        )
        response = self.client.post(reverse("core:visit-update", args=[visit.pk]), data)
        self.assertEqual(response.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.assessment, "Informe de la consulta")
        self.assertEqual(visit.status, "completed")
        self.assertEqual(visit.photos.count(), 1)
        self.assertEqual(
            self.client.post(reverse("core:visit-delete", args=[visit.pk])).status_code,
            302,
        )
        self.assertFalse(models.HealthVisit.objects.filter(pk=visit.pk).exists())

    def test_visit_saves_person_and_specialty_and_preserves_previous_names(self):
        self.grant("add_healthvisit", "view_healthvisit", "change_healthvisit")
        data = {
            "child": self.child.pk,
            "date": timezone.now() - timedelta(hours=1),
            "kind": "specialist",
            "status": "completed",
            "reason": "Consulta de ejemplo",
            "professional": "Persona de prueba",
            "specialty": "Dermatología",
        }
        response = self.client.post(reverse("core:visit-add"), data)
        self.assertEqual(response.status_code, 302)
        visit = models.HealthVisit.objects.get(reason=data["reason"])
        self.assertEqual(visit.professional, "Persona de prueba")
        self.assertEqual(visit.specialty, "Dermatología")
        response = self.client.get(reverse("core:visit-detail", args=[visit.pk]))
        self.assertContains(response, "Persona de prueba")
        self.assertContains(response, "Dermatología")

        # Old professional names reappear under the new label without rewriting them.
        self.visit.professional = "Nombre anterior"
        self.visit.save()
        response = self.client.get(reverse("core:visit-update", args=[self.visit.pk]))
        self.assertEqual(
            response.context["form"]["professional"].value(), "Nombre anterior"
        )
        self.assertFalse(response.context["form"].fields["professional"].required)
        self.assertFalse(response.context["form"].fields["specialty"].required)

        data.update(kind="checkup", reason="Revisión de ejemplo")
        response = self.client.post(reverse("core:visit-update", args=[visit.pk]), data)
        self.assertEqual(response.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.professional, "Persona de prueba")
        self.assertEqual(visit.specialty, "Dermatología")

    def test_visit_form_saves_prescribed_medication(self):
        self.grant("add_healthvisit", "view_healthvisit", "add_prescription")
        response = self.client.post(
            reverse("core:visit-add"),
            {
                "child": self.child.pk,
                "date": timezone.now() - timedelta(hours=1),
                "kind": "illness",
                "status": "completed",
                "reason": "Resfriado",
                "prescriptions-TOTAL_FORMS": "1",
                "prescriptions-INITIAL_FORMS": "0",
                "prescriptions-MIN_NUM_FORMS": "0",
                "prescriptions-MAX_NUM_FORMS": "1000",
                "prescriptions-0-name": "Jarabe",
                "prescriptions-0-instructions": "5 ml cada 8 horas",
                "prescriptions-0-start_date": timezone.localdate(),
            },
        )
        self.assertEqual(response.status_code, 302)
        visit = models.HealthVisit.objects.get(reason="Resfriado")
        prescription = visit.prescriptions.get()
        self.assertEqual(prescription.name, "Jarabe")
        self.assertEqual(prescription.instructions, "5 ml cada 8 horas")

    def test_multiple_prescriptions_validate_before_saving_the_visit(self):
        self.grant("add_healthvisit", "view_healthvisit", "add_prescription")
        data = {
            "child": self.child.pk,
            "date": timezone.now() - timedelta(hours=1),
            "kind": "checkup",
            "status": "completed",
            "reason": "Visita con dos recetas",
            "prescriptions-TOTAL_FORMS": "2",
            "prescriptions-INITIAL_FORMS": "0",
            "prescriptions-MIN_NUM_FORMS": "0",
            "prescriptions-MAX_NUM_FORMS": "1000",
            "prescriptions-0-name": "Primero",
            "prescriptions-0-instructions": "Pauta indicada",
            "prescriptions-1-name": "Segundo",
            "prescriptions-1-instructions": "",
        }
        response = self.client.post(reverse("core:visit-add"), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            models.HealthVisit.objects.filter(reason=data["reason"]).exists()
        )
        self.assertFalse(models.Prescription.objects.exists())
        self.assertIn(
            "instructions", response.context["prescription_formset"].forms[1].errors
        )

        data["prescriptions-1-instructions"] = "Otra pauta indicada"
        response = self.client.post(reverse("core:visit-add"), data)
        self.assertEqual(response.status_code, 302)
        visit = models.HealthVisit.objects.get(reason=data["reason"])
        self.assertEqual(
            set(visit.prescriptions.values_list("name", flat=True)),
            {"Primero", "Segundo"},
        )

    def test_invalid_uploads_and_other_records_photos_are_rejected(self):
        self.grant("add_vaccination", "change_vaccination")
        url = reverse("core:vaccination-add")
        bad = SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
        self.assertEqual(
            self.client.post(url, self.vaccine_data(photos=[photo(), bad])).status_code,
            200,
        )
        self.assertFalse(models.Vaccination.objects.exists())
        vaccination = models.Vaccination.objects.create(
            **{**self.vaccine_data(), "child": self.child}
        )
        other = models.HealthPhoto.objects.create(visit=self.visit, image=photo())
        response = self.client.post(
            reverse("core:vaccination-update", args=[vaccination.pk]),
            self.vaccine_data(remove_photos=[other.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(models.HealthPhoto.objects.filter(pk=other.pk).exists())

    def test_prescription_is_not_a_dose_and_cannot_reassign_visit(self):
        self.grant(
            "add_prescription",
            "view_healthvisit",
            "view_prescription",
            "change_prescription",
            "delete_prescription",
            "delete_healthvisit",
        )
        data = {
            "name": "Medicación de prueba",
            "instructions": "Según receta",
            "photos": [photo()],
            "visit": 999999,
        }
        response = self.client.post(
            reverse("core:prescription-add", args=[self.visit.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        prescription = models.Prescription.objects.get()
        self.assertEqual(prescription.visit, self.visit)
        self.assertEqual(prescription.photos.count(), 1)
        self.assertFalse(models.Medication.objects.exists())
        for name in (
            "prescription-list",
            "prescription-detail",
            "prescription-update",
            "prescription-delete",
        ):
            args = [] if name.endswith("list") else [prescription.pk]
            self.assertEqual(
                self.client.get(reverse("core:" + name, args=args)).status_code, 200
            )
        self.assertEqual(
            self.client.post(
                reverse("core:visit-delete", args=[self.visit.pk])
            ).status_code,
            409,
        )
        self.assertTrue(models.Prescription.objects.exists())

    def test_dates_validate_completed_and_scheduled_records(self):
        future = timezone.localdate() + timedelta(days=7)
        self.assertFalse(
            VaccinationForm(data=self.vaccine_data(date=future)).is_valid()
        )
        self.assertTrue(
            VaccinationForm(
                data=self.vaccine_data(date=future, status="planned")
            ).is_valid()
        )
        self.assertFalse(
            VaccinationForm(
                data=self.vaccine_data(
                    next_date=timezone.localdate() - timedelta(days=1)
                )
            ).is_valid()
        )
        form = HealthVisitForm(
            data={
                "child": self.child.pk,
                "reason": "Revisión",
                "kind": "checkup",
                "date": timezone.now() + timedelta(days=7),
                "status": "completed",
            }
        )
        self.assertFalse(form.is_valid())
        form = PrescriptionForm(
            data={
                "name": "Prueba",
                "instructions": "Según receta",
                "start_date": future,
                "end_date": timezone.localdate(),
            }
        )
        self.assertFalse(form.is_valid())

    def test_existing_medication_accepts_photos_without_changing_dose(self):
        self.grant("change_medication", "view_medication")
        dose = models.Medication.objects.create(
            child=self.child,
            name="Registrado",
            dosage=2,
            dosage_unit="ml",
            time=timezone.now() - timedelta(hours=1),
        )
        response = self.client.post(
            reverse("core:medication-update", args=[dose.pk]),
            {
                "child": self.child.pk,
                "name": dose.name,
                "dosage": 2,
                "dosage_unit": "ml",
                "time": dose.time,
                "photos": [photo()],
            },
        )
        self.assertEqual(response.status_code, 302)
        dose.refresh_from_db()
        self.assertEqual(dose.dosage, 2)
        self.assertEqual(dose.photos.count(), 1)
        self.assertEqual(models.Medication.objects.count(), 1)
        self.assertEqual(
            self.client.get(reverse("core:medication-list")).status_code, 200
        )

    def test_overview_filters_children_and_respects_permissions(self):
        self.grant("view_healthvisit", "view_weight")
        other = models.Child.objects.create(
            first_name="Other", birth_date=timezone.localdate()
        )
        models.HealthVisit.objects.create(child=other, reason="Other private visit")
        models.Weight.objects.create(
            child=self.child, weight=7, date=timezone.localdate()
        )
        response = self.client.get(
            reverse("core:health-overview"), {"child": self.child.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.visit.reason)
        self.assertNotContains(response, "Other private visit")
        self.assertNotContains(response, 'id="growth"')
        self.assertNotContains(response, "/health/#growth")
        self.assertNotContains(response, reverse("core:vaccination-list"))

    def test_upload_setting_is_respected(self):
        with override_settings(
            BABY_BUDDY={**settings.BABY_BUDDY, "ALLOW_UPLOADS": False}
        ):
            self.assertNotIn("photos", VaccinationForm().fields)

    def test_explicit_child_deletion_still_cascades_to_health_records(self):
        prescription = models.Prescription.objects.create(
            visit=self.visit, name="Prueba", instructions="Según receta"
        )
        attachment = models.HealthPhoto.objects.create(
            prescription=prescription, image=photo()
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.child.delete()
        self.assertFalse(models.HealthVisit.objects.exists())
        self.assertFalse(models.Prescription.objects.exists())
        self.assertFalse(attachment.image.storage.exists(attachment.image.name))

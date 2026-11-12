from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import models
from core.tests.tests_health import photo


class MedicationWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="medication-workflow")
        cls.child = models.Child.objects.create(
            first_name="Ana", birth_date=timezone.localdate() - timedelta(days=200)
        )
        cls.other_child = models.Child.objects.create(
            first_name="Luis", birth_date=cls.child.birth_date
        )
        cls.visit = models.HealthVisit.objects.create(
            child=cls.child, reason="Revisión", date=timezone.now() - timedelta(hours=1)
        )
        cls.other_visit = models.HealthVisit.objects.create(
            child=cls.other_child, reason="Otra revisión"
        )
        cls.prescription = models.Prescription.objects.create(
            visit=cls.visit,
            name="Medicamento de prueba",
            instructions="Pauta copiada del profesional",
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.storage = override_settings(
            STORAGES={
                **settings.STORAGES,
                "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            }
        )
        self.storage.enable()
        self.addCleanup(self.storage.disable)

    def grant(self, *permissions):
        self.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core", codename__in=permissions
            )
        )

    def source_url(self):
        return (
            reverse("core:medication-add")
            + "?"
            + urlencode({"prescription": self.prescription.pk})
        )

    def visit_data(self):
        return {
            "child": self.child.pk,
            "date": timezone.now() - timedelta(hours=1),
            "kind": "checkup",
            "status": "completed",
            "reason": "Visita con fotos de receta",
            "prescriptions-TOTAL_FORMS": "1",
            "prescriptions-INITIAL_FORMS": "0",
            "prescriptions-MIN_NUM_FORMS": "0",
            "prescriptions-MAX_NUM_FORMS": "1000",
            "prescriptions-0-name": "Nuevo medicamento",
            "prescriptions-0-instructions": "Pauta indicada",
        }

    def test_legacy_prescription_prefills_identity_and_never_creates_a_dose_on_get(
        self,
    ):
        self.grant("view_prescription", "add_medication")
        detail = self.client.get(
            reverse("core:prescription-detail", args=[self.prescription.pk])
        )
        link = detail.context["record_dose_url"]
        self.assertEqual(
            parse_qs(urlsplit(link).query)["prescription"], [str(self.prescription.pk)]
        )
        response = self.client.get(link)
        form = response.context["form"]
        self.assertEqual(form["name"].value(), self.prescription.name)
        self.assertEqual(form["child"].value(), self.child.pk)
        self.assertIsNone(form["dosage"].value())
        self.assertEqual(form["dosage_unit"].value(), "")
        self.assertTrue(form.fields["dosage"].required)
        self.assertEqual(models.Medication.objects.count(), 0)

    def test_recording_from_prescription_requires_amount_unit_and_confirmation(self):
        self.grant("view_prescription", "add_medication")
        url = self.source_url()
        before = models.Medication.objects.count()
        response = self.client.post(
            url, {"time": timezone.now() - timedelta(minutes=2)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("dosage", response.context["form"].errors)
        self.assertIn("dosage_unit", response.context["form"].errors)
        self.assertEqual(models.Medication.objects.count(), before)
        response = self.client.post(
            url,
            {
                "time": timezone.now() - timedelta(minutes=2),
                "dosage": 2,
                "dosage_unit": "ml",
                # An altered form cannot silently attribute this prescription to another child.
                "child": self.other_child.pk,
                "name": "Altered name",
            },
        )
        self.assertEqual(response.status_code, 302)
        dose = models.Medication.objects.get()
        self.assertEqual(dose.child, self.child)
        self.assertEqual(dose.name, self.prescription.name)
        self.assertEqual(dose.dosage, 2)
        self.assertEqual(dose.dosage_unit, "ml")

    def test_prescription_prefill_requires_read_permission_on_get_and_post(self):
        self.grant("add_medication")
        self.assertEqual(self.client.get(self.source_url()).status_code, 403)
        self.assertEqual(
            self.client.post(self.source_url(), {"child": self.child.pk}).status_code,
            403,
        )
        self.assertFalse(models.Medication.objects.exists())

    def test_saved_prescription_prefills_an_editable_amount_and_unit(self):
        self.grant(
            "add_prescription",
            "view_healthvisit",
            "view_prescription",
            "add_medication",
        )
        url = reverse("core:prescription-add", args=[self.visit.pk])
        data = {
            "name": "Medicación con dosis",
            "instructions": "Pauta",
            "dosage": "0.5",
            "interval_hours": "6.5",
        }
        invalid = self.client.post(url, data)
        self.assertIn("dosage_unit", invalid.context["form"].errors)
        self.assertFalse(models.Prescription.objects.filter(name=data["name"]).exists())
        data["dosage_unit"] = "g"
        self.assertEqual(self.client.post(url, data).status_code, 302)
        prescription = models.Prescription.objects.get(name=data["name"])
        self.assertEqual((prescription.dosage, prescription.dosage_unit), (0.5, "g"))

        dose_url = reverse("core:medication-add") + f"?prescription={prescription.pk}"
        response = self.client.get(dose_url)
        form = response.context["form"]
        self.assertEqual(
            (form["dosage"].value(), form["dosage_unit"].value()), (0.5, "g")
        )
        self.assertEqual(form["next_dose_interval"].value(), Decimal("6.5"))
        self.assertFalse(models.Medication.objects.exists())
        response = self.client.post(
            dose_url,
            {
                "time": timezone.now() - timedelta(minutes=2),
                "dosage": "0.25",
                "next_dose_interval": "8",
                "dosage_unit": "ml",
            },
        )
        self.assertEqual(response.status_code, 302)
        dose = models.Medication.objects.get()
        self.assertEqual((dose.dosage, dose.dosage_unit), (0.25, "ml"))
        self.assertEqual(dose.next_dose_interval, timedelta(hours=8))
        prescription.refresh_from_db()
        self.assertEqual(prescription.interval_hours, Decimal("6.5"))
        self.assertEqual((prescription.dosage, prescription.dosage_unit), (0.5, "g"))

    def test_suggestions_and_free_text_both_work(self):
        self.grant("add_medication", "view_medication", "view_prescription")
        models.Medication.objects.create(child=self.child, name="Usado anteriormente")
        response = self.client.get(reverse("core:medication-add"))
        self.assertIn(self.prescription.name, response.context["medication_names"])
        self.assertIn("Usado anteriormente", response.context["medication_names"])
        self.assertContains(response, "data-medication-choice")
        response = self.client.post(
            reverse("core:medication-add"),
            {
                "child": self.child.pk,
                "name": "Nombre completamente nuevo",
                "dosage": 1,
                "dosage_unit": "ml",
                "time": timezone.now() - timedelta(minutes=2),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            models.Medication.objects.filter(name="Nombre completamente nuevo").exists()
        )

    def test_dose_suggestions_are_scoped_by_child_date_and_permission(self):
        self.grant("add_medication", "view_medication", "view_prescription")
        self.prescription.interval_hours = Decimal("6.5")
        self.prescription.dosage = 2.5
        self.prescription.dosage_unit = "ml"
        self.prescription.save()
        today = timezone.localdate()
        models.Prescription.objects.create(
            visit=self.visit,
            name="Receta caducada",
            instructions="Pauta antigua",
            dosage=9,
            dosage_unit="g",
            end_date=today - timedelta(days=1),
        )
        models.Medication.objects.create(
            child=self.child,
            name=self.prescription.name.lower(),
            dosage=1,
            dosage_unit="ml",
        )
        models.Medication.objects.create(
            child=self.other_child,
            name=self.prescription.name,
            dosage=3,
            dosage_unit="drops",
            next_dose_interval=timedelta(hours=4),
        )
        for dosage, minutes in ((4, 4), (5, 2)):
            models.Medication.objects.create(
                child=self.child,
                name="Medicación del historial",
                dosage=dosage,
                dosage_unit="mg",
                time=timezone.now() - timedelta(minutes=minutes),
            )
        url = reverse("core:medication-add")
        response = self.client.get(url)
        doses = response.context["dose_suggestions"]["children"]
        self.assertEqual(
            doses[self.child.pk][self.prescription.name],
            (2.5, "ml", "prescription", Decimal("6.5")),
        )
        self.assertEqual(
            doses[self.child.pk][self.prescription.name.lower()],
            (2.5, "ml", "prescription", Decimal("6.5")),
        )
        self.assertEqual(
            doses[self.other_child.pk][self.prescription.name],
            (3, "drops", "history", 4),
        )
        self.assertEqual(
            doses[self.child.pk]["Medicación del historial"], (5, "mg", "history", None)
        )
        self.assertNotIn("Receta caducada", doses[self.child.pk])
        self.user.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="core", codename="view_prescription"
            )
        )
        doses = self.client.get(url).context["dose_suggestions"]["children"]
        self.assertEqual(
            doses[self.child.pk][self.prescription.name.lower()],
            (1, "ml", "history", None),
        )
        self.assertNotIn("Receta caducada", doses[self.child.pk])

    def test_incomplete_or_conflicting_prescription_leaves_dose_unspecified(self):
        self.grant("add_medication", "view_medication", "view_prescription")
        models.Medication.objects.create(
            child=self.child, name=self.prescription.name, dosage=1, dosage_unit="ml"
        )
        url = reverse("core:medication-add")
        self.assertEqual(
            self.client.get(url).context["dose_suggestions"]["children"], {}
        )
        self.prescription.dosage = 2
        self.prescription.dosage_unit = "ml"
        self.prescription.save()
        models.Prescription.objects.create(
            visit=self.visit,
            name=self.prescription.name,
            instructions="Otra pauta",
            dosage=3,
            dosage_unit="ml",
        )
        self.assertEqual(
            self.client.get(url).context["dose_suggestions"]["children"], {}
        )

    def test_recent_doses_are_scoped_to_child_and_medication_and_permissions(self):
        self.grant("view_prescription", "view_medication")
        own = models.Medication.objects.create(
            child=self.child, name=self.prescription.name
        )
        models.Medication.objects.create(
            child=self.other_child, name=self.prescription.name
        )
        models.Medication.objects.create(child=self.child, name="Otro medicamento")
        response = self.client.get(
            reverse("core:prescription-detail", args=[self.prescription.pk])
        )
        self.assertEqual(list(response.context["recent_doses"]), [own])
        self.assertNotIn("record_dose_url", response.context)

    def test_inline_prescription_photos_are_saved_with_the_right_owner(self):
        self.grant("add_healthvisit", "add_prescription")
        data = self.visit_data()
        data.update(
            {
                "photos": [photo("visit.png")],
                "prescriptions-0-photos": [photo("recipe.png"), photo("box.png")],
                "prescriptions-0-dosage": "2.5",
                "prescriptions-0-dosage_unit": "ml",
            }
        )
        response = self.client.post(reverse("core:visit-add"), data)
        self.assertEqual(response.status_code, 302)
        visit = models.HealthVisit.objects.get(reason=data["reason"])
        prescription = visit.prescriptions.get()
        self.assertEqual(visit.photos.count(), 1)
        self.assertEqual((prescription.dosage, prescription.dosage_unit), (2.5, "ml"))
        self.assertEqual(prescription.photos.count(), 2)
        self.assertTrue(all(p.visit_id is None for p in prescription.photos.all()))
        self.assertFalse(models.Medication.objects.exists())

    def test_invalid_inline_photo_does_not_save_visit_or_other_prescriptions(self):
        self.grant("add_healthvisit", "add_prescription")
        data = self.visit_data()
        data["prescriptions-0-photos"] = [
            SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
        ]
        response = self.client.post(reverse("core:visit-add"), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "photos", response.context["prescription_formset"].forms[0].errors
        )
        self.assertFalse(
            models.HealthVisit.objects.filter(reason=data["reason"]).exists()
        )
        self.assertFalse(
            models.Prescription.objects.filter(
                name=data["prescriptions-0-name"]
            ).exists()
        )

    def test_inline_editing_cannot_mutate_another_visit_or_bypass_permissions(self):
        self.grant("change_healthvisit")
        data = self.visit_data()
        data.update(
            {
                "prescriptions-INITIAL_FORMS": "1",
                "prescriptions-0-id": str(self.prescription.pk),
            }
        )
        url = reverse("core:visit-update", args=[self.visit.pk])
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.prescription.refresh_from_db()
        self.assertEqual(self.prescription.name, "Medicamento de prueba")
        self.grant("change_prescription")
        url = reverse("core:visit-update", args=[self.other_visit.pk])
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.prescription.refresh_from_db()
        self.assertEqual(self.prescription.visit, self.visit)

    def test_inline_photos_respect_the_upload_setting(self):
        from core.health_forms import PrescriptionInlineForm

        with override_settings(
            BABY_BUDDY={**settings.BABY_BUDDY, "ALLOW_UPLOADS": False}
        ):
            self.assertNotIn("photos", PrescriptionInlineForm().fields)

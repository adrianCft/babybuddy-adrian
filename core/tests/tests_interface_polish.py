from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from PIL import Image
import io

from core import models
from core.health_forms import VaccinationForm


class InterfacePolishTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            "interface-owner", is_superuser=True
        )
        cls.user.settings.language = "es"
        cls.user.settings.timezone = "Europe/Madrid"
        cls.user.settings.save()
        cls.child = models.Child.objects.create(
            first_name="Lucía", birth_date=date(2026, 1, 1)
        )
        cls.visit = models.HealthVisit.objects.create(
            child=cls.child, reason="Revisión", status="completed"
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_filter_chips_show_labels_and_individual_removal_keeps_other_filters(self):
        url = reverse("core:visit-list")
        response = self.client.get(
            url,
            {
                "child": self.child.pk,
                "status": "completed",
                "kind": "checkup",
                "filtered": "1",
            },
        )
        chips = {c["name"]: c for c in response.context["active_filters"]}
        self.assertEqual(chips["child"]["value"], str(self.child))
        self.assertNotEqual(chips["status"]["value"], "completed")
        self.assertContains(response, 'data-filter-chip="status"')
        response = self.client.get(chips["status"]["remove_url"])
        self.assertEqual(response.context["filter"].form["status"].value(), "")
        self.assertEqual(response.context["filter"].form["kind"].value(), "checkup")
        self.assertEqual(response.context["record_context"]["child"], self.child)
        response = self.client.get(response.context["clear_filters_url"])
        self.assertEqual(response.context["active_filters"], [])
        self.assertIsNone(response.context["record_context"]["child"])
        self.assertIsNone(response.context["record_context"]["date"])
        self.assertEqual(models.HealthVisit.objects.get().reason, "Revisión")

    def test_empty_state_distinguishes_empty_records_from_filtered_results(self):
        url = reverse("core:vaccination-list")
        response = self.client.get(url, {"child": "", "date": ""})
        self.assertEqual(response.context["empty_message"], "Todavía no hay registros.")
        models.Vaccination.objects.create(
            child=self.child, name="Vacuna ya registrada", status="administered"
        )
        response = self.client.get(url, {"child": "", "date": "", "status": "planned"})
        self.assertEqual(
            response.context["empty_message"], "No hay resultados con estos filtros."
        )
        self.assertContains(response, "No hay resultados con estos filtros.", count=2)

    def test_false_boolean_filter_is_active_and_text_inputs_use_text_styles(self):
        response = self.client.get(
            reverse("core:food-list"), {"active": "false", "name": "Prueba"}
        )
        self.assertIn("active", {c["name"] for c in response.context["active_filters"]})
        from html.parser import HTMLParser

        fields = {}

        class Inputs(HTMLParser):
            def handle_starttag(self, tag, attrs):
                data = dict(attrs)
                if tag == "input" and data.get("name") == "name":
                    fields.update(data)

        Inputs().feed(response.content.decode())
        self.assertIn("form-control", fields["class"])
        self.assertNotIn("form-select", fields["class"])

    def test_form_actions_have_contextual_save_labels(self):
        for route, label in [
            ("visit-add", "Guardar visita"),
            ("vaccination-add", "Guardar vacuna"),
            ("meal-add", "Guardar comida"),
            ("medication-add", "Registrar una toma"),
        ]:
            response = self.client.get(reverse("core:" + route))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["submit_label"], label)
            self.assertContains(response, label)

    @override_settings(
        STORAGES={
            **settings.STORAGES,
            "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        }
    )
    def test_saved_photo_thumbnails_use_protected_urls_and_do_not_select_removal(self):
        vaccine = models.Vaccination.objects.create(
            child=self.child, name="Vacuna de prueba"
        )
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buffer, format="PNG")
        image = models.HealthPhoto.objects.create(
            vaccination=vaccine,
            image=SimpleUploadedFile(
                "ejemplo.png", buffer.getvalue(), content_type="image/png"
            ),
        )
        response = self.client.get(
            reverse("core:vaccination-update", args=[vaccine.pk])
        )
        self.assertContains(response, "data-photo-upload")
        self.assertContains(response, "data-photo-viewer")
        self.assertContains(response, reverse("core:health-photo", args=[image.pk]))
        self.assertNotContains(response, image.image.url)
        self.assertNotContains(response, "Photo #" + str(image.pk))
        form = VaccinationForm(instance=vaccine)
        self.assertFalse(form["remove_photos"].value())
        data = {
            "child": self.child.pk,
            "name": vaccine.name,
            "date": vaccine.date,
            "status": vaccine.status,
        }
        response = self.client.post(
            reverse("core:vaccination-update", args=[vaccine.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(models.HealthPhoto.objects.filter(pk=image.pk).exists())
        self.assertTrue(image.image.storage.exists(image.image.name))

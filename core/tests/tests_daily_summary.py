import json
import os
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path
import subprocess
import tempfile
from unittest import skipUnless
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone, translation

from core import models
from core.daily import build_daily_summary, day_bounds


@override_settings(TIME_ZONE="Europe/Madrid", LANGUAGE_CODE="es")
class DailySummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="daily-reader")
        cls.user.settings.language = "es"
        cls.user.settings.timezone = "Europe/Madrid"
        cls.user.settings.save()
        cls.child = models.Child.objects.create(
            first_name="Prueba", birth_date=date(2025, 1, 1)
        )
        cls.other = models.Child.objects.create(
            first_name="Otro", birth_date=date(2025, 1, 1)
        )
        cls.day = date(2026, 6, 20)

    def setUp(self):
        timezone.activate("Europe/Madrid")
        translation.activate("es")
        self.addCleanup(timezone.deactivate)
        self.addCleanup(translation.deactivate)
        self.client.force_login(self.user)

    def grant(self, *names):
        self.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core", codename__in=names
            )
        )
        for attribute in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            self.user.__dict__.pop(attribute, None)

    def at(self, hour, minute=0, day=None):
        day = day or self.day
        return datetime.combine(
            day, datetime.min.time(), ZoneInfo("Europe/Madrid")
        ) + timedelta(hours=hour, minutes=minute)

    def build(self, **kwargs):
        return build_daily_summary(self.day, [self.child], self.user, **kwargs)

    def seed(self):
        models.Sleep.objects.create(
            child=self.child, start=self.at(-2), end=self.at(7), nap=False
        )
        models.Sleep.objects.create(
            child=self.child, start=self.at(13), end=self.at(14, 30), nap=True
        )
        models.Feeding.objects.create(
            child=self.child,
            start=self.at(8),
            end=self.at(8, 20),
            type="formula",
            method="bottle",
            amount=150,
        )
        models.Feeding.objects.create(
            child=self.child,
            start=self.at(19),
            end=self.at(19, 15),
            type="breast milk",
            method="left breast",
        )
        meal = models.Meal.objects.create(
            child=self.child,
            time=self.at(12),
            meal_type="lunch",
            dish_names=["Plato de prueba"],
        )
        meal.foods.add(
            models.Food.objects.get(name="Plátano"),
            models.Food.objects.get(name="Avena"),
        )
        meal.tags.add("Etiqueta de prueba")
        models.DiaperChange.objects.create(
            child=self.child, time=self.at(9), wet=True, solid=True
        )
        models.DiaperChange.objects.create(
            child=self.child, time=self.at(16), wet=True, solid=False
        )
        models.Medication.objects.create(
            child=self.child,
            time=self.at(10),
            name="Medicación de prueba",
            dosage=1,
            dosage_unit="ml",
        )
        models.Note.objects.create(
            child=self.child, time=self.at(15), note="Nota de prueba"
        )
        models.Temperature.objects.create(
            child=self.child, time=self.at(18), temperature=36.5
        )
        models.Pumping.objects.create(
            child=self.child, start=self.at(10), end=self.at(10, 10), amount=80
        )
        models.TummyTime.objects.create(
            child=self.child,
            start=self.at(11),
            end=self.at(11, 15),
            milestone="Ejercicio de prueba",
        )

    def grant_all(self):
        self.grant(
            "view_child",
            *[
                f"view_{kind}"
                for kind in (
                    "sleep",
                    "feeding",
                    "meal",
                    "diaperchange",
                    "medication",
                    "note",
                    "temperature",
                    "pumping",
                    "tummytime",
                    "timer",
                )
            ],
        )

    def test_unified_totals_and_all_event_types(self):
        self.seed()
        self.grant_all()
        summary = self.build()
        group = summary["groups"][0]
        cards = {card["kind"]: card for card in group["cards"]}
        self.assertEqual(cards["sleep"]["value"], "8 horas, 30 minutos")
        self.assertEqual(cards["sleep"]["detail"], "Siestas: 1")
        self.assertEqual(cards["feeding"]["value"], 2)
        self.assertIn("150,0", cards["feeding"]["detail"])
        self.assertEqual(cards["meal"]["value"], 1)
        self.assertIn("2", cards["meal"]["detail"])
        self.assertEqual(cards["diaperchange"]["value"], 2)
        self.assertEqual(
            cards["diaperchange"]["detail"], "Mojados: 2 · Con deposición: 1"
        )
        self.assertEqual(cards["medication"]["value"], 1)
        self.assertEqual(cards["note"]["value"], 1)
        self.assertEqual(len(group["events"]), 12)
        self.assertEqual(group["events"][0]["duration"], "7 horas, 0 minutos")
        self.assertTrue(group["events"][0]["continued_before"])
        self.assertIn(
            "Plato de prueba",
            next(event for event in group["events"] if event["kind"] == "meal")[
                "details"
            ],
        )

    def test_midnight_bounds_and_carrying_feeding_amount(self):
        self.grant("view_sleep", "view_feeding", "view_note")
        models.Sleep.objects.create(
            child=self.child, start=self.at(-3), end=self.at(0), nap=False
        )
        models.Sleep.objects.create(
            child=self.child, start=self.at(23), end=self.at(26), nap=False
        )
        models.Feeding.objects.create(
            child=self.child,
            start=self.at(-1),
            end=self.at(0, 10),
            amount=120,
            method="bottle",
            type="formula",
        )
        models.Note.objects.create(
            child=self.child, time=self.at(0), note="Inicio incluido"
        )
        models.Note.objects.create(
            child=self.child,
            time=self.at(24) - timedelta(microseconds=1),
            note="Último instante incluido",
        )
        models.Note.objects.create(
            child=self.child, time=self.at(24), note="Siguiente día excluido"
        )
        group = self.build()["groups"][0]
        self.assertEqual(len(group["events"]), 4)
        cards = {card["kind"]: card for card in group["cards"]}
        self.assertEqual(cards["sleep"]["value"], "1 hora, 0 minutos")
        self.assertEqual(cards["feeding"]["value"], 0)
        self.assertEqual(cards["note"]["value"], 2)

    def test_medication_dosage_keeps_recorded_precision(self):
        self.grant("view_medication")
        models.Medication.objects.create(
            child=self.child,
            time=self.at(10),
            name="Medicación de prueba",
            dosage=0.125,
            dosage_unit="ml",
        )
        event = self.build()["groups"][0]["events"][0]
        self.assertIn("Dosis: 0,125 ml", event["details"])

    def test_overlapping_sleep_not_double_counted(self):
        self.grant("view_sleep")
        for start, end in [(1, 4), (2, 3), (3, 5)]:
            models.Sleep.objects.create(
                child=self.child, start=self.at(start), end=self.at(end), nap=False
            )
        self.assertEqual(
            self.build()["groups"][0]["cards"][0]["value"], "4 horas, 0 minutos"
        )

    def test_clock_changes_use_elapsed_time(self):
        self.grant("view_sleep")
        for day, hours in [(date(2026, 3, 29), 23), (date(2025, 10, 26), 25)]:
            start, end = day_bounds(day)
            self.assertEqual((end - start).total_seconds(), hours * 3600)
            sleep = models.Sleep.objects.create(
                child=self.child, start=start, end=end, nap=False
            )
            summary = build_daily_summary(day, [self.child], self.user)
            self.assertEqual(summary["day_hours"], hours)
            self.assertEqual(summary["groups"][0]["events"][0]["width"], 100)
            self.assertEqual(
                summary["groups"][0]["cards"][0]["value"], f"{hours} horas, 0 minutos"
            )
            sleep.delete()

    def test_running_sleep_is_separate_and_requires_timer_permission(self):
        self.grant("view_sleep")
        models.Timer.objects.create(
            child=self.child,
            user=self.user,
            name=models.Timer.SLEEP_NAME,
            start=self.at(-1),
        )
        self.assertFalse(self.build(now=self.at(2))["groups"][0]["events"])
        self.grant("view_timer")
        group = self.build(now=self.at(2))["groups"][0]
        self.assertTrue(group["events"][0]["ongoing"])
        self.assertEqual(group["events"][0]["duration"], "2 horas, 0 minutos")
        self.assertEqual(group["cards"][0]["value"], "0 minutos")
        self.assertEqual(group["lanes"][0]["events"][0]["left"], 0)

    def test_multiple_children_have_separate_totals_and_links(self):
        self.grant("view_note", "change_note")
        one = models.Note.objects.create(child=self.child, time=self.at(9), note="Una")
        two = models.Note.objects.create(child=self.other, time=self.at(9), note="Otra")
        summary = build_daily_summary(self.day, [self.child, self.other], self.user)
        self.assertEqual(
            [group["cards"][0]["value"] for group in summary["groups"]], [1, 1]
        )
        self.assertEqual(
            [group["events"][0]["edit_url"] for group in summary["groups"]],
            [
                reverse("core:note-update", args=[one.pk]),
                reverse("core:note-update", args=[two.pk]),
            ],
        )

    def test_view_permissions_cover_cards_blocks_details_and_edit_links(self):
        self.seed()
        url = reverse("core:daily-summary")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant("view_child", "view_note")
        response = self.client.get(url, {"date": self.day, "child": self.child.pk})
        self.assertContains(response, "Nota de prueba")
        self.assertNotContains(response, "Plato de prueba")
        self.assertNotContains(response, 'data-daily-card="sleep"')
        note = models.Note.objects.get(child=self.child)
        self.assertNotContains(response, reverse("core:note-update", args=[note.pk]))
        self.grant("change_note")
        response = self.client.get(url, {"date": self.day, "child": self.child.pk})
        self.assertContains(response, reverse("core:note-update", args=[note.pk]))
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_filters_navigation_spanish_and_invalid_parameters(self):
        self.grant_all()
        self.seed()
        url = reverse("core:daily-summary")
        response = self.client.get(url, {"date": self.day, "child": self.child.pk})
        self.assertContains(response, "Resumen diario")
        self.assertContains(response, "Cronología visual")
        self.assertEqual(len(response.context["daily"]["groups"]), 1)
        self.assertIn(f"child={self.child.pk}", response.context["previous_url"])
        self.assertIn("2026-06-19", response.context["previous_url"])
        today = self.client.get(url)
        self.assertIsNone(today.context["next_url"])
        for parameters in [
            {"date": "incorrecta"},
            {"date": "0001-01-01"},
            {"date": "9999-12-31"},
            {"child": "99999"},
            {"child": "invalid"},
        ]:
            self.assertEqual(self.client.get(url, parameters).status_code, 400)

    def test_no_data_and_zero_measurements(self):
        self.grant_all()
        response = self.client.get(
            reverse("core:daily-summary"), {"date": self.day, "child": self.child.pk}
        )
        self.assertContains(response, "No hay registros para este día.")
        models.Feeding.objects.create(
            child=self.child,
            start=self.at(7),
            end=self.at(7),
            amount=0,
            type="formula",
            method="bottle",
        )
        group = self.build()["groups"][0]
        self.assertFalse(group["events"][0]["is_interval"])
        self.assertIn(
            "0,0",
            next(card for card in group["cards"] if card["kind"] == "feeding")[
                "detail"
            ],
        )

    def test_queries_do_not_grow_per_child_and_read_does_not_write(self):
        self.grant_all()
        self.seed()
        with CaptureQueriesContext(connection) as queries:
            self.build()
        self.assertLess(len(queries), 28)
        self.assertFalse(
            any(
                q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for q in queries
            )
        )
        with CaptureQueriesContext(connection) as multi_queries:
            build_daily_summary(self.day, [self.child, self.other], self.user)
        self.assertLessEqual(len(multi_queries), len(queries))

    @skipUnless(
        os.environ.get("BABYBUDDY_PLAYWRIGHT_MODULE"), "Optional Playwright tests"
    )
    def test_browser_mobile_desktop_and_keyboard(self):
        self.seed()
        self.grant_all()
        response = self.client.get(
            reverse("core:daily-summary"), {"date": self.day, "child": self.child.pk}
        )
        root = Path(settings.BASE_DIR)
        fixture = {
            "html": response.content.decode(),
            "previousHtml": self.client.get(
                reverse("core:daily-summary"),
                {"date": self.day - timedelta(days=1), "child": self.child.pk},
            ).content.decode(),
            "otherHtml": self.client.get(
                reverse("core:daily-summary"),
                {"date": self.day - timedelta(days=1), "child": self.other.pk},
            ).content.decode(),
            "date": self.day.isoformat(),
            "previousDate": (self.day - timedelta(days=1)).isoformat(),
            "child": str(self.child.pk),
            "otherChild": str(self.other.pk),
            "css": (
                root / "node_modules/bootstrap/dist/css/bootstrap.min.css"
            ).read_text(encoding="utf-8"),
        }
        with tempfile.TemporaryDirectory(prefix="babybuddy-daily-") as directory:
            path = Path(directory) / "fixture.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            result = subprocess.run(
                ["node", str(root / "core/tests/browser_daily.cjs"), str(path)],
                capture_output=True,
                encoding="utf-8",
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout)

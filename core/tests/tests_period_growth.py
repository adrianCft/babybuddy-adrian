import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
import subprocess
import tempfile
from unittest import skipUnless
from unittest.mock import patch
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
from core.growth import (
    age_at,
    build_growth,
    measurement_at,
    percentile_label,
    reference,
    z_score,
)
from core.growth_views import GrowthProfileForm
from core.periods import build_period_summary, period_bounds
from core.utils import duration_string


@override_settings(TIME_ZONE="Europe/Madrid", LANGUAGE_CODE="es")
class PeriodGrowthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="summary-reader")
        cls.user.settings.language = "es"
        cls.user.settings.timezone = "Europe/Madrid"
        cls.user.settings.save()
        cls.child = models.Child.objects.create(
            first_name="Ejemplo", birth_date=date(2026, 1, 1)
        )
        cls.other = models.Child.objects.create(
            first_name="Otro", birth_date=date(2026, 1, 1)
        )
        cls.day = date(2026, 6, 17)

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
        for key in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            self.user.__dict__.pop(key, None)

    def at(self, day, hour=0):
        return datetime.combine(
            day, datetime.min.time(), ZoneInfo("Europe/Madrid")
        ) + timedelta(hours=hour)

    def test_calendar_and_partial_periods(self):
        self.assertEqual(
            period_bounds(date(2024, 2, 15), "month"),
            (date(2024, 2, 1), date(2024, 2, 29)),
        )
        self.assertEqual(
            period_bounds(date(2025, 1, 1), "week"),
            (date(2024, 12, 30), date(2025, 1, 5)),
        )
        self.grant("view_feeding")
        summary = build_period_summary(
            self.day, "month", [self.child], self.user, self.day
        )
        self.assertTrue(summary["partial"])
        self.assertEqual(len(summary["groups"][0]["rows"]), 17)
        self.assertEqual(summary["previous_cutoff"], date(2026, 5, 17))
        self.assertEqual(summary["groups"][0]["cards"][0]["average"], "—")

    def test_sleep_overlap_midnight_and_dst(self):
        self.grant("view_sleep")
        day = date(2026, 3, 29)
        models.Sleep.objects.create(
            child=self.child, start=self.at(day), end=self.at(day + timedelta(days=1))
        )
        models.Sleep.objects.create(
            child=self.child, start=self.at(day, 1), end=self.at(day, 5)
        )
        result = build_period_summary(
            day, "week", [self.child], self.user, today=date(2026, 4, 1)
        )
        self.assertEqual(
            result["groups"][0]["cards"][0]["total"],
            duration_string(timedelta(hours=23), "m"),
        )
        self.assertEqual(result["groups"][0]["cards"][0]["days"], 1)

    def test_feeding_attributed_to_start_no_child_leak_and_forecasts(self):
        self.grant("view_feeding")
        for i in range(7):
            day = self.day - timedelta(days=i + 1)
            models.Feeding.objects.create(
                child=self.child,
                start=self.at(day, 23),
                end=self.at(day + timedelta(days=1), 1),
                type="formula",
                method="bottle",
                amount=90,
            )
        models.Feeding.objects.create(
            child=self.other,
            start=self.at(self.day, 7),
            end=self.at(self.day, 8),
            type="formula",
            method="bottle",
            amount=90,
        )
        result = build_period_summary(
            self.day, "week", [self.child, self.other], self.user, self.day
        )
        a, b = result["groups"]
        self.assertEqual(a["cards"][0]["total"], "2")
        self.assertEqual(b["cards"][0]["total"], "1")
        self.assertTrue(a["forecasts"][0]["ready"])
        self.assertEqual(a["forecasts"][0]["typical"], "1")
        self.assertFalse(b["forecasts"][0]["ready"])

    def test_forecast_requires_records_no_medication_forecast(self):
        self.grant("view_medication", "view_sleep")
        result = build_period_summary(
            self.day, "week", [self.child], self.user, self.day
        )
        self.assertEqual(len(result["groups"][0]["forecasts"]), 1)
        self.assertFalse(result["groups"][0]["forecasts"][0]["ready"])

    def test_summary_permissions_validation_and_no_writes(self):
        url = reverse("core:period-summary")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant("view_child", "view_sleep", "view_feeding")
        for query in (
            {"period": "bad"},
            {"date": "2050-01-01"},
            {"child": 999999},
            {"date": "invalid"},
        ):
            self.assertEqual(self.client.get(url, query).status_code, 400)
        self.user.has_perm("core.view_sleep")  # Warm the permission cache.
        with CaptureQueriesContext(connection) as queries:
            result = build_period_summary(
                self.day, "month", [self.child, self.other], self.user, self.day
            )
        self.assertLessEqual(len(queries), 2)
        self.assertFalse(
            any(
                q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for q in queries
            )
        )
        self.assertEqual(len(result["groups"][0]["cards"]), 2)
        self.assertEqual(self.client.get(url, {"date": self.day}).status_code, 200)

    def profile(self, **kwargs):
        data = dict(
            reference_system="aragon",
            sex="girl",
            weight_unit="kg",
            height_unit="cm",
            birth_status="term",
        )
        data.update(kwargs)
        return models.GrowthProfile.objects.create(child=self.child, **data)

    def seed_growth(self):
        self.profile()
        for days in (60, 100, 130, 150):
            when = self.child.birth_date + timedelta(days=days)
            models.Weight.objects.create(
                child=self.child, date=when, weight=reference("weight", "girl")[days][1]
            )
            models.Height.objects.create(
                child=self.child, date=when, height=reference("height", "girl")[days][1]
            )
            models.HeadCircumference.objects.create(
                child=self.child,
                date=when,
                head_circumference=reference("head_circumference", "girl")[days][1],
            )

    def test_who_lms_matches_shipped_percentiles(self):
        for kind in ("weight", "height", "head_circumference"):
            for sex in ("boy", "girl"):
                table = reference(kind, sex)
                self.assertEqual(
                    percentile_label(z_score(table[100][1], table[100])), "P50.0"
                )
                if kind == "head_circumference":
                    continue
                model = (
                    models.WeightPercentile
                    if kind == "weight"
                    else models.HeightPercentile
                )
                for age in (0, 100, 730, 731, 1800):
                    row = model.objects.get(sex=sex, age_in_days=timedelta(days=age))
                    for p in (3, 15, 50, 85, 97):
                        value = getattr(row, f"p{p}_{kind}")
                        from statistics import NormalDist

                        self.assertAlmostEqual(
                            measurement_at(NormalDist().inv_cdf(p / 100), table[age]),
                            value,
                            delta=0.002,
                        )

    def test_growth_missing_configuration_is_read_only(self):
        self.grant("view_weight")
        models.Weight.objects.create(child=self.child, date=self.day, weight=6)
        with CaptureQueriesContext(connection) as queries:
            growth = build_growth(self.child, self.user, self.day)
        self.assertIsNone(growth["metrics"][0]["latest"]["percentile"])
        self.assertEqual(models.GrowthProfile.objects.count(), 0)
        self.assertFalse(
            any(
                q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for q in queries
            )
        )

    def test_growth_history_and_conditional_projection(self):
        self.grant("view_weight", "view_height", "view_headcircumference")
        self.seed_growth()
        result = build_growth(self.child, self.user, self.day)
        for metric in result["metrics"]:
            self.assertEqual(metric["latest"]["percentile"], "P50.0")
            self.assertEqual(metric["change"], 0)
            target = (self.day + timedelta(days=30) - self.child.birth_date).days
            self.assertAlmostEqual(
                metric["projection"]["value"],
                reference(metric["kind"], "girl")[target][1],
            )
            self.assertTrue(metric["chart"]["forecast"])
        self.assertIsNone(
            build_growth(self.child, self.user, self.day + timedelta(days=100))[
                "metrics"
            ][0]["projection"]
        )

    def test_units_converted_only_for_calculation_and_invalid_measurements(self):
        self.grant("view_weight", "view_height")
        self.profile(weight_unit="g")
        age = (self.day - self.child.birth_date).days
        w = models.Weight.objects.create(
            child=self.child,
            date=self.day,
            weight=reference("weight", "girl")[age][1] * 1000,
        )
        models.Height.objects.create(
            child=self.child,
            date=self.day,
            height=reference("height", "girl")[age][1],
        )
        result = build_growth(self.child, self.user, self.day)
        self.assertEqual(
            [m["latest"]["percentile"] for m in result["metrics"]], ["P50.0", "P50.0"]
        )
        w.refresh_from_db()
        self.assertGreater(w.weight, 1000)
        w.weight = -5
        w.save()
        self.assertIsNone(
            build_growth(self.child, self.user, self.day)["metrics"][0]["latest"][
                "percentile"
            ]
        )

    def test_head_circumference_history_and_projection(self):
        self.grant("view_headcircumference")
        self.profile()
        for days in (100, 130):
            models.HeadCircumference.objects.create(
                child=self.child,
                date=self.child.birth_date + timedelta(days=days),
                head_circumference=reference("head_circumference", "girl")[days][1],
            )
        metric = build_growth(self.child, self.user, self.day)["metrics"][0]
        self.assertEqual(metric["kind"], "head_circumference")
        self.assertEqual(metric["latest"]["percentile"], "P50.0")
        self.assertEqual(metric["projection"]["percentile"], "P50.0")

    def test_growth_page_includes_head_circumference_curve_and_entry_link(self):
        self.grant("view_child", "view_headcircumference", "add_headcircumference")
        self.profile()
        models.HeadCircumference.objects.create(
            child=self.child,
            date=self.child.birth_date + timedelta(days=100),
            head_circumference=reference("head_circumference", "girl")[100][1],
        )
        page = self.client.get(
            reverse("core:growth-summary", args=[self.child.slug])
        )
        self.assertContains(page, 'data-growth-metric="head_circumference"')
        self.assertContains(page, reverse("core:head-circumference-add"))

    def test_preterm_and_age_limits(self):
        self.grant("view_weight")
        profile = self.profile(
            birth_status="preterm", gestational_weeks=32, gestational_days=3
        )
        self.assertEqual(
            age_at(self.child, profile, self.child.birth_date + timedelta(days=100)),
            (47, True),
        )
        models.Weight.objects.create(
            child=self.child, date=self.child.birth_date, weight=2
        )
        self.assertIsNone(
            build_growth(self.child, self.user, self.day)["metrics"][0]["latest"][
                "percentile"
            ]
        )
        old_day = self.child.birth_date + timedelta(days=2000)
        models.Weight.objects.create(child=self.child, date=old_day, weight=20)
        self.assertIsNone(
            build_growth(self.child, self.user, old_day)["metrics"][0]["latest"][
                "percentile"
            ]
        )

    def test_profile_permissions_validation_and_preserves_measurements(self):
        url = reverse("core:growth-summary", args=[self.child.slug])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant("view_child")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"sex": "girl"}).status_code, 403)
        self.grant("change_child")
        data = dict(
            reference_system="aragon",
            sex="girl",
            weight_unit="kg",
            height_unit="cm",
            birth_status="preterm",
            gestational_weeks=45,
            gestational_days=0,
        )
        self.assertEqual(self.client.post(url, data).status_code, 400)
        self.assertEqual(models.GrowthProfile.objects.count(), 0)
        data.update(gestational_weeks=34, gestational_days=2)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(
            models.GrowthProfile.objects.get(child=self.child).gestational_weeks, 34
        )
        self.assertEqual(models.Weight.objects.count(), 0)
        self.assertFalse(GrowthProfileForm({**data, "gestational_days": 7}).is_valid())
        self.assertFalse(GrowthProfileForm({**data, "weight_unit": "guess"}).is_valid())

    def test_aragon_is_default_and_who_extends_to_five_years(self):
        self.grant("view_weight")
        profile = self.profile()
        self.assertEqual(profile.reference_system, "aragon")
        after_two = self.child.birth_date + timedelta(days=800)
        models.Weight.objects.create(child=self.child, date=after_two, weight=11)
        aragon = build_growth(self.child, self.user, after_two)["metrics"][0]
        self.assertIsNone(aragon["latest"]["percentile"])
        profile.reference_system = "who"
        profile.save(update_fields=["reference_system"])
        who = build_growth(self.child, self.user, after_two)["metrics"][0]
        self.assertIsNotNone(who["latest"]["percentile"])

    def test_duplicate_dates_insufficient_history_and_method_boundary(self):
        self.grant("view_height")
        self.profile()
        day = self.child.birth_date + timedelta(days=710)
        for _ in range(2):
            models.Height.objects.create(child=self.child, date=day, height=85)
        result = build_growth(self.child, self.user, day)["metrics"][0]
        self.assertIsNone(result["projection"])
        self.assertNotIn("previous", result)
        models.Height.objects.create(
            child=self.child, date=day - timedelta(days=30), height=84
        )
        result = build_growth(self.child, self.user, day)["metrics"][0]
        self.assertIsNone(result["projection"])

    @skipUnless(
        os.environ.get("BABYBUDDY_PLAYWRIGHT_MODULE"), "Optional Playwright tests"
    )
    def test_browser_summary_and_growth(self):
        self.grant(
            "view_child",
            "view_weight",
            "view_height",
            "view_headcircumference",
            "view_sleep",
            "view_feeding",
            "view_meal",
            "view_diaperchange",
            "change_child",
        )
        self.seed_growth()
        for day_number in range(1, 30):
            day = date(2026, 6, day_number)
            models.Sleep.objects.create(
                child=self.child,
                start=self.at(day),
                end=self.at(day, 7 + day_number % 3),
            )
            for hour in (8, 13, 19):
                models.Feeding.objects.create(
                    child=self.child,
                    start=self.at(day, hour),
                    end=self.at(day, hour) + timedelta(minutes=20),
                    type="formula",
                    method="bottle",
                    amount=100,
                )
        root = Path(settings.BASE_DIR)
        with patch("django.utils.timezone.localdate", return_value=date(2026, 6, 30)):
            summary_html = self.client.get(
                reverse("core:period-summary"),
                {"date": self.day, "period": "month", "child": self.child.pk},
            ).content.decode()
            growth_html = self.client.get(
                reverse("core:growth-summary", args=[self.child.slug])
            ).content.decode()
        fixture = {
            "summary": self.client.get(
                reverse("core:period-summary"),
                {"date": self.day, "period": "month", "child": self.child.pk},
            ).content.decode(),
            "growth": self.client.get(
                reverse("core:growth-summary", args=[self.child.slug])
            ).content.decode(),
            "css": (
                root / "node_modules/bootstrap/dist/css/bootstrap.min.css"
            ).read_text(encoding="utf-8"),
        }
        fixture.update(summary=summary_html, growth=growth_html)
        with tempfile.TemporaryDirectory(prefix="babybuddy-growth-") as directory:
            path = Path(directory) / "fixture.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            result = subprocess.run(
                ["node", str(root / "core/tests/browser_period_growth.cjs"), str(path)],
                capture_output=True,
                encoding="utf-8",
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout)

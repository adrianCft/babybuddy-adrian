import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import admin, forms, models


@override_settings(LANGUAGE_CODE="es")
class SavedDishesTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="dish-user")
        cls.user.settings.language = "es"
        cls.user.settings.save(update_fields=["language"])
        cls.child = models.Child.objects.create(
            first_name="Test", birth_date=timezone.localdate()
        )
        cls.apple = models.Food.objects.get(name="Manzana")
        cls.oats = models.Food.objects.get(name="Avena")
        cls.dish = models.Dish.objects.create(name="Plato de prueba")
        cls.dish.foods.add(cls.apple, cls.oats)

    def setUp(self):
        self.client.force_login(self.user)

    def grant(self, *permissions):
        self.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core",
                codename__in=permissions,
            )
        )

    def meal_data(self, **overrides):
        return {
            "child": self.child.pk,
            "time": (timezone.now() - timezone.timedelta(hours=1)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "meal_type": "breakfast",
            "foods": [self.apple.pk, self.oats.pk],
            "dish_names": json.dumps([self.dish.name]),
            **overrides,
        }

    def test_catalog_and_creation_require_permissions(self):
        for url in ["dish-list", "dish-add"]:
            self.assertEqual(self.client.get(reverse("core:" + url)).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("core:dish-quick-add"), {}).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                reverse("core:dish-update", args=[self.dish.pk]), {}
            ).status_code,
            403,
        )

    def test_create_edit_and_deactivate_dish(self):
        self.grant("view_dish", "add_dish", "change_dish")
        for url in ["dish-list", "dish-add"]:
            self.assertEqual(self.client.get(reverse("core:" + url)).status_code, 200)
        response = self.client.post(
            reverse("core:dish-add"),
            {
                "name": "  Nuevo plato  ",
                "foods": [self.apple.pk, self.oats.pk],
                "active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        dish = models.Dish.objects.get(name="Nuevo plato")
        self.assertCountEqual(dish.foods.all(), [self.apple, self.oats])
        response = self.client.post(
            reverse("core:dish-update", args=[dish.pk]),
            {
                "name": "Plato editado",
                "foods": [self.oats.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        dish.refresh_from_db()
        self.assertFalse(dish.active)
        self.assertEqual(list(dish.foods.all()), [self.oats])

    def test_quick_creation_and_invalid_selections(self):
        self.grant("add_dish")
        response = self.client.post(
            reverse("core:dish-quick-add"),
            {
                "name": "Selección guardada",
                "foods": [self.apple.pk, self.oats.pk],
                "active": "on",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertCountEqual(response.json()["foods"], [self.apple.pk, self.oats.pk])
        count = models.Dish.objects.count()
        self.oats.active = False
        self.oats.save()
        for payload in [
            {"name": "PLATO DE PRUEBA", "foods": [self.apple.pk]},
            {"name": "Sin ingredientes"},
            {"name": "Inactivo", "foods": [self.oats.pk]},
            {"name": "No existe", "foods": [999999]},
        ]:
            response = self.client.post(reverse("core:dish-quick-add"), payload)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(models.Dish.objects.count(), count)

    def test_available_dishes_and_spanish_form(self):
        self.grant("view_dish", "add_dish", "add_meal")
        response = self.client.get(reverse("core:meal-add"))
        self.assertContains(response, "Platos guardados")
        self.assertContains(response, "Guardar selección como plato")
        self.assertContains(response, "Seleccionados")
        self.assertContains(response, 'data-name="Plato de prueba"')
        self.oats.active = False
        self.oats.save()
        response = self.client.get(reverse("core:meal-add"))
        self.assertNotContains(response, 'data-name="Plato de prueba"')
        form = forms.DishForm(instance=self.dish)
        self.assertIn(self.oats, form.fields["foods"].queryset)

    def test_meal_history_survives_recipe_changes_and_deletion(self):
        form = forms.MealForm(data=self.meal_data())
        self.assertTrue(form.is_valid(), form.errors)
        meal = form.save()
        original_name = self.dish.name
        self.dish.name = "Otro nombre"
        self.dish.active = False
        self.dish.save()
        self.dish.foods.set([self.oats])
        self.dish.delete()
        meal.refresh_from_db()
        self.assertEqual(meal.dish_names, [original_name])
        self.assertCountEqual(meal.foods.all(), [self.apple, self.oats])

    def test_meal_can_adjust_ingredients_and_edit_existing_snapshot(self):
        form = forms.MealForm(data=self.meal_data(foods=[self.apple.pk]))
        self.assertTrue(form.is_valid(), form.errors)
        meal = form.save()
        self.assertEqual(list(meal.foods.all()), [self.apple])
        self.assertCountEqual(self.dish.foods.all(), [self.apple, self.oats])
        self.grant("change_meal", "view_meal")
        response = self.client.get(reverse("core:meal-update", args=[meal.pk]))
        self.assertContains(response, "Plato de prueba")
        # Older clients that omit this optional field must preserve the snapshot.
        data = self.meal_data()
        data.pop("dish_names")
        form = forms.MealForm(data=data, instance=meal)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().dish_names, [self.dish.name])
        form = forms.MealForm(data=self.meal_data(dish_names="[]"), instance=meal)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().dish_names, [])

    def test_invalid_snapshot_is_rejected_and_duplicate_names_collapsed(self):
        for value in ["{}", '"text"', "[1]", '[""]', json.dumps(["x" * 256])]:
            form = forms.MealForm(data=self.meal_data(dish_names=value))
            self.assertFalse(form.is_valid(), value)
            self.assertIn("dish_names", form.errors)
        form = forms.MealForm(data=self.meal_data(dish_names='["Uno", "Uno", "Dos"]'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().dish_names, ["Uno", "Dos"])

    def test_export_and_import_keep_snapshot_and_ingredients(self):
        form = forms.MealForm(data=self.meal_data())
        self.assertTrue(form.is_valid(), form.errors)
        meal = form.save()
        resource = admin.MealImportExportResource()
        dataset = resource.export(models.Meal.objects.filter(pk=meal.pk))
        meal.delete()
        result = resource.import_data(dataset, dry_run=False)
        self.assertFalse(result.has_errors(), result.row_errors())
        self.assertFalse(result.has_validation_errors(), result.invalid_rows)
        restored = models.Meal.objects.get()
        self.assertEqual(restored.dish_names, [self.dish.name])
        self.assertCountEqual(restored.foods.all(), [self.apple, self.oats])

    @skipUnless(
        os.environ.get("BABYBUDDY_PLAYWRIGHT_MODULE"),
        "Optional Playwright browser tests",
    )
    def test_browser_selection_desktop_and_mobile(self):
        self.grant("view_dish", "add_dish", "add_food")
        meal = models.Meal.objects.create(
            child=self.child,
            meal_type="breakfast",
            dish_names=["Plato histórico"],
        )
        meal.foods.add(self.apple)
        shared = models.Dish.objects.create(name="Otro plato de prueba")
        shared.foods.add(self.apple)
        form = forms.MealForm(instance=meal, user=self.user)
        root = Path(settings.BASE_DIR)
        css = (root / "node_modules/bootstrap/dist/css/bootstrap.min.css").read_text(
            encoding="utf-8"
        )
        js = (
            root / "node_modules/bootstrap/dist/js/bootstrap.bundle.min.js"
        ).read_text(encoding="utf-8")
        html = (
            '<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<style>{css}</style><script>{js}</script><body><form class="p-3">'
            '<input type="hidden" name="csrfmiddlewaretoken" value="test-only">'
            f'{form["dish_names"]}{form["foods"]}</form></body></html>'
        )
        with tempfile.TemporaryDirectory(prefix="babybuddy-browser-") as directory:
            fixture = Path(directory) / "fixture.json"
            fixture.write_text(
                json.dumps(
                    {
                        "html": html,
                        "apple": self.apple.pk,
                        "oats": self.oats.pk,
                        "dish": self.dish.pk,
                        "sharedDish": shared.pk,
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["node", str(root / "core/tests/browser_dishes.cjs"), str(fixture)],
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout)

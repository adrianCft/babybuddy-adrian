import datetime
import importlib

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class FoodAndMealMigrationTestCase(TransactionTestCase):
    migrate_from = ("core", "0036_medication")
    migrate_to = ("core", "0037_food_meal_childfoodprofile")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        Child = old_apps.get_model("core", "Child")
        self.child_id = Child.objects.create(
            first_name="First",
            last_name="Last",
            birth_date=datetime.date(2025, 1, 1),
            slug="first-last",
        ).pk

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        self.apps = self.executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_migration_creates_food_meal_and_relationship(self):
        ChildFoodProfile = self.apps.get_model("core", "ChildFoodProfile")
        Food = self.apps.get_model("core", "Food")
        Meal = self.apps.get_model("core", "Meal")
        MealFood = self.apps.get_model("core", "MealFood")

        food = Food.objects.create(name="Banana", category="fruit")
        meal = Meal.objects.create(
            child_id=self.child_id,
            time=datetime.datetime(2025, 1, 2, 8, 30, tzinfo=datetime.timezone.utc),
            meal_type="breakfast",
        )
        MealFood.objects.create(meal=meal, food=food)
        profile = ChildFoodProfile.objects.create(
            child_id=self.child_id,
            food=food,
            taste="likes",
            tolerance="well tolerated",
        )

        self.assertTrue(food.active)
        self.assertEqual(list(meal.foods.values_list("name", flat=True)), ["Banana"])
        self.assertEqual(profile.taste, "likes")
        self.assertEqual(profile.tolerance, "well tolerated")
        self.assertEqual(Meal._meta.ordering, ["-time", "-id"])


class InitialSpanishFoodCatalogMigrationTestCase(TransactionTestCase):
    migrate_from = ("core", "0037_food_meal_childfoodprofile")
    migrate_to = ("core", "0038_initial_spanish_food_catalog")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        Food = old_apps.get_model("core", "Food")
        Food.objects.create(
            name="AVENA",
            category="other",
            active=False,
            notes="Valor personalizado",
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        self.apps = self.executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_catalog_is_created_without_overwriting_existing_foods(self):
        Food = self.apps.get_model("core", "Food")
        migration = importlib.import_module(
            "core.migrations.0038_initial_spanish_food_catalog"
        )

        self.assertEqual(Food.objects.count(), len(migration.FOODS))
        self.assertTrue(Food.objects.filter(name="Plátano", category="fruit").exists())
        self.assertTrue(
            Food.objects.filter(
                name="Huevo",
                category="egg",
                allergen=True,
            ).exists()
        )
        oats = Food.objects.get(name="AVENA")
        self.assertEqual(oats.category, "other")
        self.assertFalse(oats.active)
        self.assertEqual(oats.notes, "Valor personalizado")


class InterfaceUpgradePreservesDataTests(TransactionTestCase):
    """Exercise the release upgrade against populated versions of the old schema."""

    def test_existing_records_preferences_relations_and_photo_paths_are_preserved(self):
        executor = MigrationExecutor(connection)
        old_targets = [
            ("core", "0043_health_records"),
            ("babybuddy", "0035_alter_settings_language"),
        ]
        executor.migrate(old_targets)
        old = executor.loader.project_state(old_targets).apps
        try:
            user = old.get_model("auth", "User").objects.create(
                username="conservar-usuario", password="existing-password-hash"
            )
            old.get_model("babybuddy", "Settings").objects.create(
                user_id=user.pk,
                language="es",
                timezone="Europe/Madrid",
                dashboard_hide_empty=True,
            )
            child = old.get_model("core", "Child").objects.create(
                first_name="Lucía", birth_date=datetime.date(2026, 1, 1), slug="lucia"
            )
            food = old.get_model("core", "Food").objects.create(
                name="Alimento personalizado",
                notes="Notas que deben conservarse",
                active=False,
            )
            dish = old.get_model("core", "Dish").objects.create(name="Plato existente")
            dish.foods.add(food)
            meal = old.get_model("core", "Meal").objects.create(
                child_id=child.pk,
                dish_names=["Nombre histórico"],
                time=datetime.datetime(2026, 3, 1, 12, tzinfo=datetime.timezone.utc),
                notes="Detalle de la comida",
            )
            old.get_model("core", "MealFood").objects.create(
                meal_id=meal.pk, food_id=food.pk
            )
            visit = old.get_model("core", "HealthVisit").objects.create(
                child_id=child.pk,
                reason="Revisión existente",
                professional="Nombre guardado",
                assessment="Valoración que debe conservarse",
            )
            old.get_model("core", "Prescription").objects.create(
                visit_id=visit.pk,
                name="Medicación existente",
                instructions="Pauta original",
            )
            old.get_model("core", "Vaccination").objects.create(
                child_id=child.pk, name="Vacuna existente", batch="Lote conservado"
            )
            old.get_model("core", "Medication").objects.create(
                child_id=child.pk, name="Toma existente", dosage=2, dosage_unit="ml"
            )
            old.get_model("core", "Weight").objects.create(
                child_id=child.pk, date=datetime.date(2026, 6, 1), weight=7860
            )
            old.get_model("core", "HealthPhoto").objects.create(
                visit_id=visit.pk, image="health/photos/original.png"
            )
            selected = list(
                old.get_app_config("core").get_models(include_auto_created=True)
            )
            selected += [
                old.get_model("babybuddy", "Settings"),
                old.get_model("auth", "User"),
            ]
            snapshots = {}
            for model in selected:
                fields = [field.name for field in model._meta.fields]
                snapshots[model._meta.label_lower] = (
                    fields,
                    list(model.objects.order_by("pk").values(*fields)),
                )
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
            new = executor.loader.project_state().apps
            for label, (fields, rows) in snapshots.items():
                model = new.get_model(label)
                self.assertEqual(
                    list(model.objects.order_by("pk").values(*fields)), rows, label
                )
            self.assertIsNone(
                new.get_model("core", "HealthVisit").objects.get(pk=visit.pk).specialty
            )
            self.assertIsNone(
                new.get_model("babybuddy", "Settings")
                .objects.get(user_id=user.pk)
                .dashboard_cards
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())

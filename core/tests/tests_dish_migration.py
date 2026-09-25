import datetime

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SavedDishMigrationTestCase(TransactionTestCase):
    """Compare every existing table and column before/after the additive migration."""

    def test_existing_rows_are_unchanged_and_catalog_is_empty(self):
        before = ("core", "0040_merge_0037_alter_options_0039_sleep_wakeups")
        after = ("core", "0041_saved_dishes")
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([before])
            apps = executor.loader.project_state([before]).apps
            child = apps.get_model("core", "Child").objects.create(
                first_name="Histórico",
                last_name="Prueba",
                slug="historico-prueba",
                birth_date=datetime.date(2025, 1, 1),
            )
            food = apps.get_model("core", "Food").objects.create(
                name="Ingrediente histórico",
                category="other",
                active=False,
                notes="Conservar notas",
            )
            meal = apps.get_model("core", "Meal").objects.create(
                child=child,
                time=datetime.datetime(2025, 2, 1, tzinfo=datetime.timezone.utc),
                meal_type="dinner",
                quantity="little",
                preparation="pieces",
                notes="Conservar comida",
            )
            apps.get_model("core", "MealFood").objects.create(meal=meal, food=food)
            apps.get_model("core", "ChildFoodProfile").objects.create(
                child=child,
                food=food,
                taste="likes",
                notes="Conservar perfil",
            )
            snapshot = {}
            quote = connection.ops.quote_name
            with connection.cursor() as cursor:
                for table in connection.introspection.table_names():
                    if table == "django_migrations":
                        continue
                    columns = [
                        column.name
                        for column in connection.introspection.get_table_description(
                            cursor, table
                        )
                    ]
                    query = (
                        f"SELECT {', '.join(map(quote, columns))} FROM {quote(table)}"
                    )
                    cursor.execute(query)
                    snapshot[query] = sorted(map(repr, cursor.fetchall()))
            executor = MigrationExecutor(connection)
            executor.migrate([after])
            with connection.cursor() as cursor:
                for query, rows in snapshot.items():
                    cursor.execute(query)
                    self.assertEqual(sorted(map(repr, cursor.fetchall())), rows, query)
            apps = executor.loader.project_state([after]).apps
            self.assertEqual(apps.get_model("core", "Dish").objects.count(), 0)
            self.assertEqual(apps.get_model("core", "DishFood").objects.count(), 0)
            self.assertEqual(
                apps.get_model("core", "Meal").objects.get(pk=meal.pk).dish_names, []
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())

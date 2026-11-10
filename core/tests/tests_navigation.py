from datetime import datetime, time, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core import models


class NavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="context-user")
        cls.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core",
                codename__in=[
                    "view_child",
                    "view_meal",
                    "add_meal",
                    "change_meal",
                    "delete_meal",
                    "view_healthvisit",
                ],
            )
        )
        cls.user.settings.timezone = "Europe/Madrid"
        cls.user.settings.save(update_fields=["timezone"])
        cls.child = models.Child.objects.create(
            first_name="Ana", birth_date=timezone.localdate() - timedelta(days=300)
        )
        cls.other_child = models.Child.objects.create(
            first_name="Luis", birth_date=cls.child.birth_date
        )
        cls.day = timezone.localdate() - timedelta(days=3)
        cls.when = timezone.make_aware(datetime.combine(cls.day, time(12)))
        cls.meal = models.Meal.objects.create(
            child=cls.child, time=cls.when, meal_type="lunch"
        )
        cls.meal.foods.add(models.Food.objects.first())
        models.Meal.objects.create(
            child=cls.other_child, time=cls.when, meal_type="lunch"
        )
        models.Meal.objects.create(
            child=cls.child, time=cls.when - timedelta(days=1), meal_type="lunch"
        )

    def setUp(self):
        self.client.force_login(self.user)

    def choose_day(self):
        return self.client.get(
            reverse("core:daily-summary"),
            {"child": self.child.pk, "date": self.day.isoformat()},
        )

    def meal_data(self):
        return {
            "child": self.child.pk,
            "time": self.when,
            "meal_type": "lunch",
            "foods": [models.Food.objects.first().pk],
            "quantity": "normal",
        }

    def test_child_and_day_follow_the_user_between_sections(self):
        self.choose_day()
        response = self.client.get(reverse("core:meal-list"))
        self.assertEqual(list(response.context["object_list"]), [self.meal])
        self.assertEqual(response.context["record_context"]["child"], self.child)
        self.assertEqual(response.context["record_context"]["display_date"], self.day)
        self.assertEqual(
            self.client.get(reverse("core:health-overview")).context["selected_child"],
            self.child,
        )
        form = self.client.get(reverse("core:meal-add")).context["form"]
        self.assertEqual(form["child"].value(), self.child.pk)
        self.assertEqual(timezone.localtime(form.initial["time"]).date(), self.day)

    def test_all_children_and_all_dates_are_explicit_choices(self):
        self.choose_day()
        response = self.client.get(reverse("core:meal-list"), {"child": "", "date": ""})
        self.assertEqual(response.context["object_list"].count(), 3)
        response = self.client.get(reverse("core:meal-list"))
        self.assertIsNone(response.context["record_context"]["child"])
        self.assertIsNone(response.context["record_context"]["display_date"])
        self.assertEqual(response.context["object_list"].count(), 3)

    def test_filters_survive_navigation_and_can_be_cleared(self):
        url = reverse("core:meal-list")
        self.client.get(
            url,
            {
                "child": self.child.pk,
                "meal_type": "lunch",
                "quantity": "normal",
                "filtered": "1",
            },
        )
        self.client.get(reverse("core:health-overview"))
        response = self.client.get(url)
        self.assertEqual(response.context["filter"].form["meal_type"].value(), "lunch")
        self.assertEqual(response.context["filter"].form["quantity"].value(), "normal")
        response = self.client.get(url, {"clear_filters": "1"})
        self.assertIsNone(response.context["filter"].form["meal_type"].value())
        self.assertEqual(response.context["record_context"]["child"], self.child)

    def test_creating_or_cancelling_returns_to_the_full_origin_url(self):
        self.user.settings.pagination_count = 1
        self.user.settings.save(update_fields=["pagination_count"])
        models.Meal.objects.create(
            child=self.child, time=self.when - timedelta(hours=1), meal_type="lunch"
        )
        origin = (
            reverse("core:meal-list")
            + "?"
            + urlencode(
                {
                    "child": self.child.pk,
                    "date_from": self.day.isoformat(),
                    "meal_type": "lunch",
                    "page": "2",
                }
            )
        )
        source = self.client.get(origin)
        from core.navigation import contextual_url

        add_url = contextual_url(source.wsgi_request, "core:meal-add")
        self.assertEqual(parse_qs(urlsplit(add_url).query)["next"], [origin])
        response = self.client.get(add_url)
        self.assertEqual(response.context["cancel_url"], origin)
        self.assertContains(response, 'name="next"')
        data = self.meal_data()
        data["next"] = origin
        response = self.client.post(add_url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, origin)
        self.assertEqual(self.client.get(response.url).status_code, 200)

    def test_failed_validation_preserves_the_return_destination(self):
        origin = (
            reverse("core:meal-list")
            + "?child="
            + str(self.child.pk)
            + "&meal_type=lunch"
        )
        response = self.client.post(
            reverse("core:meal-add") + "?" + urlencode({"next": origin}),
            {"next": origin},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cancel_url"], origin)
        self.assertEqual(response.context["return_url"], origin)
        self.assertTrue(response.context["form"].errors)

    def test_external_or_non_page_return_urls_are_never_followed(self):
        for target in (
            "https://evil.example/",
            "//evil.example/",
            "/\\evil.example/",
            "/login/?next=https://evil.example/",
            "/meals/add/",
            "/meals/1/delete/",
        ):
            with self.subTest(target=target):
                response = self.client.get(reverse("core:meal-add"), {"next": target})
                self.assertEqual(response.context["return_url"], "")
                data = self.meal_data()
                data["next"] = target
                response = self.client.post(reverse("core:meal-add"), data)
                self.assertEqual(response.url, reverse("core:meal-list"))

    def test_update_keeps_the_existing_record_date_and_child(self):
        self.client.get(
            reverse("core:daily-summary"),
            {"child": self.other_child.pk, "date": self.day - timedelta(days=1)},
        )
        response = self.client.get(reverse("core:meal-update", args=[self.meal.pk]))
        self.assertEqual(response.context["form"]["child"].value(), self.child.pk)
        self.assertEqual(response.context["form"].initial["time"], self.when)

    def test_a_user_session_does_not_change_another_users_context(self):
        self.choose_day()
        other_user = get_user_model().objects.create_user(username="other-context")
        other_user.user_permissions.add(
            Permission.objects.get(content_type__app_label="core", codename="view_meal")
        )
        other_client = Client()
        other_client.force_login(other_user)
        response = other_client.get(reverse("core:meal-list"))
        self.assertIsNone(response.context["record_context"]["child"])
        self.assertEqual(response.context["object_list"].count(), 3)

    def test_child_page_switch_preserves_the_selected_day(self):
        response = self.client.get(
            reverse("core:child", args=[self.child.slug]),
            {"child": self.other_child.pk, "date": self.day},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            urlsplit(response.url).path,
            reverse("core:child", args=[self.other_child.slug]),
        )
        self.assertEqual(
            parse_qs(urlsplit(response.url).query)["date"], [self.day.isoformat()]
        )

    def test_links_to_a_child_with_accents_do_not_switch_to_the_previous_child(self):
        child = models.Child.objects.create(
            first_name="Lucía", birth_date=self.child.birth_date
        )
        source = self.client.get(reverse("core:meal-list"), {"child": self.child.pk})
        from core.navigation import contextual_url

        link = contextual_url(source.wsgi_request, "core:child", child.slug)
        self.assertEqual(parse_qs(urlsplit(link).query)["child"], [str(child.pk)])
        response = self.client.get(link)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object"], child)

    def test_links_between_details_do_not_accumulate_nested_return_urls(self):
        prescription = models.Prescription.objects.create(
            visit=models.HealthVisit.objects.create(
                child=self.child, reason="Revisión"
            ),
            name="Prueba",
            instructions="Pauta indicada",
        )
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="core", codename="view_prescription"
            )
        )
        origin = reverse("core:prescription-list") + "?child=" + str(self.child.pk)
        source = self.client.get(
            reverse("core:prescription-detail", args=[prescription.pk]),
            {"next": origin},
        )
        from core.navigation import contextual_url

        link = contextual_url(
            source.wsgi_request, "core:visit-detail", prescription.visit_id
        )
        self.assertEqual(parse_qs(urlsplit(link).query)["next"], [origin])

    def test_deleting_the_last_item_on_a_page_keeps_the_filters_and_opens_the_last_page(
        self,
    ):
        self.user.settings.pagination_count = 1
        self.user.settings.save(update_fields=["pagination_count"])
        origin = (
            reverse("core:meal-list")
            + "?"
            + urlencode({"child": self.child.pk, "page": 2})
        )
        last = models.Meal.objects.filter(child=self.child).order_by("time").first()
        response = self.client.post(
            reverse("core:meal-delete", args=[last.pk]), {"next": origin}
        )
        self.assertEqual(response.url, origin)
        response = self.client.get(response.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 1)
        self.assertEqual(list(response.context["object_list"]), [self.meal])

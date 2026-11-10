import re
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from core import models
from core.templatetags.mobile_records import mobile_record_cards, quick_record_links


class MobileRecordsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="mobile-reader")
        cls.child = models.Child.objects.create(
            first_name="Ana", birth_date=timezone.localdate() - timedelta(days=200)
        )
        cls.other_child = models.Child.objects.create(
            first_name="Luis", birth_date=cls.child.birth_date
        )
        cls.meals = [
            models.Meal.objects.create(
                child=cls.child,
                time=timezone.now() - timedelta(hours=index + 1),
                notes="Notas que se pueden consultar",
                meal_type="lunch",
            )
            for index in range(3)
        ]

    def setUp(self):
        self.client.force_login(self.user)

    def grant(self, *codenames):
        self.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core", codename__in=codenames
            )
        )
        # The direct inclusion-tag tests reuse this instance between checks.
        for name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            self.user.__dict__.pop(name, None)

    def context(self, **kwargs):
        request = RequestFactory().get("/")
        request.user = self.user
        return {"request": request, **kwargs}

    def test_reading_cards_does_not_offer_mutations_without_permission(self):
        self.grant("view_meal")
        response = self.client.get(reverse("core:meal-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-record-card="meal"', count=3)
        self.assertContains(response, self.meals[0].notes)
        cards = mobile_record_cards(self.context(), self.meals)["cards"]
        self.assertTrue(
            all("update_url" not in card and "delete_url" not in card for card in cards)
        )
        self.assertEqual(models.Meal.objects.count(), 3)
        self.assertEqual(
            self.client.get(
                reverse("core:meal-update", args=[self.meals[0].pk])
            ).status_code,
            403,
        )

    def test_cards_follow_the_filtered_paginated_queryset(self):
        self.grant("view_meal")
        settings = self.user.settings
        settings.pagination_count = 2
        settings.save(update_fields=["pagination_count"])
        models.Meal.objects.create(child=self.other_child, time=timezone.now())
        before = models.Meal.objects.count()
        seen = []
        for page, expected in ((1, 2), (2, 1)):
            response = self.client.get(
                reverse("core:meal-list"), {"child": self.child.pk, "page": page}
            )
            self.assertEqual(response.status_code, 200)
            ids = re.findall(r'data-record-id="(\d+)"', response.content.decode())
            self.assertEqual(len(ids), expected)
            seen.extend(map(int, ids))
        self.assertCountEqual(seen, [meal.pk for meal in self.meals])
        self.assertEqual(models.Meal.objects.count(), before)

    def test_card_actions_use_the_existing_confirmation_urls(self):
        self.grant("change_meal", "delete_meal")
        card = mobile_record_cards(self.context(), self.meals[:1])["cards"][0]
        self.assertEqual(
            card["update_url"], reverse("core:meal-update", args=[self.meals[0].pk])
        )
        self.assertEqual(
            card["delete_url"], reverse("core:meal-delete", args=[self.meals[0].pk])
        )

    def test_food_profile_edit_uses_the_model_permission(self):
        profile = models.ChildFoodProfile.objects.create(
            child=self.child, food=models.Food.objects.first()
        )
        self.grant("change_childfoodprofile")
        card = mobile_record_cards(self.context(), [profile])["cards"][0]
        self.assertEqual(
            card["update_url"],
            reverse("core:child-food-profile-update", args=[profile.pk]),
        )
        self.assertNotIn("delete_url", card)

    def test_quick_links_respect_permissions_and_keep_the_explicit_child(self):
        self.assertEqual(quick_record_links(self.context())["primary_links"], [])
        self.grant("add_meal", "add_medication")
        result = quick_record_links(self.context(child=self.child))
        self.assertEqual(len(result["primary_links"]), 2)
        self.assertEqual(result["other_links"], [])
        for link in result["primary_links"]:
            self.assertEqual(
                parse_qs(urlsplit(link["url"]).query), {"child": [self.child.slug]}
            )
        # A general list must still let the form ask which child to use.
        result = quick_record_links(self.context())
        self.assertTrue(
            all(not urlsplit(link["url"]).query for link in result["primary_links"])
        )

    def test_health_card_keeps_details_separate_from_editing(self):
        visit = models.HealthVisit.objects.create(child=self.child, reason="Revisión")
        self.grant("view_healthvisit")
        card = mobile_record_cards(self.context(), [visit])["cards"][0]
        self.assertEqual(
            card["detail_url"], reverse("core:visit-detail", args=[visit.pk])
        )
        self.assertNotIn("update_url", card)

    def test_timer_duration_is_rendered_as_a_value(self):
        timer = models.Timer.objects.create(
            user=self.user,
            child=self.child,
            start=timezone.now() - timedelta(minutes=5),
        )
        card = mobile_record_cards(self.context(), [timer])["cards"][0]
        self.assertNotIn("bound method", card["summary"])
        self.assertIn("5", card["summary"])

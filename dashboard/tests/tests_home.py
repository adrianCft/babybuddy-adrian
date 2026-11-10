from datetime import date, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Child, HealthVisit, Medication, Sleep, Timer


class HomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("home-owner", is_superuser=True)
        cls.other = get_user_model().objects.create_user(
            "other-owner", is_superuser=True
        )
        cls.child = Child.objects.create(
            first_name="Lucía", birth_date=date(2026, 1, 1)
        )
        cls.url = reverse("dashboard:dashboard-child", args=[cls.child.slug])

    def setUp(self):
        self.client.force_login(self.user)

    def test_home_shows_only_the_next_scheduled_visit_for_this_child(self):
        now = timezone.now()
        for reason, days, status in (
            ("Earlier cancelled appointment", 1, "cancelled"),
            ("Past appointment", -1, "planned"),
            ("Upcoming appointment", 2, "planned"),
            ("Later appointment", 3, "planned"),
        ):
            HealthVisit.objects.create(
                child=self.child, reason=reason, date=now + timedelta(days=days), status=status
            )
        response = self.client.get(self.url)
        self.assertEqual(response.context["home"]["next_visit"].reason, "Upcoming appointment")
        self.assertContains(response, reverse("core:visit-add"))
        self.assertNotContains(response, "Later appointment")

    def test_medication_countdown_uses_the_recorded_interval(self):
        dose = Medication.objects.create(
            child=self.child, name="Example", dosage=1, dosage_unit="ml",
            time=timezone.now() - timedelta(minutes=5), next_dose_interval=timedelta(hours=4),
        )
        response = self.client.get(self.url)
        self.assertContains(response, f'data-dose-deadline="{int(dose.next_dose_time.timestamp())}"')
        dose.next_dose_interval = None
        dose.save(update_fields=["next_dose_interval"])
        self.assertNotContains(self.client.get(self.url), "data-dose-deadline=\"")

    def save_layout(self, **data):
        return self.client.post(self.url + "?date=2026-06-17", data)

    def test_favorites_are_ordered_personal_and_keep_other_cards_accessible(self):
        response = self.save_layout(cards=["sleep-last", "feeding-last"], hide_empty="")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(parse_qs(urlsplit(response.url).query)["date"], ["2026-06-17"])
        response = self.client.get(response.url)
        self.assertEqual(
            [card["key"] for card in response.context["home"]["favorites"]],
            ["sleep-last", "feeding-last"],
        )
        self.assertIn(
            "meal-summary", [card["key"] for card in response.context["home"]["others"]]
        )
        self.assertContains(response, '<div class="card card-dashboard')
        self.assertNotContains(response, '&lt;div class="card card-dashboard')
        self.user.settings.refresh_from_db()
        self.other.settings.refresh_from_db()
        self.assertEqual(
            self.user.settings.dashboard_cards, ["sleep-last", "feeding-last"]
        )
        self.assertIsNone(self.other.settings.dashboard_cards)
        self.assertEqual(Child.objects.count(), 1)
        self.assertEqual(Timer.objects.count(), 0)
        self.assertEqual(Sleep.objects.count(), 0)

    def test_invalid_or_excessive_favorites_leave_preferences_unchanged(self):
        self.save_layout(cards=["sleep-last"])
        for selected in (
            ["not-a-card"],
            ["sleep-last", "sleep-last"],
            [
                "feeding-last",
                "diaper-change-last",
                "meal-summary",
                "sleep-last",
                "medication-last",
                "pumping-last",
                "statistics",
            ],
        ):
            response = self.save_layout(cards=selected)
            self.assertEqual(response.status_code, 400)
            self.user.settings.refresh_from_db()
            self.assertEqual(self.user.settings.dashboard_cards, ["sleep-last"])

    def test_hide_empty_and_no_favorites_do_not_hide_sleep_controls(self):
        self.save_layout(cards=["feeding-last"], hide_empty="on")
        response = self.client.get(self.url)
        self.assertEqual(response.context["home"]["favorites"], [])
        self.assertContains(response, "data-home-sleep")
        self.assertContains(response, 'name="kind" value="sleep"')
        self.save_layout(cards=[])
        self.assertEqual(self.client.get(self.url).context["home"]["favorites"], [])
        self.save_layout(reset_home="1")
        self.user.settings.refresh_from_db()
        self.assertIsNone(self.user.settings.dashboard_cards)

    def test_sleep_indicator_ignores_generic_and_other_children_timers(self):
        other_child = Child.objects.create(
            first_name="Otro", birth_date=date(2026, 1, 1)
        )
        Timer.objects.create(child=self.child, name="Unrelated timer", user=self.user)
        Timer.objects.create(child=other_child, name=Timer.SLEEP_NAME, user=self.user)
        response = self.client.get(self.url)
        self.assertIsNone(response.context["home_sleep"]["timer"])
        self.assertNotContains(response, "card-timer")
        timer = Timer.objects.create(
            child=self.child, name=Timer.SLEEP_NAME, user=self.user
        )
        response = self.client.get(self.url)
        self.assertEqual(response.context["home_sleep"]["timer"], timer)
        self.assertContains(
            response, reverse("core:sleep-finish-quick", args=[timer.pk])
        )
        self.assertContains(response, "btn-dashboard-sleep", count=1)
        response = self.client.get(reverse("dashboard:dashboard"), {"child": ""})
        children = {child.pk: child for child in response.context["objects"]}
        self.assertEqual(children[self.child.pk].active_sleep, timer)

    def test_existing_sleep_workflow_starts_and_finishes_and_returns_home(self):
        home = self.url + "?child=" + str(self.child.pk) + "&date=2026-06-17"
        response = self.client.post(
            reverse("core:timer-add-quick"),
            {"child": self.child.pk, "kind": "sleep", "next": home},
        )
        self.assertEqual(response.url, home)
        timer = Timer.objects.get(child=self.child, name=Timer.SLEEP_NAME)
        timer.start = timezone.now() - timedelta(minutes=30)
        timer.save()
        response = self.client.post(
            reverse("core:sleep-finish-quick", args=[timer.pk]), {"next": home}
        )
        self.assertEqual(response.url, home)
        self.assertEqual(Sleep.objects.filter(child=self.child).count(), 1)
        self.assertFalse(
            Timer.objects.filter(
                child=self.child, name=Timer.SLEEP_NAME, active=True
            ).exists()
        )

    def test_permissions_and_csrf_protect_customization_and_hidden_data(self):
        reader = get_user_model().objects.create_user("limited-reader")
        reader.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="core",
                codename__in=["view_child", "view_feeding"],
            )
        )
        self.client.force_login(reader)
        response = self.client.get(self.url)
        cards = (
            response.context["home"]["favorites"] + response.context["home"]["others"]
        )
        self.assertEqual(
            {card["key"] for card in cards},
            {"feeding-last", "feeding-last-method", "feeding-recent", "breastfeeding"},
        )
        self.assertNotContains(response, "data-home-sleep")
        self.assertEqual(self.save_layout(cards=["statistics"]).status_code, 400)
        client = Client(enforce_csrf_checks=True)
        client.force_login(reader)
        self.assertEqual(
            client.post(self.url, {"cards": ["feeding-last"]}).status_code, 403
        )
        reader.user_permissions.clear()
        self.assertEqual(self.client.post(self.url, {"cards": []}).status_code, 403)

    def test_home_actions_preserve_child_day_and_return_destination(self):
        response = self.client.get(self.url, {"date": "2026-06-17"})
        from html.parser import HTMLParser

        class Links(HTMLParser):
            urls = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "a" and "btn-dashboard-add-link" in attrs.get("class", ""):
                    self.urls.append(attrs["href"])

        parser = Links()
        parser.feed(response.content.decode())
        self.assertEqual(len(parser.urls), 6)
        for url in parser.urls:
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(query["child"], [self.child.slug])
            self.assertEqual(query["date"], ["2026-06-17"])
            self.assertEqual(query["next"], [unquote(self.url) + "?date=2026-06-17"])

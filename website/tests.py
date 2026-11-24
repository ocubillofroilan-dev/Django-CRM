from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Note, Record
from .roles import AGENT_GROUP, MANAGER_GROUP, ensure_roles

User = get_user_model()
PASSWORD = "S3cure-pass-phrase!"


def make_user(username, manager=False, **extra):
    user = User.objects.create_user(
        username=username, password=PASSWORD, email=f"{username}@example.com", **extra
    )
    if manager:
        _, manager_group = ensure_roles()
        user.groups.add(manager_group)
        user = User.objects.get(pk=user.pk)  # drop cached permissions
    return user


def make_record(owner, first="Ana", last="Cruz", **extra):
    data = dict(
        first_name=first,
        last_name=last,
        email=f"{first}.{last}@example.com".lower(),
        phone="+63 912 345 6789",
        address="1 Rizal St",
        city="Calauan",
        province="Laguna",
        zipcode="4012",
        owner=owner,
    )
    data.update(extra)
    return Record.objects.create(**data)


def form_data(**extra):
    data = {
        "first_name": "Maria",
        "last_name": "Santos",
        "email": "Maria@Example.com",
        "phone": "09123456789",
        "status": "lead",
        "address": "2 Mabini St",
        "city": "Calauan",
        "province": "Laguna",
        "zipcode": "4012",
        "notes": "",
    }
    data.update(extra)
    return data


@override_settings(SECURE_SSL_REDIRECT=False)
class BaseTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.boss = make_user("boss", manager=True)
        self.alice_record = make_record(self.alice, "Ana", "Cruz")
        self.bob_record = make_record(self.bob, "Ben", "Reyes")


class VisibilityTests(BaseTestCase):
    def test_agent_only_sees_own_records(self):
        self.assertEqual(list(Record.objects.visible_to(self.alice)), [self.alice_record])

    def test_manager_sees_everything(self):
        self.assertEqual(Record.objects.visible_to(self.boss).count(), 2)

    def test_superuser_sees_everything(self):
        root = User.objects.create_superuser("root", "root@example.com", PASSWORD)
        self.assertEqual(Record.objects.visible_to(root).count(), 2)

    def test_unowned_records_are_manager_only(self):
        make_record(None, "No", "Owner")
        self.assertEqual(Record.objects.visible_to(self.alice).count(), 1)
        self.assertEqual(Record.objects.visible_to(self.boss).count(), 3)

    def test_inactive_user_sees_nothing(self):
        self.alice.is_active = False
        self.assertEqual(Record.objects.visible_to(self.alice).count(), 0)


class AccessControlTests(BaseTestCase):
    def test_anonymous_users_are_sent_to_login(self):
        urls = [
            reverse("home"),
            reverse("add_record"),
            reverse("record", args=[self.alice_record.pk]),
            reverse("export_records"),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("login"), response["Location"])

    def test_agent_cannot_read_edit_or_delete_others_records(self):
        self.client.force_login(self.alice)
        for name in ("record", "update_record", "delete_record"):
            response = self.client.get(reverse(name, args=[self.bob_record.pk]))
            self.assertEqual(response.status_code, 404, name)
        response = self.client.post(reverse("delete_record", args=[self.bob_record.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Record.objects.filter(pk=self.bob_record.pk).exists())

    def test_manager_can_open_any_record(self):
        self.client.force_login(self.boss)
        response = self.client.get(reverse("record", args=[self.bob_record.pk]))
        self.assertEqual(response.status_code, 200)

    def test_delete_requires_post_and_csrf(self):
        self.client.force_login(self.alice)
        url = reverse("delete_record", args=[self.alice_record.pk])
        self.assertEqual(self.client.get(url).status_code, 200)  # confirm page only
        self.assertTrue(Record.objects.filter(pk=self.alice_record.pk).exists())

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.alice)
        self.assertEqual(strict.post(url).status_code, 403)
        self.assertTrue(Record.objects.filter(pk=self.alice_record.pk).exists())

        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(Record.objects.filter(pk=self.alice_record.pk).exists())

    def test_logout_rejects_get(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)


class CrudTests(BaseTestCase):
    def test_create_sets_owner_and_normalises_email(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("add_record"), form_data())
        record = Record.objects.get(first_name="Maria")
        self.assertRedirects(response, reverse("record", args=[record.pk]))
        self.assertEqual(record.owner, self.alice)
        self.assertEqual(record.email, "maria@example.com")

    def test_agent_form_has_no_owner_field_and_ignores_tampering(self):
        self.client.force_login(self.alice)
        self.assertNotIn("owner", self.client.get(reverse("add_record")).context["form"].fields)
        self.client.post(reverse("add_record"), form_data(owner=self.bob.pk))
        self.assertEqual(Record.objects.get(first_name="Maria").owner, self.alice)

    def test_agent_cannot_reassign_on_update(self):
        self.client.force_login(self.alice)
        self.client.post(
            reverse("update_record", args=[self.alice_record.pk]),
            form_data(first_name="Ana", owner=self.bob.pk),
        )
        self.alice_record.refresh_from_db()
        self.assertEqual(self.alice_record.owner, self.alice)

    def test_manager_can_reassign(self):
        self.client.force_login(self.boss)
        self.client.post(
            reverse("update_record", args=[self.alice_record.pk]),
            form_data(first_name="Ana", owner=self.bob.pk),
        )
        self.alice_record.refresh_from_db()
        self.assertEqual(self.alice_record.owner, self.bob)

    def test_validation_rejects_bad_email_and_phone(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("add_record"), form_data(email="nope", phone="abc"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertIn("phone", response.context["form"].errors)
        self.assertFalse(Record.objects.filter(first_name="Maria").exists())


class ListTests(BaseTestCase):
    def test_list_only_shows_own_records(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Ana Cruz")
        self.assertNotContains(response, "Ben Reyes")

    def test_search_and_status_filter(self):
        make_record(self.alice, "Zed", "Active", status="active")
        self.client.force_login(self.alice)
        response = self.client.get(reverse("home"), {"q": "zed"})
        self.assertEqual([r.first_name for r in response.context["records"]], ["Zed"])
        response = self.client.get(reverse("home"), {"status": "active"})
        self.assertEqual(len(response.context["records"]), 1)
        response = self.client.get(reverse("home"), {"status": "bogus"})
        self.assertEqual(len(response.context["records"]), 2)

    def test_pagination(self):
        for i in range(12):
            make_record(self.alice, f"P{i}", "Page")
        self.client.force_login(self.alice)
        self.assertEqual(len(self.client.get(reverse("home")).context["records"]), 10)
        self.assertEqual(len(self.client.get(reverse("home"), {"page": 2}).context["records"]), 3)

    def test_ajax_returns_partial_only(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("home"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertNotContains(response, "<html")
        self.assertContains(response, "Ana Cruz")
        self.assertIn("X-Requested-With", response["Vary"])

    def test_stats_only_count_visible_records(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("home")).context["stats"]["total"], 1)


class ExportTests(BaseTestCase):
    def test_csv_contains_only_visible_rows(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("export_records"))
        body = response.content.decode("utf-8")
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Ana", body)
        self.assertNotIn("Ben", body)

    def test_csv_neutralises_formula_injection(self):
        make_record(self.alice, "=HYPERLINK(\"http://evil\")", "Evil")
        self.client.force_login(self.alice)
        body = self.client.get(reverse("export_records")).content.decode("utf-8")
        self.assertIn("'=HYPERLINK", body)


class NoteTests(BaseTestCase):
    def test_add_note(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("add_note", args=[self.alice_record.pk]), {"body": "Called, will follow up."})
        note = Note.objects.get()
        self.assertEqual((note.author, note.record), (self.alice, self.alice_record))

    def test_cannot_add_note_to_others_record(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("add_note", args=[self.bob_record.pk]), {"body": "hi"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Note.objects.count(), 0)

    def test_only_author_or_manager_can_delete_note(self):
        note = Note.objects.create(record=self.alice_record, author=self.alice, body="x")
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse("delete_note", args=[note.pk])).status_code, 404)
        self.client.force_login(self.boss)
        self.assertEqual(self.client.post(reverse("delete_note", args=[note.pk])).status_code, 302)
        self.assertEqual(Note.objects.count(), 0)


class LoginTests(BaseTestCase):
    def login(self, password=PASSWORD, **extra):
        return self.client.post(reverse("login"), {"username": "alice", "password": password, **extra})

    def test_login_success_redirects_home(self):
        self.assertRedirects(self.login(), reverse("home"))

    def test_login_ignores_external_next(self):
        response = self.login(next="https://evil.example/steal")
        self.assertRedirects(response, reverse("home"))

    def test_login_follows_safe_next(self):
        response = self.login(next=reverse("add_record"))
        self.assertRedirects(response, reverse("add_record"))

    @override_settings(LOGIN_MAX_ATTEMPTS=3)
    def test_lockout_after_repeated_failures(self):
        for _ in range(3):
            self.assertEqual(self.login("wrong-password").status_code, 200)
        self.assertEqual(self.login(PASSWORD).status_code, 429)  # even the right password is refused

    @override_settings(LOGIN_MAX_ATTEMPTS=3)
    def test_success_resets_failure_counter(self):
        self.login("wrong-password")
        self.login("wrong-password")
        self.assertEqual(self.login(PASSWORD).status_code, 302)
        self.client.post(reverse("logout"))
        self.assertEqual(self.login("wrong-password").status_code, 200)


class RegistrationTests(BaseTestCase):
    def payload(self, **extra):
        data = {
            "first_name": "Nina",
            "last_name": "Lopez",
            "email": "nina@example.com",
            "username": "nina",
            "password1": "Correct-horse-battery-9",
            "password2": "Correct-horse-battery-9",
        }
        data.update(extra)
        return data

    def test_register_creates_agent_and_signs_in(self):
        response = self.client.post(reverse("register"), self.payload())
        self.assertRedirects(response, reverse("home"))
        user = User.objects.get(username="nina")
        self.assertTrue(user.groups.filter(name=AGENT_GROUP).exists())
        self.assertFalse(user.groups.filter(name=MANAGER_GROUP).exists())
        self.assertEqual(Record.objects.visible_to(user).count(), 0)

    def test_duplicate_email_rejected(self):
        response = self.client.post(reverse("register"), self.payload(email="ALICE@example.com"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="nina").exists())

    def test_weak_password_rejected(self):
        response = self.client.post(
            reverse("register"), self.payload(password1="12345678", password2="12345678")
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="nina").exists())

    @override_settings(ALLOW_REGISTRATION=False)
    def test_registration_can_be_closed(self):
        self.assertEqual(self.client.get(reverse("register")).status_code, 404)


class PasswordFlowTests(BaseTestCase):
    def test_reset_email_is_sent_for_known_address(self):
        from django.core import mail

        response = self.client.post(reverse("password_reset"), {"email": "alice@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/password-reset/", mail.outbox[0].body)

    def test_reset_does_not_reveal_unknown_addresses(self):
        from django.core import mail

        response = self.client.post(reverse("password_reset"), {"email": "ghost@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_is_rate_limited(self):
        for _ in range(5):
            self.client.post(reverse("password_reset"), {"email": "alice@example.com"})
        self.assertEqual(
            self.client.post(reverse("password_reset"), {"email": "alice@example.com"}).status_code, 429
        )

    def test_change_password_requires_login(self):
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 302)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 200)


class RoleCommandTests(BaseTestCase):
    def test_setup_roles_promotes_and_assigns(self):
        from django.core.management import call_command

        orphan = make_record(None, "Or", "Phan")
        call_command("setup_roles", manager=["alice"], assign_unowned="alice", stdout=open("/dev/null", "w"))
        orphan.refresh_from_db()
        self.assertEqual(orphan.owner, self.alice)
        alice = User.objects.get(pk=self.alice.pk)
        self.assertTrue(alice.groups.filter(name=MANAGER_GROUP).exists())
        self.assertTrue(Group.objects.filter(name=AGENT_GROUP).exists())


class ApiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()

    def token_for(self, username):
        response = self.api.post(
            reverse("api-token"), {"username": username, "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["token"]

    def test_requires_authentication(self):
        self.assertIn(self.api.get("/api/v1/customers/").status_code, (401, 403))

    def test_token_auth_lists_only_own_records(self):
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {self.token_for('alice')}")
        data = self.api.get("/api/v1/customers/").json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["last_name"], "Cruz")

    def test_other_users_record_is_404(self):
        self.api.force_authenticate(self.alice)
        self.assertEqual(self.api.get(f"/api/v1/customers/{self.bob_record.pk}/").status_code, 404)
        self.assertEqual(self.api.delete(f"/api/v1/customers/{self.bob_record.pk}/").status_code, 404)

    def test_create_sets_owner_and_ignores_owner_in_payload(self):
        self.api.force_authenticate(self.alice)
        payload = form_data(owner="bob")
        payload.pop("notes")
        response = self.api.post("/api/v1/customers/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["owner"], "alice")

    def test_validation_errors_are_400(self):
        self.api.force_authenticate(self.alice)
        response = self.api.post("/api/v1/customers/", form_data(email="bad"), format="json")
        self.assertEqual(response.status_code, 400)

    def test_manager_sees_all(self):
        self.api.force_authenticate(self.boss)
        self.assertEqual(self.api.get("/api/v1/customers/").json()["count"], 2)

    def test_search_and_stats(self):
        self.api.force_authenticate(self.alice)
        self.assertEqual(self.api.get("/api/v1/customers/", {"search": "zzz"}).json()["count"], 0)
        self.assertEqual(self.api.get("/api/v1/customers/stats/").json()["total"], 1)

    def test_timeline(self):
        self.api.force_authenticate(self.alice)
        url = f"/api/v1/customers/{self.alice_record.pk}/timeline/"
        self.assertEqual(self.api.post(url, {"body": "Hello"}, format="json").status_code, 201)
        self.assertEqual(self.api.get(url).json()["count"], 1)

    def test_token_revoke(self):
        token = self.token_for("alice")
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.api.post(reverse("api-token-revoke")).status_code, 204)
        self.assertIn(self.api.get("/api/v1/me/").status_code, (401, 403))

    def test_token_endpoint_is_throttled(self):
        statuses = [
            self.api.post(reverse("api-token"), {"username": "alice", "password": "x"}, format="json").status_code
            for _ in range(7)
        ]
        self.assertIn(429, statuses)
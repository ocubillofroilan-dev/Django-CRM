from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Company, Contact, Note
from .utils import normalize_domains
from .verification import verify_sender

User = get_user_model()
PASSWORD = "S3cure-pass-phrase!"


def make_staff(username):
    return User.objects.create_user(username=username, password=PASSWORD, email=f"{username}@example.com")


def make_admin(username="boss"):
    return User.objects.create_superuser(username=username, password=PASSWORD, email=f"{username}@example.com")


def make_company(name="Everbest", status="client", domains="everbest.com", **extra):
    return Company.objects.create(name=name, status=status, email_domains=domains, **extra)


def make_contact(first="Ana", last="Cruz", company=None, email=None, can_request=True, **extra):
    data = dict(
        first_name=first,
        last_name=last,
        email=email or f"{first}.{last}@example.com".lower(),
        phone="+63 912 345 6789",
        company=company,
        can_request=can_request,
    )
    data.update(extra)
    return Contact.objects.create(**data)


def contact_form(**extra):
    data = {
        "first_name": "Maria",
        "last_name": "Santos",
        "email": "Maria@Example.com",
        "phone": "09123456789",
        "status": "lead",
        "can_request": "on",
    }
    data.update(extra)
    return data


@override_settings(SECURE_SSL_REDIRECT=False)
class BaseTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.ana = make_staff("ana")
        self.ben = make_staff("ben")
        self.boss = make_admin()
        self.company = make_company()
        self.maria = make_contact("Maria", "Santos", self.company, "maria@everbest.com")


# --------------------------------------------------------------------------
class UtilsTests(TestCase):
    def test_normalize_domains(self):
        self.assertEqual(normalize_domains("@Everbest.com, everbest.ph;  EVERBEST.com"), ["everbest.com", "everbest.ph"])
        self.assertEqual(normalize_domains(""), [])

    def test_normalize_rejects_garbage(self):
        for bad in ("not a domain!", "nodots", "-bad.com", "http://x.com"):
            with self.assertRaises(ValueError):
                normalize_domains(bad)


class VerificationTests(BaseTestCase):
    def test_registered_contact_of_active_client_is_verified(self):
        result = verify_sender("MARIA@everbest.com")
        self.assertEqual(result.level, "verified")
        self.assertEqual((result.contact, result.company), (self.maria, self.company))
        self.assertTrue(result.is_trusted)

    def test_contact_who_cannot_request_is_only_known(self):
        make_contact("Liza", "Cruz", self.company, "liza@everbest.com", can_request=False)
        self.assertEqual(verify_sender("liza@everbest.com").level, "known")

    def test_contact_of_prospect_is_only_known(self):
        prospect = make_company("Dental", status="prospect", domains="dental.ph")
        make_contact("Paolo", "Lim", prospect, "paolo@dental.ph")
        self.assertEqual(verify_sender("paolo@dental.ph").level, "known")

    def test_contact_without_company_is_only_known(self):
        make_contact("Solo", "Person", None, "solo@example.com")
        self.assertEqual(verify_sender("solo@example.com").level, "known")

    def test_client_domain_but_unknown_person(self):
        result = verify_sender("stranger@everbest.com")
        self.assertEqual(result.level, "domain")
        self.assertEqual(result.company, self.company)
        self.assertIsNone(result.contact)

    def test_domain_match_is_exact_not_substring(self):
        self.assertEqual(verify_sender("x@noteverbest.com").level, "unverified")
        self.assertEqual(verify_sender("x@everbest.com.evil.net").level, "unverified")

    def test_unknown_and_invalid(self):
        self.assertEqual(verify_sender("someone@gmail.com").level, "unverified")
        self.assertEqual(verify_sender("not-an-email").level, "invalid")
        self.assertEqual(verify_sender("").level, "invalid")


class AccessControlTests(BaseTestCase):
    def test_anonymous_users_are_sent_to_login(self):
        urls = [
            reverse("home"),
            reverse("contact_list"),
            reverse("contact_add"),
            reverse("contact_detail", args=[self.maria.pk]),
            reverse("company_list"),
            reverse("company_detail", args=[self.company.pk]),
            reverse("contact_export"),
            reverse("team_list"),
            reverse("pipeline"),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("login"), response["Location"])

    def test_staff_see_everything_and_can_edit_others_records(self):
        self.client.force_login(self.ana)
        self.assertContains(self.client.get(reverse("contact_list")), "Maria Santos")
        response = self.client.post(
            reverse("contact_edit", args=[self.maria.pk]),
            contact_form(first_name="Maria", last_name="Santos", email="maria@everbest.com", job_title="CFO"),
        )
        self.assertEqual(response.status_code, 302)
        self.maria.refresh_from_db()
        self.assertEqual(self.maria.job_title, "CFO")

    def test_staff_cannot_delete(self):
        self.client.force_login(self.ana)
        for name, pk in (("contact_delete", self.maria.pk), ("company_delete", self.company.pk)):
            url = reverse(name, args=[pk])
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(Contact.objects.filter(pk=self.maria.pk).exists())
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_staff_do_not_see_delete_buttons(self):
        self.client.force_login(self.ana)
        self.assertNotContains(self.client.get(reverse("contact_list")), "data-confirm-delete")
        self.client.force_login(self.boss)
        self.assertContains(self.client.get(reverse("contact_list")), "data-confirm-delete")

    def test_admin_delete_requires_post_and_csrf(self):
        self.client.force_login(self.boss)
        url = reverse("contact_delete", args=[self.maria.pk])
        self.assertEqual(self.client.get(url).status_code, 200)  # confirmation page only
        self.assertTrue(Contact.objects.filter(pk=self.maria.pk).exists())

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.boss)
        self.assertEqual(strict.post(url).status_code, 403)
        self.assertTrue(Contact.objects.filter(pk=self.maria.pk).exists())

        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(Contact.objects.filter(pk=self.maria.pk).exists())

    def test_deleting_a_company_keeps_its_contacts(self):
        self.client.force_login(self.boss)
        self.client.post(reverse("company_delete", args=[self.company.pk]))
        self.maria.refresh_from_db()
        self.assertIsNone(self.maria.company)

    def test_logout_rejects_get(self):
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)


class TeamTests(BaseTestCase):
    def new_member(self, **extra):
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

    def test_only_admin_can_open_team_pages(self):
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get(reverse("team_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("team_add")).status_code, 403)
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(reverse("team_list")).status_code, 200)

    def test_admin_creates_a_staff_account_that_can_sign_in(self):
        self.client.force_login(self.boss)
        response = self.client.post(reverse("team_add"), self.new_member())
        self.assertRedirects(response, reverse("team_list"))
        nina = User.objects.get(username="nina")
        self.assertFalse(nina.is_superuser)
        self.assertFalse(nina.is_staff)  # no access to the Django admin site
        self.assertTrue(Client().login(username="nina", password="Correct-horse-battery-9"))

    def test_staff_cannot_create_accounts(self):
        self.client.force_login(self.ana)
        self.assertEqual(self.client.post(reverse("team_add"), self.new_member()).status_code, 403)
        self.assertFalse(User.objects.filter(username="nina").exists())

    def test_weak_password_and_duplicate_email_rejected(self):
        self.client.force_login(self.boss)
        weak = self.new_member(password1="12345678", password2="12345678")
        self.assertEqual(self.client.post(reverse("team_add"), weak).status_code, 200)
        dupe = self.new_member(email="ANA@example.com")
        self.assertEqual(self.client.post(reverse("team_add"), dupe).status_code, 200)
        self.assertFalse(User.objects.filter(username="nina").exists())

    def test_toggle_disables_staff_but_not_admins_or_self(self):
        self.client.force_login(self.boss)
        self.client.post(reverse("team_toggle", args=[self.ana.pk]))
        self.ana.refresh_from_db()
        self.assertFalse(self.ana.is_active)
        self.client.post(reverse("team_toggle", args=[self.boss.pk]))
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.is_active)
        self.assertFalse(Client().login(username="ana", password=PASSWORD))

    def test_staff_cannot_toggle(self):
        self.client.force_login(self.ana)
        self.assertEqual(self.client.post(reverse("team_toggle", args=[self.ben.pk])).status_code, 403)


class ContactTests(BaseTestCase):
    def test_create_assigns_creator_by_default_and_lowercases_email(self):
        self.client.force_login(self.ana)
        response = self.client.post(reverse("contact_add"), contact_form(owner=self.ana.pk, company=self.company.pk))
        contact = Contact.objects.get(first_name="Maria", last_name="Santos", email="maria@example.com")
        self.assertRedirects(response, reverse("contact_detail", args=[contact.pk]))
        self.assertEqual(contact.owner, self.ana)
        self.assertEqual(contact.company, self.company)

    def test_duplicate_email_is_rejected(self):
        self.client.force_login(self.ana)
        response = self.client.post(reverse("contact_add"), contact_form(email="MARIA@everbest.com"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)

    def test_editing_a_contact_keeps_its_own_email(self):
        self.client.force_login(self.ana)
        response = self.client.post(
            reverse("contact_edit", args=[self.maria.pk]),
            contact_form(email="maria@everbest.com", first_name="Maria", last_name="Santos"),
        )
        self.assertEqual(response.status_code, 302)

    def test_validation_rejects_bad_email_and_phone(self):
        self.client.force_login(self.ana)
        response = self.client.post(reverse("contact_add"), contact_form(email="nope", phone="abc"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertIn("phone", response.context["form"].errors)

    def test_prefill_from_query_string(self):
        self.client.force_login(self.ana)
        response = self.client.get(reverse("contact_add"), {"email": "new@x.com", "company": self.company.pk})
        self.assertEqual(response.context["form"].initial["email"], "new@x.com")
        self.assertEqual(response.context["form"].initial["company"], self.company.pk)

    def test_search_by_company_name_and_status(self):
        make_contact("Zed", "Active", None, "zed@example.com", status="active")
        self.client.force_login(self.ana)
        by_company = self.client.get(reverse("contact_list"), {"q": "everbest"})
        self.assertEqual([c.first_name for c in by_company.context["contacts"]], ["Maria"])
        by_status = self.client.get(reverse("contact_list"), {"status": "active"})
        self.assertEqual([c.first_name for c in by_status.context["contacts"]], ["Zed"])
        ignored = self.client.get(reverse("contact_list"), {"status": "bogus"})
        self.assertEqual(len(ignored.context["contacts"]), 2)

    def test_company_filter(self):
        make_contact("Other", "Person", None, "other@example.com")
        self.client.force_login(self.ana)
        response = self.client.get(reverse("contact_list"), {"company": self.company.pk})
        self.assertEqual(len(response.context["contacts"]), 1)

    def test_pagination(self):
        for i in range(12):
            make_contact(f"P{i}", "Page", None, f"p{i}@example.com")
        self.client.force_login(self.ana)
        self.assertEqual(len(self.client.get(reverse("contact_list")).context["contacts"]), 10)
        self.assertEqual(len(self.client.get(reverse("contact_list"), {"page": 2}).context["contacts"]), 3)

    def test_ajax_returns_partial_only(self):
        self.client.force_login(self.ana)
        response = self.client.get(reverse("contact_list"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertNotContains(response, "<html")
        self.assertContains(response, "Maria Santos")
        self.assertIn("X-Requested-With", response["Vary"])

    def test_detail_shows_verification(self):
        self.client.force_login(self.ana)
        response = self.client.get(reverse("contact_detail", args=[self.maria.pk]))
        self.assertEqual(response.context["verification"].level, "verified")
        self.assertContains(response, "Verified client contact")

    def test_csv_export_and_formula_injection(self):
        make_contact("=HYPERLINK(\"http://evil\")", "Evil", None, "evil@example.com")
        self.client.force_login(self.ana)
        response = self.client.get(reverse("contact_export"))
        body = response.content.decode("utf-8")
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Maria", body)
        self.assertIn("'=HYPERLINK", body)


class NoteTests(BaseTestCase):
    def test_add_note(self):
        self.client.force_login(self.ana)
        self.client.post(reverse("note_add", args=[self.maria.pk]), {"body": "Called, will follow up."})
        note = Note.objects.get()
        self.assertEqual((note.author, note.contact), (self.ana, self.maria))

    def test_empty_note_is_rejected(self):
        self.client.force_login(self.ana)
        self.client.post(reverse("note_add", args=[self.maria.pk]), {"body": "  "})
        self.assertEqual(Note.objects.count(), 0)

    def test_only_author_or_admin_can_delete_note(self):
        note = Note.objects.create(contact=self.maria, author=self.ana, body="x")
        self.client.force_login(self.ben)
        self.assertEqual(self.client.post(reverse("note_delete", args=[note.pk])).status_code, 403)
        self.client.force_login(self.boss)
        self.assertEqual(self.client.post(reverse("note_delete", args=[note.pk])).status_code, 302)
        self.assertEqual(Note.objects.count(), 0)


class CompanyTests(BaseTestCase):
    def company_form(self, **extra):
        data = {"name": "Laguna Bright", "status": "client", "email_domains": "@LBLC.edu.ph, lblc.ph"}
        data.update(extra)
        return data

    def test_client_code_is_assigned(self):
        self.assertRegex(self.company.code, r"^CL-\d{4}$")
        other = make_company("Second", domains="second.com")
        self.assertNotEqual(self.company.code, other.code)

    def test_create_normalises_domains(self):
        self.client.force_login(self.ana)
        response = self.client.post(reverse("company_add"), self.company_form())
        company = Company.objects.get(name="Laguna Bright")
        self.assertRedirects(response, reverse("company_detail", args=[company.pk]))
        self.assertEqual(company.email_domains, "lblc.edu.ph, lblc.ph")
        self.assertEqual(company.domains, ["lblc.edu.ph", "lblc.ph"])

    def test_invalid_domain_is_rejected(self):
        self.client.force_login(self.ana)
        response = self.client.post(reverse("company_add"), self.company_form(email_domains="not a domain"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("email_domains", response.context["form"].errors)

    def test_duplicate_name_is_rejected(self):
        self.client.force_login(self.ana)
        response = self.client.post(reverse("company_add"), self.company_form(name="Everbest"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("name", response.context["form"].errors)

    def test_list_shows_contact_counts(self):
        self.client.force_login(self.ana)
        response = self.client.get(reverse("company_list"))
        self.assertEqual(response.context["companies"][0].contact_count, 1)

    def test_detail_shows_verification_notes_and_contacts(self):
        self.company.verification_notes = "Ask for the billing contact name."
        self.company.save()
        self.client.force_login(self.ana)
        response = self.client.get(reverse("company_detail", args=[self.company.pk]))
        self.assertContains(response, "Ask for the billing contact name.")
        self.assertContains(response, "Maria Santos")


class TodayTests(BaseTestCase):
    def test_today_page_and_verify_tool(self):
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        response = self.client.get(reverse("home"), {"verify": "stranger@gmail.com"})
        self.assertEqual(response.context["verification"].level, "unverified")
        self.assertContains(response, "Unknown sender")
        response = self.client.get(reverse("home"), {"verify": "boss@everbest.com"})
        self.assertEqual(response.context["verification"].level, "domain")

    def test_placeholder_pages_render(self):
        self.client.force_login(self.ana)
        for name in ("pipeline", "tasks", "tickets", "reports"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


class LoginTests(BaseTestCase):
    def login(self, password=PASSWORD, **extra):
        return self.client.post(reverse("login"), {"username": "ana", "password": password, **extra})

    def test_login_success_redirects_home(self):
        self.assertRedirects(self.login(), reverse("home"))

    def test_login_ignores_external_next(self):
        self.assertRedirects(self.login(next="https://evil.example/steal"), reverse("home"))

    def test_login_follows_safe_next(self):
        self.assertRedirects(self.login(next=reverse("contact_add")), reverse("contact_add"))

    def test_there_is_no_public_registration(self):
        self.assertEqual(self.client.get("/register/").status_code, 404)

    @override_settings(LOGIN_MAX_ATTEMPTS=3)
    def test_lockout_after_repeated_failures(self):
        for _ in range(3):
            self.assertEqual(self.login("wrong-password").status_code, 200)
        self.assertEqual(self.login(PASSWORD).status_code, 429)

    @override_settings(LOGIN_MAX_ATTEMPTS=3)
    def test_success_resets_failure_counter(self):
        self.login("wrong-password")
        self.login("wrong-password")
        self.assertEqual(self.login(PASSWORD).status_code, 302)
        self.client.post(reverse("logout"))
        self.assertEqual(self.login("wrong-password").status_code, 200)


class PasswordFlowTests(BaseTestCase):
    def test_reset_email_is_sent_for_known_address(self):
        response = self.client.post(reverse("password_reset"), {"email": "ana@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/password-reset/", mail.outbox[0].body)
        self.assertIn("ClientDesk", mail.outbox[0].subject)

    def test_reset_does_not_reveal_unknown_addresses(self):
        response = self.client.post(reverse("password_reset"), {"email": "ghost@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_is_rate_limited(self):
        for _ in range(5):
            self.client.post(reverse("password_reset"), {"email": "ana@example.com"})
        self.assertEqual(self.client.post(reverse("password_reset"), {"email": "ana@example.com"}).status_code, 429)

    def test_change_password_requires_login(self):
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 302)
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 200)


class SeedTests(TestCase):
    def test_seed_demo_is_repeatable(self):
        out = open("/dev/null", "w")
        call_command("seed_demo", stdout=out)
        counts = (Company.objects.count(), Contact.objects.count(), User.objects.count())
        call_command("seed_demo", stdout=out)
        self.assertEqual(counts, (Company.objects.count(), Contact.objects.count(), User.objects.count()))
        self.assertEqual(verify_sender("maria.santos@everbest.com.ph").level, "verified")


# --------------------------------------------------------------------------
class ApiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()

    def token_for(self, username):
        response = self.api.post(reverse("api-token"), {"username": username, "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200)
        return response.json()["token"]

    def contact_payload(self, **extra):
        data = {
            "first_name": "Nora",
            "last_name": "Diaz",
            "email": "Nora@Example.com",
            "phone": "09123456789",
            "status": "lead",
            "company": self.company.pk,
        }
        data.update(extra)
        return data

    def test_requires_authentication(self):
        self.assertIn(self.api.get("/api/v1/contacts/").status_code, (401, 403))

    def test_token_auth_lists_shared_contacts(self):
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {self.token_for('ana')}")
        data = self.api.get("/api/v1/contacts/").json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["company_name"], "Everbest")

    def test_create_contact_sets_owner_and_normalises_email(self):
        self.api.force_authenticate(self.ana)
        response = self.api.post("/api/v1/contacts/", self.contact_payload(owner="ben"), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["owner"], "ana")
        self.assertEqual(response.json()["email"], "nora@example.com")

    def test_duplicate_email_is_400(self):
        self.api.force_authenticate(self.ana)
        response = self.api.post("/api/v1/contacts/", self.contact_payload(email="maria@everbest.com"), format="json")
        self.assertEqual(response.status_code, 400)

    def test_staff_cannot_delete_but_admin_can(self):
        url = f"/api/v1/contacts/{self.maria.pk}/"
        self.api.force_authenticate(self.ana)
        self.assertEqual(self.api.delete(url).status_code, 403)
        self.api.force_authenticate(self.boss)
        self.assertEqual(self.api.delete(url).status_code, 204)

    def test_company_crud_and_domain_validation(self):
        self.api.force_authenticate(self.ana)
        ok = self.api.post("/api/v1/companies/", {"name": "New Co", "status": "prospect", "email_domains": "@New.co"}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(ok.json()["email_domains"], "new.co")
        self.assertRegex(ok.json()["code"], r"^CL-\d{4}$")
        bad = self.api.post("/api/v1/companies/", {"name": "Bad Co", "email_domains": "nope"}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_verify_endpoint(self):
        self.api.force_authenticate(self.ana)
        trusted = self.api.get("/api/v1/verify/", {"email": "maria@everbest.com"}).json()
        self.assertEqual((trusted["level"], trusted["trusted"]), ("verified", True))
        self.assertEqual(trusted["company"]["name"], "Everbest")
        unknown = self.api.get("/api/v1/verify/", {"email": "x@gmail.com"}).json()
        self.assertEqual((unknown["level"], unknown["trusted"]), ("unverified", False))

    def test_verify_requires_authentication(self):
        self.assertIn(self.api.get("/api/v1/verify/", {"email": "x@y.com"}).status_code, (401, 403))

    def test_me_reports_role(self):
        self.api.force_authenticate(self.ana)
        self.assertEqual(self.api.get("/api/v1/me/").json()["role"], "staff")
        self.api.force_authenticate(self.boss)
        self.assertEqual(self.api.get("/api/v1/me/").json()["role"], "admin")

    def test_search_stats_and_timeline(self):
        self.api.force_authenticate(self.ana)
        self.assertEqual(self.api.get("/api/v1/contacts/", {"search": "zzz"}).json()["count"], 0)
        self.assertEqual(self.api.get("/api/v1/companies/stats/").json()["clients"], 1)
        url = f"/api/v1/contacts/{self.maria.pk}/timeline/"
        self.assertEqual(self.api.post(url, {"body": "Hello"}, format="json").status_code, 201)
        self.assertEqual(self.api.get(url).json()["count"], 1)

    def test_token_revoke(self):
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {self.token_for('ana')}")
        self.assertEqual(self.api.post(reverse("api-token-revoke")).status_code, 204)
        self.assertIn(self.api.get("/api/v1/me/").status_code, (401, 403))

    def test_token_endpoint_is_throttled(self):
        statuses = [
            self.api.post(reverse("api-token"), {"username": "ana", "password": "x"}, format="json").status_code
            for _ in range(7)
        ]
        self.assertIn(429, statuses)
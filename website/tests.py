from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from datetime import timedelta

from django.utils import timezone

from . import tickets as workflow
from .models import Company, Contact, Note, Ticket, TicketEvent
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
            reverse("ticket_list"),
            reverse("ticket_completed"),
            reverse("ticket_add"),
            reverse("reports"),
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
        self.assertEqual(Ticket.objects.count(), 8)
        self.assertEqual(Ticket.objects.filter(status="open", assigned_to__isnull=True).count(), 3)


# --------------------------------------------------------------------------
def make_ticket(subject="Printer problem", status="open", assigned_to=None, company=None, **extra):
    data = dict(subject=subject, status=status, assigned_to=assigned_to, company=company)
    if status == "done":
        data.update(
            completed_by=assigned_to,
            completed_at=extra.pop("completed_at", timezone.now()),
            resolution=extra.pop("resolution", "Fixed it and confirmed with the client."),
        )
    data.update(extra)
    return Ticket.objects.create(**data)


class TicketWorkflowTests(BaseTestCase):
    """The rules in tickets.py, called through the web views like the buttons do."""

    def setUp(self):
        super().setUp()
        self.ticket = make_ticket("Printer", company=self.company)

    def assign(self, user, assignee):
        self.client.force_login(user)
        value = "" if assignee is None else assignee.pk
        return self.client.post(reverse("ticket_assign", args=[self.ticket.pk]), {"assignee": value})

    def test_staff_can_claim_an_unassigned_ticket(self):
        self.assign(self.ana, self.ana)
        self.ticket.refresh_from_db()
        self.assertEqual((self.ticket.assigned_to, self.ticket.status), (self.ana, "in_progress"))
        self.assertEqual(self.ticket.events.get().kind, "claimed")

    def test_staff_cannot_give_a_ticket_to_someone_else(self):
        self.assign(self.ana, self.ben)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assigned_to)

    def test_staff_cannot_take_a_ticket_someone_is_working_on(self):
        self.assign(self.ana, self.ana)
        self.assign(self.ben, self.ben)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.ana)

    def test_admin_can_assign_and_reassign_anyone(self):
        self.assign(self.boss, self.ana)
        self.assign(self.boss, self.ben)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.ben)
        self.assertEqual(list(self.ticket.events.values_list("kind", flat=True)), ["assigned", "assigned"])

    def test_release_rules(self):
        self.assign(self.ana, self.ana)
        self.assign(self.ben, None)  # not his ticket
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.ana)
        self.assign(self.ana, None)  # her own
        self.ticket.refresh_from_db()
        self.assertEqual((self.ticket.assigned_to, self.ticket.status), (None, "open"))
        self.assign(self.boss, self.ben)
        self.assign(self.boss, None)  # admin may release anyone's
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assigned_to)

    def test_inactive_user_cannot_be_assigned(self):
        self.ben.is_active = False
        self.ben.save()
        self.assign(self.boss, self.ben)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assigned_to)

    def test_done_needs_a_note_about_what_was_done(self):
        self.assign(self.ana, self.ana)
        url = reverse("ticket_done", args=[self.ticket.pk])
        self.client.post(url, {"resolution": "x"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "in_progress")
        self.client.post(url, {"resolution": "Replaced the cable and tested printing."})
        self.ticket.refresh_from_db()
        self.assertEqual((self.ticket.status, self.ticket.completed_by), ("done", self.ana))
        self.assertIsNotNone(self.ticket.completed_at)
        self.assertIn("Replaced the cable", self.ticket.resolution)

    def test_only_the_owner_or_an_admin_can_finish_it(self):
        self.assign(self.ana, self.ana)
        url = reverse("ticket_done", args=[self.ticket.pk])
        self.client.force_login(self.ben)
        self.client.post(url, {"resolution": "I did it instead."})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "in_progress")
        self.client.force_login(self.boss)
        self.client.post(url, {"resolution": "Finished by the admin."})
        self.ticket.refresh_from_db()
        self.assertEqual((self.ticket.status, self.ticket.completed_by), ("done", self.boss))

    def test_finishing_an_unassigned_ticket_makes_you_its_owner(self):
        self.client.force_login(self.ben)
        self.client.post(reverse("ticket_done", args=[self.ticket.pk]), {"resolution": "Quick fix over the phone."})
        self.ticket.refresh_from_db()
        self.assertEqual((self.ticket.status, self.ticket.assigned_to), ("done", self.ben))

    def test_done_tickets_cannot_be_assigned_until_reopened(self):
        done = make_ticket("Old", status="done", assigned_to=self.ana)
        self.client.force_login(self.boss)
        self.client.post(reverse("ticket_assign", args=[done.pk]), {"assignee": self.ben.pk})
        done.refresh_from_db()
        self.assertEqual(done.assigned_to, self.ana)

    def test_reopen_brings_it_back_with_the_same_owner(self):
        done = make_ticket("Old", status="done", assigned_to=self.ana)
        self.client.force_login(self.ben)  # any staff can follow up
        self.client.post(reverse("ticket_reopen", args=[done.pk]))
        done.refresh_from_db()
        self.assertEqual((done.status, done.assigned_to, done.completed_at), ("in_progress", self.ana, None))
        self.assertEqual(done.events.last().kind, "reopened")

    def test_service_raises_friendly_errors(self):
        with self.assertRaises(workflow.TicketError):
            workflow.assign(self.ticket.pk, self.ana, self.ben)
        with self.assertRaises(workflow.TicketError):
            workflow.complete(self.ticket.pk, self.ana, "   ")
        with self.assertRaises(workflow.TicketError):
            workflow.reopen(self.ticket.pk, self.ana)


class TicketPageTests(BaseTestCase):
    def ticket_form(self, **extra):
        data = {"subject": "Invoice has the wrong address", "requester_email": "Maria@Everbest.com", "priority": "normal"}
        data.update(extra)
        return data

    def test_create_links_the_client_from_the_email_address(self):
        self.client.force_login(self.ana)
        response = self.client.post(reverse("ticket_add"), self.ticket_form())
        ticket = Ticket.objects.get()
        self.assertRedirects(response, reverse("ticket_detail", args=[ticket.pk]))
        self.assertRegex(ticket.number, r"^TCK-\d{4}$")
        self.assertEqual((ticket.contact, ticket.company, ticket.created_by), (self.maria, self.company, self.ana))
        self.assertEqual(ticket.requester_email, "maria@everbest.com")
        self.assertEqual((ticket.status, ticket.assigned_to), ("open", None))
        self.assertEqual(ticket.events.get().kind, "created")

    def test_create_and_assign_to_me(self):
        self.client.force_login(self.ana)
        self.client.post(reverse("ticket_add"), self.ticket_form(claim_now="on"))
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.assigned_to, ticket.status), (self.ana, "in_progress"))

    def test_unknown_sender_is_not_linked_and_is_flagged(self):
        self.client.force_login(self.ana)
        self.client.post(reverse("ticket_add"), self.ticket_form(requester_email="stranger@gmail.com"))
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.contact, ticket.company), (None, None))
        self.assertContains(self.client.get(reverse("ticket_detail", args=[ticket.pk])), "Unknown sender")

    def test_picking_a_contact_fills_in_company_and_email(self):
        self.client.force_login(self.ana)
        self.client.post(reverse("ticket_add"), {"subject": "Call back", "contact": self.maria.pk, "priority": "high"})
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.company, ticket.requester_email), (self.company, "maria@everbest.com"))

    def test_open_list_hides_done_and_completed_page_shows_only_done(self):
        make_ticket("Still open")
        make_ticket("All finished", status="done", assigned_to=self.ana)
        self.client.force_login(self.ana)
        open_page = self.client.get(reverse("ticket_list"))
        self.assertEqual([t.subject for t in open_page.context["tickets"]], ["Still open"])
        done_page = self.client.get(reverse("ticket_completed"))
        self.assertEqual([t.subject for t in done_page.context["tickets"]], ["All finished"])

    def test_tabs_unassigned_and_mine(self):
        make_ticket("Nobody has this")
        make_ticket("Ana has this", status="in_progress", assigned_to=self.ana)
        make_ticket("Ben has this", status="in_progress", assigned_to=self.ben)
        self.client.force_login(self.ana)
        names = lambda view: sorted(t.subject for t in self.client.get(reverse("ticket_list"), {"view": view}).context["tickets"])
        self.assertEqual(names("unassigned"), ["Nobody has this"])
        self.assertEqual(names("mine"), ["Ana has this"])
        self.assertEqual(len(names("open")), 3)
        self.assertEqual(len(names("in_progress")), 2)
        tabs = {key: count for key, _, count in self.client.get(reverse("ticket_list")).context["tabs"]}
        self.assertEqual(tabs, {"open": 3, "unassigned": 1, "mine": 1, "in_progress": 2})

    def test_first_column_shows_unassigned_or_the_person(self):
        make_ticket("Nobody has this")
        make_ticket("Ben has this", status="in_progress", assigned_to=self.ben)
        self.client.force_login(self.ana)
        response = self.client.get(reverse("ticket_list"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertNotContains(response, "<html")
        self.assertContains(response, "Unassigned")
        self.assertContains(response, "ben")  # shown, but a plain label: staff cannot change Ben's ticket
        self.assertIn("X-Requested-With", response["Vary"])

    def test_staff_see_a_clickable_unassigned_button_with_the_staff_list(self):
        ticket = make_ticket("Nobody has this")
        self.client.force_login(self.ana)
        response = self.client.get(reverse("ticket_list"))
        self.assertContains(response, "data-assign-ticket")
        self.assertContains(response, reverse("ticket_assign", args=[ticket.pk]))
        self.assertEqual(sorted(u.username for u in response.context["staff"]), ["ana", "ben", "boss"])

    def test_detail_for_an_unassigned_ticket_offers_assign_to_me(self):
        ticket = make_ticket("Nobody has this", company=self.company, requester_email="maria@everbest.com")
        self.client.force_login(self.ana)
        response = self.client.get(reverse("ticket_detail", args=[ticket.pk]))
        self.assertContains(response, "Nobody is working on this yet")
        self.assertContains(response, "Assign to me")
        self.assertEqual(response.context["verification"].level, "verified")

    def test_done_ticket_page_shows_what_was_done_and_allows_follow_up(self):
        done = make_ticket("Finished job", status="done", assigned_to=self.ana, resolution="Swapped the router.")
        self.client.force_login(self.ben)
        page = self.client.get(reverse("ticket_detail", args=[done.pk]))
        self.assertContains(page, "Swapped the router.")
        self.assertContains(page, "Reopen for a follow-up")
        self.client.post(reverse("ticket_comment", args=[done.pk]), {"body": "Client says it dropped again."})
        self.assertEqual(done.events.last().kind, "comment")

    def test_completed_filters_by_person_and_period(self):
        make_ticket("Recent by Ana", status="done", assigned_to=self.ana)
        make_ticket("Recent by Ben", status="done", assigned_to=self.ben)
        make_ticket("Old by Ana", status="done", assigned_to=self.ana, completed_at=timezone.now() - timedelta(days=90))
        self.client.force_login(self.boss)
        subjects = lambda **p: sorted(t.subject for t in self.client.get(reverse("ticket_completed"), p).context["tickets"])
        self.assertEqual(subjects(), ["Recent by Ana", "Recent by Ben"])  # last 30 days by default
        self.assertEqual(subjects(by=self.ana.pk), ["Recent by Ana"])
        self.assertEqual(len(subjects(period="")), 3)

    def test_sidebar_count_of_unassigned_tickets(self):
        make_ticket("A")
        make_ticket("B")
        make_ticket("C", status="in_progress", assigned_to=self.ben)
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get(reverse("home")).context["unassigned_tickets"], 2)

    def test_back_redirect_only_follows_safe_referers(self):
        ticket = make_ticket("Printer")
        self.client.force_login(self.ana)
        url = reverse("ticket_assign", args=[ticket.pk])
        safe = self.client.post(url, {"assignee": self.ana.pk}, HTTP_REFERER="http://testserver/tickets/?view=unassigned")
        self.assertEqual(safe["Location"], "http://testserver/tickets/?view=unassigned")
        ticket.assigned_to = None
        ticket.status = "open"
        ticket.save()
        unsafe = self.client.post(url, {"assignee": self.ana.pk}, HTTP_REFERER="https://evil.example/steal")
        self.assertEqual(unsafe["Location"], reverse("ticket_detail", args=[ticket.pk]))

    def test_buttons_are_post_only_and_csrf_protected(self):
        ticket = make_ticket("Printer")
        self.client.force_login(self.ana)
        for name in ("ticket_assign", "ticket_done", "ticket_reopen", "ticket_comment"):
            self.assertEqual(self.client.get(reverse(name, args=[ticket.pk])).status_code, 405, name)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.ana)
        self.assertEqual(strict.post(reverse("ticket_assign", args=[ticket.pk]), {"assignee": self.ana.pk}).status_code, 403)

    def test_only_admins_delete_tickets(self):
        ticket = make_ticket("Printer")
        url = reverse("ticket_delete", args=[ticket.pk])
        self.client.force_login(self.ana)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.boss)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(Ticket.objects.filter(pk=ticket.pk).exists())

    def test_edit_a_ticket(self):
        ticket = make_ticket("Printer")
        self.client.force_login(self.ana)
        response = self.client.post(reverse("ticket_edit", args=[ticket.pk]), {"subject": "Printer is jammed", "priority": "urgent"})
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual((ticket.subject, ticket.priority), ("Printer is jammed", "urgent"))


class ReportsTests(BaseTestCase):
    def test_reports_numbers(self):
        make_ticket("Open one")
        make_ticket("In progress", status="in_progress", assigned_to=self.ana)
        done = make_ticket("Done one", status="done", assigned_to=self.ben, company=self.company)
        Ticket.objects.filter(pk=done.pk).update(created_at=timezone.now() - timedelta(hours=10))
        self.client.force_login(self.ana)
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 200)
        totals = response.context["totals"]
        self.assertEqual((totals["open_now"], totals["unassigned_now"], totals["done_7"]), (2, 1, 1))
        self.assertAlmostEqual(totals["avg_hours"], 10, delta=0.5)
        self.assertEqual(len(response.context["chart"]), 14)
        team = {m.username: (m.open_count, m.done_count) for m in response.context["team"]}
        self.assertEqual(team["ana"], (1, 0))
        self.assertEqual(team["ben"], (0, 1))
        self.assertEqual(response.context["clients"][0], self.company)

    def test_reports_with_no_tickets(self):
        self.client.force_login(self.ana)
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["totals"]["avg_hours"])


# --------------------------------------------------------------------------
class DemoModeTests(BaseTestCase):
    def test_login_page_shows_demo_accounts_only_in_demo_mode(self):
        self.assertNotContains(self.client.get(reverse("login")), "Try the demo")
        with override_settings(DEMO_MODE=True, DEMO_PASSWORD="open-sesame-1"):
            page = self.client.get(reverse("login"))
            self.assertContains(page, "Try the demo")
            self.assertContains(page, "open-sesame-1")

    @override_settings(DEMO_MODE=True)
    def test_banner_and_no_admin_site_link(self):
        self.client.force_login(self.boss)
        page = self.client.get(reverse("home"))
        self.assertContains(page, "Demo site.")
        self.assertNotContains(page, reverse("admin:index"))

    @override_settings(DEMO_MODE=True)
    def test_django_admin_site_is_switched_off(self):
        self.client.force_login(self.boss)
        self.assertRedirects(self.client.get("/admin/"), reverse("home"), fetch_redirect_response=False)

    @override_settings(DEMO_MODE=True)
    def test_visitors_cannot_add_staff_or_change_passwords(self):
        self.client.force_login(self.boss)
        data = {
            "first_name": "Spam", "last_name": "Bot", "email": "spam@example.com", "username": "spam",
            "password1": "Correct-horse-battery-9", "password2": "Correct-horse-battery-9",
        }
        response = self.client.post(reverse("team_add"), data)
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(username="spam").exists())
        self.client.post(
            reverse("password_change"),
            {"old_password": PASSWORD, "new_password1": "Another-pass-phrase-7", "new_password2": "Another-pass-phrase-7"},
        )
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.check_password(PASSWORD))
        self.client.post(reverse("team_toggle", args=[self.ana.pk]))
        self.ana.refresh_from_db()
        self.assertTrue(self.ana.is_active)

    @override_settings(DEMO_MODE=True)
    def test_everyday_work_still_functions_in_demo_mode(self):
        self.client.force_login(self.ana)
        response = self.client.post(reverse("ticket_add"), {"subject": "Demo ticket", "priority": "normal", "claim_now": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Ticket.objects.get().assigned_to, self.ana)

    def test_nothing_is_blocked_outside_demo_mode(self):
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        
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
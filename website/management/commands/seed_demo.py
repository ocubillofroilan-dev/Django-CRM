from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from website.models import Company, Contact, Note, Ticket, TicketEvent

# Fictional organisations and people, for demos and screenshots only.
COMPANIES = [
    dict(
        name="Everbest Manufacturing", status="client", industry="Manufacturing",
        website="https://everbest.example", email_domains="everbest.com.ph",
        city="Calamba", province="Laguna", zipcode="4027", phone="+63 49 555 0101",
        services="Managed IT support (Business plan), 25 workstations.",
        needs="Wants faster response on printer and email issues. Planning to add 10 workstations next quarter.",
        verification_notes="Ask the caller for the billing contact's full name and the contract renewal month.",
    ),
    dict(
        name="Laguna Bright Learning Center", status="client", industry="Education",
        website="https://lblc.example", email_domains="lblc.edu.ph",
        city="Santa Rosa", province="Laguna", zipcode="4026", phone="+63 49 555 0144",
        services="Website hosting and monthly maintenance.",
        needs="Needs enrolment form changes before June. Asked about a student portal.",
        verification_notes="Requests only from the registrar or the principal. Confirm the school year the site covers.",
    ),
    dict(
        name="Calauan Fresh Mart", status="client", industry="Retail",
        website="https://calauanfreshmart.example", email_domains="calauanfreshmart.ph",
        city="Calauan", province="Laguna", zipcode="4012", phone="+63 49 555 0188",
        services="Point-of-sale support, two branches.",
        needs="Receipt printer keeps disconnecting at the second branch.",
        verification_notes="Confirm which branch is calling and the manager on duty.",
    ),
    dict(
        name="Sampaguita Dental Clinic", status="prospect", industry="Healthcare",
        website="https://sampaguitadental.example", email_domains="sampaguitadental.ph",
        city="San Pablo", province="Laguna", zipcode="4000", phone="+63 49 555 0166",
        services="", needs="Interested in an online appointment booking page.",
        verification_notes="Prospect: no account yet, so do not share any client information.",
    ),
    dict(
        name="Northwind Logistics", status="former", industry="Logistics",
        website="https://northwind.example", email_domains="northwind.ph",
        city="Batangas City", province="Batangas", zipcode="4200", phone="+63 43 555 0120",
        services="Former client (contract ended).", needs="",
        verification_notes="Contract ended. Direct any request to the account manager.",
    ),
]

# (first, last, email, phone, company, title, can_request, status)
CONTACTS = [
    ("Maria", "Santos", "maria.santos@everbest.com.ph", "+63 917 555 0101", "Everbest Manufacturing", "Finance Manager", True, "active"),
    ("Jose", "Reyes", "jose.reyes@everbest.com.ph", "+63 917 555 0102", "Everbest Manufacturing", "IT Coordinator", True, "active"),
    ("Liza", "Dela Cruz", "liza.delacruz@everbest.com.ph", "+63 917 555 0103", "Everbest Manufacturing", "Receptionist", False, "active"),
    ("Ramon", "Garcia", "principal@lblc.edu.ph", "+63 918 555 0144", "Laguna Bright Learning Center", "Principal", True, "active"),
    ("Anne", "Villanueva", "registrar@lblc.edu.ph", "+63 918 555 0145", "Laguna Bright Learning Center", "Registrar", True, "active"),
    ("Carlo", "Mendoza", "carlo@calauanfreshmart.ph", "+63 919 555 0188", "Calauan Fresh Mart", "Owner", True, "active"),
    ("Grace", "Aquino", "grace@calauanfreshmart.ph", "+63 919 555 0189", "Calauan Fresh Mart", "Branch Manager", True, "active"),
    ("Dr. Paolo", "Lim", "paolo@sampaguitadental.ph", "+63 920 555 0166", "Sampaguita Dental Clinic", "Dentist", False, "lead"),
    ("Tessa", "Ramos", "tessa.ramos@northwind.ph", "+63 921 555 0120", "Northwind Logistics", "Operations Head", False, "inactive"),
    ("Ikaw", "Ako", "testing@gmail.com", "09876543210", None, "", False, "lead"),
]

# (subject, company, requester email, priority, status, staff index or None, resolution, age in days, days since done)
TICKETS = [
    ("Printer invoice shows the wrong address", "Everbest Manufacturing", "maria.santos@everbest.com.ph", "normal", "open", None, "", 0, 0),
    ("Cannot log in to staff email", "Everbest Manufacturing", "jose.reyes@everbest.com.ph", "high", "in_progress", 0, "", 1, 0),
    ("Enrolment form needs a new field", "Laguna Bright Learning Center", "registrar@lblc.edu.ph", "normal", "in_progress", 1, "", 2, 0),
    ("Receipt printer disconnects at branch 2", "Calauan Fresh Mart", "grace@calauanfreshmart.ph", "urgent", "open", None, "", 0, 0),
    ("Question about contract renewal", None, "stranger@gmail.com", "normal", "open", None, "", 1, 0),
    ("Quote for 10 more workstations", "Everbest Manufacturing", "maria.santos@everbest.com.ph", "low", "done", 2,
     "Sent the quote and confirmed the delivery date with Maria.", 6, 3),
    ("Website SSL certificate expired", "Laguna Bright Learning Center", "principal@lblc.edu.ph", "high", "done", 0,
     "Renewed the certificate and checked the site on desktop and mobile.", 9, 7),
    ("Reset password for the point-of-sale", "Calauan Fresh Mart", "carlo@calauanfreshmart.ph", "normal", "done", 1,
     "Reset the password on a call with Carlo and confirmed he could sign in.", 4, 1),
]

STAFF = [("ana", "Ana", "Lopez"), ("ben", "Ben", "Torres"), ("carla", "Carla", "Mercado")]


class Command(BaseCommand):
    help = "Fill the app with fictional demo data (safe to run more than once)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="demo-pass-123", help="Password for the demo accounts.")

    def handle(self, *args, **options):
        User = get_user_model()
        password = options["password"]

        admin, created = User.objects.get_or_create(
            username="demo_admin",
            defaults=dict(email="demo_admin@example.com", first_name="Demo", last_name="Admin", is_staff=True, is_superuser=True),
        )
        if created:
            admin.set_password(password)
            admin.save()

        staff = []
        for username, first, last in STAFF:
            user, created = User.objects.get_or_create(
                username=username, defaults=dict(email=f"{username}@example.com", first_name=first, last_name=last)
            )
            if created:
                user.set_password(password)
                user.save()
            staff.append(user)

        companies = {}
        for index, data in enumerate(COMPANIES):
            data = dict(data)
            name = data.pop("name")
            company, _ = Company.objects.get_or_create(
                name=name, defaults=dict(data, account_manager=staff[index % len(staff)])
            )
            companies[name] = company

        for index, (first, last, email, phone, company_name, title, can_request, status) in enumerate(CONTACTS):
            contact, created = Contact.objects.get_or_create(
                email=email,
                defaults=dict(
                    first_name=first, last_name=last, phone=phone, job_title=title, can_request=can_request,
                    status=status, company=companies.get(company_name), owner=staff[index % len(staff)],
                ),
            )
            if created and status == "active":
                Note.objects.create(contact=contact, author=staff[index % len(staff)], body="Introduced ourselves and confirmed the best way to reach them.")

        now = timezone.now()
        for subject, company_name, email, priority, status, who, resolution, age, done_ago in TICKETS:
            if Ticket.objects.filter(subject=subject).exists():
                continue
            contact = Contact.objects.filter(email__iexact=email).first()
            company = companies.get(company_name) or (contact.company if contact else None)
            worker = staff[who] if who is not None else None
            ticket = Ticket.objects.create(
                subject=subject, requester_email=email, company=company, contact=contact, priority=priority,
                status=status, assigned_to=worker, created_by=staff[0],
                description="Raised by phone and entered by hand.",
            )
            Ticket.objects.filter(pk=ticket.pk).update(created_at=now - timedelta(days=age, hours=2))
            TicketEvent.objects.create(ticket=ticket, actor=staff[0], kind="created", text="created this ticket.")
            if worker is not None:
                TicketEvent.objects.create(ticket=ticket, actor=worker, kind="claimed", text="claimed this ticket.")
            if status == "done":
                Ticket.objects.filter(pk=ticket.pk).update(
                    resolution=resolution, completed_by=worker, completed_at=now - timedelta(days=done_ago, hours=1)
                )
                TicketEvent.objects.create(ticket=ticket, actor=worker, kind="done", text=f"marked this ticket Done: {resolution}")

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  Admin: demo_admin / {password}")
        self.stdout.write(f"  Staff: ana, ben, carla / {password}")
        self.stdout.write("  Try verifying: maria.santos@everbest.com.ph, someone@everbest.com.ph, stranger@gmail.com")
        self.stdout.write("  Tickets: 5 open (3 nobody is working on) and 3 completed.")
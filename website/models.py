from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

from .utils import normalize_domains

phone_validator = RegexValidator(
    regex=r"^\+?[0-9 ()\-]{7,20}$",
    message="Enter a valid phone number (digits, spaces, +, - and brackets only).",
)

zipcode_validator = RegexValidator(
    regex=r"^[A-Za-z0-9 \-]{3,10}$",
    message="Enter a valid zip / postal code.",
)


class Company(models.Model):
    """A client (or prospect) organisation. Holds what staff need to verify and help them."""

    class Status(models.TextChoices):
        PROSPECT = "prospect", "Prospect"
        CLIENT = "client", "Client"
        FORMER = "former", "Former client"

    # Filled in automatically after the first save (CL-0001, CL-0002, ...).
    # Nullable so several rows can exist before their code is assigned.
    code = models.CharField(max_length=12, unique=True, null=True, blank=True, editable=False)
    name = models.CharField(max_length=120, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROSPECT)
    industry = models.CharField(max_length=80, blank=True)
    website = models.URLField(blank=True)
    phone = models.CharField(max_length=20, blank=True, validators=[phone_validator])

    email_domains = models.CharField(
        max_length=255,
        blank=True,
        help_text="Email domains this client uses, separated by commas (e.g. everbest.com, everbest.ph). "
        "Used to recognise incoming emails.",
    )
    verification_notes = models.TextField(
        blank=True,
        help_text="How staff confirm someone really works for this client "
        "(e.g. 'Ask for the billing contact's full name'). Never store passwords or ID numbers here.",
    )
    services = models.TextField(blank=True, help_text="The plan or services this client has with us.")
    needs = models.TextField(blank=True, help_text="What this client needs or has asked for.")

    address = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=50, blank=True)
    province = models.CharField(max_length=50, blank=True)
    zipcode = models.CharField(max_length=10, blank=True, validators=[zipcode_validator])

    account_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_companies",
        help_text="The staff member who looks after this client.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "company"
        verbose_name_plural = "companies"
        indexes = [models.Index(fields=["status"], name="company_status_idx")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.code:
            self.code = f"CL-{self.pk:04d}"
            super().save(update_fields=["code"])

    def get_absolute_url(self):
        return reverse("company_detail", args=[self.pk])

    @property
    def domains(self):
        try:
            return normalize_domains(self.email_domains)
        except ValueError:
            return []

    @property
    def initials(self):
        words = self.name.split()
        return "".join(word[0] for word in words[:2]).upper() or "?"


class Contact(models.Model):
    """A person. Usually works for a Company."""

    class Status(models.TextChoices):
        LEAD = "lead", "Lead"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contacts",
        help_text="Staff member responsible for this contact.",
    )
    company = models.ForeignKey(
        Company,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contacts",
    )
    job_title = models.CharField("job title", max_length=80, blank=True)
    can_request = models.BooleanField(
        "authorized to make requests",
        default=True,
        help_text="Tick if this person may make requests on the company's behalf.",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.LEAD)

    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField(max_length=100)
    phone = models.CharField(max_length=20, validators=[phone_validator])
    address = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=50, blank=True)
    province = models.CharField(max_length=50, blank=True)
    zipcode = models.CharField(max_length=10, blank=True, validators=[zipcode_validator])
    notes = models.TextField(blank=True, help_text="Internal remarks about this contact.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "contact"
        verbose_name_plural = "contacts"
        indexes = [
            models.Index(fields=["status"], name="record_status_idx"),
            models.Index(fields=["last_name", "first_name"], name="record_name_idx"),
        ]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def initials(self):
        return f"{self.first_name[:1]}{self.last_name[:1]}".upper() or "?"

    def get_absolute_url(self):
        return reverse("contact_detail", args=[self.pk])


class Note(models.Model):
    """A timeline entry on a contact (call summary, follow-up, etc.)."""

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="timeline")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="record_notes",
    )
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Note on {self.contact_id} by {self.author_id}"


class Ticket(models.Model):
    """A request from a client. Entered by hand; claimed by one staff member; closed as Done."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    # Filled in after the first save (TCK-0001, TCK-0002, ...).
    number = models.CharField(max_length=12, unique=True, null=True, blank=True, editable=False)
    subject = models.CharField(max_length=150)
    description = models.TextField(blank=True, help_text="What the client asked for, in their words.")
    requester_email = models.EmailField(
        max_length=100,
        blank=True,
        help_text="The address the request came from. We use it to recognise the client.",
    )
    company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    contact = models.ForeignKey(
        Contact, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_tickets",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_tickets",
    )

    resolution = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="completed_tickets",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "assigned_to"], name="ticket_status_idx"),
            models.Index(fields=["completed_at"], name="ticket_completed_idx"),
        ]

    def __str__(self):
        return f"{self.number or 'Ticket'}: {self.subject}"

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.number:
            self.number = f"TCK-{self.pk:04d}"
            super().save(update_fields=["number"])

    def get_absolute_url(self):
        return reverse("ticket_detail", args=[self.pk])

    @property
    def is_done(self):
        return self.status == self.Status.DONE

    @property
    def is_unassigned(self):
        return self.assigned_to_id is None and not self.is_done


class TicketEvent(models.Model):
    """One line in a ticket's history: who did what, and when."""

    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        CLAIMED = "claimed", "Claimed"
        ASSIGNED = "assigned", "Assigned"
        RELEASED = "released", "Released"
        DONE = "done", "Done"
        REOPENED = "reopened", "Reopened"
        COMMENT = "comment", "Note"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="ticket_events",
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.ticket_id} {self.kind}"
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

phone_validator = RegexValidator(
    regex=r"^\+?[0-9 ()\-]{7,20}$",
    message="Enter a valid phone number (digits, spaces, +, - and brackets only).",
)

zipcode_validator = RegexValidator(
    regex=r"^[A-Za-z0-9 \-]{3,10}$",
    message="Enter a valid zip / postal code.",
)

MANAGE_ALL_PERMISSION = "website.manage_all_records"


class RecordQuerySet(models.QuerySet):
    def visible_to(self, user):
        """
        The single place that decides which customers a user may see.

        * Managers (and superusers) see everything.
        * Everyone else only sees the customers they own.
        * Anonymous / inactive users see nothing.
        """
        if not user.is_authenticated or not user.is_active:
            return self.none()
        if user.has_perm(MANAGE_ALL_PERMISSION):
            return self
        return self.filter(owner=user)


class Record(models.Model):
    class Status(models.TextChoices):
        LEAD = "lead", "Lead"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="records",
        help_text="The team member responsible for this customer.",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.LEAD)

    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField(max_length=100)
    phone = models.CharField(max_length=20, validators=[phone_validator])
    address = models.CharField(max_length=100)
    city = models.CharField(max_length=50)
    province = models.CharField(max_length=50)
    zipcode = models.CharField(max_length=10, validators=[zipcode_validator])
    notes = models.TextField(blank=True, help_text="Internal remarks about this customer.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RecordQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "customer"
        verbose_name_plural = "customers"
        permissions = [
            (
                "manage_all_records",
                "Can view, edit, delete and reassign every customer (manager)",
            ),
        ]
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
        return reverse("record", args=[self.pk])


class Note(models.Model):
    """A timeline entry on a customer (call summary, follow-up, etc.)."""

    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="timeline")
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
        return f"Note on {self.record_id} by {self.author_id}"
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

PHONE = django.core.validators.RegexValidator(
    message="Enter a valid phone number (digits, spaces, +, - and brackets only).",
    regex=r"^\+?[0-9 ()\-]{7,20}$",
)
ZIPCODE = django.core.validators.RegexValidator(
    message="Enter a valid zip / postal code.",
    regex=r"^[A-Za-z0-9 \-]{3,10}$",
)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("website", "0002_customer_upgrade"),
    ]

    operations = [
        # 1. New: companies
        migrations.CreateModel(
            name="Company",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(blank=True, editable=False, max_length=12, null=True, unique=True)),
                ("name", models.CharField(max_length=120, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("prospect", "Prospect"), ("client", "Client"), ("former", "Former client")],
                        default="prospect",
                        max_length=10,
                    ),
                ),
                ("industry", models.CharField(blank=True, max_length=80)),
                ("website", models.URLField(blank=True)),
                ("phone", models.CharField(blank=True, max_length=20, validators=[PHONE])),
                (
                    "email_domains",
                    models.CharField(
                        blank=True,
                        help_text="Email domains this client uses, separated by commas (e.g. everbest.com, everbest.ph). Used to recognise incoming emails.",
                        max_length=255,
                    ),
                ),
                (
                    "verification_notes",
                    models.TextField(
                        blank=True,
                        help_text="How staff confirm someone really works for this client (e.g. 'Ask for the billing contact's full name'). Never store passwords or ID numbers here.",
                    ),
                ),
                ("services", models.TextField(blank=True, help_text="The plan or services this client has with us.")),
                ("needs", models.TextField(blank=True, help_text="What this client needs or has asked for.")),
                ("address", models.CharField(blank=True, max_length=120)),
                ("city", models.CharField(blank=True, max_length=50)),
                ("province", models.CharField(blank=True, max_length=50)),
                ("zipcode", models.CharField(blank=True, max_length=10, validators=[ZIPCODE])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "account_manager",
                    models.ForeignKey(
                        blank=True,
                        help_text="The staff member who looks after this client.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="managed_companies",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"verbose_name": "company", "verbose_name_plural": "companies", "ordering": ["name"]},
        ),
        migrations.AddIndex(
            model_name="company",
            index=models.Index(fields=["status"], name="company_status_idx"),
        ),
        # 2. Customers become contacts (rows are kept)
        migrations.RenameModel(old_name="Record", new_name="Contact"),
        migrations.RenameField(model_name="note", old_name="record", new_name="contact"),
        migrations.AlterModelOptions(
            name="contact",
            options={
                "ordering": ["-created_at", "-id"],
                "verbose_name": "contact",
                "verbose_name_plural": "contacts",
            },
        ),
        migrations.AlterField(
            model_name="contact",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                help_text="Staff member responsible for this contact.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="contacts",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="contact",
            name="notes",
            field=models.TextField(blank=True, help_text="Internal remarks about this contact."),
        ),
        migrations.AddField(
            model_name="contact",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="contacts",
                to="website.company",
            ),
        ),
        migrations.AddField(
            model_name="contact",
            name="job_title",
            field=models.CharField(blank=True, max_length=80, verbose_name="job title"),
        ),
        migrations.AddField(
            model_name="contact",
            name="can_request",
            field=models.BooleanField(
                default=True,
                help_text="Tick if this person may make requests on the company's behalf.",
                verbose_name="authorized to make requests",
            ),
        ),
        migrations.AlterField(model_name="contact", name="address", field=models.CharField(blank=True, max_length=100)),
        migrations.AlterField(model_name="contact", name="city", field=models.CharField(blank=True, max_length=50)),
        migrations.AlterField(model_name="contact", name="province", field=models.CharField(blank=True, max_length=50)),
        migrations.AlterField(
            model_name="contact",
            name="zipcode",
            field=models.CharField(blank=True, max_length=10, validators=[ZIPCODE]),
        ),
    ]
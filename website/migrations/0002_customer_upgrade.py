import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("website", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="record",
            options={
                "ordering": ["-created_at", "-id"],
                "permissions": [
                    (
                        "manage_all_records",
                        "Can view, edit, delete and reassign every customer (manager)",
                    )
                ],
                "verbose_name": "customer",
                "verbose_name_plural": "customers",
            },
        ),
        migrations.AddField(
            model_name="record",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                help_text="The team member responsible for this customer.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="records",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="record",
            name="status",
            field=models.CharField(
                choices=[("lead", "Lead"), ("active", "Active"), ("inactive", "Inactive")],
                default="lead",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="record",
            name="notes",
            field=models.TextField(blank=True, help_text="Internal remarks about this customer."),
        ),
        migrations.AddField(
            model_name="record",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="record",
            name="email",
            field=models.EmailField(max_length=100),
        ),
        migrations.AlterField(
            model_name="record",
            name="phone",
            field=models.CharField(
                max_length=20,
                validators=[
                    django.core.validators.RegexValidator(
                        message="Enter a valid phone number (digits, spaces, +, - and brackets only).",
                        regex=r"^\+?[0-9 ()\-]{7,20}$",
                    )
                ],
            ),
        ),
        migrations.AlterField(
            model_name="record",
            name="zipcode",
            field=models.CharField(
                max_length=10,
                validators=[
                    django.core.validators.RegexValidator(
                        message="Enter a valid zip / postal code.",
                        regex=r"^[A-Za-z0-9 \-]{3,10}$",
                    )
                ],
            ),
        ),
        migrations.AddIndex(
            model_name="record",
            index=models.Index(fields=["status"], name="record_status_idx"),
        ),
        migrations.AddIndex(
            model_name="record",
            index=models.Index(fields=["last_name", "first_name"], name="record_name_idx"),
        ),
        migrations.CreateModel(
            name="Note",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("body", models.TextField(max_length=2000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "author",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="record_notes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "record",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="timeline",
                        to="website.record",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)

from .models import Company, Contact, Note, Ticket
from .utils import normalize_domains
from .verification import verify_sender

User = get_user_model()


def person_label(user):
    return user.get_full_name() or user.get_username()


class BootstrapFormMixin:
    """Gives every widget the right Bootstrap class. Validation state is added at render time."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            existing = widget.attrs.get("class", "")
            if css not in existing:
                widget.attrs["class"] = f"{existing} {css}".strip()


# --------------------------------------------------------------------------
# Authentication forms
# --------------------------------------------------------------------------
class LoginForm(BootstrapFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"autocomplete": "username", "autocapitalize": "none", "spellcheck": "false"}
        )
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})


class StaffCreateForm(BootstrapFormMixin, UserCreationForm):
    """Used by administrators to add a staff account."""

    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name")
    email = forms.EmailField(max_length=254, label="Work email")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "email", "username", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hints = {
            "first_name": "off",
            "last_name": "off",
            "email": "off",
            "username": "off",
            "password1": "new-password",
            "password2": "new-password",
        }
        for name, autocomplete in hints.items():
            self.fields[name].widget.attrs["autocomplete"] = autocomplete
        self.fields["password1"].label = "Temporary password"
        self.fields["password2"].label = "Confirm password"

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class StyledPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    pass


class StyledPasswordResetForm(BootstrapFormMixin, PasswordResetForm):
    pass


class StyledSetPasswordForm(BootstrapFormMixin, SetPasswordForm):
    pass


# --------------------------------------------------------------------------
# Companies and contacts
# --------------------------------------------------------------------------
class CompanyForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "name",
            "status",
            "industry",
            "website",
            "phone",
            "email_domains",
            "verification_notes",
            "services",
            "needs",
            "address",
            "city",
            "province",
            "zipcode",
            "account_manager",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "off"}),
            "website": forms.URLInput(attrs={"placeholder": "https://"}),
            "phone": forms.TextInput(attrs={"type": "tel", "inputmode": "tel"}),
            "email_domains": forms.TextInput(attrs={"placeholder": "everbest.com, everbest.ph"}),
            "verification_notes": forms.Textarea(attrs={"rows": 3}),
            "services": forms.Textarea(attrs={"rows": 3}),
            "needs": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        manager = self.fields["account_manager"]
        manager.queryset = User.objects.filter(is_active=True).order_by("username")
        manager.empty_label = "Unassigned"
        manager.label_from_instance = person_label

    def clean_email_domains(self):
        try:
            return ", ".join(normalize_domains(self.cleaned_data.get("email_domains", "")))
        except ValueError as error:
            raise forms.ValidationError(f"'{error}' is not a valid domain name (use something like example.com).")


class ContactForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Contact
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "company",
            "job_title",
            "can_request",
            "status",
            "owner",
            "address",
            "city",
            "province",
            "zipcode",
            "notes",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "off"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "off"}),
            "email": forms.EmailInput(attrs={"autocomplete": "off", "inputmode": "email"}),
            "phone": forms.TextInput(
                attrs={"type": "tel", "autocomplete": "off", "inputmode": "tel", "placeholder": "+63 912 345 6789"}
            ),
            "zipcode": forms.TextInput(attrs={"autocomplete": "off"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = self.fields["company"]
        company.empty_label = "No company"
        company.queryset = Company.objects.order_by("name")
        owner = self.fields["owner"]
        owner.required = False
        owner.empty_label = "Unassigned"
        owner.queryset = User.objects.filter(is_active=True).order_by("username")
        owner.label_from_instance = person_label
        owner.label = "Assigned to"

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        # One address, one person: sender verification depends on this.
        duplicates = Contact.objects.filter(email__iexact=email)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        existing = duplicates.first()
        if existing:
            raise forms.ValidationError(f"{existing.full_name} already uses this email address.")
        return email


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 3,
                    "class": "form-control",
                    "placeholder": "Log a call, a follow-up or anything worth remembering…",
                    "maxlength": 2000,
                }
            )
        }
        labels = {"body": "Add a note"}


# --------------------------------------------------------------------------
# Tickets
# --------------------------------------------------------------------------
class TicketForm(BootstrapFormMixin, forms.ModelForm):
    claim_now = forms.BooleanField(
        required=False,
        label="I'm working on this now (assign it to me)",
    )

    class Meta:
        model = Ticket
        fields = ["subject", "requester_email", "company", "contact", "priority", "description"]
        widgets = {
            "subject": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "e.g. Printer invoice shows the wrong address"}),
            "requester_email": forms.EmailInput(attrs={"autocomplete": "off", "inputmode": "email", "placeholder": "name@company.com"}),
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = self.fields["company"]
        company.empty_label = "Not linked yet"
        company.queryset = Company.objects.order_by("name")
        contact = self.fields["contact"]
        contact.empty_label = "Not linked yet"
        contact.queryset = Contact.objects.select_related("company").order_by("last_name", "first_name")
        contact.label_from_instance = lambda c: f"{c.full_name} ({c.company.name})" if c.company_id else c.full_name
        if self.instance.pk:  # "assign to me" only makes sense when creating
            del self.fields["claim_now"]

    def clean_requester_email(self):
        return (self.cleaned_data.get("requester_email") or "").strip().lower()

    def clean(self):
        data = super().clean()
        contact, company = data.get("contact"), data.get("company")
        email = data.get("requester_email") or ""
        # Link the ticket to the client automatically when we recognise the sender.
        if email and not contact:
            found = verify_sender(email)
            if found.contact:
                data["contact"] = contact = found.contact
            if not company and found.company:
                data["company"] = company = found.company
        if contact and not company and contact.company_id:
            data["company"] = contact.company
        if contact and not email:
            data["requester_email"] = contact.email
        return data


class TicketDoneForm(forms.Form):
    resolution = forms.CharField(
        label="What was done?",
        min_length=5,
        max_length=2000,
        widget=forms.Textarea(
            attrs={"rows": 4, "class": "form-control", "placeholder": "e.g. Updated the billing address and sent a corrected invoice."}
        ),
    )


class TicketCommentForm(forms.Form):
    body = forms.CharField(
        label="Add a note",
        max_length=2000,
        widget=forms.Textarea(
            attrs={"rows": 3, "class": "form-control", "placeholder": "Add an update or a follow-up note…", "maxlength": 2000}
        ),
    )
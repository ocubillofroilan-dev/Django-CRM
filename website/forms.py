from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)

from .models import MANAGE_ALL_PERMISSION, Note, Record

User = get_user_model()


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


class SignUpForm(BootstrapFormMixin, UserCreationForm):
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name")
    email = forms.EmailField(max_length=254, label="Work email")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "email", "username", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hints = {
            "first_name": "given-name",
            "last_name": "family-name",
            "email": "email",
            "username": "username",
            "password1": "new-password",
            "password2": "new-password",
        }
        for name, autocomplete in hints.items():
            self.fields[name].widget.attrs["autocomplete"] = autocomplete
        self.fields["password1"].label = "Password"
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
# Customer forms
# --------------------------------------------------------------------------
class RecordForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Record
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
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

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user.has_perm(MANAGE_ALL_PERMISSION):
            owner = self.fields["owner"]
            owner.required = False
            owner.empty_label = "Unassigned"
            owner.queryset = User.objects.filter(is_active=True).order_by("username")
            owner.label_from_instance = lambda u: u.get_full_name() or u.get_username()
        else:
            # Agents can never choose or change the owner. The field is removed, so
            # a tampered POST cannot set it either.
            del self.fields["owner"]

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


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
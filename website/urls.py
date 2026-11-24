from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .forms import (
    StyledPasswordChangeForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
)

SHELL = "base.html"        # signed-in layout (sidebar + top bar)
PUBLIC = "auth_base.html"  # signed-out layout (split screen)

urlpatterns = [
    # --- Customers ---------------------------------------------------------
    path("", views.RecordListView.as_view(), name="home"),
    path("customers/new/", views.RecordCreateView.as_view(), name="add_record"),
    path("customers/export.csv", views.RecordExportView.as_view(), name="export_records"),
    path("customers/<int:pk>/", views.RecordDetailView.as_view(), name="record"),
    path("customers/<int:pk>/edit/", views.RecordUpdateView.as_view(), name="update_record"),
    path("customers/<int:pk>/delete/", views.RecordDeleteView.as_view(), name="delete_record"),
    path("customers/<int:pk>/notes/add/", views.NoteCreateView.as_view(), name="add_note"),
    path("notes/<int:pk>/delete/", views.NoteDeleteView.as_view(), name="delete_note"),
    # --- Sign in / out / up ------------------------------------------------
    path("login/", views.ThrottledLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),  # POST only
    path("register/", views.RegisterView.as_view(), name="register"),
    # --- Change password (signed in) --------------------------------------
    path(
        "account/password/",
        auth_views.PasswordChangeView.as_view(
            template_name="registration/auth_form.html",
            form_class=StyledPasswordChangeForm,
            success_url=reverse_lazy("password_change_done"),
            extra_context={
                "base_template": SHELL,
                "heading": "Change password",
                "subheading": "Use a long, unique password. A password manager helps.",
                "submit_label": "Update password",
            },
        ),
        name="password_change",
    ),
    path(
        "account/password/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="registration/auth_message.html",
            extra_context={
                "base_template": SHELL,
                "heading": "Password updated",
                "message": "Your password was changed. Other devices stay signed in until their session ends.",
                "action_url": reverse_lazy("home"),
                "action_label": "Back to customers",
            },
        ),
        name="password_change_done",
    ),
    # --- Forgot password (signed out) --------------------------------------
    path(
        "password-reset/",
        views.RateLimitedPasswordResetView.as_view(
            template_name="registration/auth_form.html",
            form_class=StyledPasswordResetForm,
            email_template_name="registration/crm_reset_email.txt",
            subject_template_name="registration/crm_reset_subject.txt",
            success_url=reverse_lazy("password_reset_done"),
            extra_context={
                "base_template": PUBLIC,
                "heading": "Forgot your password?",
                "subheading": "Enter your account email and we'll send you a reset link.",
                "submit_label": "Send reset link",
                "back_url": reverse_lazy("login"),
                "back_label": "Back to sign in",
            },
        ),
        name="password_reset",
    ),
    path(
        "password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/auth_message.html",
            extra_context={
                "base_template": PUBLIC,
                "heading": "Check your inbox",
                "message": "If an account exists for that email, a reset link is on its way. It expires in 3 days.",
                "action_url": reverse_lazy("login"),
                "action_label": "Back to sign in",
            },
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/auth_form.html",
            form_class=StyledSetPasswordForm,
            success_url=reverse_lazy("password_reset_complete"),
            extra_context={
                "base_template": PUBLIC,
                "heading": "Choose a new password",
                "subheading": "Pick something you have not used anywhere else.",
                "submit_label": "Save new password",
                "back_url": reverse_lazy("login"),
                "back_label": "Back to sign in",
            },
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/auth_message.html",
            extra_context={
                "base_template": PUBLIC,
                "heading": "All set",
                "message": "Your password has been changed. You can sign in now.",
                "action_url": reverse_lazy("login"),
                "action_label": "Sign in",
            },
        ),
        name="password_reset_complete",
    ),
]
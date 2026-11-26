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
    # --- Today -------------------------------------------------------------
    path("", views.TodayView.as_view(), name="home"),
    # --- Contacts ----------------------------------------------------------
    path("contacts/", views.ContactListView.as_view(), name="contact_list"),
    path("contacts/new/", views.ContactCreateView.as_view(), name="contact_add"),
    path("contacts/export.csv", views.ContactExportView.as_view(), name="contact_export"),
    path("contacts/<int:pk>/", views.ContactDetailView.as_view(), name="contact_detail"),
    path("contacts/<int:pk>/edit/", views.ContactUpdateView.as_view(), name="contact_edit"),
    path("contacts/<int:pk>/delete/", views.ContactDeleteView.as_view(), name="contact_delete"),
    path("contacts/<int:pk>/notes/add/", views.NoteCreateView.as_view(), name="note_add"),
    path("notes/<int:pk>/delete/", views.NoteDeleteView.as_view(), name="note_delete"),
    # --- Companies ---------------------------------------------------------
    path("companies/", views.CompanyListView.as_view(), name="company_list"),
    path("companies/new/", views.CompanyCreateView.as_view(), name="company_add"),
    path("companies/<int:pk>/", views.CompanyDetailView.as_view(), name="company_detail"),
    path("companies/<int:pk>/edit/", views.CompanyUpdateView.as_view(), name="company_edit"),
    path("companies/<int:pk>/delete/", views.CompanyDeleteView.as_view(), name="company_delete"),
    # --- Team (administrators) --------------------------------------------
    path("team/", views.TeamListView.as_view(), name="team_list"),
    path("team/new/", views.TeamCreateView.as_view(), name="team_add"),
    path("team/<int:pk>/toggle/", views.TeamToggleActiveView.as_view(), name="team_toggle"),
    # --- Tickets -----------------------------------------------------------
    path("tickets/", views.TicketListView.as_view(), name="ticket_list"),
    path("tickets/new/", views.TicketCreateView.as_view(), name="ticket_add"),
    path("tickets/completed/", views.TicketCompletedView.as_view(), name="ticket_completed"),
    path("tickets/<int:pk>/", views.TicketDetailView.as_view(), name="ticket_detail"),
    path("tickets/<int:pk>/edit/", views.TicketUpdateView.as_view(), name="ticket_edit"),
    path("tickets/<int:pk>/delete/", views.TicketDeleteView.as_view(), name="ticket_delete"),
    path("tickets/<int:pk>/assign/", views.TicketAssignView.as_view(), name="ticket_assign"),
    path("tickets/<int:pk>/done/", views.TicketDoneView.as_view(), name="ticket_done"),
    path("tickets/<int:pk>/reopen/", views.TicketReopenView.as_view(), name="ticket_reopen"),
    path("tickets/<int:pk>/comment/", views.TicketCommentView.as_view(), name="ticket_comment"),
    # --- Reports -----------------------------------------------------------
    path("reports/", views.ReportsView.as_view(), name="reports"),
    # --- Sign in / out -----------------------------------------------------
    path("login/", views.ThrottledLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),  # POST only
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
                "action_label": "Back to Today",
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
import csv

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, PasswordResetView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from . import security, tickets
from .forms import (
    CompanyForm,
    ContactForm,
    LoginForm,
    NoteForm,
    StaffCreateForm,
    TicketCommentForm,
    TicketDoneForm,
    TicketForm,
)
from .models import Company, Contact, Note, Ticket, TicketEvent
from .permissions import AdminRequiredMixin, is_admin
from .queries import (
    COMPANY_SORT_LABELS,
    COMPLETED_PERIODS,
    COMPLETED_SORT_LABELS,
    CONTACT_SORT_LABELS,
    TICKET_SORT_LABELS,
    dashboard_stats,
    filter_companies,
    filter_completed,
    filter_contacts,
    filter_tickets,
    report_data,
    ticket_tabs,
    with_contact_counts,
)
from .security import security_logger
from .verification import verify_sender

User = get_user_model()


def is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


# ==========================================================================
# Authentication
# ==========================================================================
class ThrottledLoginView(LoginView):
    """Login with brute-force protection, safe `next` handling and friendly messages."""

    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "")
        if security.login_is_locked(username, security.client_ip(request)):
            security_logger.warning(
                "Blocked login while locked username=%r ip=%s", username[:50], security.client_ip(request)
            )
            form = self.get_form_class()(request=request)  # fresh, unbound form
            context = self.get_context_data(form=form, locked=True)
            return self.render_to_response(context, status=429)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        username = self.request.POST.get("username", "")
        security.login_succeeded(username, security.client_ip(self.request))
        response = super().form_valid(form)
        name = form.get_user().first_name or form.get_user().get_username()
        messages.success(self.request, f"Welcome back, {name}.")
        return response

    def form_invalid(self, form):
        username = self.request.POST.get("username", "")
        security.login_failed(username, security.client_ip(self.request))
        return super().form_invalid(form)


class RateLimitedPasswordResetView(PasswordResetView):
    """Stops the reset form from being used to flood someone's inbox."""

    def post(self, request, *args, **kwargs):
        ip = security.client_ip(request)
        if security.reset_is_blocked(ip):
            messages.error(request, "Too many reset requests. Please try again in an hour.")
            form = self.get_form_class()()
            return self.render_to_response(self.get_context_data(form=form), status=429)
        security.reset_requested(ip)
        return super().post(request, *args, **kwargs)


# ==========================================================================
# Today (home)
# ==========================================================================
class TodayView(LoginRequiredMixin, TemplateView):
    template_name = "website/today.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hour = timezone.localtime().hour
        context["greeting"] = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        context["stats"] = dashboard_stats()
        open_tickets = Ticket.objects.exclude(status=Ticket.Status.DONE).select_related("company")
        context["unassigned_list"] = open_tickets.filter(assigned_to__isnull=True).order_by("created_at")[:5]
        context["my_tickets"] = open_tickets.filter(assigned_to=self.request.user).order_by("-updated_at")[:5]
        context["recent_contacts"] = Contact.objects.select_related("company")[:5]
        context["recent_companies"] = Company.objects.order_by("-created_at", "-id")[:5]
        email = self.request.GET.get("verify", "").strip()
        if email:
            context["verify_email"] = email
            context["verification"] = verify_sender(email)
        return context


# ==========================================================================
# Shared list behaviour (full page, or just the results for live search)
# ==========================================================================
class ListContextMixin:
    full_template = None
    partial_template = None
    sort_labels = ()
    default_sort = "newest"
    status_choices = ()

    def get_template_names(self):
        return [self.partial_template if is_ajax(self.request) else self.full_template]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        query_params = params.copy()
        query_params.pop("page", None)
        page_obj, paginator = context["page_obj"], context["paginator"]
        q = params.get("q", "").strip()
        status = params.get("status", "")
        if status not in dict(self.status_choices):
            status = ""
        context.update(
            q=q,
            status=status,
            sort=params.get("sort", self.default_sort),
            sort_options=self.sort_labels,
            status_choices=self.status_choices,
            has_filters=bool(q or status),
            querystring=query_params.urlencode(),
            page_range=list(paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)),
            ellipsis=Paginator.ELLIPSIS,
        )
        return context

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        # Same URL, two different bodies (full page vs. partial): tell caches apart.
        patch_vary_headers(response, ["X-Requested-With"])
        return response


# ==========================================================================
# Contacts
# ==========================================================================
class ContactListView(LoginRequiredMixin, ListContextMixin, ListView):
    context_object_name = "contacts"
    paginate_by = 10
    full_template = "website/contact_list.html"
    partial_template = "website/_contact_results.html"
    sort_labels = CONTACT_SORT_LABELS
    default_sort = "newest"
    status_choices = Contact.Status.choices

    def get_queryset(self):
        params = self.request.GET
        return filter_contacts(
            Contact.objects.select_related("company", "owner"),
            q=params.get("q", ""),
            status=params.get("status", ""),
            sort=params.get("sort", "newest"),
            company=params.get("company", ""),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company_id = self.request.GET.get("company", "")
        context["company_filter"] = (
            Company.objects.filter(pk=int(company_id)).first() if company_id.isdigit() else None
        )
        return context


class ContactDetailView(LoginRequiredMixin, DetailView):
    context_object_name = "contact"
    template_name = "website/contact_detail.html"

    def get_queryset(self):
        return Contact.objects.select_related("company", "owner").prefetch_related(
            Prefetch("timeline", queryset=Note.objects.select_related("author"))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["note_form"] = NoteForm()
        context["verification"] = verify_sender(self.object.email)
        return context


class ContactFormMixin(LoginRequiredMixin):
    model = Contact
    form_class = ContactForm
    template_name = "website/contact_form.html"


class ContactCreateView(ContactFormMixin, CreateView):
    def get_initial(self):
        initial = super().get_initial()
        initial["owner"] = self.request.user.pk
        company = self.request.GET.get("company", "")
        if company.isdigit():
            initial["company"] = int(company)
        if self.request.GET.get("email"):
            initial["email"] = self.request.GET["email"][:100]
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="New contact", submit_label="Create contact")
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.object.full_name} was added.")
        return response


class ContactUpdateView(ContactFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title=f"Edit {self.object.full_name}", submit_label="Save changes")
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.object.full_name} was updated.")
        return response


class ContactDeleteView(AdminRequiredMixin, DeleteView):
    """GET shows a confirmation page. Only POST (with a CSRF token) deletes. Admins only."""

    model = Contact
    context_object_name = "contact"
    template_name = "website/contact_confirm_delete.html"
    success_url = reverse_lazy("contact_list")

    def form_valid(self, form):
        name, pk = self.object.full_name, self.object.pk
        response = super().form_valid(form)
        security_logger.info("Contact deleted id=%s by=%r", pk, self.request.user.get_username())
        messages.success(self.request, f"{name} was deleted.")
        return response


def csv_safe(value):
    """Neutralise spreadsheet formula injection (a cell starting with = + - @ runs as a formula)."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


class ContactExportView(LoginRequiredMixin, View):
    """CSV of exactly what the list shows, with the same filters applied."""

    def get(self, request):
        params = request.GET
        queryset = filter_contacts(
            Contact.objects.select_related("company", "owner"),
            q=params.get("q", ""),
            status=params.get("status", ""),
            sort=params.get("sort", "newest"),
            company=params.get("company", ""),
        )
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        filename = f"contacts-{timezone.localdate():%Y%m%d}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("\ufeff")  # BOM: lets Excel open UTF-8 correctly
        writer = csv.writer(response)
        writer.writerow(
            ["First name", "Last name", "Email", "Phone", "Company", "Job title", "Authorized", "Status", "Assigned to", "Created"]
        )
        count = 0
        for c in queryset.iterator():
            owner = (c.owner.get_full_name() or c.owner.get_username()) if c.owner else ""
            writer.writerow(
                [
                    csv_safe(value)
                    for value in (
                        c.first_name,
                        c.last_name,
                        c.email,
                        c.phone,
                        c.company.name if c.company else "",
                        c.job_title,
                        "Yes" if c.can_request else "No",
                        c.get_status_display(),
                        owner,
                        timezone.localtime(c.created_at).strftime("%Y-%m-%d %H:%M"),
                    )
                ]
            )
            count += 1
        security_logger.info("CSV export rows=%d by=%r", count, request.user.get_username())
        return response


# ==========================================================================
# Notes (contact timeline)
# ==========================================================================
class NoteCreateView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        contact = get_object_or_404(Contact, pk=pk)
        form = NoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.contact = contact
            note.author = request.user
            note.save()
            messages.success(request, "Note added.")
        else:
            messages.error(request, "A note can't be empty or longer than 2,000 characters.")
        return redirect(f"{contact.get_absolute_url()}#timeline")


class NoteDeleteView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        note = get_object_or_404(Note.objects.select_related("contact"), pk=pk)
        if note.author_id != request.user.pk and not is_admin(request.user):
            raise PermissionDenied("Only the author or an administrator can delete this note.")
        contact = note.contact
        note.delete()
        messages.success(request, "Note deleted.")
        return redirect(f"{contact.get_absolute_url()}#timeline")


# ==========================================================================
# Companies
# ==========================================================================
class CompanyListView(LoginRequiredMixin, ListContextMixin, ListView):
    context_object_name = "companies"
    paginate_by = 10
    full_template = "website/company_list.html"
    partial_template = "website/_company_results.html"
    sort_labels = COMPANY_SORT_LABELS
    default_sort = "name"
    status_choices = Company.Status.choices

    def get_queryset(self):
        params = self.request.GET
        queryset = with_contact_counts(Company.objects.select_related("account_manager"))
        return filter_companies(
            queryset,
            q=params.get("q", ""),
            status=params.get("status", ""),
            sort=params.get("sort", "name"),
        )


class CompanyDetailView(LoginRequiredMixin, DetailView):
    context_object_name = "company"
    template_name = "website/company_detail.html"

    def get_queryset(self):
        return Company.objects.select_related("account_manager")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["contacts"] = self.object.contacts.select_related("owner").order_by("last_name", "first_name")
        return context


class CompanyFormMixin(LoginRequiredMixin):
    model = Company
    form_class = CompanyForm
    template_name = "website/company_form.html"


class CompanyCreateView(CompanyFormMixin, CreateView):
    def get_initial(self):
        initial = super().get_initial()
        initial["account_manager"] = self.request.user.pk
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="New company", submit_label="Create company")
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.object.name} was added.")
        return response


class CompanyUpdateView(CompanyFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title=f"Edit {self.object.name}", submit_label="Save changes")
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.object.name} was updated.")
        return response


class CompanyDeleteView(AdminRequiredMixin, DeleteView):
    """Deleting a company keeps its contacts; they simply become 'No company'. Admins only."""

    model = Company
    context_object_name = "company"
    template_name = "website/company_confirm_delete.html"
    success_url = reverse_lazy("company_list")

    def form_valid(self, form):
        name, pk = self.object.name, self.object.pk
        response = super().form_valid(form)
        security_logger.info("Company deleted id=%s by=%r", pk, self.request.user.get_username())
        messages.success(self.request, f"{name} was deleted.")
        return response


# ==========================================================================
# Team (administrators manage staff accounts)
# ==========================================================================
class TeamListView(AdminRequiredMixin, ListView):
    template_name = "website/team_list.html"
    context_object_name = "members"

    def get_queryset(self):
        return User.objects.order_by("-is_active", "-is_superuser", "username")


class TeamCreateView(AdminRequiredMixin, FormView):
    template_name = "website/team_form.html"
    form_class = StaffCreateForm
    success_url = reverse_lazy("team_list")

    def form_valid(self, form):
        user = form.save()
        security_logger.info(
            "Staff account created username=%r by=%r", user.get_username(), self.request.user.get_username()
        )
        messages.success(self.request, f"{user.get_full_name() or user.get_username()} can now sign in.")
        return super().form_valid(form)


class TeamToggleActiveView(AdminRequiredMixin, View):
    """Switch a staff account off (or back on). You can't switch off yourself or an administrator."""

    http_method_names = ["post"]

    def post(self, request, pk):
        member = get_object_or_404(User, pk=pk)
        if member.pk == request.user.pk or member.is_superuser:
            messages.error(request, "You can't change the status of an administrator or of yourself.")
            return redirect("team_list")
        member.is_active = not member.is_active
        member.save(update_fields=["is_active"])
        security_logger.info(
            "Account %s username=%r by=%r",
            "enabled" if member.is_active else "disabled",
            member.get_username(),
            request.user.get_username(),
        )
        messages.success(request, f"{member.get_username()} was {'enabled' if member.is_active else 'disabled'}.")
        return redirect("team_list")


# ==========================================================================
# Tickets
# ==========================================================================
def active_staff():
    return User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")


class StaffListMixin:
    """Gives the page the list of people shown in the 'who is working on this?' window."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["staff"] = active_staff()
        return context


class TicketListView(LoginRequiredMixin, StaffListMixin, ListContextMixin, ListView):
    """Open tickets. The first column shows who is working on each one (or 'Unassigned')."""

    context_object_name = "tickets"
    paginate_by = 10
    full_template = "website/ticket_list.html"
    partial_template = "website/_ticket_results.html"
    sort_labels = TICKET_SORT_LABELS
    default_sort = "newest"
    status_choices = ()  # tabs are used instead of a status menu

    def current_tab(self):
        tab = self.request.GET.get("view", "open")
        return tab if tab in ("open", "unassigned", "mine", "in_progress") else "open"

    def get_queryset(self):
        params = self.request.GET
        return filter_tickets(
            Ticket.objects.select_related("company", "contact", "assigned_to"),
            self.request.user,
            q=params.get("q", ""),
            view=self.current_tab(),
            priority=params.get("priority", ""),
            sort=params.get("sort", "newest"),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        priority = self.request.GET.get("priority", "")
        context.update(
            tab=self.current_tab(),
            tabs=ticket_tabs(self.request.user),
            priority=priority if priority in Ticket.Priority.values else "",
            priority_choices=Ticket.Priority.choices,
            has_filters=bool(context["q"] or priority or self.current_tab() != "open"),
        )
        return context


class TicketCompletedView(LoginRequiredMixin, ListContextMixin, ListView):
    """Finished tickets, so staff can check that something is complete and follow up if needed."""

    context_object_name = "tickets"
    paginate_by = 10
    full_template = "website/ticket_completed.html"
    partial_template = "website/_completed_results.html"
    sort_labels = COMPLETED_SORT_LABELS
    default_sort = "newest"
    status_choices = ()

    def get_queryset(self):
        params = self.request.GET
        return filter_completed(
            Ticket.objects.select_related("company", "contact", "completed_by"),
            q=params.get("q", ""),
            by=params.get("by", ""),
            period=params.get("period", "30"),
            sort=params.get("sort", "newest"),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.request.GET.get("period", "30")
        context.update(
            by=self.request.GET.get("by", ""),
            period=period if period in dict(COMPLETED_PERIODS) else "30",
            period_choices=COMPLETED_PERIODS,
            staff=active_staff(),
            has_filters=bool(context["q"] or self.request.GET.get("by") or period != "30"),
        )
        return context


class TicketDetailView(LoginRequiredMixin, StaffListMixin, DetailView):
    context_object_name = "ticket"
    template_name = "website/ticket_detail.html"

    def get_queryset(self):
        return Ticket.objects.select_related("company", "contact", "assigned_to", "created_by", "completed_by").prefetch_related(
            Prefetch("events", queryset=TicketEvent.objects.select_related("actor"))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ticket = self.object
        email = ticket.requester_email or (ticket.contact.email if ticket.contact_id else "")
        context.update(
            verification=verify_sender(email) if email else None,
            done_form=TicketDoneForm(),
            comment_form=TicketCommentForm(),
        )
        return context


class TicketCreateView(LoginRequiredMixin, CreateView):
    model = Ticket
    form_class = TicketForm
    template_name = "website/ticket_form.html"

    def get_initial(self):
        initial = super().get_initial()
        for key in ("company", "contact"):
            if self.request.GET.get(key, "").isdigit():
                initial[key] = int(self.request.GET[key])
        if self.request.GET.get("email"):
            initial["requester_email"] = self.request.GET["email"][:100]
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="New ticket", submit_label="Create ticket")
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        tickets.log(self.object, self.request.user, TicketEvent.Kind.CREATED, "created this ticket.")
        if form.cleaned_data.get("claim_now"):
            tickets.assign(self.object.pk, self.request.user, self.request.user)
            messages.success(self.request, f"{self.object.number} was created and assigned to you.")
        else:
            messages.success(self.request, f"{self.object.number} was created. It is waiting for someone to take it.")
        return response


class TicketUpdateView(LoginRequiredMixin, UpdateView):
    model = Ticket
    form_class = TicketForm
    template_name = "website/ticket_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title=f"Edit {self.object.number}", submit_label="Save changes")
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.object.number} was updated.")
        return response


class TicketDeleteView(AdminRequiredMixin, DeleteView):
    model = Ticket
    context_object_name = "ticket"
    template_name = "website/ticket_confirm_delete.html"
    success_url = reverse_lazy("ticket_list")

    def form_valid(self, form):
        number, pk = self.object.number, self.object.pk
        response = super().form_valid(form)
        security_logger.info("Ticket deleted id=%s by=%r", pk, self.request.user.get_username())
        messages.success(self.request, f"{number} was deleted.")
        return response


class TicketActionView(LoginRequiredMixin, View):
    """Base for the buttons on a ticket. POST only; goes back to the page the person was on."""

    http_method_names = ["post"]

    def back(self, request, ticket):
        referer = request.META.get("HTTP_REFERER", "")
        if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
            return redirect(referer)
        return redirect(ticket.get_absolute_url())

    def post(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        try:
            message = self.run(request, ticket)
            if message:
                messages.success(request, message)
        except tickets.TicketError as error:
            messages.error(request, str(error))
        return self.back(request, ticket)


class TicketAssignView(TicketActionView):
    """POST assignee=<user id> to assign (or claim), or assignee= (empty) to release."""

    def run(self, request, ticket):
        raw = request.POST.get("assignee", "")
        if raw == "":
            tickets.assign(ticket.pk, request.user, None)
            return f"{ticket.number} is unassigned again. Nobody is working on it."
        if not raw.isdigit():
            raise tickets.TicketError("Choose a person from the list.")
        assignee = User.objects.filter(pk=int(raw), is_active=True).first()
        if assignee is None:
            raise tickets.TicketError("That person was not found.")
        tickets.assign(ticket.pk, request.user, assignee)
        if assignee.pk == request.user.pk:
            return f"{ticket.number} is yours now."
        return f"{ticket.number} was assigned to {tickets.person(assignee)}."


class TicketDoneView(TicketActionView):
    def run(self, request, ticket):
        form = TicketDoneForm(request.POST)
        if not form.is_valid():
            raise tickets.TicketError("Write what was done (at least a few words) before marking the ticket Done.")
        tickets.complete(ticket.pk, request.user, form.cleaned_data["resolution"])
        return f"{ticket.number} is Done. You can find it under Completed."


class TicketReopenView(TicketActionView):
    def run(self, request, ticket):
        tickets.reopen(ticket.pk, request.user)
        return f"{ticket.number} was reopened."


class TicketCommentView(TicketActionView):
    def run(self, request, ticket):
        form = TicketCommentForm(request.POST)
        if not form.is_valid():
            raise tickets.TicketError("A note can't be empty or longer than 2,000 characters.")
        tickets.log(ticket, request.user, TicketEvent.Kind.COMMENT, form.cleaned_data["body"])
        return "Note added."

    def back(self, request, ticket):
        return redirect(f"{ticket.get_absolute_url()}#history")


# ==========================================================================
# Reports
# ==========================================================================
class ReportsView(LoginRequiredMixin, TemplateView):
    template_name = "website/reports.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(report_data())
        return context
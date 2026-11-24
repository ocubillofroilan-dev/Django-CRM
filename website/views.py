import csv

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView, PasswordResetView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, UpdateView

from . import security
from .forms import LoginForm, NoteForm, RecordForm, SignUpForm
from .models import MANAGE_ALL_PERMISSION, Note, Record
from .queries import SORT_LABELS, filter_records, record_stats
from .roles import AGENT_GROUP
from .security import security_logger


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
                "Blocked login while locked username=%r ip=%s",
                username[:50],
                security.client_ip(request),
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


class RegisterView(FormView):
    template_name = "registration/register.html"
    form_class = SignUpForm
    success_url = reverse_lazy("home")

    def dispatch(self, request, *args, **kwargs):
        if not settings.ALLOW_REGISTRATION:
            raise Http404("Registration is closed.")
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        # New accounts are Agents: they only ever see the customers they create.
        agent_group, _ = Group.objects.get_or_create(name=AGENT_GROUP)
        user.groups.add(agent_group)
        login(self.request, user)
        security_logger.info("New account username=%r ip=%s", user.get_username(), security.client_ip(self.request))
        messages.success(self.request, "Your account is ready. Add your first customer to get started.")
        return super().form_valid(form)


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
# Customers
# ==========================================================================
class RecordAccessMixin(LoginRequiredMixin):
    """Every customer view starts from the rows the current user is allowed to see."""

    def get_queryset(self):
        return Record.objects.visible_to(self.request.user).select_related("owner")


class RecordListView(RecordAccessMixin, ListView):
    context_object_name = "records"
    paginate_by = 10

    def get_queryset(self):
        params = self.request.GET
        return filter_records(
            super().get_queryset(),
            q=params.get("q", ""),
            status=params.get("status", ""),
            sort=params.get("sort", "newest"),
        )

    def get_template_names(self):
        if is_ajax(self.request):
            return ["website/_record_results.html"]
        return ["website/record_list.html"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        query_params = params.copy()
        query_params.pop("page", None)

        page_obj = context["page_obj"]
        paginator = context["paginator"]
        q = params.get("q", "").strip()
        status = params.get("status", "")
        if status not in Record.Status.values:
            status = ""

        context.update(
            q=q,
            status=status,
            sort=params.get("sort", "newest"),
            sort_options=SORT_LABELS,
            status_choices=Record.Status.choices,
            has_filters=bool(q or status),
            querystring=query_params.urlencode(),
            page_range=list(paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)),
            ellipsis=Paginator.ELLIPSIS,
        )
        if not is_ajax(self.request):
            context["stats"] = record_stats(Record.objects.visible_to(self.request.user))
        return context

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        # Same URL, two different bodies (full page vs. partial): tell caches apart.
        patch_vary_headers(response, ["X-Requested-With"])
        return response


class RecordDetailView(RecordAccessMixin, DetailView):
    context_object_name = "record"
    template_name = "website/record_detail.html"

    def get_queryset(self):
        return super().get_queryset().prefetch_related(
            Prefetch("timeline", queryset=Note.objects.select_related("author"))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["note_form"] = NoteForm()
        return context


class RecordFormMixin(RecordAccessMixin):
    form_class = RecordForm
    template_name = "website/record_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class RecordCreateView(RecordFormMixin, CreateView):
    def get_initial(self):
        initial = super().get_initial()
        initial["owner"] = self.request.user.pk
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="New customer", submit_label="Create customer")
        return context

    def form_valid(self, form):
        if not form.instance.owner_id:
            form.instance.owner = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f"{self.object.full_name} was added.")
        return response


class RecordUpdateView(RecordFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title=f"Edit {self.object.full_name}", submit_label="Save changes")
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.object.full_name} was updated.")
        return response


class RecordDeleteView(RecordAccessMixin, DeleteView):
    """GET shows a confirmation page. Only POST (with a CSRF token) deletes."""

    context_object_name = "record"
    template_name = "website/record_confirm_delete.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        name, pk = self.object.full_name, self.object.pk
        response = super().form_valid(form)
        security_logger.info("Customer deleted id=%s by=%r", pk, self.request.user.get_username())
        messages.success(self.request, f"{name} was deleted.")
        return response


def csv_safe(value):
    """Neutralise spreadsheet formula injection (a cell starting with = + - @ runs as a formula)."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


class RecordExportView(RecordAccessMixin, View):
    """CSV of exactly what the user could see in the list, with the same filters applied."""

    def get(self, request):
        params = request.GET
        queryset = filter_records(
            self.get_queryset(),
            q=params.get("q", ""),
            status=params.get("status", ""),
            sort=params.get("sort", "newest"),
        )
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        filename = f"customers-{timezone.localdate():%Y%m%d}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("\ufeff")  # BOM: lets Excel open UTF-8 correctly
        writer = csv.writer(response)
        writer.writerow(
            ["First name", "Last name", "Email", "Phone", "Status", "Address", "City", "Province", "Zip", "Owner", "Created"]
        )
        count = 0
        for r in queryset.iterator():
            owner = (r.owner.get_full_name() or r.owner.get_username()) if r.owner else ""
            writer.writerow(
                [
                    csv_safe(value)
                    for value in (
                        r.first_name,
                        r.last_name,
                        r.email,
                        r.phone,
                        r.get_status_display(),
                        r.address,
                        r.city,
                        r.province,
                        r.zipcode,
                        owner,
                        timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
                    )
                ]
            )
            count += 1
        security_logger.info("CSV export rows=%d by=%r", count, request.user.get_username())
        return response


# ==========================================================================
# Notes (customer timeline)
# ==========================================================================
class NoteCreateView(RecordAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        record = get_object_or_404(self.get_queryset(), pk=pk)
        form = NoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.record = record
            note.author = request.user
            note.save()
            messages.success(request, "Note added.")
        else:
            messages.error(request, "A note can't be empty or longer than 2,000 characters.")
        return redirect(f"{record.get_absolute_url()}#timeline")


class NoteDeleteView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        visible = Record.objects.visible_to(request.user)
        note = get_object_or_404(Note.objects.filter(record__in=visible), pk=pk)
        if note.author_id != request.user.pk and not request.user.has_perm(MANAGE_ALL_PERMISSION):
            raise PermissionDenied("Only the author or a manager can delete this note.")
        record = note.record
        note.delete()
        messages.success(request, "Note deleted.")
        return redirect(f"{record.get_absolute_url()}#timeline")
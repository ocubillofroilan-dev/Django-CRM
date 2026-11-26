from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.utils import timezone

from .models import Company, Contact, Ticket

# --- Contacts ---------------------------------------------------------------
CONTACT_SORTS = {
    "newest": ("-created_at", "-id"),
    "oldest": ("created_at", "id"),
    "name": ("last_name", "first_name", "id"),
    "-name": ("-last_name", "-first_name", "-id"),
    "company": ("company__name", "last_name", "id"),
    "status": ("status", "last_name", "id"),
}
CONTACT_SORT_LABELS = [
    ("newest", "Newest first"),
    ("oldest", "Oldest first"),
    ("name", "Name A to Z"),
    ("-name", "Name Z to A"),
    ("company", "Company"),
    ("status", "Status"),
]
CONTACT_SEARCH = ("first_name", "last_name", "email", "phone", "job_title", "city", "company__name")


def _search(queryset, q, fields):
    q = (q or "").strip()[:100]
    for term in q.split()[:5]:  # every word must match somewhere
        condition = Q()
        for field in fields:
            condition |= Q(**{f"{field}__icontains": term})
        queryset = queryset.filter(condition)
    return queryset


def filter_contacts(queryset, q="", status="", sort="newest", company=""):
    queryset = _search(queryset, q, CONTACT_SEARCH)
    if status in Contact.Status.values:
        queryset = queryset.filter(status=status)
    if str(company).isdigit():
        queryset = queryset.filter(company_id=int(company))
    return queryset.order_by(*CONTACT_SORTS.get(sort, CONTACT_SORTS["newest"]))


# --- Companies --------------------------------------------------------------
COMPANY_SORTS = {
    "name": ("name",),
    "newest": ("-created_at", "-id"),
    "status": ("status", "name"),
}
COMPANY_SORT_LABELS = [("name", "Name A to Z"), ("newest", "Newest first"), ("status", "Status")]
COMPANY_SEARCH = ("name", "code", "industry", "email_domains", "city")


def filter_companies(queryset, q="", status="", sort="name"):
    queryset = _search(queryset, q, COMPANY_SEARCH)
    if status in Company.Status.values:
        queryset = queryset.filter(status=status)
    return queryset.order_by(*COMPANY_SORTS.get(sort, COMPANY_SORTS["name"]))


def with_contact_counts(queryset):
    return queryset.annotate(contact_count=Count("contacts"))


# --- Dashboard --------------------------------------------------------------
def dashboard_stats():
    since = timezone.now() - timedelta(days=30)
    companies = Company.objects.aggregate(
        clients=Count("id", filter=Q(status=Company.Status.CLIENT)),
        prospects=Count("id", filter=Q(status=Company.Status.PROSPECT)),
        new_companies=Count("id", filter=Q(created_at__gte=since)),
    )
    contacts = Contact.objects.aggregate(
        contacts=Count("id"),
        new_contacts=Count("id", filter=Q(created_at__gte=since)),
    )
    tickets = Ticket.objects.aggregate(
        open_tickets=Count("id", filter=~Q(status=Ticket.Status.DONE)),
        unassigned_tickets=Count("id", filter=Q(status=Ticket.Status.OPEN, assigned_to__isnull=True)),
    )
    return {
        "clients": companies["clients"],
        "prospects": companies["prospects"],
        "contacts": contacts["contacts"],
        "new_30": companies["new_companies"] + contacts["new_contacts"],
        "open_tickets": tickets["open_tickets"],
        "unassigned_tickets": tickets["unassigned_tickets"],
    }


# --- Tickets ----------------------------------------------------------------
TICKET_SEARCH = ("number", "subject", "description", "requester_email", "company__name", "contact__first_name", "contact__last_name")
TICKET_SORT_LABELS = [("newest", "Newest first"), ("oldest", "Oldest first"), ("priority", "Highest priority")]


def _priority_rank():
    return Case(
        When(priority=Ticket.Priority.URGENT, then=Value(0)),
        When(priority=Ticket.Priority.HIGH, then=Value(1)),
        When(priority=Ticket.Priority.NORMAL, then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )


def ticket_tabs(user):
    """(key, label, count) for the tabs above the ticket list."""
    counts = Ticket.objects.aggregate(
        open=Count("id", filter=~Q(status=Ticket.Status.DONE)),
        unassigned=Count("id", filter=Q(status=Ticket.Status.OPEN, assigned_to__isnull=True)),
        mine=Count("id", filter=~Q(status=Ticket.Status.DONE) & Q(assigned_to=user)),
        in_progress=Count("id", filter=Q(status=Ticket.Status.IN_PROGRESS)),
    )
    return [
        ("open", "All open", counts["open"]),
        ("unassigned", "Unassigned", counts["unassigned"]),
        ("mine", "My tickets", counts["mine"]),
        ("in_progress", "In progress", counts["in_progress"]),
    ]


def filter_tickets(queryset, user, q="", view="open", priority="", sort="newest"):
    queryset = _search(queryset, q, TICKET_SEARCH)
    if view == "unassigned":
        queryset = queryset.filter(status=Ticket.Status.OPEN, assigned_to__isnull=True)
    elif view == "mine":
        queryset = queryset.exclude(status=Ticket.Status.DONE).filter(assigned_to=user)
    elif view == "in_progress":
        queryset = queryset.filter(status=Ticket.Status.IN_PROGRESS)
    else:
        queryset = queryset.exclude(status=Ticket.Status.DONE)
    if priority in Ticket.Priority.values:
        queryset = queryset.filter(priority=priority)
    if sort == "oldest":
        return queryset.order_by("created_at", "id")
    if sort == "priority":
        return queryset.annotate(rank=_priority_rank()).order_by("rank", "-created_at", "-id")
    return queryset.order_by("-created_at", "-id")


COMPLETED_PERIODS = [("7", "Last 7 days"), ("30", "Last 30 days"), ("", "All time")]
COMPLETED_SORT_LABELS = [("newest", "Recently completed"), ("oldest", "Oldest completed")]


def filter_completed(queryset, q="", by="", period="30", sort="newest"):
    queryset = _search(queryset.filter(status=Ticket.Status.DONE), q, TICKET_SEARCH + ("resolution",))
    if str(by).isdigit():
        queryset = queryset.filter(completed_by_id=int(by))
    if str(period).isdigit():
        queryset = queryset.filter(completed_at__gte=timezone.now() - timedelta(days=int(period)))
    return queryset.order_by("completed_at", "id") if sort == "oldest" else queryset.order_by("-completed_at", "-id")


# --- Reports ------------------------------------------------------------------
def report_data(days=14):
    """Everything the Reports page shows."""
    now = timezone.now()
    since_7, since_30 = now - timedelta(days=7), now - timedelta(days=30)
    User = get_user_model()

    totals = Ticket.objects.aggregate(
        open_now=Count("id", filter=~Q(status=Ticket.Status.DONE)),
        unassigned_now=Count("id", filter=Q(status=Ticket.Status.OPEN, assigned_to__isnull=True)),
        in_progress_now=Count("id", filter=Q(status=Ticket.Status.IN_PROGRESS)),
        created_7=Count("id", filter=Q(created_at__gte=since_7)),
        done_7=Count("id", filter=Q(status=Ticket.Status.DONE, completed_at__gte=since_7)),
        done_30=Count("id", filter=Q(status=Ticket.Status.DONE, completed_at__gte=since_30)),
    )

    # Average time from "created" to "done" for tickets finished in the last 30 days.
    finished = Ticket.objects.filter(status=Ticket.Status.DONE, completed_at__gte=since_30)
    hours = [
        (completed - created).total_seconds() / 3600
        for created, completed in finished.values_list("created_at", "completed_at")[:5000]
    ]
    totals["avg_hours"] = round(sum(hours) / len(hours), 1) if hours else None

    # Per-day counts for the bar chart.
    start = timezone.localtime(now).date() - timedelta(days=days - 1)
    start_dt = timezone.make_aware(datetime.combine(start, time.min))  # avoids DB time-zone functions
    created, done = {}, {}
    for value in Ticket.objects.filter(created_at__gte=start_dt).values_list("created_at", flat=True):
        day = timezone.localtime(value).date()
        created[day] = created.get(day, 0) + 1
    for value in Ticket.objects.filter(status=Ticket.Status.DONE, completed_at__gte=start_dt).values_list("completed_at", flat=True):
        day = timezone.localtime(value).date()
        done[day] = done.get(day, 0) + 1
    peak = max([1] + list(created.values()) + list(done.values()))
    chart = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        c, d = created.get(day, 0), done.get(day, 0)
        chart.append({"day": day, "created": c, "done": d, "created_h": round(c / peak * 10), "done_h": round(d / peak * 10)})

    team = (
        User.objects.filter(is_active=True)
        .annotate(
            open_count=Count("assigned_tickets", filter=~Q(assigned_tickets__status=Ticket.Status.DONE), distinct=True),
            done_count=Count("completed_tickets", filter=Q(completed_tickets__completed_at__gte=since_30), distinct=True),
        )
        .order_by("-done_count", "-open_count", "username")
    )
    clients = (
        Company.objects.annotate(n=Count("tickets", filter=Q(tickets__created_at__gte=since_30), distinct=True))
        .filter(n__gt=0)
        .order_by("-n", "name")[:5]
    )
    return {"totals": totals, "chart": chart, "team": team, "clients": clients}
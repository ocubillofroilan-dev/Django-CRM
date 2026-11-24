from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from .models import Record

SORT_OPTIONS = {
    "newest": ("-created_at", "-id"),
    "oldest": ("created_at", "id"),
    "name": ("last_name", "first_name", "id"),
    "-name": ("-last_name", "-first_name", "-id"),
    "city": ("city", "last_name", "id"),
    "status": ("status", "last_name", "id"),
}

SORT_LABELS = [
    ("newest", "Newest first"),
    ("oldest", "Oldest first"),
    ("name", "Name A to Z"),
    ("-name", "Name Z to A"),
    ("city", "City"),
    ("status", "Status"),
]

SEARCH_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "city",
    "province",
    "address",
)


def filter_records(queryset, q="", status="", sort="newest"):
    """Apply the shared search / status filter / sort used by the UI, CSV export and API."""
    q = (q or "").strip()[:100]
    for term in q.split()[:5]:  # every word must match somewhere (AND), any field (OR)
        condition = Q()
        for field in SEARCH_FIELDS:
            condition |= Q(**{f"{field}__icontains": term})
        queryset = queryset.filter(condition)

    if status in Record.Status.values:
        queryset = queryset.filter(status=status)

    return queryset.order_by(*SORT_OPTIONS.get(sort, SORT_OPTIONS["newest"]))


def record_stats(queryset):
    """Dashboard numbers for whatever the user is allowed to see."""
    since = timezone.now() - timedelta(days=30)
    return queryset.aggregate(
        total=Count("id"),
        leads=Count("id", filter=Q(status=Record.Status.LEAD)),
        active=Count("id", filter=Q(status=Record.Status.ACTIVE)),
        inactive=Count("id", filter=Q(status=Record.Status.INACTIVE)),
        new_30=Count("id", filter=Q(created_at__gte=since)),
    )
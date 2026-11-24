from rest_framework import filters, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from ..models import MANAGE_ALL_PERMISSION, Record
from ..queries import record_stats
from .serializers import NoteSerializer, RecordSerializer


class RecordViewSet(viewsets.ModelViewSet):
    """
    Customers. Agents only ever see (and can only change) their own customers;
    managers see everyone's. Anything outside your scope is a 404, not a 403,
    so the API never confirms that someone else's record exists.

    Query params: `search`, `status`, `ordering` (e.g. `-created_at`, `last_name`), `page`.
    """

    serializer_class = RecordSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["first_name", "last_name", "email", "phone", "city", "province"]
    ordering_fields = ["created_at", "updated_at", "last_name", "city", "status"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self):
        queryset = Record.objects.visible_to(self.request.user).select_related("owner")
        status = self.request.query_params.get("status")
        if status in Record.Status.values:
            queryset = queryset.filter(status=status)
        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Counts for the customers you can see."""
        return Response(record_stats(Record.objects.visible_to(request.user)))

    @action(detail=True, methods=["get", "post"])
    def timeline(self, request, pk=None):
        """GET the notes on a customer, or POST {"body": "..."} to add one."""
        record = self.get_object()
        if request.method == "POST":
            serializer = NoteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(record=record, author=request.user)
            return Response(serializer.data, status=201)
        page = self.paginate_queryset(record.timeline.select_related("author"))
        serializer = NoteSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class ThrottledObtainAuthToken(ObtainAuthToken):
    """POST {"username": "...", "password": "..."} -> {"token": "..."}  (5 requests/minute)."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class RevokeTokenView(APIView):
    """POST to invalidate your API token (e.g. on sign-out or if it leaked)."""

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=204)


class MeView(APIView):
    """Who am I, and what can I do?"""

    def get(self, request):
        user = request.user
        return Response(
            {
                "id": user.pk,
                "username": user.get_username(),
                "name": user.get_full_name(),
                "email": user.email,
                "is_manager": user.has_perm(MANAGE_ALL_PERMISSION),
            }
        )
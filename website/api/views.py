from rest_framework import filters, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from ..models import Company, Contact
from ..permissions import is_admin
from ..queries import dashboard_stats, with_contact_counts
from ..verification import verify_sender
from .serializers import CompanySerializer, ContactSerializer, NoteSerializer


class AdminOnlyDelete(BasePermission):
    """Any signed-in staff member may read and write; only administrators may delete."""

    def has_permission(self, request, view):
        if request.method == "DELETE":
            return is_admin(request.user)
        return True


class ContactViewSet(viewsets.ModelViewSet):
    """
    Contacts (people). All staff share the same data; only administrators can delete.

    Query params: `search`, `status`, `company` (id), `ordering` (e.g. `-created_at`, `last_name`), `page`.
    """

    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated, AdminOnlyDelete]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["first_name", "last_name", "email", "phone", "job_title", "company__name"]
    ordering_fields = ["created_at", "updated_at", "last_name", "status"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self):
        queryset = Contact.objects.select_related("company", "owner")
        params = self.request.query_params
        if params.get("status") in Contact.Status.values:
            queryset = queryset.filter(status=params["status"])
        if params.get("company", "").isdigit():
            queryset = queryset.filter(company_id=int(params["company"]))
        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["get", "post"])
    def timeline(self, request, pk=None):
        """GET the notes on a contact, or POST {"body": "..."} to add one."""
        contact = self.get_object()
        if request.method == "POST":
            serializer = NoteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(contact=contact, author=request.user)
            return Response(serializer.data, status=201)
        page = self.paginate_queryset(contact.timeline.select_related("author"))
        return self.get_paginated_response(NoteSerializer(page, many=True).data)


class CompanyViewSet(viewsets.ModelViewSet):
    """
    Companies (clients and prospects), including the details staff use to verify a sender.

    Query params: `search`, `status`, `ordering`, `page`.
    """

    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated, AdminOnlyDelete]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "code", "industry", "email_domains", "city"]
    ordering_fields = ["name", "created_at", "status"]
    ordering = ["name"]

    def get_queryset(self):
        queryset = with_contact_counts(Company.objects.select_related("account_manager"))
        status = self.request.query_params.get("status")
        if status in Company.Status.values:
            queryset = queryset.filter(status=status)
        return queryset

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Totals for the dashboard."""
        return Response(dashboard_stats())


class VerifyView(APIView):
    """GET /verify/?email=someone@example.com tells you whether that sender is one of our clients."""

    def get(self, request):
        result = verify_sender(request.query_params.get("email", ""))
        return Response(
            {
                "email": result.email,
                "level": result.level,
                "headline": result.headline,
                "trusted": result.is_trusted,
                "contact": {"id": result.contact.pk, "name": result.contact.full_name} if result.contact else None,
                "company": (
                    {
                        "id": result.company.pk,
                        "code": result.company.code,
                        "name": result.company.name,
                        "status": result.company.status,
                        "verification_notes": result.company.verification_notes,
                    }
                    if result.company
                    else None
                ),
            }
        )


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
                "role": "admin" if is_admin(user) else "staff",
            }
        )
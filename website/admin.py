from django.contrib import admin

from .models import Company, Contact, Note, Ticket, TicketEvent


class NoteInline(admin.TabularInline):
    model = Note
    extra = 0
    readonly_fields = ("author", "created_at")


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "status", "industry", "account_manager", "created_at")
    list_filter = ("status", "industry")
    search_fields = ("name", "code", "email_domains")
    readonly_fields = ("code", "created_at", "updated_at")


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("full_name", "company", "email", "phone", "status", "owner", "created_at")
    list_filter = ("status", "can_request", "company")
    search_fields = ("first_name", "last_name", "email", "phone", "company__name")
    list_select_related = ("company", "owner")
    readonly_fields = ("created_at", "updated_at")
    inlines = [NoteInline]


class TicketEventInline(admin.TabularInline):
    model = TicketEvent
    extra = 0
    readonly_fields = ("actor", "kind", "text", "created_at")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("number", "subject", "company", "status", "priority", "assigned_to", "created_at")
    list_filter = ("status", "priority", "assigned_to")
    search_fields = ("number", "subject", "requester_email", "company__name")
    list_select_related = ("company", "assigned_to")
    readonly_fields = ("number", "created_at", "updated_at", "completed_at")
    inlines = [TicketEventInline]
from django.contrib import admin

from .models import Note, Record


class NoteInline(admin.TabularInline):
    model = Note
    extra = 0
    readonly_fields = ("author", "created_at")


@admin.register(Record)
class RecordAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "phone", "city", "status", "owner", "created_at")
    list_filter = ("status", "province", "owner")
    search_fields = ("first_name", "last_name", "email", "phone", "city")
    list_select_related = ("owner",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    inlines = [NoteInline]
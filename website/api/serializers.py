from rest_framework import serializers

from ..models import Note, Record


class NoteSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = ["id", "body", "author", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_author(self, obj):
        return obj.author.get_username() if obj.author_id else None


class RecordSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    owner = serializers.SerializerMethodField()

    class Meta:
        model = Record
        fields = [
            "id",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "status",
            "address",
            "city",
            "province",
            "zipcode",
            "notes",
            "owner",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_owner(self, obj):
        return obj.owner.get_username() if obj.owner_id else None

    def validate_email(self, value):
        return value.strip().lower()
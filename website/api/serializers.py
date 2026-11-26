from rest_framework import serializers

from ..models import Company, Contact, Note
from ..utils import normalize_domains


class NoteSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = ["id", "body", "author", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_author(self, obj):
        return obj.author.get_username() if obj.author_id else None


class CompanySerializer(serializers.ModelSerializer):
    contact_count = serializers.IntegerField(read_only=True)
    account_manager = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id",
            "code",
            "name",
            "status",
            "industry",
            "website",
            "phone",
            "email_domains",
            "verification_notes",
            "services",
            "needs",
            "address",
            "city",
            "province",
            "zipcode",
            "account_manager",
            "contact_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "created_at", "updated_at"]

    def get_account_manager(self, obj):
        return obj.account_manager.get_username() if obj.account_manager_id else None

    def validate_email_domains(self, value):
        try:
            return ", ".join(normalize_domains(value))
        except ValueError as error:
            raise serializers.ValidationError(f"'{error}' is not a valid domain name.")


class ContactSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    company_name = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = [
            "id",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "company",
            "company_name",
            "job_title",
            "can_request",
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

    def get_company_name(self, obj):
        return obj.company.name if obj.company_id else None

    def get_owner(self, obj):
        return obj.owner.get_username() if obj.owner_id else None

    def validate_email(self, value):
        email = value.strip().lower()
        duplicates = Contact.objects.filter(email__iexact=email)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("A contact with this email address already exists.")
        return email
    
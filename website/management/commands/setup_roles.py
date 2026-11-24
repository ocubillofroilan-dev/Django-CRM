from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from website.models import Record
from website.roles import ensure_roles


class Command(BaseCommand):
    help = (
        "Create the Agent and Manager roles. Optionally promote users to Manager "
        "and hand customers that have no owner (e.g. data from before roles existed) to a user."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--manager",
            action="append",
            default=[],
            metavar="USERNAME",
            help="Promote this user to Manager (repeat for several users).",
        )
        parser.add_argument(
            "--assign-unowned",
            metavar="USERNAME",
            help="Give every customer without an owner to this user.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            _, manager_group = ensure_roles()
        except RuntimeError as error:
            raise CommandError(str(error))
        self.stdout.write(self.style.SUCCESS("Roles ready: Agent, Manager."))

        for username in options["manager"]:
            try:
                user = User.objects.get(**{User.USERNAME_FIELD: username})
            except User.DoesNotExist:
                raise CommandError(f"User '{username}' does not exist.")
            user.groups.add(manager_group)
            self.stdout.write(self.style.SUCCESS(f"{username} is now a Manager."))

        target = options["assign_unowned"]
        if target:
            try:
                user = User.objects.get(**{User.USERNAME_FIELD: target})
            except User.DoesNotExist:
                raise CommandError(f"User '{target}' does not exist.")
            updated = Record.objects.filter(owner__isnull=True).update(owner=user)
            self.stdout.write(self.style.SUCCESS(f"Assigned {updated} customer(s) to {target}."))
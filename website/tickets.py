"""
Ticket workflow. Every change goes through these functions so the rules live in one place
and every change leaves a line in the ticket's history.

Rules
-----
* Anyone on staff can claim an UNASSIGNED ticket for themselves.
* Staff cannot give a ticket to someone else, or take one that someone is already working on.
  Only an admin can assign or reassign tickets to anybody.
* You can release your own ticket (it goes back to "Unassigned"). Admins can release anyone's.
* A ticket is finished by whoever is working on it (or an admin), with a note of what was done.
  Finishing an unassigned ticket makes you its owner.
* A Done ticket can be reopened by any staff member, so it can be followed up.
"""
from django.db import transaction
from django.utils import timezone

from .models import Ticket, TicketEvent
from .permissions import is_admin


class TicketError(Exception):
    """A rule was broken. The message is safe to show to the user."""


def person(user):
    return user.get_full_name() or user.get_username()


def log(ticket, actor, kind, text=""):
    return TicketEvent.objects.create(ticket=ticket, actor=actor, kind=kind, text=text)


@transaction.atomic
def assign(ticket_id, actor, assignee):
    """Give the ticket to `assignee` (a user), or release it (assignee=None)."""
    ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
    admin = is_admin(actor)
    current = ticket.assigned_to

    if ticket.is_done:
        raise TicketError("This ticket is done. Reopen it first.")

    if assignee is None:  # release
        if current is None:
            raise TicketError("Nobody is working on this ticket.")
        if not admin and current.pk != actor.pk:
            raise TicketError(f"{person(current)} is working on this ticket. Only an admin can release it.")
        ticket.assigned_to = None
        ticket.status = Ticket.Status.OPEN
        kind, text = TicketEvent.Kind.RELEASED, "released this ticket. Nobody is working on it now."
    else:
        if not assignee.is_active:
            raise TicketError("That account is disabled.")
        if current is not None and current.pk == assignee.pk:
            raise TicketError(f"{person(assignee)} already has this ticket.")
        if not admin:
            if assignee.pk != actor.pk:
                raise TicketError("Only an admin can assign tickets to other people.")
            if current is not None:
                raise TicketError(
                    f"{person(current)} is already working on this ticket. Ask an admin to reassign it."
                )
        ticket.assigned_to = assignee
        ticket.status = Ticket.Status.IN_PROGRESS
        if assignee.pk == actor.pk:
            kind, text = TicketEvent.Kind.CLAIMED, "claimed this ticket."
        else:
            kind, text = TicketEvent.Kind.ASSIGNED, f"assigned this ticket to {person(assignee)}."

    ticket.save(update_fields=["assigned_to", "status", "updated_at"])
    log(ticket, actor, kind, text)
    return ticket


@transaction.atomic
def complete(ticket_id, actor, resolution):
    """Mark the ticket Done and record what was done."""
    ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
    resolution = (resolution or "").strip()
    if ticket.is_done:
        raise TicketError("This ticket is already done.")
    if not resolution:
        raise TicketError("Write what was done before marking the ticket Done.")
    owner = ticket.assigned_to
    if owner is not None and owner.pk != actor.pk and not is_admin(actor):
        raise TicketError(f"Only {person(owner)} or an admin can mark this ticket Done.")

    if owner is None:
        ticket.assigned_to = actor  # whoever finished it owns it
    ticket.status = Ticket.Status.DONE
    ticket.resolution = resolution
    ticket.completed_by = actor
    ticket.completed_at = timezone.now()
    ticket.save(update_fields=["assigned_to", "status", "resolution", "completed_by", "completed_at", "updated_at"])
    log(ticket, actor, TicketEvent.Kind.DONE, f"marked this ticket Done: {resolution}")
    return ticket


@transaction.atomic
def reopen(ticket_id, actor):
    """Bring a Done ticket back, e.g. because the client wrote again."""
    ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
    if not ticket.is_done:
        raise TicketError("This ticket is not done.")
    ticket.status = Ticket.Status.IN_PROGRESS if ticket.assigned_to_id else Ticket.Status.OPEN
    ticket.completed_by = None
    ticket.completed_at = None
    ticket.save(update_fields=["status", "completed_by", "completed_at", "updated_at"])
    log(ticket, actor, TicketEvent.Kind.REOPENED, "reopened this ticket for a follow-up.")
    return ticket
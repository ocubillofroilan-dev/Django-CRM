from django.conf import settings

from .models import Ticket
from .permissions import is_admin


def app_settings(request):
    user = getattr(request, "user", None)
    signed_in = bool(user and user.is_authenticated)
    return {
        "unassigned_tickets": (
            Ticket.objects.filter(status=Ticket.Status.OPEN, assigned_to__isnull=True).count() if signed_in else 0
        ),
        "APP_NAME": settings.APP_NAME,
        "APP_TAGLINE": settings.APP_TAGLINE,
        "DEMO_MODE": settings.DEMO_MODE,
        "DEMO_PASSWORD": settings.DEMO_PASSWORD,
        "is_admin": bool(user and is_admin(user)),
    }
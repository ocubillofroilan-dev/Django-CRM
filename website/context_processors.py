from django.conf import settings

from .models import MANAGE_ALL_PERMISSION


def app_settings(request):
    user = getattr(request, "user", None)
    return {
        "ALLOW_REGISTRATION": settings.ALLOW_REGISTRATION,
        "can_manage_all": bool(user and user.is_authenticated and user.has_perm(MANAGE_ALL_PERMISSION)),
    }
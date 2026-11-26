"""
Two roles:

* Staff  - every signed-in, active account. Sees everything, creates and edits.
* Admin  - a Django superuser. Also creates staff accounts, assigns work to other
           people and deletes records.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


def is_admin(user):
    return bool(user.is_authenticated and user.is_active and user.is_superuser)


class AdminRequiredMixin(LoginRequiredMixin):
    """Signed-out users go to the login page; signed-in staff get a 403."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not is_admin(request.user):
            raise PermissionDenied("Administrators only.")
        return super().dispatch(request, *args, **kwargs)
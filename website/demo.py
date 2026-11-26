"""
Public demo mode (DEMO_MODE=True).

A demo site is open to anyone who reads the login box, so a few things are switched off:
changing passwords, adding or disabling staff, and the Django admin site. Everything else
works, and the data resets whenever the free server goes to sleep.
"""
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

BLOCKED_ON_POST = {"password_change", "password_reset", "team_add", "team_toggle"}


class DemoModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DEMO_MODE and request.path.startswith("/admin/"):
            messages.info(request, "The Django admin site is switched off in the public demo.")
            return redirect("home")
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if settings.DEMO_MODE and request.method == "POST" and match and match.url_name in BLOCKED_ON_POST:
            messages.info(request, "That is switched off in the public demo.")
            return redirect("home")
        return None
"""
Small, dependency-free rate limiting built on Django's cache.

The default cache is per-process memory, which is fine for development and a
single worker. For several workers/servers point CACHES at Redis or Memcached
so every worker shares the same counters.
"""
import hashlib
import logging

from django.conf import settings
from django.core.cache import cache

security_logger = logging.getLogger("website.security")


def client_ip(request):
    # REMOTE_ADDR is the only value a client cannot spoof. If you deploy behind
    # a reverse proxy, configure the proxy / WSGI server to set it correctly
    # rather than trusting X-Forwarded-For here.
    return request.META.get("REMOTE_ADDR", "unknown")


def _key(scope, identity):
    digest = hashlib.sha256(identity.strip().lower().encode("utf-8")).hexdigest()
    return f"ratelimit:{scope}:{digest}"


def current_count(scope, identity):
    return cache.get(_key(scope, identity), 0)


def register_hit(scope, identity, limit, window):
    """Count one event. When the limit is reached the window restarts (full lockout)."""
    key = _key(scope, identity)
    cache.add(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:  # key expired between add() and incr()
        cache.set(key, 1, window)
        count = 1
    if count >= limit:
        cache.set(key, count, window)
    return count


def reset(scope, identity):
    cache.delete(_key(scope, identity))


# --- Login throttling ------------------------------------------------------
def _login_identity(username, ip):
    return f"{username}|{ip}"


def login_is_locked(username, ip):
    return current_count("login", _login_identity(username, ip)) >= settings.LOGIN_MAX_ATTEMPTS


def login_failed(username, ip):
    count = register_hit(
        "login",
        _login_identity(username, ip),
        settings.LOGIN_MAX_ATTEMPTS,
        settings.LOGIN_LOCKOUT_SECONDS,
    )
    security_logger.warning(
        "Failed login username=%r ip=%s attempt=%d", username[:50], ip, count
    )
    if count == settings.LOGIN_MAX_ATTEMPTS:
        security_logger.warning("Login locked username=%r ip=%s", username[:50], ip)
    return count


def login_succeeded(username, ip):
    reset("login", _login_identity(username, ip))
    security_logger.info("Login ok username=%r ip=%s", username[:50], ip)


# --- Password-reset throttling (stops email flooding) -----------------------
RESET_LIMIT = 5
RESET_WINDOW = 60 * 60


def reset_is_blocked(ip):
    return current_count("pwreset", ip) >= RESET_LIMIT


def reset_requested(ip):
    return register_hit("pwreset", ip, RESET_LIMIT, RESET_WINDOW)
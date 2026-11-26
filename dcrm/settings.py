"""
Django settings for the dcrm project.

Everything that differs between your laptop and a server (secret key, debug
flag, database credentials, hosts, HTTPS) is read from environment variables.
Copy `.env.example` to `.env` for local development. Nothing secret lives in
this file or in Git.
"""
import os
from pathlib import Path

from django.contrib.messages import constants as message_constants
from django.core.exceptions import ImproperlyConfigured

try:  # python-dotenv is only a convenience for local development
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def env_required(name):
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(
            f"Missing environment variable {name}. Copy .env.example to .env and fill it in."
        )
    return value


# --------------------------------------------------------------------------
# Core security
# --------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        # Local development only. Never reaches production because DEBUG must be on.
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is not set. Copy .env.example to .env "
            "(and set DJANGO_DEBUG=True for local development)."
        )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Render sets this automatically, so the live site works without extra host settings.
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_HOST}")

# Public demo mode: shows a banner and the demo logins, and switches off the things a
# visitor could use to lock others out (password changes, new staff, the Django admin site).
DEMO_MODE = env_bool("DEMO_MODE", False)
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo-pass-123")


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "website",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "website.demo.DemoModeMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

try:  # WhiteNoise serves the CSS/JS in production. Optional on your own computer.
    import whitenoise  # noqa: F401

    HAS_WHITENOISE = True
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
except ImportError:  # pragma: no cover
    HAS_WHITENOISE = False

ROOT_URLCONF = "dcrm.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "website.context_processors.app_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "dcrm.wsgi.application"
ASGI_APPLICATION = "dcrm.asgi.application"


# --------------------------------------------------------------------------
# Database: SQLite by default (zero setup), MySQL when DB_ENGINE=mysql
# --------------------------------------------------------------------------
DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite").strip().lower()

if DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env_required("DB_NAME"),
            "USER": env_required("DB_USER"),
            "PASSWORD": env_required("DB_PASSWORD"),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "3306"),
            "CONN_MAX_AGE": 60,
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# Brute-force protection (see website/security.py)
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "900"))

# Product name shown in the UI and emails.
APP_NAME = "ClientDesk"
APP_TAGLINE = "Client Relationship Management"

# Sessions
SESSION_COOKIE_AGE = 60 * 60 * 12  # 12 hours
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"


# --------------------------------------------------------------------------
# HTTP security headers & HTTPS (switch on in production with DJANGO_FORCE_HTTPS=True)
# --------------------------------------------------------------------------
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if env_bool("DJANGO_FORCE_HTTPS", False):
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Start small, raise once you are sure HTTPS works everywhere.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_SUBDOMAINS", False)
    if env_bool("DJANGO_BEHIND_PROXY", False):
        # Only enable when a trusted reverse proxy sets/strips this header.
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# --------------------------------------------------------------------------
# Email (password reset). Prints to the console unless EMAIL_HOST is set.
# --------------------------------------------------------------------------
if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "ClientDesk <no-reply@localhost>")


# --------------------------------------------------------------------------
# Internationalisation
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Manila")
USE_I18N = True
USE_TZ = True


# --------------------------------------------------------------------------
# Static files & messages
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedStaticFilesStorage"
            if HAS_WHITENOISE
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
    },
}

# Map Django message levels to Bootstrap colour names.
MESSAGE_TAGS = {
    message_constants.DEBUG: "secondary",
    message_constants.INFO: "info",
    message_constants.SUCCESS: "success",
    message_constants.WARNING: "warning",
    message_constants.ERROR: "danger",
}


# --------------------------------------------------------------------------
# REST API
# --------------------------------------------------------------------------
_renderers = ["rest_framework.renderers.JSONRenderer"]
if DEBUG:
    _renderers.append("rest_framework.renderers.BrowsableAPIRenderer")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": _renderers,
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/min",
        "user": "120/min",
        "auth": "5/min",
    },
}


# --------------------------------------------------------------------------
# Logging: security events (failed logins, lockouts, exports) go to the console
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "loggers": {
        "website.security": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
"""
Django settings for the Online Auction Management System.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# -------------------------------------------------------------------
# Core / Security
# -------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-change-this-in-production-!!!",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")

# -------------------------------------------------------------------
# Applications
# -------------------------------------------------------------------
INSTALLED_APPS = [
    # Provides the ASGI-capable runserver; must precede staticfiles.
    "daphne",
    "channels",

    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    # third party
    "crispy_forms",
    "crispy_bootstrap5",

    # local apps
    "core",
    "dashboard",
    "accounts",
    "categories",
    "products",
    "auctions",
    "bids",
    "winners",
    "payments",
    "notifications",
    "watchlist",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "auctions.middleware.AuctionLifecycleMiddleware",
]

ROOT_URLCONF = "auction_system.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "notifications.context_processors.unread_notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "auction_system.wsgi.application"
ASGI_APPLICATION = "auction_system.asgi.application"

# -------------------------------------------------------------------
# Channels (live auction updates over WebSocket)
#
# Uses an in-memory channel layer by default, which is fine for a single
# dev/prod process. Set REDIS_URL to use Redis so updates fan out across
# multiple workers/servers:
#     REDIS_URL=redis://127.0.0.1:6379/0
# The HTTP polling fallback keeps working even if this isn't configured.
# -------------------------------------------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }

# -------------------------------------------------------------------
# Database
# -------------------------------------------------------------------
if os.environ.get("DB_ENGINE") == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "auction_db"),
            "USER": os.environ.get("DB_USER", "postgres"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# -------------------------------------------------------------------
# Auth
# -------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

# Allow logging in with the username or the registered email address.
AUTHENTICATION_BACKENDS = [
    "accounts.backends.EmailOrUsernameModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard_redirect"
LOGOUT_REDIRECT_URL = "core:home"

# -------------------------------------------------------------------
# Internationalization
# -------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kathmandu"
USE_I18N = True
USE_TZ = True

# -------------------------------------------------------------------
# Static & Media
# -------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -------------------------------------------------------------------
# Crispy forms
# -------------------------------------------------------------------
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# -------------------------------------------------------------------
# Email (console backend by default; swap to SMTP via env vars)
#
# Local dev: nothing happens — messages are printed to the console.
# Real mail:  set EMAIL_USE_SMTP=True (and the EMAIL_HOST_* / DEFAULT_FROM_EMAIL
#             values), or set EMAIL_BACKEND explicitly. Credentials must come
#             from the environment and are never hardcoded here.
# -------------------------------------------------------------------
EMAIL_USE_SMTP = os.environ.get("EMAIL_USE_SMTP", "False") == "True"
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND") or (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_USE_SMTP
    else "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True") == "True"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@auctionsystem.local")

# Absolute origin used to build verification links. When set, links never
# depend on the incoming Host header. Leave blank to fall back to the request.
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "").rstrip("/")

# Email verification lifetime / anti-abuse knobs (seconds).
EMAIL_VERIFICATION_TIMEOUT = int(os.environ.get("EMAIL_VERIFICATION_TIMEOUT", 60 * 60 * 24))
EMAIL_OTP_TIMEOUT = int(os.environ.get("EMAIL_OTP_TIMEOUT", 30 * 60))
EMAIL_VERIFICATION_RESEND_COOLDOWN = int(os.environ.get("EMAIL_VERIFICATION_RESEND_COOLDOWN", 60))
EMAIL_VERIFICATION_RESEND_MAX_PER_HOUR = int(os.environ.get("EMAIL_VERIFICATION_RESEND_MAX_PER_HOUR", 10))

# -------------------------------------------------------------------
# Auction business rules
# -------------------------------------------------------------------
MINIMUM_BID_INCREMENT = 10  # fallback increment if a product doesn't define one
AUCTION_ENDING_SOON_MINUTES = 15  # threshold to flag "ending soon" + notify

# -------------------------------------------------------------------
# Messages framework -> bootstrap alert classes
# -------------------------------------------------------------------
from django.contrib.messages import constants as messages_constants  # noqa: E402

MESSAGE_TAGS = {
    messages_constants.DEBUG: "secondary",
    messages_constants.INFO: "info",
    messages_constants.SUCCESS: "success",
    messages_constants.WARNING: "warning",
    messages_constants.ERROR: "danger",
}

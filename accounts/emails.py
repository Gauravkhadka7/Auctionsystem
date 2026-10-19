"""Building and sending the registration verification email.

The email carries two ways to verify an account:

* a signed, time-limited **link** (the primary flow), and
* a 6-digit **code** rendered by the existing OTP screen (kept as a fallback
  and to preserve the original email-OTP workflow).

Messages are sent with :class:`~django.core.mail.EmailMultiAlternatives` so
clients that support HTML get a branded template while everyone else gets a
readable plain-text version.
"""

import logging
import random

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import EmailOTP
from .tokens import email_verification_token

logger = logging.getLogger(__name__)

VERIFICATION_SUBJECT = "Verify your email address for LotHouse"


def build_verification_url(user, request=None):
    """Return the absolute verification URL for ``user``.

    Prefers an explicitly configured ``SITE_BASE_URL`` so the link never
    depends on the incoming ``Host`` header. When that isn't set we fall back
    to Django's ``build_absolute_uri`` (which still validates the host against
    ``ALLOWED_HOSTS``).
    """
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    path = reverse(
        "accounts:verify_email_token",
        kwargs={"uidb64": uidb64, "token": token},
    )

    base_url = getattr(settings, "SITE_BASE_URL", "").rstrip("/")
    if base_url:
        return f"{base_url}{path}"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def generate_otp(user):
    """Create and persist a fresh verification code for ``user``."""
    code = f"{random.randint(0, 999999):06d}"
    EmailOTP.objects.create(user=user, code=code, purpose="VERIFY")
    return code


def send_verification_email(user, request=None):
    """Send the verification email to ``user``.

    Returns ``(delivered, code, verification_url)``. Email delivery failures
    are caught and logged so a flaky mail server can never leave the caller
    (and therefore the freshly created account) in a broken state -- the user
    can always request another email from the resend screen.
    """
    code = generate_otp(user)
    verification_url = build_verification_url(user, request)

    context = {
        "user": user,
        "verification_url": verification_url,
        "code": code,
        "site_name": "LotHouse",
        "expires_hours": max(
            1, int(getattr(settings, "EMAIL_VERIFICATION_TIMEOUT", 86400)) // 3600
        ),
    }
    subject = VERIFICATION_SUBJECT
    text_body = render_to_string("accounts/emails/verify_email.txt", context)
    html_body = render_to_string("accounts/emails/verify_email.html", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(html_body, "text/html")

    delivered = True
    try:
        message.send(fail_silently=False)
    except Exception:  # pragma: no cover - exercised via tests with mocks
        delivered = False
        logger.exception("Failed to send verification email to %s", user.email)

    return delivered, code, verification_url

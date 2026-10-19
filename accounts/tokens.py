"""Time-limited, single-use tokens for email verification.

Built on top of Django's own :class:`~django.contrib.auth.tokens.PasswordResetTokenGenerator`
so we inherit the same hardened token format (HMAC over a salted secret with a
timestamp) used by Django's password-reset flow.

The hash deliberately mixes in the user's email and ``is_email_verified`` flag,
which means a token:

* can only ever verify the account it was issued for,
* stops working the moment the account is marked verified (no re-use),
* stops working if the address or password changes.

Expiry is controlled by ``settings.EMAIL_VERIFICATION_TIMEOUT`` (seconds).
"""

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "accounts.tokens.EmailVerificationTokenGenerator"

    def _make_hash_value(self, user, timestamp):
        email = user.email or ""
        verified = int(bool(user.is_email_verified))
        return f"{user.pk}{user.password}{timestamp}{email}{verified}"

    def check_token(self, user, token):
        """Validate the token and enforce our own (shorter) expiry window."""
        if not (user and token):
            return False

        try:
            ts_b36, _ = token.split("-")
        except ValueError:
            return False

        try:
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False

        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(
                self._make_token_with_timestamp(user, ts, secret), token
            ):
                break
        else:
            return False

        timeout = getattr(
            settings, "EMAIL_VERIFICATION_TIMEOUT", 60 * 60 * 24
        )
        if (self._num_seconds(self._now()) - ts) > timeout:
            return False

        return True


email_verification_token = EmailVerificationTokenGenerator()

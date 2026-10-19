from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


def email_is_verified(user):
    """Users must verify their email before they can log in.

    Staff/superusers are exempt so the Django admin and operational accounts
    keep working regardless of the public email flow.
    """
    return bool(
        getattr(user, "is_email_verified", False)
        or getattr(user, "is_staff", False)
        or getattr(user, "is_superuser", False)
    )


class EmailOrUsernameModelBackend(ModelBackend):
    """Authenticate against the username OR the email address.

    Users commonly try to log in with the email they registered with, so
    fall back to a case-insensitive email lookup when the username doesn't
    match (or vice versa).

    Authentication is refused for accounts that have not verified their email
    address, which is the single server-side gate every login path goes
    through (the login view, the Django admin, and any future API endpoint
    that calls ``authenticate()``).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = UserModel.objects.get(
                Q(username__iexact=username) | Q(email__iexact=username)
            )
        except UserModel.DoesNotExist:
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            user = (
                UserModel.objects.filter(
                    Q(username__iexact=username) | Q(email__iexact=username)
                )
                .order_by("pk")
                .first()
            )

        if user.check_password(password) and self.user_can_authenticate(user):
            if email_is_verified(user):
                return user
        return None

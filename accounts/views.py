import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from .backends import email_is_verified
from .emails import build_verification_url, send_verification_email
from .forms import ProfileForm, RegisterForm, ResendVerificationForm
from .models import EmailOTP, Profile, User
from .tokens import email_verification_token

logger = logging.getLogger(__name__)


class AuctionAuthenticationForm(AuthenticationForm):
    """Login form that gives unverified accounts a helpful message.

    The auth backend already refuses unverified logins; this only exists to
    turn that refusal into a friendly, actionable error instead of the
    generic "incorrect username or password".
    """

    unverified_error = (
        "Your email address hasn't been verified yet. Check your inbox and "
        "spam folder, or request a new verification email."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email or username"

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username is not None and password:
            self.user_cache = authenticate(
                self.request, username=username, password=password
            )
            if self.user_cache is None:
                if self._looks_unverified(username, password):
                    raise ValidationError(self.unverified_error, code="unverified")
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data

    @staticmethod
    def _looks_unverified(username, password):
        """True only when the password is correct but the account is unverified.

        Checking the password first means we never reveal whether an account
        exists to someone who can't authenticate.
        """
        candidates = get_user_model().objects.filter(
            Q(username__iexact=username) | Q(email__iexact=username)
        )
        for user in candidates:
            if (
                user.check_password(password)
                and user.is_active
                and not email_is_verified(user)
            ):
                return True
        return False


class AuctionLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = AuctionAuthenticationForm
    redirect_authenticated_user = True


# ---------------------------------------------------------------------------
# Registration & email verification
# ---------------------------------------------------------------------------


def register(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard_redirect")

    if request.method == "POST":
        form = RegisterForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
            except Exception:
                logger.exception("Registration failed while creating the account")
                messages.error(
                    request,
                    "We couldn't create your account right now. Please try again.",
                )
                return render(request, "accounts/register.html", {"form": form})

            delivered, _code, _url = send_verification_email(user, request)
            request.session["pending_verification_user_id"] = user.pk
            if delivered:
                messages.success(
                    request,
                    "Account created! We've emailed you a verification link.",
                )
            else:
                messages.warning(
                    request,
                    "Your account was created, but we couldn't send the "
                    "verification email. Use 'Resend email' to try again.",
                )
            return redirect("accounts:verify_email_sent")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


def _pending_verification_user(request):
    user_id = request.session.get("pending_verification_user_id")
    if not user_id:
        return None
    return User.objects.filter(pk=user_id).first()


def _email_delivery_works():
    """True when mail actually leaves the process (SMTP etc.).

    The bundled defaults use the console/locmem backends, which just print
    the mail to the terminal; a user registering in a browser would never see
    it. In that case we surface the code/link on the page instead.
    """
    backend = settings.EMAIL_BACKEND
    return "console" not in backend and "locmem" not in backend


def _otp_expired(otp):
    timeout = getattr(settings, "EMAIL_OTP_TIMEOUT", 1800)
    return timezone.now() > otp.created_at + timedelta(seconds=timeout)


def verify_email_sent(request):
    """Confirmation page shown right after registration."""
    user = _pending_verification_user(request)
    context = {
        "target_user": user,
        "target_email": user.email if user else None,
        "resend_form": ResendVerificationForm(
            initial={"email": user.email} if user else None
        ),
        "delivery_works": _email_delivery_works(),
    }
    if user and not _email_delivery_works():
        latest_otp = (
            EmailOTP.objects.filter(user=user, purpose="VERIFY", is_used=False)
            .order_by("-created_at")
            .first()
        )
        context["dev_code"] = latest_otp.code if latest_otp else None
        context["dev_url"] = build_verification_url(user, request)
    return render(request, "accounts/verify_email_sent.html", context)


def _get_user_from_uidb64(uidb64):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        return User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None


def verify_email_token(request, uidb64, token):
    """Primary verification endpoint: validates the signed link token."""
    user = _get_user_from_uidb64(uidb64)
    if user is None:
        return render(
            request, "accounts/verify_email_invalid.html", {"reason": "invalid"}
        )

    if user.is_email_verified:
        return render(
            request,
            "accounts/verify_email_success.html",
            {"target_user": user, "already_verified": True},
        )

    if not email_verification_token.check_token(user, token):
        return render(
            request,
            "accounts/verify_email_invalid.html",
            {"target_user": user, "reason": "invalid_or_expired"},
        )

    user.is_email_verified = True
    user.save(update_fields=["is_email_verified"])
    EmailOTP.objects.filter(user=user, purpose="VERIFY", is_used=False).update(
        is_used=True
    )
    request.session.pop("pending_verification_user_id", None)
    login(request, user, backend="accounts.backends.EmailOrUsernameModelBackend")
    messages.success(request, "Your email has been verified — welcome aboard!")
    return render(
        request, "accounts/verify_email_success.html", {"target_user": user}
    )


def verify_email(request, user_id):
    """Fallback code-entry screen (preserves the original OTP workflow)."""
    user = get_object_or_404(User, id=user_id)

    if user.is_email_verified:
        messages.info(request, "That email is already verified — please log in.")
        return redirect("accounts:login")

    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        otp = (
            EmailOTP.objects.filter(
                user=user, purpose="VERIFY", is_used=False, code=code
            )
            .order_by("-created_at")
            .first()
        )
        if otp and not _otp_expired(otp):
            otp.is_used = True
            otp.save(update_fields=["is_used"])
            user.is_email_verified = True
            user.save(update_fields=["is_email_verified"])
            request.session.pop("pending_verification_user_id", None)
            login(request, user, backend="accounts.backends.EmailOrUsernameModelBackend")
            messages.success(request, "Email verified! Welcome aboard.")
            return redirect("core:dashboard_redirect")
        messages.error(request, "Invalid or expired code. Please try again.")

    latest_otp = (
        EmailOTP.objects.filter(user=user, purpose="VERIFY", is_used=False)
        .order_by("-created_at")
        .first()
    )
    dev_code = latest_otp.code if latest_otp and not _email_delivery_works() else None
    return render(
        request,
        "accounts/verify_email.html",
        {"target_user": user, "dev_code": dev_code},
    )


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _resend_allowed(identifier, request):
    """Per-key cooldown + per-IP hourly cap. Uses ``cache.add`` for atomicity."""
    cooldown = max(int(getattr(settings, "EMAIL_VERIFICATION_RESEND_COOLDOWN", 60)), 1)
    per_hour = int(getattr(settings, "EMAIL_VERIFICATION_RESEND_MAX_PER_HOUR", 10))

    if identifier and not cache.add(
        f"emailverif:cooldown:{identifier}", "1", timeout=cooldown
    ):
        return False

    ip = _client_ip(request)
    if ip:
        ip_key = f"emailverif:ip:{ip}"
        try:
            count = cache.incr(ip_key)
        except ValueError:
            cache.add(ip_key, 1, timeout=3600)
            count = 1
        if count > per_hour:
            return False
    return True


def resend_verification(request):
    """Anonymous, email-based resend. Never reveals whether an account exists."""
    if request.method == "POST":
        form = ResendVerificationForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            if _resend_allowed(f"email:{email}", request):
                user = User.objects.filter(
                    email__iexact=email, is_active=True, is_email_verified=False
                ).first()
                if user:
                    send_verification_email(user, request)
                messages.info(
                    request,
                    "If an account exists for that address, we've sent a new "
                    "verification email. Check your inbox and spam folder.",
                )
            else:
                messages.warning(
                    request,
                    "Too many requests. Please wait a moment before trying again.",
                )
            return redirect("accounts:resend_verification")
        messages.error(request, "Please enter a valid email address.")
    else:
        form = ResendVerificationForm()
    return render(request, "accounts/resend_verification.html", {"form": form})


def resend_otp(request, user_id):
    """Session/id-based resend used by the OTP screen (kept for compatibility)."""
    user = get_object_or_404(User, id=user_id)
    if user.is_email_verified:
        messages.info(request, "That email is already verified — please log in.")
        return redirect("accounts:login")

    if _resend_allowed(f"user:{user.pk}", request):
        send_verification_email(user, request)
        messages.info(request, "A new verification email has been sent.")
    else:
        messages.warning(
            request, "Please wait a moment before requesting another email."
        )
    return redirect("accounts:verify_email", user_id=user.id)


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------


@login_required
def profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = ProfileForm(
            request.POST, request.FILES, instance=profile, user=request.user
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=profile, user=request.user)
    return render(request, "accounts/profile.html", {"form": form})


@login_required
def change_password(request):
    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Password changed successfully.")
            return redirect("accounts:profile")
    else:
        form = PasswordChangeForm(user=request.user)
    return render(request, "accounts/change_password.html", {"form": form})


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("core:home")

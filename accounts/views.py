import random

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy

from .forms import RegisterForm, ProfileForm
from .models import EmailOTP, Profile


class AuctionLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


def register(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard_redirect")

    if request.method == "POST":
        form = RegisterForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            _send_otp(user)
            messages.success(
                request,
                "Account created! We've sent a verification code to your email.",
            )
            return redirect("accounts:verify_email", user_id=user.id)
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


def _send_otp(user):
    code = f"{random.randint(0, 999999):06d}"
    EmailOTP.objects.create(user=user, code=code, purpose="VERIFY")
    send_mail(
        subject="Verify your Auction System account",
        message=f"Your verification code is: {code}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )


def verify_email(request, user_id):
    from .models import User
    user = get_object_or_404(User, id=user_id)

    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        otp = EmailOTP.objects.filter(
            user=user, purpose="VERIFY", is_used=False, code=code
        ).order_by("-created_at").first()
        if otp:
            otp.is_used = True
            otp.save()
            user.is_email_verified = True
            user.save(update_fields=["is_email_verified"])
            login(request, user)
            messages.success(request, "Email verified! Welcome aboard.")
            return redirect("core:dashboard_redirect")
        messages.error(request, "Invalid or expired code. Please try again.")

    return render(request, "accounts/verify_email.html", {"target_user": user})


def resend_otp(request, user_id):
    from .models import User
    user = get_object_or_404(User, id=user_id)
    _send_otp(user)
    messages.info(request, "A new verification code has been sent.")
    return redirect("accounts:verify_email", user_id=user.id)


@login_required
def profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=profile, user=request.user)
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

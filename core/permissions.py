"""Shared role-based access helpers used across apps."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def role_required(*roles):
    """Allow access only to users whose .role is in `roles` (superusers always allowed)."""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser or user.role in roles:
                return view_func(request, *args, **kwargs)
            messages.error(request, "You don't have permission to access that page.")
            return redirect("core:dashboard_redirect")

        return _wrapped

    return decorator


def admin_required(view_func):
    return role_required("ADMIN")(view_func)


def seller_required(view_func):
    return role_required("SELLER")(view_func)


def bidder_required(view_func):
    return role_required("BIDDER")(view_func)

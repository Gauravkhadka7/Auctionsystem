"""
Administrator dashboard views.

Every view is guarded by :func:`core.permissions.admin_required`; state-changing
views are POST-only and CSRF-protected, and delegate to the app services rather
than writing to the database directly.
"""
from datetime import datetime

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Profile
from auctions.services import sync_auction_states
from bids.models import Bid
from categories.models import Category
from core.permissions import admin_required
from payments import services as payment_services
from payments.models import Payment
from products import services as product_services
from products.models import Product
from winners import services as winner_services
from winners.models import Winner

from . import services

User = get_user_model()

PAGE_SIZE = 20

USER_SORTS = {
    "newest": "-date_joined",
    "oldest": "date_joined",
    "username": "username",
    "role": "role",
}

PRODUCT_SORTS = {
    "newest": "-created_at",
    "oldest": "created_at",
    "price_high": "-current_price",
    "price_low": "current_price",
    "ending_soon": "auction_end",
    "most_bids": "-bid_count",
}

BID_SORTS = {
    "newest": "-created_at",
    "oldest": "created_at",
    "amount_high": "-amount",
    "amount_low": "amount",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _paginate(request, queryset, per_page=PAGE_SIZE):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def _get_int(request, key):
    try:
        return int(request.GET.get(key))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
@admin_required
def overview(request):
    stats = services.get_overview_stats()
    charts = {
        "registrationTrend": services.registration_trend(days=30),
        "bidsTrend": services.bids_trend(days=30),
        "auctionsByStatus": services.auctions_by_status(),
    }
    context = {
        "active_nav": "overview",
        "page_title": "Overview",
        "page_subtitle": "Platform health at a glance",
        "breadcrumbs": [{"label": "Overview"}],
        "stats": stats,
        "charts": charts,
        "activity": services.get_recent_activity(limit=8),
        "recent_products": Product.objects.select_related("seller", "category").order_by("-created_at")[:6],
        "recent_payments": Payment.objects.select_related("winner__product", "payer").order_by("-created_at")[:6],
    }
    return render(request, "dashboard/overview.html", context)


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------
@admin_required
def global_search(request):
    query = request.GET.get("q", "").strip()
    products = users = bids = []
    if query:
        products = (
            Product.objects.filter(Q(title__icontains=query) | Q(description__icontains=query))
            .select_related("seller", "category")
            .order_by("-created_at")[:10]
        )
        users = (
            User.objects.filter(
                Q(username__icontains=query)
                | Q(email__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
            ).order_by("-date_joined")[:10]
        )
        bids = (
            Bid.objects.filter(Q(product__title__icontains=query) | Q(bidder__username__icontains=query))
            .select_related("product", "bidder")
            .order_by("-created_at")[:10]
        )
    return render(request, "dashboard/search.html", {
        "active_nav": "search",
        "page_title": "Search",
        "page_subtitle": f'Results for "{query}"' if query else "Search users, listings and bids",
        "breadcrumbs": [{"label": "Search"}],
        "query": query,
        "products": products,
        "users": users,
        "bids": bids,
    })


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------
def _render_user_list(request, role, active_nav, page_title, page_subtitle):
    queryset = User.objects.all().order_by("-date_joined")
    if role:
        queryset = queryset.filter(role=role)

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(mobile_number__icontains=query)
        )

    if not role:
        role_filter = request.GET.get("role", "")
        if role_filter in dict(User.Role.choices):
            queryset = queryset.filter(role=role_filter)

    status_filter = request.GET.get("status", "")
    if status_filter == "active":
        queryset = queryset.filter(is_active=True)
    elif status_filter == "inactive":
        queryset = queryset.filter(is_active=False)

    queryset = queryset.order_by(USER_SORTS.get(request.GET.get("sort"), "-date_joined"))
    page_obj = _paginate(request, queryset)

    return render(request, "dashboard/user_list.html", {
        "active_nav": active_nav,
        "page_title": page_title,
        "page_subtitle": page_subtitle,
        "breadcrumbs": [{"label": "Users"}, {"label": page_title}],
        "page_obj": page_obj,
        "query": query,
        "role": role,
        "roles": User.Role.choices,
        "filters": {
            "role": request.GET.get("role", ""),
            "status": status_filter,
            "sort": request.GET.get("sort", ""),
        },
    })


@admin_required
def user_list(request):
    return _render_user_list(request, None, "users", "User Management", "All registered accounts")


@admin_required
def seller_list(request):
    return _render_user_list(request, User.Role.SELLER, "sellers", "Seller Management", "Accounts that list items")


@admin_required
def bidder_list(request):
    return _render_user_list(request, User.Role.BIDDER, "bidders", "Bidder Management", "Accounts that place bids")


@admin_required
def user_detail(request, pk):
    user = get_object_or_404(User, pk=pk)
    profile = Profile.objects.filter(user=user).first()
    context = {
        "active_nav": "users",
        "page_title": user.get_full_name() or user.username,
        "page_subtitle": f"{user.get_role_display()} account",
        "breadcrumbs": [{"label": "Users", "url": "dashboard:users"}, {"label": user.username}],
        "account": user,
        "profile": profile,
        "products": Product.objects.filter(seller=user).select_related("category")[:6],
        "product_count": Product.objects.filter(seller=user).count(),
        "bids": Bid.objects.filter(bidder=user).select_related("product")[:6],
        "bid_count": Bid.objects.filter(bidder=user).count(),
        "wins": Winner.objects.filter(bidder=user).select_related("product")[:6],
        "win_count": Winner.objects.filter(bidder=user).count(),
        "payments": Payment.objects.filter(payer=user).select_related("winner__product")[:6],
        "unread_notifications": user.notifications.filter(is_read=False).count(),
        "roles": User.Role.choices,
    }
    return render(request, "dashboard/user_detail.html", context)


@admin_required
@require_POST
def user_toggle_active(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "You can't deactivate your own account.")
    elif user.is_superuser and not request.user.is_superuser:
        messages.error(request, "Only a superuser can modify a superuser account.")
    else:
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        state = "reactivated" if user.is_active else "deactivated"
        messages.success(request, f"{user.username} was {state}.")
    return redirect("dashboard:user_detail", pk=pk)


@admin_required
@require_POST
def user_set_role(request, pk):
    user = get_object_or_404(User, pk=pk)
    role = request.POST.get("role", "")
    if user == request.user:
        messages.error(request, "You can't change your own role.")
    elif user.is_superuser:
        messages.error(request, "Superuser roles can't be changed here.")
    elif role not in dict(User.Role.choices):
        messages.error(request, "That's not a valid role.")
    else:
        user.role = role
        user.save(update_fields=["role"])
        messages.success(request, f"{user.username} is now a {user.get_role_display()}.")
    return redirect("dashboard:user_detail", pk=pk)


@admin_required
@require_POST
def user_toggle_kyc(request, pk):
    user = get_object_or_404(User, pk=pk)
    user.is_kyc_verified = not user.is_kyc_verified
    user.save(update_fields=["is_kyc_verified"])
    state = "verified" if user.is_kyc_verified else "unverified"
    messages.success(request, f"{user.username} is now marked {state}.")
    return redirect("dashboard:user_detail", pk=pk)


# ---------------------------------------------------------------------------
# Product / listing management
# ---------------------------------------------------------------------------
def _render_product_list(request, mode, active_nav, page_title, page_subtitle):
    queryset = Product.objects.select_related("seller", "category").annotate(bid_count=Count("bids"))

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(Q(title__icontains=query) | Q(description__icontains=query))

    status_filter = request.GET.get("status", "")
    if status_filter in dict(Product.Status.choices):
        queryset = queryset.filter(status=status_filter)

    category_id = _get_int(request, "category")
    if category_id:
        queryset = queryset.filter(category_id=category_id)

    seller_query = request.GET.get("seller", "").strip()
    if seller_query:
        queryset = queryset.filter(seller__username__icontains=seller_query)

    queryset = queryset.order_by(PRODUCT_SORTS.get(request.GET.get("sort"), "-created_at"))
    page_obj = _paginate(request, queryset)

    return render(request, "dashboard/product_list.html", {
        "active_nav": active_nav,
        "page_title": page_title,
        "page_subtitle": page_subtitle,
        "breadcrumbs": [{"label": page_title}],
        "page_obj": page_obj,
        "query": query,
        "mode": mode,
        "categories": Category.objects.order_by("name"),
        "statuses": Product.Status.choices,
        "filters": {
            "status": status_filter,
            "category": category_id or "",
            "seller": seller_query,
            "sort": request.GET.get("sort", ""),
        },
    })


@admin_required
def product_list(request):
    return _render_product_list(request, "products", "products", "Product & Listing Management",
                                 "Every item across all sellers")


@admin_required
def auction_list(request):
    return _render_product_list(request, "auctions", "auctions", "Auction Management",
                                 "Lifecycle states, schedules and approvals")


@admin_required
def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("seller", "category", "subcategory").annotate(bid_count=Count("bids")),
        pk=pk,
    )
    context = {
        "active_nav": "products",
        "page_title": product.title,
        "page_subtitle": f"Listed by {product.seller.username}",
        "breadcrumbs": [
            {"label": "Products", "url": "dashboard:products"},
            {"label": product.title},
        ],
        "product": product,
        "images": product.images.all(),
        "specifications": product.specifications.all(),
        "bids": product.bids.select_related("bidder").order_by("-amount")[:20],
        "winner": getattr(product, "winner", None),
    }
    return render(request, "dashboard/product_detail.html", context)


@admin_required
@require_POST
def product_approve(request, pk):
    product = get_object_or_404(Product, pk=pk)
    try:
        product_services.approve_product(product)
        messages.success(request, f'"{product.title}" approved and scheduled.')
    except product_services.ListingError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:product_detail", pk=pk)


@admin_required
@require_POST
def product_reject(request, pk):
    product = get_object_or_404(Product, pk=pk)
    try:
        product_services.reject_product(product, request.POST.get("reason", "").strip())
        messages.success(request, f'"{product.title}" rejected.')
    except product_services.ListingError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:product_detail", pk=pk)


@admin_required
@require_POST
def product_toggle_featured(request, pk):
    product = get_object_or_404(Product, pk=pk)
    try:
        product_services.set_featured(product, not product.is_featured)
        messages.success(request, f'Featured status updated for "{product.title}".')
    except product_services.ListingError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:product_detail", pk=pk)


@admin_required
@require_POST
def auction_sync(request):
    result = sync_auction_states()
    messages.info(
        request,
        f"Auction lifecycle synced: {result['started']} started, {result['closed']} closed.",
    )
    return redirect("dashboard:auctions")


# ---------------------------------------------------------------------------
# Bid history (read-only)
# ---------------------------------------------------------------------------
@admin_required
def bid_list(request):
    queryset = Bid.objects.select_related("product", "bidder")

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(product__title__icontains=query) | Q(bidder__username__icontains=query)
        )

    date_from = _parse_date(request.GET.get("from", ""))
    date_to = _parse_date(request.GET.get("to", ""))
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    queryset = queryset.order_by(BID_SORTS.get(request.GET.get("sort"), "-created_at"))
    page_obj = _paginate(request, queryset)

    return render(request, "dashboard/bid_list.html", {
        "active_nav": "bids",
        "page_title": "Bid History",
        "page_subtitle": "Read-only record of every bid placed",
        "breadcrumbs": [{"label": "Bid History"}],
        "page_obj": page_obj,
        "query": query,
        "filters": {"from": request.GET.get("from", ""), "to": request.GET.get("to", ""),
                    "sort": request.GET.get("sort", "")},
        "total_bids": Bid.objects.count(),
    })


# ---------------------------------------------------------------------------
# Winner verification
# ---------------------------------------------------------------------------
@admin_required
def winner_list(request):
    queryset = Winner.objects.select_related("product", "bidder")

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(product__title__icontains=query) | Q(bidder__username__icontains=query)
        )

    verification = request.GET.get("verification", "")
    if verification == "submitted":
        queryset = queryset.filter(is_verification_submitted=True)
    elif verification == "pending":
        queryset = queryset.filter(is_verification_submitted=False)
    elif verification == "verified":
        queryset = queryset.filter(bidder__is_kyc_verified=True)

    payment_filter = request.GET.get("payment", "")
    if payment_filter == "verified":
        queryset = queryset.filter(is_payment_verified=True)
    elif payment_filter == "pending":
        queryset = queryset.filter(is_payment_verified=False)

    page_obj = _paginate(request, queryset)
    return render(request, "dashboard/winner_list.html", {
        "active_nav": "winners",
        "page_title": "Winner Verification",
        "page_subtitle": "Review closed auctions and confirm winning bidders",
        "breadcrumbs": [{"label": "Winner Verification"}],
        "page_obj": page_obj,
        "query": query,
        "filters": {"verification": verification, "payment": payment_filter},
    })


@admin_required
def winner_detail(request, pk):
    winner = get_object_or_404(Winner.objects.select_related("product", "bidder"), pk=pk)
    return render(request, "dashboard/winner_detail.html", {
        "active_nav": "winners",
        "page_title": f"Winner — {winner.product.title}",
        "page_subtitle": f"{winner.bidder.username} · {winner.winning_price}",
        "breadcrumbs": [
            {"label": "Winner Verification", "url": "dashboard:winners"},
            {"label": winner.product.title},
        ],
        "winner": winner,
        "profile": Profile.objects.filter(user=winner.bidder).first(),
        "payments": winner.payments.select_related("payer").order_by("-created_at"),
        "top_bids": winner.product.bids.select_related("bidder").order_by("-amount")[:10],
    })


@admin_required
@require_POST
def winner_verify(request, pk):
    winner = get_object_or_404(Winner, pk=pk)
    try:
        winner_services.verify_winner(winner)
        messages.success(request, f"Winner {winner.bidder.username} verified.")
    except winner_services.VerificationError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:winner_detail", pk=pk)


@admin_required
@require_POST
def winner_reject(request, pk):
    winner = get_object_or_404(Winner, pk=pk)
    try:
        winner_services.reject_winner_verification(winner, request.POST.get("reason", "").strip())
        messages.success(request, f"Verification for {winner.bidder.username} was sent back.")
    except winner_services.VerificationError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:winner_detail", pk=pk)


# ---------------------------------------------------------------------------
# Payment verification
# ---------------------------------------------------------------------------
@admin_required
def payment_list(request):
    queryset = Payment.objects.select_related("winner__product", "payer")

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(transaction_id__icontains=query)
            | Q(winner__product__title__icontains=query)
            | Q(payer__username__icontains=query)
        )

    status_filter = request.GET.get("status", "")
    if status_filter in dict(Payment.Status.choices):
        queryset = queryset.filter(status=status_filter)

    method_filter = request.GET.get("method", "")
    if method_filter in dict(Payment.Method.choices):
        queryset = queryset.filter(method=method_filter)

    page_obj = _paginate(request, queryset)
    return render(request, "dashboard/payment_list.html", {
        "active_nav": "payments",
        "page_title": "Payment Verification",
        "page_subtitle": "Confirm payments against winning bids",
        "breadcrumbs": [{"label": "Payment Verification"}],
        "page_obj": page_obj,
        "query": query,
        "statuses": Payment.Status.choices,
        "methods": Payment.Method.choices,
        "filters": {"status": status_filter, "method": method_filter},
    })


@admin_required
def payment_detail(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("winner__product", "payer"), pk=pk)
    return render(request, "dashboard/payment_detail.html", {
        "active_nav": "payments",
        "page_title": f"Payment — {payment.winner.product.title}",
        "page_subtitle": f"{payment.amount} · {payment.get_method_display()}",
        "breadcrumbs": [
            {"label": "Payment Verification", "url": "dashboard:payments"},
            {"label": str(payment.pk)},
        ],
        "payment": payment,
        "winner": payment.winner,
    })


@admin_required
@require_POST
def payment_verify(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    try:
        payment_services.verify_payment(payment)
        messages.success(request, f"Payment {payment.pk} verified.")
    except payment_services.PaymentError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:payment_detail", pk=pk)


@admin_required
@require_POST
def payment_reject(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    try:
        payment_services.reject_payment(payment, request.POST.get("reason", "").strip())
        messages.success(request, f"Payment {payment.pk} rejected.")
    except payment_services.PaymentError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:payment_detail", pk=pk)


# ---------------------------------------------------------------------------
# Reports & activity
# ---------------------------------------------------------------------------
@admin_required
def reports(request):
    start = _parse_date(request.GET.get("start", ""))
    end = _parse_date(request.GET.get("end", ""))
    start_date, end_date = services.resolve_range(30, start, end)

    charts = {
        "registrationTrend": services.registration_trend(start_date=start_date, end_date=end_date),
        "bidsTrend": services.bids_trend(start_date=start_date, end_date=end_date),
        "auctionsByStatus": services.auctions_by_status(),
        "categoryDistribution": services.category_distribution(),
        "topWinningBids": services.top_winning_bids(),
    }
    return render(request, "dashboard/reports.html", {
        "active_nav": "reports",
        "page_title": "Reports & Analytics",
        "page_subtitle": f"{start_date:%b %d, %Y} – {end_date:%b %d, %Y}",
        "breadcrumbs": [{"label": "Reports & Analytics"}],
        "charts": charts,
        "stats": services.get_overview_stats(),
        "seller_performance": services.seller_performance(),
        "top_listings": services.top_listings(),
        "start_date": start_date,
        "end_date": end_date,
        "filters": {"start": request.GET.get("start", ""), "end": request.GET.get("end", "")},
    })


@admin_required
def activity(request):
    return render(request, "dashboard/activity.html", {
        "active_nav": "activity",
        "page_title": "Notifications & Activity",
        "page_subtitle": "Recent platform activity and your alerts",
        "breadcrumbs": [{"label": "Notifications & Activity"}],
        "activity": services.get_recent_activity(limit=40, per_source=12),
        "notifications": request.user.notifications.all()[:15],
        "unread_count": request.user.notifications.filter(is_read=False).count(),
    })

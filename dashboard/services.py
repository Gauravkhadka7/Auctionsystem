"""
Read-only aggregation helpers for the admin dashboard.

Everything here is derived from existing models/fields; nothing is invented.
Monetary figures are deliberately kept distinct:

* ``winning_value``      -> SUM(Winner.winning_price)   (gross winning bids)
* ``verified_total``     -> SUM(Payment.amount) where status == VERIFIED
* platform revenue       -> not recorded anywhere in the schema, so it is
                            intentionally NOT reported (see ``platform_revenue``).

Queries use aggregate()/annotate() so counts never load whole tables into
memory. All date truncation uses ``TruncDate`` which works on both SQLite
and PostgreSQL.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from bids.models import Bid
from categories.models import Category
from payments.models import Payment
from products.models import Product
from winners.models import Winner

User = get_user_model()


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------
def get_overview_stats():
    product_stats = Product.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status=Product.Status.PENDING)),
        upcoming=Count("id", filter=Q(status=Product.Status.UPCOMING)),
        live=Count("id", filter=Q(status=Product.Status.LIVE)),
        closed=Count("id", filter=Q(status=Product.Status.CLOSED)),
        rejected=Count("id", filter=Q(status=Product.Status.REJECTED)),
    )
    user_stats = User.objects.aggregate(
        total=Count("id"),
        sellers=Count("id", filter=Q(role=User.Role.SELLER)),
        bidders=Count("id", filter=Q(role=User.Role.BIDDER)),
        admins=Count("id", filter=Q(role=User.Role.ADMIN)),
        active=Count("id", filter=Q(is_active=True)),
    )
    payment_stats = Payment.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status=Payment.Status.PENDING)),
        verified=Count("id", filter=Q(status=Payment.Status.VERIFIED)),
        rejected=Count("id", filter=Q(status=Payment.Status.REJECTED)),
        verified_total=Sum("amount", filter=Q(status=Payment.Status.VERIFIED)),
    )
    winner_stats = Winner.objects.aggregate(
        total=Count("id"),
        pending_verification=Count(
            "id",
            filter=Q(is_verification_submitted=True, bidder__is_kyc_verified=False),
        ),
        verified_bidders=Count("id", filter=Q(bidder__is_kyc_verified=True)),
        payment_verified=Count("id", filter=Q(is_payment_verified=True)),
        delivered=Count("id", filter=Q(is_delivered=True)),
        winning_value=Sum("winning_price"),
    )
    return {
        "users": user_stats,
        "products": product_stats,
        "payments": payment_stats,
        "winners": winner_stats,
        "total_bids": Bid.objects.count(),
        "total_categories": Category.objects.count(),
        "generated_at": timezone.now(),
        # Not stored in the schema -> surfaced as "unavailable" rather than faked.
        "platform_revenue": None,
    }


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------
def _date_keys(start_date, end_date):
    days = (end_date - start_date).days
    return [start_date + timedelta(days=i) for i in range(days + 1)]


def resolve_range(days=30, start_date=None, end_date=None):
    end_date = end_date or timezone.localdate()
    start_date = start_date or (end_date - timedelta(days=days - 1))
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return start_date, end_date


def registration_trend(days=30, start_date=None, end_date=None):
    start_date, end_date = resolve_range(days, start_date, end_date)
    rows = (
        User.objects.filter(date_joined__date__range=(start_date, end_date))
        .annotate(day=TruncDate("date_joined"))
        .values("day")
        .annotate(count=Count("id"))
    )
    counts = {row["day"]: row["count"] for row in rows}
    keys = _date_keys(start_date, end_date)
    return {
        "type": "line",
        "label": "New users",
        "labels": [d.strftime("%b %d") for d in keys],
        "values": [counts.get(d, 0) for d in keys],
    }


def bids_trend(days=30, start_date=None, end_date=None):
    start_date, end_date = resolve_range(days, start_date, end_date)
    rows = (
        Bid.objects.filter(created_at__date__range=(start_date, end_date))
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    counts = {row["day"]: row["count"] for row in rows}
    keys = _date_keys(start_date, end_date)
    return {
        "type": "line",
        "label": "Bids placed",
        "labels": [d.strftime("%b %d") for d in keys],
        "values": [counts.get(d, 0) for d in keys],
    }


def auctions_by_status():
    order = [
        Product.Status.PENDING,
        Product.Status.UPCOMING,
        Product.Status.LIVE,
        Product.Status.CLOSED,
        Product.Status.REJECTED,
        Product.Status.SUSPENDED,
        Product.Status.CANCELLED,
    ]
    counts = {
        row["status"]: row["count"]
        for row in Product.objects.values("status").annotate(count=Count("id"))
    }
    labels_map = dict(Product.Status.choices)
    labels = [labels_map.get(value, value) for value in order if counts.get(value)]
    values = [counts[value] for value in order if counts.get(value)]
    return {"type": "doughnut", "label": "Auctions", "labels": labels, "values": values}


def category_distribution(limit=8):
    rows = (
        Category.objects.annotate(count=Count("products"))
        .filter(count__gt=0)
        .values("name", "count")
        .order_by("-count")[:limit]
    )
    return {
        "type": "bar",
        "label": "Listings",
        "labels": [row["name"] for row in rows],
        "values": [row["count"] for row in rows],
    }


def top_winning_bids(limit=6):
    winners = (
        Winner.objects.select_related("product")
        .filter(winning_price__isnull=False)
        .order_by("-winning_price")[:limit]
    )
    return {
        "type": "bar",
        "label": "Winning bid",
        "labels": [w.product.title[:22] for w in winners],
        "values": [float(w.winning_price) for w in winners],
    }


def seller_performance(limit=6):
    return list(
        User.objects.filter(role=User.Role.SELLER)
        .annotate(
            listing_count=Count("products", distinct=True),
            won_count=Count("products__winner", distinct=True),
            sales_total=Sum("products__winner__winning_price"),
        )
        .order_by("-listing_count", "username")[:limit]
    )


def top_listings(limit=6):
    return list(
        Product.objects.annotate(bid_count=Count("bids"))
        .filter(bid_count__gt=0)
        .select_related("seller", "category")
        .order_by("-bid_count", "-current_price")[:limit]
    )


# ---------------------------------------------------------------------------
# Activity feed (audit-style trail derived from existing rows + timestamps)
# ---------------------------------------------------------------------------
def get_recent_activity(limit=12, per_source=6):
    items = []

    for product in Product.objects.select_related("seller").order_by("-created_at")[:per_source]:
        items.append({
            "ts": product.created_at,
            "kind": "product",
            "icon": "bi-box-seam",
            "text": f'New listing "{product.title}" by {product.seller.username}',
            "url": reverse("dashboard:product_detail", args=[product.pk]),
        })

    for bid in Bid.objects.select_related("product", "bidder").order_by("-created_at")[:per_source]:
        items.append({
            "ts": bid.created_at,
            "kind": "bid",
            "icon": "bi-hammer",
            "text": f"{bid.bidder.username} bid {bid.amount} on \"{bid.product.title}\"",
            "url": reverse("dashboard:product_detail", args=[bid.product_id]),
        })

    for winner in Winner.objects.select_related("product", "bidder").order_by("-created_at")[:per_source]:
        items.append({
            "ts": winner.created_at,
            "kind": "winner",
            "icon": "bi-trophy",
            "text": f'{winner.bidder.username} won "{winner.product.title}" for {winner.winning_price}',
            "url": reverse("dashboard:winner_detail", args=[winner.pk]),
        })

    for payment in Payment.objects.select_related("winner__product", "payer").order_by("-created_at")[:per_source]:
        items.append({
            "ts": payment.created_at,
            "kind": "payment",
            "icon": "bi-credit-card",
            "text": f'{payment.payer.username} submitted a {payment.get_status_display()} payment for "{payment.winner.product.title}"',
            "url": reverse("dashboard:payment_detail", args=[payment.pk]),
        })

    for user in User.objects.order_by("-date_joined")[:per_source]:
        items.append({
            "ts": user.date_joined,
            "kind": "user",
            "icon": "bi-person-plus",
            "text": f'{user.username} registered as a {user.get_role_display()}',
            "url": reverse("dashboard:user_detail", args=[user.pk]),
        })

    items.sort(key=lambda item: item["ts"], reverse=True)
    return items[:limit]

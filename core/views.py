from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import redirect, render

from bids.models import Bid
from categories.models import Category
from core.models import NewsletterSubscriber, SiteContact
from core.permissions import admin_required, bidder_required, seller_required
from payments.models import Payment
from products.models import Product
from winners.models import Winner


def home(request):
    live = Product.objects.filter(status=Product.Status.LIVE).order_by("auction_end")[:8]
    upcoming = Product.objects.filter(status=Product.Status.UPCOMING).order_by("auction_start")[:8]
    closed = Product.objects.filter(status=Product.Status.CLOSED).order_by("-updated_at")[:8]
    featured = Product.objects.filter(is_featured=True, status=Product.Status.LIVE)[:6]
    recent_winners = Winner.objects.select_related("product", "bidder").order_by("-created_at")[:6]
    categories = Category.objects.filter(is_active=True)[:10]

    return render(request, "core/home.html", {
        "live_products": live,
        "upcoming_products": upcoming,
        "closed_products": closed,
        "featured_products": featured,
        "recent_winners": recent_winners,
        "categories": categories,
    })


@login_required
def dashboard_redirect(request):
    user = request.user
    if user.is_admin_role:
        return redirect("dashboard:overview")
    if user.is_seller:
        return redirect("core:seller_dashboard")
    return redirect("core:bidder_dashboard")


@bidder_required
def bidder_dashboard(request):
    my_bids = Bid.objects.filter(bidder=request.user).select_related("product")
    active_product_ids = (
        my_bids.filter(product__status=Product.Status.LIVE)
        .values_list("product_id", flat=True)
        .distinct()
    )
    won_count = Winner.objects.filter(bidder=request.user).count()
    lost_count = Product.objects.filter(
        status=Product.Status.CLOSED, bids__bidder=request.user
    ).exclude(winner__bidder=request.user).distinct().count()

    context = {
        "active_bids_count": len(set(active_product_ids)),
        "won_count": won_count,
        "lost_count": lost_count,
        "total_participation": my_bids.values("product_id").distinct().count(),
        "recent_bids": my_bids.order_by("-created_at")[:8],
    }
    return render(request, "core/bidder_dashboard.html", context)


def seller_analytics(seller):
    """Aggregations for the seller dashboard, scoped to one seller.

    Each metric comes from its own single aggregate query so joining several
    one-to-many relations can never multiply counts or money. Revenue and
    winning prices are reported side by side but never added together: verified
    ``Payment.amount`` is the money actually received, while
    ``Winner.winning_price`` is the hammer value of the same settled lots.
    """
    products = Product.objects.filter(seller=seller)

    total_bids = Bid.objects.filter(product__seller=seller).count()
    total_views = products.aggregate(total=Sum("view_count"))["total"] or 0
    total_listings = products.count()

    verified_revenue = (
        Payment.objects.filter(
            status=Payment.Status.VERIFIED, winner__product__seller=seller
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    pending_revenue = (
        Payment.objects.filter(
            status=Payment.Status.PENDING, winner__product__seller=seller
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    # Winners whose payment already cleared (flag maintained by verify_payment),
    # so each winner row is counted exactly once.
    settled = Winner.objects.filter(product__seller=seller, is_payment_verified=True)
    settled_count = settled.count()
    settled_winning_value = settled.aggregate(total=Sum("winning_price"))["total"] or Decimal("0.00")

    # --- category breakdowns (separate queries, merged in Python) -----------
    bids_by_category = {
        row["product__category_id"]: row["bid_count"]
        for row in Bid.objects.filter(product__seller=seller)
        .values("product__category_id")
        .annotate(bid_count=Count("id", distinct=True))
    }
    revenue_by_category = {
        row["winner__product__category_id"]: row
        for row in Payment.objects.filter(
            status=Payment.Status.VERIFIED, winner__product__seller=seller
        )
        .values("winner__product__category_id")
        .annotate(revenue=Sum("amount"), payments=Count("id", distinct=True))
    }

    category_rows = []
    for category in Category.objects.filter(products__seller=seller).distinct():
        revenue_row = revenue_by_category.get(category.pk, {})
        revenue = revenue_row.get("revenue") or Decimal("0.00")
        category_rows.append({
            "category": category,
            "bids": bids_by_category.get(category.pk, 0),
            "revenue": revenue,
            "payments": revenue_row.get("payments", 0),
        })
    category_rows.sort(key=lambda row: (row["bids"], row["revenue"]), reverse=True)

    max_bids = max((row["bids"] for row in category_rows), default=0)
    max_revenue = max((row["revenue"] for row in category_rows), default=Decimal("0"))
    for row in category_rows:
        row["bids_pct"] = round(row["bids"] / max_bids * 100) if max_bids else 0
        row["revenue_pct"] = round(float(row["revenue"]) / float(max_revenue) * 100) if max_revenue else 0

    return {
        "total_listings": total_listings,
        "total_bids": total_bids,
        "total_views": total_views,
        "verified_revenue": verified_revenue,
        "pending_revenue": pending_revenue,
        "settled_count": settled_count,
        "settled_winning_value": settled_winning_value,
        "category_rows": category_rows,
        "total_revenue_by_category": sum(
            (row["revenue"] for row in category_rows), Decimal("0.00")
        ),
    }


@seller_required
def seller_dashboard(request):
    products = Product.objects.filter(seller=request.user)
    context = {
        "total_products": products.count(),
        "live_count": products.filter(status=Product.Status.LIVE).count(),
        "upcoming_count": products.filter(status=Product.Status.UPCOMING).count(),
        "closed_count": products.filter(status=Product.Status.CLOSED).count(),
        "pending_count": products.filter(status=Product.Status.PENDING).count(),
        "recent_products": products.order_by("-created_at")[:8],
        "analytics": seller_analytics(request.user),
    }
    return render(request, "core/seller_dashboard.html", context)


@admin_required
def admin_dashboard(request):
    # Superseded by the dedicated admin dashboard app; kept as a redirect so
    # older bookmarks/links keep working.
    return redirect("dashboard:overview")


def about(request):
    return render(request, "core/static_page.html", {"page_title": "About Us", "template_body": "about"})


def how_it_works(request):
    return render(request, "core/static_page.html", {"page_title": "How It Works", "template_body": "how_it_works"})


def contact(request):
    if request.method == "POST":
        SiteContact.objects.create(
            name=request.POST.get("name", ""),
            email=request.POST.get("email", ""),
            subject=request.POST.get("subject", ""),
            message=request.POST.get("message", ""),
        )
        messages.success(request, "Thanks for reaching out — we'll get back to you soon.")
        return redirect("core:contact")
    return render(request, "core/contact.html")


def newsletter_signup(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        if email:
            NewsletterSubscriber.objects.get_or_create(email=email)
            messages.success(request, "Subscribed! Watch your inbox for auction alerts.")
    return redirect(request.META.get("HTTP_REFERER", "core:home"))


def terms(request):
    return render(request, "core/static_page.html", {"page_title": "Terms & Conditions", "template_body": "terms"})


def privacy(request):
    return render(request, "core/static_page.html", {"page_title": "Privacy Policy", "template_body": "privacy"})

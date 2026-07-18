from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render, redirect
from django.utils import timezone

from bids.models import Bid
from categories.models import Category
from core.models import NewsletterSubscriber, SiteContact
from core.permissions import admin_required, seller_required, bidder_required
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
        return redirect("core:admin_dashboard")
    if user.is_seller:
        return redirect("core:seller_dashboard")
    return redirect("core:bidder_dashboard")


@bidder_required
def bidder_dashboard(request):
    my_bids = Bid.objects.filter(bidder=request.user).select_related("product")
    active_product_ids = my_bids.filter(product__status=Product.Status.LIVE).values_list("product_id", flat=True).distinct()
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
    }
    return render(request, "core/seller_dashboard.html", context)


@admin_required
def admin_dashboard(request):
    from accounts.models import User
    products = Product.objects.all()
    context = {
        "total_sellers": User.objects.filter(role=User.Role.SELLER).count(),
        "total_bidders": User.objects.filter(role=User.Role.BIDDER).count(),
        "total_products": products.count(),
        "live_count": products.filter(status=Product.Status.LIVE).count(),
        "upcoming_count": products.filter(status=Product.Status.UPCOMING).count(),
        "closed_count": products.filter(status=Product.Status.CLOSED).count(),
        "pending_approval_count": products.filter(status=Product.Status.PENDING).count(),
        "total_winners": Winner.objects.count(),
        "total_revenue": Winner.objects.aggregate(total=Sum("winning_price"))["total"] or 0,
        "top_categories": Category.objects.annotate(num=Count("products")).order_by("-num")[:5],
        "recent_products": products.order_by("-created_at")[:8],
    }
    return render(request, "core/admin_dashboard.html", context)


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

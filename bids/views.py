from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from products.models import Product
from .services import place_bid, BidError


@login_required
@require_POST
def place_bid_view(request, slug):
    """Standard form POST fallback (works without JS)."""
    product = get_object_or_404(Product, slug=slug)
    try:
        amount = Decimal(request.POST.get("amount", "0"))
    except InvalidOperation:
        messages.error(request, "Enter a valid bid amount.")
        return redirect("products:detail", slug=slug)

    try:
        place_bid(product, request.user, amount)
        messages.success(request, f"Your bid of {amount} was placed successfully!")
    except BidError as exc:
        messages.error(request, str(exc))

    return redirect("products:detail", slug=slug)


@login_required
@require_POST
def place_bid_ajax(request, slug):
    """AJAX endpoint used by the live bidding widget on the product page."""
    product = get_object_or_404(Product, slug=slug)
    try:
        amount = Decimal(request.POST.get("amount", "0"))
    except InvalidOperation:
        return JsonResponse({"ok": False, "error": "Invalid amount."}, status=400)

    try:
        bid = place_bid(product, request.user, amount)
    except BidError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    product.refresh_from_db()
    return JsonResponse({
        "ok": True,
        "current_price": str(product.current_price),
        "minimum_next_bid": str(product.minimum_next_bid),
        "total_bids": product.total_bids,
        "total_bidders": product.total_bidders,
        "leader": bid.bidder.username,
        "bid_time": bid.created_at.strftime("%b %d, %Y %I:%M %p"),
    })


def bid_status_ajax(request, slug):
    """Polled by the countdown widget to keep price/time-remaining fresh
    without a full page reload, and to detect when an auction has closed."""
    product = get_object_or_404(Product, slug=slug)
    return JsonResponse({
        "status": product.status,
        "current_price": str(product.current_price),
        "minimum_next_bid": str(product.minimum_next_bid),
        "total_bids": product.total_bids,
        "total_bidders": product.total_bidders,
        "time_remaining_seconds": product.time_remaining_seconds,
    })

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.permissions import bidder_required
from products.models import Product
from .models import WatchlistItem


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _safe_redirect_target(request, product):
    """Send no-JS submissions back where they came from, if that's safe."""
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return product.get_absolute_url()


@bidder_required
def my_watchlist(request):
    items = (
        WatchlistItem.objects.filter(user=request.user)
        .select_related("product", "product__category", "product__seller")
        .order_by("-created_at")
    )

    status = request.GET.get("status")
    if status in Product.Status.values:
        items = items.filter(product__status=status)

    return render(request, "watchlist/my_watchlist.html", {
        "watchlist_items": items,
        "status_filter": status or "",
        "status_choices": [
            (Product.Status.UPCOMING, "Upcoming"),
            (Product.Status.LIVE, "Live"),
            (Product.Status.CLOSED, "Closed"),
        ],
    })


@bidder_required
@require_POST
def toggle_watchlist(request, slug):
    product = get_object_or_404(Product, slug=slug)
    item = WatchlistItem.objects.filter(user=request.user, product=product).first()

    if item:
        item.delete()
        watching = False
        message = "Removed from your watchlist."
    elif product.status in (Product.Status.UPCOMING, Product.Status.LIVE):
        WatchlistItem.objects.create(user=request.user, product=product)
        watching = True
        message = "Added to your watchlist."
    else:
        error = "You can only watch upcoming or live auctions."
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": error}, status=400)
        messages.error(request, error)
        return redirect(_safe_redirect_target(request, product))

    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "watching": watching,
            "watchers_count": product.watchlisted_by.count(),
            "message": message,
        })

    messages.success(request, message)
    return redirect(_safe_redirect_target(request, product))

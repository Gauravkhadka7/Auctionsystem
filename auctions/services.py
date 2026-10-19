"""
Auction lifecycle engine.

sync_auction_states() is the single function that moves products through:
  PENDING --(admin approval)--> UPCOMING --(auction_start reached)--> LIVE
  LIVE --(auction_end reached)--> CLOSED  (+ creates Winner, notifies both sides)

It's called from AuctionLifecycleMiddleware on every request (fine for a
small/medium site) and can also be run on a schedule via:
    python manage.py close_expired_auctions
for a more production-appropriate cron/celery-beat setup.
"""
from django.db import transaction
from django.utils import timezone

from notifications.models import Notification
from products.models import Product
from winners.models import Winner
from .broadcast import broadcast_auction


def sync_auction_states():
    now = timezone.now()
    started = _activate_upcoming_auctions(now)
    closed = _close_expired_auctions(now)
    return {"started": started, "closed": closed}


@transaction.atomic
def _activate_upcoming_auctions(now):
    upcoming = Product.objects.select_for_update().filter(
        status=Product.Status.UPCOMING, auction_start__lte=now
    )
    count = 0
    for product in upcoming:
        count += 1
        product.status = Product.Status.LIVE
        product.save(update_fields=["status"])
        Notification.objects.create(
            user=product.seller,
            message=f"Your auction \"{product.title}\" has gone live.",
            link=product.get_absolute_url(),
        )
        broadcast_auction(product, event="live")
    return count


@transaction.atomic
def _close_expired_auctions(now):
    expiring = Product.objects.select_for_update().filter(
        status=Product.Status.LIVE, auction_end__lte=now
    )
    count = 0
    for product in expiring:
        count += 1
        top_bid = product.bids.order_by("-amount", "created_at").first()
        product.status = Product.Status.CLOSED
        product.save(update_fields=["status"])

        if top_bid and product.reserve_met:
            winner, created = Winner.objects.get_or_create(
                product=product,
                defaults={"bidder": top_bid.bidder, "winning_price": top_bid.amount},
            )
            Notification.objects.create(
                user=winner.bidder,
                message=f"Congratulations! You won \"{product.title}\" for {winner.winning_price}.",
                link=product.get_absolute_url(),
            )
            Notification.objects.create(
                user=product.seller,
                message=f"Your auction \"{product.title}\" closed. Winner: {winner.bidder}.",
                link=product.get_absolute_url(),
            )
        else:
            reason = "no bids were placed" if not top_bid else "the reserve price wasn't met"
            Notification.objects.create(
                user=product.seller,
                message=f"Your auction \"{product.title}\" closed with no winner ({reason}).",
                link=product.get_absolute_url(),
            )
        broadcast_auction(product, event="closed")
    return count

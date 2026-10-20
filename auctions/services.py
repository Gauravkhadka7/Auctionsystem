"""
Auction lifecycle engine.

sync_auction_states() is the single function that moves products through:
  PENDING --(admin approval)--> UPCOMING --(auction_start reached)--> LIVE
  LIVE --(auction_end reached)--> CLOSED  (+ creates Winner, notifies both sides)

It also fires the one-shot "ending soon" reminder (AUCTION_ENDING_SOON_MINUTES)
for live auctions entering their final window.

It's called from AuctionLifecycleMiddleware on every request (fine for a
small/medium site) and can also be run on a schedule via:
    python manage.py close_expired_auctions
for a more production-appropriate cron/celery-beat setup.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from notifications.broadcast import notify, recipients_for
from products.models import Product
from winners.models import Winner

from .broadcast import broadcast_auction


def sync_auction_states():
    now = timezone.now()
    started = _activate_upcoming_auctions(now)
    ending_soon = _notify_ending_soon_auctions(now)
    closed = _close_expired_auctions(now)
    return {"started": started, "closed": closed, "ending_soon": ending_soon}


@transaction.atomic
def _activate_upcoming_auctions(now):
    upcoming = Product.objects.select_for_update().filter(
        status=Product.Status.UPCOMING, auction_start__lte=now
    )
    count = 0
    for product in upcoming:
        count += 1
        product.status = Product.Status.LIVE
        # Fresh live auction: the ending-soon reminder hasn't fired yet.
        product.ending_soon_notified = False
        product.save(update_fields=["status", "ending_soon_notified"])
        notify(
            product.seller,
            f"Your auction \"{product.title}\" has gone live.",
            link=product.get_absolute_url(),
        )
        broadcast_auction(product, event="live")
    return count


@transaction.atomic
def _notify_ending_soon_auctions(now):
    """One-shot reminder when a live auction enters its final minutes."""
    window = timedelta(minutes=settings.AUCTION_ENDING_SOON_MINUTES)
    candidates = Product.objects.select_for_update().filter(
        status=Product.Status.LIVE,
        ending_soon_notified=False,
        auction_end__gt=now,
        auction_end__lte=now + window,
    )
    count = 0
    for product in candidates:
        count += 1
        product.ending_soon_notified = True
        product.save(update_fields=["ending_soon_notified"])

        message = (
            f"\"{product.title}\" is ending within the next "
            f"{settings.AUCTION_ENDING_SOON_MINUTES} minutes."
        )
        recipients = {user.pk: user for user in recipients_for(product)}
        leader = product.bids.order_by("-amount", "created_at").first()
        if leader:
            recipients[leader.bidder_id] = leader.bidder
        for user in recipients.values():
            notify(user, message, link=product.get_absolute_url())
        broadcast_auction(product, event="ending_soon")
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
            notify(
                winner.bidder,
                f"Congratulations! You won \"{product.title}\" for {winner.winning_price}.",
                link=product.get_absolute_url(),
            )
            notify(
                product.seller,
                f"Your auction \"{product.title}\" closed. Winner: {winner.bidder}.",
                link=product.get_absolute_url(),
            )
        else:
            reason = "no bids were placed" if not top_bid else "the reserve price wasn't met"
            notify(
                product.seller,
                f"Your auction \"{product.title}\" closed with no winner ({reason}).",
                link=product.get_absolute_url(),
            )
        broadcast_auction(product, event="closed")
    return count

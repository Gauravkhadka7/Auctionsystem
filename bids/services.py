"""Business logic for placing a bid — kept out of views so it's reusable
from both the regular POST view and the AJAX endpoint."""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from auctions.broadcast import broadcast_auction
from notifications.broadcast import notify, recipients_for

from .models import Bid


class BidError(Exception):
    pass


def sniping_extension_for(product, now=None):
    """Return the new ``auction_end`` if ``now`` falls inside the anti-sniping
    window, else ``None``.

    Pure helper so the rule can be unit-tested without placing a bid. The
    extension is only ever *added* — the deadline never moves earlier — and it
    respects ``AUCTION_MAX_EXTENSIONS``.
    """
    now = now or timezone.now()
    window = timedelta(seconds=settings.SNIP_WINDOW_SECONDS)
    if product.status != product.Status.LIVE:
        return None
    if product.auction_end <= now:
        return None
    if product.extension_count >= settings.AUCTION_MAX_EXTENSIONS:
        return None
    if (product.auction_end - now) >= window:
        return None
    new_end = now + timedelta(minutes=settings.AUCTION_EXTENSION_MINUTES)
    return new_end if new_end > product.auction_end else None


@transaction.atomic
def place_bid(product, bidder, amount):
    """Place a bid, update the product's current price, apply the anti-sniping
    extension when the bid lands in the final moments, and notify the
    previously-highest bidder that they've been outbid.

    The product row is re-read under ``select_for_update()`` *inside* this
    transaction, so a competing bidder that committed first is always seen and
    re-validated against the fresh price/deadline.
    """
    product = type(product).objects.select_for_update().get(pk=product.pk)

    bid = Bid(product=product, bidder=bidder, amount=amount)
    try:
        bid.clean()
    except ValidationError as exc:
        raise BidError("; ".join(exc.messages)) from exc

    previous_leader = product.bids.order_by("-amount").first()

    bid.save()
    product.current_price = amount

    # Anti-sniping: a valid bid inside the closing window pushes the deadline
    # back. Persisted before the broadcast below so every client (and the
    # closing job) sees the same extended deadline.
    new_end = sniping_extension_for(product)
    update_fields = ["current_price"]
    extended = new_end is not None
    if extended:
        product.auction_end = new_end
        product.extension_count += 1
        update_fields += ["auction_end", "extension_count"]
    product.save(update_fields=update_fields)

    if previous_leader and previous_leader.bidder_id != bidder.id:
        notify(
            previous_leader.bidder,
            f"You've been outbid on \"{product.title}\". New highest bid: {amount}.",
            link=product.get_absolute_url(),
        )

    if extended:
        _notify_extension(product)

    broadcast_auction(product, event="extended" if extended else "bid")

    return bid


def _notify_extension(product):
    """Tell the seller (and every watcher) that the clock just moved back."""
    message = (
        f"Anti-sniping: a late bid on \"{product.title}\" extended the auction "
        f"to {product.auction_end:%b %d, %H:%M %Z}."
    )
    for user in recipients_for(product):
        notify(user, message, link=product.get_absolute_url())

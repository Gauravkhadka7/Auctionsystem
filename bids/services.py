"""Business logic for placing a bid — kept out of views so it's reusable
from both the regular POST view and the AJAX endpoint."""
from django.core.exceptions import ValidationError
from django.db import transaction

from notifications.models import Notification
from .models import Bid


class BidError(Exception):
    pass


@transaction.atomic
def place_bid(product, bidder, amount):
    """Place a bid, update the product's current price, and notify the
    previously-highest bidder that they've been outbid."""
    product = type(product).objects.select_for_update().get(pk=product.pk)

    bid = Bid(product=product, bidder=bidder, amount=amount)
    try:
        bid.clean()
    except ValidationError as exc:
        raise BidError("; ".join(exc.messages)) from exc

    previous_leader = product.bids.order_by("-amount").first()

    bid.save()
    product.current_price = amount
    product.save(update_fields=["current_price"])

    if previous_leader and previous_leader.bidder_id != bidder.id:
        Notification.objects.create(
            user=previous_leader.bidder,
            message=f"You've been outbid on \"{product.title}\". New highest bid: {amount}.",
            link=product.get_absolute_url(),
        )

    return bid

"""Helpers for pushing live auction state to WebSocket subscribers.

Uses the configured channel layer; if Channels isn't available (or no channel
layer is configured) these calls are safe no-ops, so the HTTP polling fallback
keeps the site working without any WebSocket infrastructure.
"""
from asgiref.sync import async_to_sync

from products.models import Product


def auction_group_name(slug):
    return f"auction_{slug}"


def serialize_auction(product, event):
    leader = product.bids.order_by("-amount", "created_at").first()
    return {
        "type": "auction.update",
        "event": event,
        "slug": product.slug,
        "status": product.status,
        "current_price": str(product.current_price),
        "minimum_next_bid": str(product.minimum_next_bid),
        "total_bids": product.total_bids,
        "total_bidders": product.total_bidders,
        "time_remaining_seconds": product.time_remaining_seconds,
        "leader": leader.bidder.username if leader else None,
    }


def broadcast_auction(product, event="update"):
    """Broadcast the latest state of `product` to everyone watching it."""
    try:
        from channels.layers import get_channel_layer
    except ImportError:  # Channels not installed — polling fallback handles it.
        return

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    fresh = Product.objects.filter(pk=product.pk).first()
    if fresh is None:
        return

    payload = serialize_auction(fresh, event)
    async_to_sync(channel_layer.group_send)(
        auction_group_name(fresh.slug),
        {"type": "auction.update", "payload": payload},
    )

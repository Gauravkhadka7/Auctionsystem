"""Real-time delivery for notification rows.

``Notification`` rows are still the source of truth (bell icon, notification
page); this module additionally pushes each newly created row to the owning
user's WebSocket group so the bell updates without a page reload.

Everything degrades gracefully: if Channels isn't installed or no channel
layer is configured, creating the row is all that happens — exactly the
pre-existing behaviour.
"""
from asgiref.sync import async_to_sync
from django.urls import reverse

from .models import Notification


def recipients_for(product, include_seller=True):
    """Everyone who should hear about an auction event, deduplicated by pk.

    By default that's the seller plus every watcher; some events (e.g. the
    leader being outbid) are handled by the caller.
    """
    recipients = {}
    if include_seller:
        recipients[product.seller_id] = product.seller
    for item in product.watchlisted_by.select_related("user"):
        recipients[item.user_id] = item.user
    return recipients.values()


def user_group_name(user_id):
    return f"user_{user_id}"


def serialize_notification(notification):
    return {
        "type": "notification.new",
        "id": notification.pk,
        "message": notification.message,
        "link": notification.link or "",
        # Where the bell should point so opening it also marks it read.
        "open_url": reverse("notifications:open", args=[notification.pk]),
        "unread_count": notification.user.notifications.filter(is_read=False).count(),
    }


def dispatch_notification(notification):
    """Push an already-persisted notification to its owner's channel group."""
    try:
        from channels.layers import get_channel_layer
    except ImportError:  # pragma: no cover - Channels is a hard dependency
        return

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    async_to_sync(channel_layer.group_send)(
        user_group_name(notification.user_id),
        serialize_notification(notification),
    )


def notify(user, message, link=""):
    """Create a notification row and push it to the user in real time."""
    notification = Notification.objects.create(user=user, message=message, link=link)
    dispatch_notification(notification)
    return notification
